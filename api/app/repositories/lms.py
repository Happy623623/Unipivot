"""LearningX 연결과 과목 (F-50·F-14, ERD 3-2).

- 토큰은 암호화한 값만 저장하고(`lms_connections.access_token`), 화면에는 끝 4자리만 보낸다
- 과목은 `(user_id, canvas_course_id)`로 upsert하고, 이번 동기화에 없던 과목은 `is_active`를 내린다
  (수강을 뺀 과목이다 — 과제·공지 기록은 남겨 두고 목록에서만 뺀다). **목록이 비어 오면 내리지 않는다**
- 과목 목록의 숫자는 지금 저장된 것으로 센다. 과제·주차 항목 동기화는 F-51·F-52라 그때까지 0이다
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection

from app.db import get_conn
from app.eligibility import KST
from app.lms.parse import course_name
from app.schemas.lms import ConnectionView, CourseItem, NextDue


@dataclass(frozen=True)
class Connection:
    status: str
    token_last4: str | None
    access_token: str = field(repr=False)  # 암호화된 값. 실수로 찍지 않게 repr에서 뺀다
    canvas_user_id: int | None
    last_synced_at: datetime | None
    last_error: str | None

    def view(self) -> ConnectionView:
        """DB에 있는 상태를 그대로 내려준다(active·error·disconnected)."""
        return ConnectionView(
            status=self.status,  # type: ignore[arg-type]  # DB enum이 세 값으로 묶어 준다
            token_last4=self.token_last4,
            last_synced_at=self.last_synced_at.astimezone(KST) if self.last_synced_at else None,
            last_error=self.last_error,
        )


_COURSES = (
    "select c.id, c.canvas_course_id, c.name, c.last_viewed_at,"
    " exists (select 1 from syllabi s where s.lms_course_id = c.id and s.user_id = c.user_id)"
    "   as has_syllabus,"
    " (select count(*) from lms_assignments a where a.user_id = c.user_id"
    "   and a.lms_course_id = c.id and a.submission_state = 'unsubmitted'"
    "   and a.removed_at is null) as open_assignments,"
    # 주차 항목은 과목 공통 표라 과목 번호로 잇는다. 마지막으로 과목을 본 뒤 생긴 것만 센다
    " (select count(*) from lms_module_items i where i.canvas_course_id = c.canvas_course_id"
    "   and i.first_seen_at > coalesce(c.last_viewed_at, c.synced_at)) as new_materials,"
    # 가장 가까운 것 하나: 미제출 과제와 확정된 계획서 일정 중에서(명세 8장)
    " (select json_build_object('kind', due.kind, 'title', due.title, 'due_at', due.at) from ("
    "    select 'assignment' as kind, a.title, a.due_at as at from lms_assignments a"
    "      where a.user_id = c.user_id and a.lms_course_id = c.id"
    "      and a.submission_state = 'unsubmitted' and a.removed_at is null and a.due_at >= %(now)s"
    "    union all"
    "    select 'syllabus_item', i.title, i.starts_at from syllabus_items i"
    "      join syllabi s on s.id = i.syllabus_id"
    "      where s.lms_course_id = c.id and s.user_id = c.user_id and i.is_confirmed"
    "      and i.starts_at >= %(now)s"
    "  ) as due order by due.at limit 1) as next_due"
    " from lms_courses c where c.user_id = %(uid)s and coalesce(c.is_active, true)"
    " order by c.name"
)

_SAVE = (
    "insert into lms_connections (user_id, access_token, token_last4, canvas_user_id, status,"
    " last_synced_at, last_error) values (%(uid)s, %(token)s, %(last4)s, %(canvas)s, 'active',"
    " %(now)s, null)"
    " on conflict (user_id) do update set access_token = excluded.access_token,"
    " token_last4 = excluded.token_last4, canvas_user_id = excluded.canvas_user_id,"
    " status = 'active', last_synced_at = excluded.last_synced_at, last_error = null"
)

_UPSERT_COURSE = (
    "insert into lms_courses (user_id, canvas_course_id, name, term, portal_year, portal_term,"
    " portal_course_no, is_active, synced_at)"
    " values (%(uid)s, %(canvas)s, %(name)s, %(term)s, %(year)s, %(pterm)s, %(no)s, true, %(now)s)"
    " on conflict (user_id, canvas_course_id) do update set name = excluded.name,"
    " term = excluded.term, portal_year = excluded.portal_year,"
    " portal_term = excluded.portal_term, portal_course_no = excluded.portal_course_no,"
    " is_active = true, synced_at = excluded.synced_at"
)


class LmsRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def connection(self, user_id: str) -> Connection | None:
        row = await self._row(
            "select status, token_last4, access_token, canvas_user_id, last_synced_at, last_error"
            " from lms_connections where user_id = %s",
            (user_id,),
        )
        return Connection(**row) if row else None

    async def save_connection(
        self, user_id: str, *, token: str, last4: str, canvas_user_id: int | None, now: datetime
    ) -> None:
        """연결을 만들거나 토큰을 갈아 끼운다(명세 8장: 이미 연결돼 있으면 교체)."""
        await self.conn.execute(
            _SAVE,
            {
                "uid": user_id,
                "token": token,
                "last4": last4,
                "canvas": canvas_user_id,
                "now": now,
            },
        )

    async def mark_error(self, user_id: str, message: str) -> None:
        """다음 동기화에서 토큰이 막혔을 때. 화면은 이 문구로 다시 연결을 안내한다."""
        await self.conn.execute(
            "update lms_connections set status = 'error', last_error = %s where user_id = %s",
            (message, user_id),
        )

    async def delete_connection(self, user_id: str) -> bool:
        """토큰을 즉시 지운다. 과목·과제 기록은 남기고 동기화만 멈춘다(명세 8장)."""
        cursor = await self.conn.execute(
            "delete from lms_connections where user_id = %s", (user_id,)
        )
        return cursor.rowcount > 0

    async def save_courses(
        self, user_id: str, courses: list[dict[str, Any]], *, now: datetime
    ) -> int:
        """수강 과목을 저장하고, 이번에 없던 과목은 목록에서 뺀다. 저장한 과목 수를 돌려준다."""
        ids: list[int] = []
        for course in courses:
            canvas_id = course.get("id")
            name = (course.get("name") or "").strip()
            if not isinstance(canvas_id, int) or not name:
                continue
            parsed = course_name(name)
            term = (
                (course.get("term") or {}).get("name")
                if isinstance(course.get("term"), dict)
                else None
            )
            await self.conn.execute(
                _UPSERT_COURSE,
                {
                    "uid": user_id,
                    "canvas": canvas_id,
                    "name": name,
                    "term": parsed.term(term),
                    "year": parsed.portal_year,
                    "pterm": parsed.portal_term,
                    "no": parsed.portal_course_no,
                    "now": now,
                },
            )
            ids.append(canvas_id)
        # 빈 목록으로는 내리지 않는다. 학기 사이·필터·끊긴 목록 때문에 비어 올 수 있고,
        # 그때 전부 내리면 사용자가 토큰을 다시 붙여넣기 전까지 과목이 하나도 안 보인다
        if ids:
            await self.conn.execute(
                "update lms_courses set is_active = false"
                " where user_id = %s and not (canvas_course_id = any(%s::bigint[]))",
                (user_id, ids),
            )
        return len(ids)

    async def courses(self, user_id: str, *, now: datetime) -> list[CourseItem]:
        rows = await self._rows(_COURSES, {"uid": user_id, "now": now})
        return [_course(row) for row in rows]

    # ── 조회 ────────────────────────────────────────────────────────────────

    async def _rows(self, query: str, params: Any) -> list[dict[str, Any]]:
        return await (await self.conn.execute(query, params)).fetchall()

    async def _row(self, query: str, params: Any) -> dict[str, Any] | None:
        return await (await self.conn.execute(query, params)).fetchone()


def _course(row: dict[str, Any]) -> CourseItem:
    parsed = course_name(row["name"])
    due = row["next_due"]
    return CourseItem(
        id=str(row["id"]),
        canvas_course_id=row["canvas_course_id"],
        name=row["name"],
        short_name=parsed.short_name,
        has_syllabus=row["has_syllabus"],
        portal_syllabus_url=parsed.syllabus_url,
        open_assignments=int(row["open_assignments"]),
        new_materials=int(row["new_materials"]),
        next_due=NextDue(
            kind=due["kind"],
            title=due["title"],
            due_at=datetime.fromisoformat(due["due_at"]).astimezone(KST),
        )
        if due
        else None,
    )


def get_lms_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> LmsRepository:
    return LmsRepository(conn)


LmsRepoDep = Annotated[LmsRepository, Depends(get_lms_repo)]
