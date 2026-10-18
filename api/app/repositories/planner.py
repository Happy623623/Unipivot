"""플래너 할 일 SQL (F-43, API 명세 7장).

할 일은 사용자 것만 읽고 쓴다(서버가 서비스 권한으로 붙어 RLS가 막아주지 않는다). 공고에서 온 할 일은
공고 제목·카테고리를 같이 읽어 화면의 칩에 쓴다. 마커는 준비를 마친 공고의 마감일이다(공고 상세의 prepared와 같은 기준:
실행이 성공했거나 실행 기록이 없는 계획). 실행 중이거나 멈춘 계획은 상세가 준비하지 않은 것으로 보여서,
플래너에만 마감이 뜨면 두 화면이 어긋난다. 강의계획서·LMS 할 일은 그 기능(F-14·F-51)이 생기면 같은 표에 쌓인다.
"""

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection, sql

from app.db import get_conn
from app.errors import ApiError
from app.lms.parse import course_name
from app.repositories.opportunities import PREP_DONE
from app.schemas.planner import PlannerLink, PlannerMarker, PlannerResponse, PlannerTask

# 공고에서 온 할 일은 계획 → 공고로 이어 제목·카테고리를 읽는다. 계획서 일정·LMS 과제·과목 공지는
# 그 과목 이름을 이어 읽는다(명세 7장의 `link.type`). 공지는 과목 공통 표라 과목 번호로 잇는다
_TASK = (
    "select t.id::text as id, t.title, t.due_date, coalesce(t.is_done, false) as is_done,"
    " t.source::text as source, o.id::text as opportunity_id, o.title as opportunity_title,"
    " o.category::text as category,"
    " t.syllabus_item_id::text as syllabus_item_id, coalesce(sc.name, sy.course_name) as syllabus_course,"
    " t.lms_assignment_id::text as lms_assignment_id, lc.name as assignment_course,"
    " t.lms_announcement_id::text as lms_announcement_id, ac.name as announcement_course"
    " from planner_tasks t"
    " left join prep_plans p on p.id = t.prep_plan_id and p.user_id = t.user_id"
    " left join opportunities o on o.id = p.opportunity_id"
    " left join syllabus_items si on si.id = t.syllabus_item_id"
    " left join syllabi sy on sy.id = si.syllabus_id and sy.user_id = t.user_id"
    " left join lms_courses sc on sc.id = sy.lms_course_id and sc.user_id = t.user_id"
    " left join lms_assignments la on la.id = t.lms_assignment_id and la.user_id = t.user_id"
    " left join lms_courses lc on lc.id = la.lms_course_id and lc.user_id = t.user_id"
    " left join lms_announcements an on an.id = t.lms_announcement_id"
    " left join lms_courses ac on ac.canvas_course_id = an.canvas_course_id"
    "   and ac.user_id = t.user_id"
)


def _link(row: dict[str, Any]) -> PlannerLink:
    """그 할 일이 가리키는 것(명세 7장). 이어진 것이 없으면 type은 null이다."""
    if row["opportunity_id"]:
        return PlannerLink(
            type="opportunity",
            id=row["opportunity_id"],
            title=row["opportunity_title"],
            category=row["category"],
        )
    if row["syllabus_item_id"]:
        return PlannerLink(
            type="syllabus_item",
            id=row["syllabus_item_id"],
            title=_short(row["syllabus_course"]),
            category=None,
        )
    if row["lms_assignment_id"]:
        return PlannerLink(
            type="lms_assignment",
            id=row["lms_assignment_id"],
            title=_short(row["assignment_course"]),
            category=None,
        )
    if row["lms_announcement_id"]:
        return PlannerLink(
            type="lms_announcement",
            id=row["lms_announcement_id"],
            title=_short(row["announcement_course"]),
            category=None,
        )
    return PlannerLink(type=None, id=None, title=None, category=None)


def _short(course: str | None) -> str | None:
    """과목 화면 이름(`202620HY23525_데이터베이스` → `데이터베이스`)."""
    return course_name(course).short_name if course else None


def _task(row: dict[str, Any]) -> PlannerTask:
    link = _link(row)
    return PlannerTask(
        id=row["id"],
        title=row["title"],
        due_date=row["due_date"],
        is_done=row["is_done"],
        source=row["source"],
        link=link,
    )


