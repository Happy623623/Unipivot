"""에이전트가 읽는 자료: 본문, 첨부, 원문 페이지. 모델에 보낸 글자만 근거 대조(Evidence)에 넣는다.

첨부는 실행을 시작할 때 모두 훑는다(형식 판별과 글자 추출은 코드라 비용이 없다).
그래서 모델은 첨부 목록에서 형식·쪽 수·글자 유무를 보고 읽을 첨부와 도구를 고른다.
어디까지 읽었는지도 센다. 끝까지 읽지 않은 자료는 원문 확인 필요 사유가 된다(뒷부분에 요건이 있을 수 있다).
"""

import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.attachments import (
    KIND_LABELS,
    MIME_TYPES,
    AttachmentText,
    UnreadableAttachment,
    VisionPayload,
    clean_text,
    detect_format,
    read_attachment_text,
    vision_payload,
)
from app.crawl.fetch import FetchError
from app.extraction.models import AttachmentInput, AttachmentOutcome, Limits, NoticeInput
from app.extraction.prompt import READ_IMAGE, READ_TEXT
from app.extraction.validate import Evidence

logger = logging.getLogger(__name__)
PageFetcher = Callable[[str], Awaitable[str]]
_VISION_KINDS = frozenset({"pdf", "png", "jpeg", "webp"})


class ToolError(Exception):
    """도구를 쓸 수 없는 경우. 메시지를 모델에 {"error": …}로 돌려주고 루프는 이어진다."""


