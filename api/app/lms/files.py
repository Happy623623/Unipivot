"""공지 첨부를 학생 문서함에 저장한다 (F-54, API 명세 9장).

동기화가 받은 과목 공지의 첨부를 받아 파일 저장소에 올리고 `files`에 남긴다(`origin = lms_attachment`,
`kind = lecture_material`, `external_ref` = Canvas 첨부 번호, `lms_course_id` = 그 과목).

- **사용자마다 따로 저장한다.** 첨부는 교수 저작물이라 사용자 사이에 나누지 않는다(PRD F-53 아래 메모,
  ERD 5장). 같은 첨부는 `(user_id, external_ref)` 유니크라 한 번만 들어간다
- **20MB(업로드 상한)를 넘는 첨부는 받지 않는다.** 형식은 가리지 않는다(10/19 결정). 화면은 공지
  목록의 크기로 "커서 저장하지 않았어요"를 보여 준다
- 한 동기화에서 **10개까지**. 최근 공지의 첨부부터 받고 남은 것은 다음 동기화가 받는다(연결 직후에는
  한 학기 분량의 공지가 한꺼번에 들어온다)
- 분반 한정 공지의 첨부는 받지 않는다 — 화면에 보이지 않는 공지다(명세 9장)
- 받거나 올리는 동안 DB 연결을 쥐지 않는다. 기록은 첨부 하나마다 짧은 트랜잭션이다. 올렸는데 기록을
  못 남기면 올린 것을 지운다(저장소에 주인 없는 파일이 남지 않게)
- 하나가 실패해도 나머지를 계속하고 동기화도 성공이다. 못 받은 첨부는 "저장 전"으로 남아 다음 동기화가
  다시 시도한다. 첨부 주소(verifier가 든 열쇠)는 로그·실행 기록에 남기지 않는다
"""

import hashlib
import logging
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from psycopg import AsyncConnection

from app.agent_log import AgentRun
from app.lms.announcements import CanvasAnnouncement, CanvasAttachment, too_large
from app.lms.client import AttachmentUnavailable, LearningXClient
from app.repositories.files import FileRepository
from app.repositories.lms import CourseRow
from app.schemas.lms import ATTACHMENT_TOOL
from app.uploads import MAX_BYTES
from app.uploads.storage import StorageError, SupabaseStorage

logger = logging.getLogger(__name__)
Connect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]

TOOL = ATTACHMENT_TOOL
MAX_PER_SYNC = 10
FALLBACK_TYPE = "application/octet-stream"
_EXTENSION = re.compile(r"\.([A-Za-z0-9]{1,10})$")
_OLDEST = datetime(1970, 1, 1, tzinfo=UTC)


def storage_path(user_id: str, file_id: str, name: str) -> str:
    """`<user_id>/lecture_material/<file_id>.<확장자>`(업로드와 같은 꼴). 원래 이름은 경로에 넣지 않는다."""
    found = _EXTENSION.search(name)
    extension = found.group(1).lower() if found else "bin"
    return f"{user_id}/lecture_material/{file_id}.{extension}"


@dataclass(frozen=True)
class _Wanted:
    course: CourseRow
    posted_at: datetime | None
    attachment: CanvasAttachment


@dataclass(frozen=True)
class AttachmentOutcome:
    saved: int = 0
    failed: int = 0


