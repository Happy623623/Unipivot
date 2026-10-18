"""Canvas 공지 응답 → 저장할 값 (F-53, API 명세 8·9장).

`GET /api/v1/courses/{id}/discussion_topics?only_announcements=true`가 주는 모양이다.
녹화(2026-10-17, 6과목·공지 16건)에서 확인한 것만 따른다:

- 같은 공지인지는 **`id`(canvas_topic_id)로만** 가린다. 제목은 "휴강 안내"·"휴강안내 (Class
  Cancellation Notice)"처럼 비슷한 것이 섞여 있어서 제목으로 묶으면 다른 공지를 하나로 만든다
- 본문(`message`)은 HTML이다. **평문으로 바꿔 저장한다** — 분류 프롬프트·화면·요건 추출이 모두
  같은 글을 본다. 16건의 본문 길이는 80–4,458자였다
- `posted_at`은 16건 모두 있었다(UTC). 없는 공지는 예약 공지(`delayed_post_at`, 16건 중 1건)라
  **저장만 하고 분류하지 않는다**(아직 학생에게 보이지 않은 글이다)
- `attachments`는 16건 중 2건에 있었다(JSON 파일 하나, 포스터 PNG 하나). **수만 센다** — 첨부
  다운로드는 아직 허용 경로가 아니다(명세 8장)
- `is_section_specific`는 16건 모두 false였다. true면 분반 한정 공지라 저장은 하되 화면에
  내려주지 않는다(명세 9장) — 내 분반 글인지 가릴 수 있는 칸이 응답에 없다
- `locked`(16건 중 8건)는 댓글 잠금이라 우리와 상관없다
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.attachments import html_text
from app.lms.parse import is_canvas_id

logger = logging.getLogger(__name__)

NO_TITLE = "(제목 없음)"
TITLE_MAX = 300  # lms_announcements.title은 text지만 화면·알림에 쓰는 길이로 줄인다
MESSAGE_MAX = 20_000  # 평문 본문 상한. 녹화 최대 4,458자라 넉넉하다
ATTACHMENT_MAX = 32_767  # smallint 칸. 터무니없는 수가 와도 칸을 넘기지 않는다


@dataclass(frozen=True)
class CanvasAnnouncement:
    """저장 직전의 공지 하나. `lms_announcements` 칸과 같은 이름이다."""

    canvas_topic_id: int
    title: str
    message: str | None
    posted_at: datetime | None
    attachment_count: int
    is_section_specific: bool


def announcements(raw: list[Any]) -> list[CanvasAnnouncement]:
    """공지 목록 응답을 저장할 값으로. 번호가 없는 항목은 버린다."""
    items: list[CanvasAnnouncement] = []
    for one in raw:
        parsed = announcement(one)
        if parsed is not None:
            items.append(parsed)
    return items


def announcement(raw: Any) -> CanvasAnnouncement | None:
    """공지 하나. 번호가 없으면 None이다(같은 공지인지 가리는 유일한 기준이다)."""
    if not isinstance(raw, dict) or not is_canvas_id(raw.get("id")):
        return None
    title = " ".join((raw.get("title") or "").split())[:TITLE_MAX] or NO_TITLE
    return CanvasAnnouncement(
        canvas_topic_id=raw["id"],
        title=title,
        message=_message(raw.get("message")),
        posted_at=_moment(raw.get("posted_at")),
        attachment_count=_count(raw.get("attachments")),
        is_section_specific=raw.get("is_section_specific") is True,
    )


def _message(value: Any) -> str | None:
    """HTML 본문 → 평문. 글자가 없으면 None이다(분류가 제목만 보고 판단한다)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = html_text(value)[:MESSAGE_MAX].strip()
    return text or None


def _moment(value: Any) -> datetime | None:
    """`2026-09-28T04:43:23Z` → aware datetime. 읽을 수 없으면 None이다."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("공지 게시 시각을 읽지 못했어요: %r", value[:40])
        return None


def _count(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    return min(len(value), ATTACHMENT_MAX)