class _Coverage:
    """모델에 보낸 글자 범위."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._ranges: list[tuple[int, int]] = []

    def add(self, start: int, end: int) -> None:
        self._ranges.append((start, end))

    @property
    def read(self) -> int:
        total, reach = 0, 0
        for start, end in sorted(self._ranges):
            start = max(start, reach)
            if end > start:
                total += end - start
                reach = end
        return total

    @property
    def complete(self) -> bool:
        return self.read >= self.size


@dataclass
class _Attachment:
    input: AttachmentInput
    kind: str
    sha256: str
    scanned: AttachmentText | None = None
    error: str | None = None  # 형식을 못 읽음, 또는 읽으려다 실패함 → extract_error
    text: _Coverage | None = None  # 글자로 읽은 범위(읽은 적이 없으면 None)
    vision_texts: list[str] = field(default_factory=list)
    vision_pages: set[int] = field(default_factory=set)


class Library:
    def __init__(self, notice: NoticeInput, limits: Limits) -> None:
        self.notice, self.limits = notice, limits
        body = notice.body.strip()
        self.body = body[: limits.max_body_chars]  # 첫 메시지에 넣는 본문
        self.body_truncated = len(body) > len(self.body)
        self.evidence = Evidence()
        self.evidence.add(notice.title)
        self.evidence.add(self.body)
        self.items = {attachment.seq: _scan(attachment) for attachment in notice.attachments}
        self._page_text: str | None = None
        self._page: _Coverage | None = None

    def listing(self) -> list[str]:
        """첫 메시지의 [첨부] 목록. 모델이 이걸 보고 도구를 고른다."""
        return [_line(item) for item in self.items.values()]

    def read_text(self, number: Any, offset: Any) -> dict[str, Any]:
        item = self._get(number)
        scanned = self._readable(item)
        if scanned.needs_vision:
            raise ToolError(f"글자가 없는 첨부예요. {READ_IMAGE}로 읽어 주세요")
        text = scanned.text
        start, end = _chunk(text, offset, self.limits.max_read_chars)
        if item.text is None:
            item.text = _Coverage(len(text))
        item.text.add(start, end)
        self.evidence.add(text[start:end])
        result: dict[str, Any] = {
            "file_name": item.input.file_name,
            "chars": len(text),
            "offset": start,
            "text": text[start:end],
        }
        if end < len(text):
            result["next_offset"] = end
        if scanned.image_pages:
            result["pages_without_text"] = list(scanned.image_pages)
        return result

    def vision_input(self, number: Any, start_page: Any) -> tuple[_Attachment, VisionPayload]:
        item = self._get(number)
        scanned = self._readable(item)
        if item.kind not in _VISION_KINDS:
            raise ToolError(f"글자가 있는 문서예요. {READ_TEXT}로 읽어 주세요")
        page = whole(start_page) or 1
        if scanned.page_count and not 1 <= page <= scanned.page_count:
            raise ToolError(f"{scanned.page_count}쪽까지만 있어요")
        try:
            payload = vision_payload(
                item.input.data, item.kind, start_page=page, max_pages=self.limits.vision_max_pages
            )
        except UnreadableAttachment as exc:
            item.error = str(exc)  # 파일이 깨져 Vision으로도 보낼 수 없다
            raise ToolError(str(exc)) from exc
        return item, payload

    def record_vision(self, item: _Attachment, payload: VisionPayload, text: str) -> dict[str, Any]:
        sent = clean_text(text)[: self.limits.max_read_chars]
        item.vision_texts.append(sent)
        if payload.first_page is not None and payload.last_page is not None:
            item.vision_pages.update(range(payload.first_page, payload.last_page + 1))
        else:
            item.vision_pages.add(1)  # 이미지는 한 장
        self.evidence.add(sent)
        result: dict[str, Any] = {"file_name": item.input.file_name, "text": sent}
        if payload.first_page is not None and payload.page_count is not None:
            result["pages"] = f"{payload.first_page}–{payload.last_page}/{payload.page_count}"
            if payload.last_page is not None and payload.last_page < payload.page_count:
                result["next_start_page"] = payload.last_page + 1
        return result

    def vision_failed(self, item: _Attachment, reason: str) -> None:
        item.error = reason

    async def read_original(self, fetch: PageFetcher | None, offset: Any) -> dict[str, Any]:
        url = self.notice.original_url
        if not url:
            raise ToolError("원문 링크가 없는 공고예요")
        if fetch is None:
            raise ToolError("원문 다시 읽기를 쓸 수 없어요")
        if self._page_text is None:
            try:
                self._page_text = clean_text(await fetch(url))
            except FetchError as exc:
                raise ToolError(f"원문을 가져오지 못했어요: {exc}") from exc
            self._page = _Coverage(len(self._page_text))
        text = self._page_text
        start, end = _chunk(text, offset, self.limits.max_read_chars)
        if self._page is not None:
            self._page.add(start, end)
        self.evidence.add(text[start:end])
        result: dict[str, Any] = {"chars": len(text), "offset": start, "text": text[start:end]}
        if end < len(text):
            result["next_offset"] = end
        return result

    def unread(self) -> list[int]:
        """읽을 수 있는데 읽지 않은 첨부 번호."""
        return [
            seq
            for seq, item in self.items.items()
            if item.error is None and item.text is None and not item.vision_pages
        ]

    def partial_reads(self) -> list[str]:
        """끝까지 읽지 않은 자료. 뒷부분에 요건이 있을 수 있어 원문 확인 필요 사유가 된다."""
        notes = []
        if self.body_truncated and not (self._page and self._page.complete):
            notes.append(f"본문이 길어 앞 {len(self.body):,}자만 읽음")
        if self._page is not None and not self._page.complete:
            notes.append(f"원문 페이지를 {self._page.read:,}/{self._page.size:,}자만 읽음")
        # 학생에게 보이는 문구다(공고 상세 review_reasons). 첨부는 번호 대신 파일 이름으로 쓴다
        for item in self.items.values():
            name = item.input.file_name
            if item.text is not None and not item.text.complete:
                notes.append(f"첨부 '{name}' {item.text.read:,}/{item.text.size:,}자만 읽음")
            scanned = item.scanned
            if item.vision_pages and scanned and scanned.needs_vision and scanned.page_count:
                if len(item.vision_pages) < scanned.page_count:
                    notes.append(
                        f"첨부 '{name}' {len(item.vision_pages)}/{scanned.page_count}쪽만 읽음"
                    )
        return notes

    def outcomes(self) -> tuple[AttachmentOutcome, ...]:
        """opportunity_attachments에 쓸 값. 글자로 읽은 첨부는 추출한 글자 전체를 저장한다."""
        out = []
        for item in self.items.values():
            read_text = item.text is not None and item.scanned is not None
            parts = [item.scanned.text] if read_text and item.scanned else []
            parts += item.vision_texts
            if item.vision_texts:
                method: str | None = "vision"
            else:
                method = item.scanned.method if read_text and item.scanned else None
            out.append(
                AttachmentOutcome(
                    seq=item.input.seq,
                    file_name=item.input.file_name,
                    kind=item.kind,
                    mime_type=MIME_TYPES.get(item.kind),
                    sha256=item.sha256,
                    id=item.input.id,
                    method=method,
                    text="\n".join(parts) if parts else None,
                    error=item.error,
                )
            )
        return tuple(out)

    def _get(self, number: Any) -> _Attachment:
        seq = whole(number)
        item = self.items.get(seq) if seq is not None else None
        if item is None:
            raise ToolError(f"첨부 번호가 없어요. [첨부] 목록의 번호를 쓰세요: {number!r}")
        return item

    @staticmethod
    def _readable(item: _Attachment) -> AttachmentText:
        if item.scanned is None or item.error:
            raise ToolError(item.error or "읽을 수 없는 첨부예요")
        return item.scanned


def whole(value: Any) -> int | None:
    """모델이 준 정수. JSON 숫자가 1.0처럼 올 수 있어 정수 값인 실수도 받는다."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value if isinstance(value, int) else None