class AttachmentSaver:
    def __init__(
        self,
        *,
        transaction: Connect,
        client: LearningXClient,
        storage: SupabaseStorage,
        files: Callable[[AsyncConnection], FileRepository] = FileRepository,
    ) -> None:
        self.transaction = transaction
        self.client = client
        self.storage = storage
        self.files = files

    async def run(
        self,
        run: AgentRun,
        user_id: str,
        notices: list[tuple[CourseRow, list[CanvasAnnouncement]]],
    ) -> AttachmentOutcome:
        """이번에 받은 공지의 첨부 중 아직 저장하지 않은 것을 받는다. 할 것이 없으면 기록도 없다."""
        wanted = _wanted(notices)
        if not wanted:
            return AttachmentOutcome()
        async with self.transaction() as conn:
            have = await self.files(conn).lms_attachment_refs(
                user_id, [_ref(one.attachment) for one in wanted]
            )
        todo = [one for one in wanted if _ref(one.attachment) not in have][:MAX_PER_SYNC]
        if not todo:
            return AttachmentOutcome()
        saved = failed = 0
        async with run.tool(TOOL, {"attachments": len(todo)}) as call:
            for one in todo:
                result = await self._save(user_id, one)
                saved += result == "saved"
                failed += result == "failed"
            call.output = {"saved": saved, "failed": failed}
        return AttachmentOutcome(saved=saved, failed=failed)

    async def _save(self, user_id: str, one: _Wanted) -> Literal["saved", "failed", "skipped"]:
        attachment = one.attachment
        assert attachment.url is not None  # _wanted가 주소 없는 첨부를 뺐다
        try:
            got = await self.client.attachment(
                attachment.url, max_bytes=MAX_BYTES, html_ok=_is_html(attachment.content_type)
            )
        except AttachmentUnavailable as exc:
            logger.warning("공지 첨부를 받지 못했어요: file %s, %s", attachment.canvas_file_id, exc)
            return "failed"
        file_id = str(uuid4())
        path = storage_path(user_id, file_id, attachment.name)
        mime_type = attachment.content_type or _bare(got.content_type) or FALLBACK_TYPE
        try:
            await self.storage.upload(path, got.data, mime_type)
        except StorageError as exc:
            logger.warning(
                "공지 첨부를 저장소에 올리지 못했어요: file %s, %s", attachment.canvas_file_id, exc
            )
            return "failed"
        try:
            async with self.transaction() as conn:
                added = await self.files(conn).add_lms_attachment(
                    user_id,
                    file_id=file_id,
                    course_id=one.course.id,
                    ref=_ref(attachment),
                    path=path,
                    mime_type=mime_type,
                    size_bytes=len(got.data),
                    sha256=hashlib.sha256(got.data).hexdigest(),
                    original_name=attachment.name,
                )
        except Exception as exc:  # 그새 탈퇴했거나 DB가 멈췄다. 올린 것을 지우고 다음 첨부로 간다
            logger.warning(
                "공지 첨부 기록을 남기지 못해 올린 파일을 지워요: file %s, %s",
                attachment.canvas_file_id,
                type(exc).__name__,
            )
            await self._remove(path)
            return "failed"
        if added is None:  # 그새 같은 첨부가 들어왔거나 과목이 내 것이 아니다. 올린 것은 지운다
            await self._remove(path)
            return "skipped"
        return "saved"

    async def _remove(self, path: str) -> None:
        try:
            await self.storage.remove(path)
        except StorageError as exc:
            logger.warning("올린 첨부를 지우지 못했어요: %s", exc)


def _wanted(notices: list[tuple[CourseRow, list[CanvasAnnouncement]]]) -> list[_Wanted]:
    """받을 첨부. 분반 한정 공지·상한을 넘는 것·주소가 없는 것은 뺀다. 최근 공지의 첨부부터."""
    found: dict[int, _Wanted] = {}
    for course, items in notices:
        for notice in items:
            if notice.is_section_specific:
                continue
            for attachment in notice.attachments:
                if attachment.url is None or too_large(attachment.size):
                    continue
                current = found.get(attachment.canvas_file_id)
                # 같은 첨부가 두 공지에 붙어 있으면 최근 공지 쪽으로 센다(한 번만 받는다)
                if current is None or (notice.posted_at or _OLDEST) > (
                    current.posted_at or _OLDEST
                ):
                    found[attachment.canvas_file_id] = _Wanted(course, notice.posted_at, attachment)
    return sorted(
        found.values(),
        key=lambda one: ((one.posted_at or _OLDEST), one.attachment.canvas_file_id),
        reverse=True,
    )


def _ref(attachment: CanvasAttachment) -> str:
    return str(attachment.canvas_file_id)


def _bare(content_type: str | None) -> str | None:
    """`text/html; charset=utf-8` → `text/html`."""
    if not content_type:
        return None
    return content_type.split(";")[0].strip().lower() or None


def _is_html(content_type: str | None) -> bool:
    return _bare(content_type) == "text/html"