@dataclass(frozen=True)
class TaskRow:
    id: str
    source: str
    is_done: bool


class PlannerRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def tasks(
        self, user_id: str, *, start: date, end: date, include_done: bool
    ) -> PlannerResponse:
        """기간 안의 할 일과 마커. 날짜 → 만든 순으로 준다(화면이 날짜별로 묶는다)."""
        where = " where t.user_id = %(user)s and t.due_date between %(start)s and %(end)s"
        if not include_done:
            where += " and coalesce(t.is_done, false) = false"
        params = {"user": user_id, "start": start, "end": end}
        rows = await (
            await self.conn.execute(
                _TASK + where + " order by t.due_date, t.sort_order, t.created_at, t.id", params
            )
        ).fetchall()
        markers = await (
            await self.conn.execute(
                "select distinct o.id::text as opportunity_id, o.title,"
                " (o.deadline_at at time zone 'Asia/Seoul')::date as date,"
                " o.category::text as category"
                " from prep_plans p join opportunities o on o.id = p.opportunity_id"
                " where p.user_id = %(user)s and " + PREP_DONE + " and o.deadline_at is not null"
                " and (o.deadline_at at time zone 'Asia/Seoul')::date"
                " between %(start)s and %(end)s"
                " order by date, title",
                params,
            )
        ).fetchall()
        return PlannerResponse(
            items=[_task(row) for row in rows],
            markers=[
                PlannerMarker(
                    date=row["date"],
                    title=f"{row['title']} 마감",
                    opportunity_id=row["opportunity_id"],
                    category=row["category"],
                )
                for row in markers
            ],
        )

    async def task(self, user_id: str, task_id: str) -> TaskRow | None:
        """고치기·지우기 전에 보는 행. 남의 할 일은 None이다(없는 것과 같이 다룬다)."""
        row = await (
            await self.conn.execute(
                "select id::text as id, source::text as source,"
                " coalesce(is_done, false) as is_done"
                " from planner_tasks where id = %s and user_id = %s for update",
                (task_id, user_id),
            )
        ).fetchone()
        return None if row is None else TaskRow(row["id"], row["source"], row["is_done"])

    async def add(self, user_id: str, title: str, due_date: date) -> PlannerTask:
        row = await (
            await self.conn.execute(
                "insert into planner_tasks (user_id, source, title, due_date)"
                " values (%s, 'manual', %s, %s) returning id",
                (user_id, title, due_date),
            )
        ).fetchone()
        assert row is not None  # insert ... returning은 늘 한 행이다
        found = await self.one(user_id, str(row["id"]))
        assert found is not None
        return found

    async def update(self, user_id: str, task_id: str, changes: dict[str, Any]) -> PlannerTask:
        """보낸 필드만 바꾼다. 완료로 바뀌면 done_at을 찍고, 풀면 지운다."""
        sets = [
            sql.SQL("{} = {}").format(sql.Identifier(name), sql.Placeholder(name))
            for name in changes
        ]
        if "is_done" in changes:
            sets.append(
                sql.SQL("done_at = case when {} then now() else null end").format(
                    sql.Placeholder("is_done")
                )
            )
        await self.conn.execute(
            sql.SQL(
                "update planner_tasks set {sets} where id = %(id)s and user_id = %(user)s"
            ).format(sets=sql.SQL(", ").join(sets)),
            {**changes, "id": task_id, "user": user_id},
        )
        found = await self.one(user_id, task_id)
        if found is None:  # 그새 지워졌다(계획이 cascade로 지워지는 등)
            raise ApiError(404, "NOT_FOUND", "할 일을 찾을 수 없어요.")
        return found

    async def remove(self, user_id: str, task_id: str) -> None:
        await self.conn.execute(
            "delete from planner_tasks where id = %s and user_id = %s", (task_id, user_id)
        )

    async def one(self, user_id: str, task_id: str) -> PlannerTask | None:
        row = await (
            await self.conn.execute(
                _TASK + " where t.id = %(id)s and t.user_id = %(user)s",
                {"id": task_id, "user": user_id},
            )
        ).fetchone()
        return None if row is None else _task(row)


def get_planner_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> PlannerRepository:
    return PlannerRepository(conn)


PlannerRepoDep = Annotated[PlannerRepository, Depends(get_planner_repo)]
