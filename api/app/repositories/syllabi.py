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


def get_syllabus_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> SyllabusRepository:
    return SyllabusRepository(conn)


SyllabusRepoDep = Annotated[SyllabusRepository, Depends(get_syllabus_repo)]
