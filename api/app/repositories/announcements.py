"""과목 공지 저장·분류 결과 SQL (F-53, ERD 3-2·3-3).

**이 표에는 `user_id`가 없다.** `lms_announcements`는 과목 공통이다(ERD 3-2: 공지는 그 과목 수강생
모두에게 같다). 그래서 다른 저장소와 달리 조회에 사용자 조건이 없고, 누가 먼저 동기화하든 공지 행과
분류는 **한 번만** 생긴다. 화면이 읽는 쪽(과목 상세·새 글 피드)은 `repositories/lms.py`에 있고 거기서는
`lms_courses`를 거쳐 내 과목인지 가린다.

분류는 비싸다(공지 하나에 모델 호출 한 번, 기회성이면 요건 추출까지). 그래서 한 동기화에서 집는 수를
`limit`으로 묶고, 이미 분류한 공지는 다시 집지 않는다. 두 가지를 집는다.

1. **분류 전**(`category is null`): 게시된 지 얼마 안 된 공지만. 연결 직후에는 한 학기 분량이 한꺼번에
   들어오는데(녹화 6과목 16건, 가장 오래된 것은 두 달 전) 지난 공지를 다 분류해도 지금 할 일이 없다
2. **기회성인데 공고가 없는 것**(`category = 'opportunity' and opportunity_id is null`): 요건 추출이
   실패했거나 그 트랜잭션이 깨진 공지다. 분류는 다시 하지 않고 공고 만들기만 다시 한다

예약 공지(`posted_at is null`)와 분반 한정 공지(`is_section_specific`)는 집지 않는다. 앞은 아직 학생에게
보이지 않은 글이고, 뒤는 내 분반 글인지 가릴 칸이 응답에 없어 공고로 올리면 분반 밖 학생에게 보인다.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.db import get_conn
from app.extraction.models import ExtractionResult
from app.extraction.store import content_hash, save_extraction
from app.lms.announcements import CanvasAnnouncement
from app.schemas.lms import AnnouncementCategory
from app.schemas.opportunities import Category

logger = logging.getLogger(__name__)

TITLE_MAX = 200  # 공고 제목 길이(포스터 등록과 같다)

# 첨부 목록(F-54)은 번호·이름·크기·형식만 넣는다. 주소는 verifier가 든 열쇠라 넣지 않는다
_UPSERT = (
    "insert into lms_announcements (canvas_course_id, canvas_topic_id, title, message, posted_at,"
    " attachment_count, attachments, is_section_specific, first_seen_at)"
    " values (%(canvas)s, %(topic)s, %(title)s, %(message)s, %(posted)s, %(files)s,"
    " %(attachments)s, %(section)s, %(now)s)"
    " on conflict (canvas_topic_id) do update set"
    " canvas_course_id = excluded.canvas_course_id, title = excluded.title,"
    " message = excluded.message, posted_at = excluded.posted_at,"
    " attachment_count = excluded.attachment_count, attachments = excluded.attachments,"
    " is_section_specific = excluded.is_section_specific"
    " returning id, (xmax = 0) as inserted"
)
# 공고를 못 만든 기회성 공지를 먼저 집고(분류는 끝났다), 그다음 분류 전 공지를 최신순으로 집는다
_PENDING = (
    "select id, canvas_course_id, canvas_topic_id, title, message, posted_at,"
    " category::text as category, summary"
    " from lms_announcements"
    " where canvas_course_id = any(%(courses)s::bigint[])"
    "   and not is_section_specific and posted_at is not null"
    "   and ((category = 'opportunity' and opportunity_id is null)"
    "        or (category is null and posted_at >= %(recent)s))"
    # 게시 시각이 같으면 Canvas 번호가 큰 쪽(나중 글)을 먼저. id(uuid)로 가르면 순서가 실행마다 바뀐다
    " order by (category is null), posted_at desc, canvas_topic_id desc"
    " limit %(limit)s"
)


_OLDEST = datetime(1970, 1, 1, tzinfo=UTC)  # 게시 시각이 없는 공지는 가장 먼저 넣는다


def _posted_first(one: CanvasAnnouncement) -> tuple[datetime, int]:
    """올린 순(오래된 것 먼저). 시각이 같으면 Canvas 번호가 작은 쪽이 먼저다."""
    return (one.posted_at or _OLDEST, one.canvas_topic_id)


@dataclass(frozen=True)
class SavedAnnouncement:
    """막 저장한 공지. 새로 본 것만 돌려준다."""

    id: str
    canvas_topic_id: int
    title: str


@dataclass(frozen=True)
class PendingAnnouncement:
    """분류하거나 공고를 만들어야 하는 공지 하나."""

    id: str
    canvas_course_id: int
    canvas_topic_id: int
    title: str
    message: str | None
    posted_at: datetime | None
    category: AnnouncementCategory | None
    summary: str | None

    @property
    def classified(self) -> bool:
        """이미 분류했고 공고만 못 만든 공지(모델을 다시 부르지 않는다)."""
        return self.category is not None


class AnnouncementRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def save(
        self, canvas_course_id: int, items: list[CanvasAnnouncement], *, now: datetime
    ) -> list[SavedAnnouncement]:
        """공지를 저장하고 **이번에 처음 본 것**을 돌려준다.

        제목·본문이 바뀐 공지는 내용만 맞추고 분류는 그대로 둔다(공지 수정은 S10 몫이다 — 아래
        "남은 것"). 사라진 공지는 지우지 않는다(표에 `removed_at`이 없다).
        """
        created: list[SavedAnnouncement] = []
        # **올린 순으로 넣는다.** 새 글 피드는 "처음 본 순"(first_seen_at)이고 한 동기화의 공지는
        # 모두 같은 `now`를 받아, 그대로 넣으면 같은 값끼리의 순서가 id(uuid)로 정해져 실행마다
        # 뒤집힌다. 요건 저장(extraction/store)과 같은 수법으로 1마이크로초씩 밀어 **나중에 올라온
        # 공지가 피드 위로** 오게 한다
        for index, one in enumerate(sorted(items, key=_posted_first)):
            row = await self._row(
                _UPSERT,
                {
                    "canvas": canvas_course_id,
                    "topic": one.canvas_topic_id,
                    "title": one.title,
                    "message": one.message,
                    "posted": one.posted_at,
                    "files": one.attachment_count,
                    "attachments": Jsonb([item.stored() for item in one.attachments]),
                    "section": one.is_section_specific,
                    "now": now + timedelta(microseconds=index),
                },
            )
            assert row is not None  # insert … returning은 늘 한 행이다
            if row["inserted"]:
                created.append(
                    SavedAnnouncement(
                        id=str(row["id"]),
                        canvas_topic_id=one.canvas_topic_id,
                        title=one.title,
                    )
                )
        return created

    async def pending(
        self, *, courses: list[int], recent_from: datetime, limit: int
    ) -> list[PendingAnnouncement]:
        """분류하거나 공고를 만들어야 하는 공지. 머리말의 두 가지를 합쳐 `limit`개까지다.

        `courses`는 **지금 동기화하는 사용자의 과목**이다. 공지는 과목 공통이라 조건을 빼면 남의
        과목 공지까지 이 사람의 동기화가 분류한다(일은 같지만 비용을 엉뚱한 실행에 적는다).
        """
        if not courses:
            return []
        rows = await self._rows(
            _PENDING, {"courses": courses, "recent": recent_from, "limit": limit}
        )
        return [
            PendingAnnouncement(
                id=str(row["id"]),
                canvas_course_id=row["canvas_course_id"],
                canvas_topic_id=row["canvas_topic_id"],
                title=row["title"],
                message=row["message"],
                posted_at=row["posted_at"],
                category=row["category"],
                summary=row["summary"],
            )
            for row in rows
        ]

    async def save_classification(
        self,
        announcement_id: str,
        *,
        category: AnnouncementCategory,
        summary: str | None,
        run_id: str | None,
    ) -> None:
        """분류 결과를 적는다. **이미 분류된 공지는 건드리지 않는다**(다른 수강생이 먼저 했다)."""
        await self.conn.execute(
            "update lms_announcements set category = %s::announcement_category, summary = %s,"
            " classified_run_id = %s where id = %s and category is null",
            (category, summary, run_id, announcement_id),
        )

    async def create_opportunity(
        self,
        announcement: PendingAnnouncement,
        *,
        category: Category,
        original_url: str | None,
        extraction: ExtractionResult,
        run_id: str | None,
    ) -> str | None:
        """기회성 공지로 공고 행을 만들고 요건·서류까지 넣는다. 이미 이어져 있으면 None이다.

        **그 과목 수강생만 보이는 공고다**(`visible_canvas_course_id`). 공개 범위는 피드·상세가
        그 칸으로 가린다(명세 5장). 요건·서류 저장은 공지 가져오기·포스터 등록과 **같은 코드**를
        쓴다(`extraction/store.save_extraction`) — 판정이 쓰는 모양이 한 곳에서만 만들어진다.

        요건을 못 뽑았으면 공고는 만들되 `extraction_run_id`가 비어 판정에서 빠진다(원문 확인
        필요로 보인다). 그 공지는 다음 동기화가 다시 집어 공고 만들기만 되풀이한다.
        """
        locked = await self._row(
            "select opportunity_id from lms_announcements where id = %s for update",
            (announcement.id,),
        )
        if locked is None or locked["opportunity_id"] is not None:
            return None  # 그새 다른 수강생의 동기화가 만들었다
        row = await self._row(
            "insert into opportunities (source_type, external_id, category, title, raw_text,"
            " original_url, visible_canvas_course_id)"
            " values ('lms_announcement', %s, %s::opportunity_category, %s, %s, %s, %s)"
            " returning id::text as id",
            (
                str(announcement.canvas_topic_id),
                category,
                announcement.title[:TITLE_MAX],
                announcement.message,
                original_url,
                announcement.canvas_course_id,
            ),
        )
        assert row is not None
        opportunity_id = str(row["id"])
        await self.conn.execute(
            "update lms_announcements set opportunity_id = %s where id = %s",
            (opportunity_id, announcement.id),
        )
        await save_extraction(
            self.conn,
            opportunity_id,
            extraction,
            run_id=run_id if extraction.succeeded else None,
            content_hash=content_hash(announcement.message or announcement.title, ()),
        )
        return opportunity_id

    async def add_schedule_task(
        self,
        announcement_id: str,
        canvas_course_id: int,
        *,
        title: str,
        on: date,
    ) -> int:
        """일정 변경 공지를 **그 과목 수강생 모두의** 플래너에 넣는다(F-53 2부).

        공지는 과목 공통이라(ERD 3-2) 누가 동기화했는지와 상관없이 수강생 전체가 받는다 — 새 주차
        항목 알림(`add_material_notices`)과 같은 모양이다. 연결을 끊은 사람은 뺀다.

        `(user_id, lms_announcement_id)`에는 유일 인덱스가 없어서 `not exists`로 막는다. 인덱스를
        만들면 마이그레이션이 하나 더 생긴다(아래 "남은 것").

        고칠 수 있는 것은 완료 여부뿐이다(명세 7장) — 제목·날짜는 LMS가 기준이다.
        """
        cursor = await self.conn.execute(
            "insert into planner_tasks (user_id, source, lms_announcement_id, title, due_date)"
            " select c.user_id, 'lms_announcement', %(ann)s::uuid, %(title)s, %(on)s"
            " from lms_courses c"
            " join lms_connections n on n.user_id = c.user_id and n.status <> 'disconnected'"
            " where c.canvas_course_id = %(canvas)s and coalesce(c.is_active, true)"
            "   and not exists (select 1 from planner_tasks t"
            "     where t.user_id = c.user_id and t.lms_announcement_id = %(ann)s::uuid)",
            {"ann": announcement_id, "canvas": canvas_course_id, "title": title, "on": on},
        )
        return max(cursor.rowcount, 0)

    async def _row(self, sql: str, params: Any) -> dict[str, Any] | None:
        return await (await self.conn.execute(sql, params)).fetchone()

    async def _rows(self, sql: str, params: Any) -> list[dict[str, Any]]:
        return await (await self.conn.execute(sql, params)).fetchall()


def get_announcement_repo(
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> AnnouncementRepository:
    return AnnouncementRepository(conn)
