"""강의계획서 SQL (F-14, ERD `syllabi`·`syllabus_items`).

내 것만 읽고 쓴다. 과목당 계획서는 하나다(`syllabi (lms_course_id)` 부분 유니크) — 다시 올리면
`replace`로 갈아 끼운다(옛 일정과 그것으로 만든 할 일·캘린더 기록은 함께 지워진다, cascade).

과목을 붙이지 않은 계획서(LMS 미연결)는 여러 개 있을 수 있다. 그때는 과목 연결 없이 저장한다.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated

from fastapi import Depends
from psycopg import AsyncConnection

from app.db import get_conn
from app.eligibility import KST
from app.lms.parse import course_name as parse_course_name
from app.schemas.syllabi import SyllabusItemView
from app.syllabi.extract import DraftItem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyllabusFile:
    id: str
    storage_path: str


@dataclass(frozen=True)
class SyllabusCourse:
    """계획서를 붙일 LMS 과목. 학기 시작일로 연도 없는 날짜를 읽는다."""

    id: str
    name: str
    short_name: str
    semester_start: date | None


@dataclass(frozen=True)
class SyllabusHead:
    """확인 화면이 다루는 계획서 머리말. 과목을 붙였으면 그 이름도 함께."""

    id: str
    course_id: str | None
    course_name: str | None
    short_name: str | None


@dataclass(frozen=True)
class StoredItem:
    """저장해 둔 일정 하나."""

    id: str
    item_type: str
    title: str
    starts_at: datetime | None
    is_confirmed: bool


@dataclass(frozen=True)
class SavedSyllabus:
    id: str
    course_name: str | None
    items: list[SyllabusItemView]


class SyllabusRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def syllabus_file(self, user_id: str, file_id: str) -> SyllabusFile | None:
        """내가 올린 계획서 PDF. 남의 파일·다른 종류는 None이다."""
        row = await (
            await self.conn.execute(
                "select id::text as id, storage_path from files"
                " where id = %s and user_id = %s and origin = 'upload'"
                "   and kind::text = 'syllabus'",
                (file_id, user_id),
            )
        ).fetchone()
        return None if row is None else SyllabusFile(row["id"], row["storage_path"])

    async def course(self, user_id: str, course_id: str) -> SyllabusCourse | None:
        """내 수강 과목. 수강을 뺀 과목과 남의 과목은 None이다."""
        row = await (
            await self.conn.execute(
                "select id::text as id, name from lms_courses"
                " where id = %s and user_id = %s and coalesce(is_active, true)",
                (course_id, user_id),
            )
        ).fetchone()
        if row is None:
            return None
        # 학기 시작일은 과목명에서 센다(`202620HY23525_…` → 2026-2 → 9/1). 개강일 칸은 없다
        parsed = parse_course_name(row["name"])
        return SyllabusCourse(
            id=row["id"],
            name=row["name"],
            short_name=parsed.short_name,
            semester_start=parsed.semester_start,
        )

    async def existing(self, user_id: str, course_id: str) -> str | None:
        """그 과목에 이미 붙은 계획서 id(없으면 None). 덮어쓸지 묻는 데 쓴다."""
        row = await (
            await self.conn.execute(
                "select id::text as id from syllabi where user_id = %s and lms_course_id = %s",
                (user_id, course_id),
            )
        ).fetchone()
        return None if row is None else row["id"]

    async def existing_items(self, user_id: str, course_id: str) -> int:
        """그 과목 계획서에 이미 들어 있는 일정 수. 빈 결과로 덮어쓰지 않으려고 센다."""
        row = await (
            await self.conn.execute(
                "select count(i.id) as count from syllabi s"
                " left join syllabus_items i on i.syllabus_id = s.id"
                " where s.user_id = %s and s.lms_course_id = %s",
                (user_id, course_id),
            )
        ).fetchone()
        return int(row["count"]) if row else 0

    async def save(
        self,
        user_id: str,
        *,
        file_id: str,
        course_id: str | None,
        course_name: str | None,
        semester: str | None,
        items: Sequence[DraftItem],
        now: datetime,
    ) -> SavedSyllabus:
        """계획서와 일정을 저장한다. 같은 과목에 있던 계획서는 지우고 새로 넣는다.

        일정은 **확정 전**(`is_confirmed` false)이다. 확인 화면에서 고른 것만 플래너·캘린더로 간다.
        """
        if course_id is not None:
            # 과목당 하나다. 옛 일정과 그것으로 만든 할 일·일정 기록도 cascade로 함께 지워진다
            await self.conn.execute(
                "delete from syllabi where user_id = %s and lms_course_id = %s",
                (user_id, course_id),
            )
        row = await (
            await self.conn.execute(
                "insert into syllabi (user_id, lms_course_id, file_id, course_name, semester,"
                " created_at) values (%(uid)s, %(course)s, %(file)s, %(name)s, %(semester)s,"
                " %(now)s) returning id::text as id",
                {
                    "uid": user_id,
                    "course": course_id,
                    "file": file_id,
                    "name": course_name,
                    "semester": semester,
                    "now": now,
                },
            )
        ).fetchone()
        assert row is not None
        syllabus_id = row["id"]
        saved: list[SyllabusItemView] = []
        for item in items:
            made = await (
                await self.conn.execute(
                    "insert into syllabus_items (syllabus_id, item_type, title, starts_at,"
                    " is_confirmed) values (%s, %s, %s, %s, false) returning id::text as id",
                    (syllabus_id, item.item_type, item.title, item.starts_at),
                )
            ).fetchone()
            assert made is not None
            saved.append(
                SyllabusItemView(
                    id=made["id"],
                    item_type=item.item_type,
                    title=item.title,
                    starts_at=item.starts_at,
                    is_confirmed=False,
                )
            )
        return SavedSyllabus(syllabus_id, course_name, saved)

    async def one(self, user_id: str, syllabus_id: str) -> SyllabusHead | None:
        """내 계획서 하나(확인 화면이 보내온 것). 남의 계획서는 None이다."""
        row = await (
            await self.conn.execute(
                "select s.id::text as id, s.course_name, s.lms_course_id::text as course_id,"
                " c.name as course_full_name from syllabi s"
                " left join lms_courses c on c.id = s.lms_course_id and c.user_id = s.user_id"
                " where s.id = %s and s.user_id = %s",
                (syllabus_id, user_id),
            )
        ).fetchone()
        if row is None:
            return None
        full = row["course_full_name"]
        return SyllabusHead(
            id=row["id"],
            course_id=row["course_id"],
            course_name=row["course_name"],
            short_name=parse_course_name(full).short_name if full else row["course_name"],
        )

    async def items(self, user_id: str, syllabus_id: str) -> list[StoredItem]:
        """그 계획서의 일정(확인 전·후 모두). 순서는 부른 쪽이 정한다.

        일정 표에는 `user_id`가 없어서 계획서로 거른다(api/CLAUDE.md: 사용자 API의 SQL에는 늘
        `user_id` 조건). 부른 쪽이 이미 주인을 봤더라도 여기서 한 번 더 막는다.
        """
        rows = await (
            await self.conn.execute(
                "select i.id::text as id, i.item_type::text as item_type, i.title, i.starts_at,"
                " coalesce(i.is_confirmed, false) as is_confirmed from syllabus_items i"
                " join syllabi s on s.id = i.syllabus_id"
                " where i.syllabus_id = %s and s.user_id = %s",
                (syllabus_id, user_id),
            )
        ).fetchall()
        return [
            StoredItem(
                id=row["id"],
                item_type=row["item_type"],
                title=row["title"],
                starts_at=row["starts_at"],
                is_confirmed=row["is_confirmed"],
            )
            for row in rows
        ]

    async def confirm_item(
        self,
        user_id: str,
        item_id: str,
        *,
        syllabus_id: str,
        title: str,
        starts_at: datetime | None,
        selected: bool,
    ) -> None:
        """학생이 고친 제목·시각을 저장하고 확인 여부를 적는다. 내 계획서의 일정만 고친다."""
        await self.conn.execute(
            "update syllabus_items set title = %(title)s, starts_at = %(starts)s,"
            " is_confirmed = %(selected)s where id = %(iid)s and syllabus_id in"
            "   (select id from syllabi where id = %(sid)s and user_id = %(uid)s)",
            {
                "title": title,
                "starts": starts_at,
                "selected": selected,
                "iid": item_id,
                "sid": syllabus_id,
                "uid": user_id,
            },
        )

    async def sync_task(
        self, user_id: str, item: StoredItem, *, selected: bool, course_id: str | None
    ) -> bool:
        """고른 일정은 플래너 할 일로 만들고, 뺀 일정은 할 일에서 지운다.

        만들었으면 True다. 이미 있으면 제목·날짜만 맞추고 False다(두 번 눌러도 하나다).
        끝낸 할 일은 지우지 않는다 — 학생이 체크한 것을 되돌리지 않는다.
        """
        if not selected or item.starts_at is None:
            await self.conn.execute(
                "delete from planner_tasks where user_id = %s and syllabus_item_id = %s"
                " and coalesce(is_done, false) = false",
                (user_id, item.id),
            )
            return False
        # 날짜는 KST로 센다(timestamptz는 UTC로 들어 있어 밤·새벽 일정이 하루 밀린다)
        due = item.starts_at.astimezone(KST).date()
        # 한 번에 넣고, 이미 있으면 제목·날짜만 맞춘다. 두 탭에서 같이 눌러도 할 일은 하나다
        # (부분 유니크 인덱스 planner_tasks_user_syllabus_item_uq). `xmax = 0`이면 이번에 새로 넣은 행이다
        row = await (
            await self.conn.execute(
                "insert into planner_tasks (user_id, source, syllabus_item_id, title, due_date)"
                " values (%s, 'syllabus', %s, %s, %s)"
                " on conflict (user_id, syllabus_item_id) where syllabus_item_id is not null"
                "   do update set title = excluded.title, due_date = excluded.due_date"
                " returning (xmax = 0) as inserted",
                (user_id, item.id, item.title, due),
            )
        ).fetchone()
        return bool(row and row["inserted"])


def get_syllabus_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> SyllabusRepository:
    return SyllabusRepository(conn)


SyllabusRepoDep = Annotated[SyllabusRepository, Depends(get_syllabus_repo)]