def _chunk(text: str, offset: Any, size: int) -> tuple[int, int]:
    """offset부터 size자. 줄 중간에서 자르지 않는다(근거 문장이 두 조각으로 나뉘지 않게)."""
    start = whole(offset) if offset is not None else 0
    if start is None or not 0 <= start < max(len(text), 1):
        raise ToolError(f"offset은 0 이상 {len(text)} 미만이어야 해요")
    end = min(len(text), start + size)
    if end < len(text):
        line_end = text.rfind("\n", start, end)
        if line_end > start + size * 0.8:
            end = line_end + 1
    return start, end


def _scan(attachment: AttachmentInput) -> _Attachment:
    sha256 = hashlib.sha256(attachment.data).hexdigest()
    try:
        scanned = read_attachment_text(attachment.data, attachment.file_name)
    except UnreadableAttachment as exc:
        kind = detect_format(attachment.data, attachment.file_name)
        return _Attachment(attachment, kind, sha256, error=str(exc))
    except Exception:  # 추출기 버그로 실행 전체를 멈추지 않는다. 로그에 남기고 못 읽은 첨부로 둔다
        logger.exception("첨부 읽기 실패: %s", attachment.file_name)
        kind = detect_format(attachment.data, attachment.file_name)
        return _Attachment(attachment, kind, sha256, error="첨부를 읽다가 오류가 났어요")
    return _Attachment(attachment, scanned.kind, sha256, scanned=scanned)


def _line(item: _Attachment) -> str:
    head = f"{item.input.seq}. {item.input.file_name} — "
    scanned = item.scanned
    if scanned is None:
        return head + f"못 읽음: {item.error}"
    label = KIND_LABELS.get(item.kind, item.kind)
    if item.kind == "pdf":
        if scanned.needs_vision:
            return head + f"PDF {scanned.page_count}쪽, 글자 없음(스캔본) → {READ_IMAGE}"
        line = head + f"PDF {scanned.page_count}쪽, 글자 {len(scanned.text):,}자 → {READ_TEXT}"
        if scanned.image_pages:
            line += f" (글자가 거의 없는 {_pages(scanned.image_pages)}쪽은 {READ_IMAGE})"
        return line
    if scanned.needs_vision:
        return head + f"{label}, {_size(len(item.input.data))} → {READ_IMAGE}"
    return head + f"{label}, 글자 {len(scanned.text):,}자 → {READ_TEXT}"


def _pages(pages: tuple[int, ...]) -> str:
    """(3, 4, 5, 9) → "3–5, 9"."""
    runs: list[list[int]] = []
    for page in pages:
        if runs and page == runs[-1][-1] + 1:
            runs[-1].append(page)
        else:
            runs.append([page])
    return ", ".join(f"{run[0]}–{run[-1]}" if len(run) > 1 else str(run[0]) for run in runs)


def _size(size: int) -> str:
    return f"{size / 1024 / 1024:.1f}MB" if size >= 1024 * 1024 else f"{max(1, size // 1024)}KB"
