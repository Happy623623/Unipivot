"""LearningX 연결과 과목 (F-50·F-14, ERD 3-2).

- 토큰은 암호화한 값만 저장하고(`lms_connections.access_token`), 화면에는 끝 4자리만 보낸다
- 과목은 `(user_id, canvas_course_id)`로 upsert하고, 이번 동기화에 없던 과목은 `is_active`를 내린다
  (수강을 뺀 과목이다 — 과제·공지 기록은 남겨 두고 목록에서만 뺀다). **목록이 비어 오면 내리지 않는다**
- 과목 목록의 숫자는 지금 저장된 것으로 센다. 주차 항목 동기화는 F-52라 `new_materials`는 그때까지 0이다
- 과제는 `(user_id, canvas_assignment_id)`로 upsert한다(제출 상태가 사람마다 달라 사용자별 표다, ERD 5장).
  이번 목록에 없던 과제는 `removed_at`을 찍고, 다시 나타나면 지운다. **목록이 비어 와도 찍는다** —
  과제는 과목과 달리 0건인 과목이 흔하고(녹화 6과목 중 2과목), 클라이언트가 끝까지 받지 못하면 예외라
  빈 목록은 "정말 없다"는 뜻이다
- 저장하면서 바뀐 것(새 과제·마감 변경·이번에 제출)을 모아 돌려준다. 플래너·알림·캘린더가 그걸 쓴다
- `last_synced_at`은 동기화를 **시작할 때** 찍는다(`claim_sync`). 같은 사용자를 두 번 동시에
  동기화하지 않고, 실패한 사람이 배치 앞자리를 계속 차지하지도 않는다
- 목록 순서는 `ordered()`·`by_due()`가 정한다. DB의 정렬 규칙은 환경마다 달라서 쓰지 않는다
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection

from app.db import get_conn
from app.eligibility import KST
from app.lms.assignments import SUBMITTED, CanvasAssignment
from app.lms.parse import course_name, is_canvas_id
from app.schemas.lms import (
    AssignmentCourse,
    AssignmentItem,
    ConnectionView,
    CourseItem,
    NextDue,
)


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


@dataclass(frozen=True)
class CourseRow:
    """동기화할 과목 하나. 화면 이름은 알림 문구에 쓴다."""

    id: str
    canvas_course_id: int
    short_name: str


@dataclass(frozen=True)
class SavedAssignment:
    """막 저장한 과제. 플래너 할 일과 알림 문구를 만들 만큼만 담는다."""

    id: str
    title: str
    due_at: datetime | None
    # 이미 낸 과제인지. 연결 첫 동기화에는 지난 학기분까지 한꺼번에 들어와서(녹화 17건 중 13건이
    # 제출·채점 완료였다), 낸 과제로 할 일을 만들거나 "새 과제" 알림을 보내면 안 된다
    submitted: bool = False


@dataclass(frozen=True)
class AssignmentChanges:
    """한 과목을 저장하고 바뀐 것. 수는 `POST /lms/sync` 결과에 그대로 들어간다(명세 9장)."""

    created: list[SavedAssignment] = field(default_factory=list)
    due_changed: list[SavedAssignment] = field(default_factory=list)
    # due_changed 중 **마감이 없다가 생긴** 과제. 이것만 할 일을 새로 만든다(아래 sync_planner)
    new_deadline: list[SavedAssignment] = field(default_factory=list)
    submitted: list[str] = field(default_factory=list)  # 이번에 제출로 바뀐 과제 id
    removed: int = 0

    def __add__(self, other: "AssignmentChanges") -> "AssignmentChanges":
        return AssignmentChanges(
            created=self.created + other.created,
            due_changed=self.due_changed + other.due_changed,
            new_deadline=self.new_deadline + other.new_deadline,
            submitted=self.submitted + other.submitted,
            removed=self.removed + other.removed,
        )


_FAR = datetime.max.replace(tzinfo=UTC)  # 마감 없는 과제를 뒤로 보낼 때 쓰는 비교값

_ASSIGNMENTS = (
    "select a.id, a.title, a.due_at, a.submission_state::text as submission_state, a.html_url,"
    " c.id as course_id, c.name as course_name,"
    # 할 일은 과제 하나에 한 줄이다(sync_planner의 not exists). 그래도 가장 먼저 만든 것을 쓴다
    " (select t.id from planner_tasks t where t.lms_assignment_id = a.id"
    "   and t.user_id = a.user_id order by t.created_at, t.id limit 1) as planner_task_id,"
    # 캘린더는 실제로 등록된 것만 true다(공고 상세와 같은 기준: external_event_id가 있는 행)
    " exists (select 1 from calendar_events e where e.lms_assignment_id = a.id"
    "   and e.user_id = a.user_id and e.external_event_id is not null) as calendar_registered"
    " from lms_assignments a"
    " join lms_courses c on c.id = a.lms_course_id and c.user_id = a.user_id"
    # 수강을 뺀 과목의 과제는 더 받지 않으니(active_courses) 사라진 표시도 안 붙는다. 여기서 뺀다
    " where a.user_id = %(uid)s and a.removed_at is null and coalesce(c.is_active, true)"
)
# `pending_review`(냈고 채점만 남은 상태)는 제출로 본다. 안 그러면 어느 state에도 안 들어간다
_STATE_FILTERS = {
    "open": " and a.submission_state = 'unsubmitted'",
    "submitted": " and a.submission_state <> 'unsubmitted'",
    "all": "",
}

_UPSERT_ASSIGNMENT = (
    "insert into lms_assignments (user_id, lms_course_id, canvas_assignment_id, title, due_at,"
    " html_url, submission_state, submitted_at, first_seen_at, removed_at)"
    " values (%(uid)s, %(course)s, %(canvas)s, %(title)s, %(due)s, %(url)s, %(state)s,"
    " %(submitted)s, %(now)s, null)"
    " on conflict (user_id, canvas_assignment_id) do update set"
    " lms_course_id = excluded.lms_course_id, title = excluded.title, due_at = excluded.due_at,"
    " html_url = excluded.html_url, submission_state = excluded.submission_state,"
    " submitted_at = excluded.submitted_at, removed_at = null"
    " returning id"
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
    # 가장 가까운 것 하나: 미제출 과제와 확정된 계획서 일정 중에서(명세 9장)
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
    # 정렬은 ordered()가 한다. DB의 정렬 규칙(collation)은 환경마다 달라서 순서를 맡기지 않는다
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
        """토큰을 즉시 지운다. 과목·과제 기록은 남기고 동기화만 멈춘다(명세 9장)."""
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
            if not is_canvas_id(canvas_id) or not name:
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

    async def active_courses(self, user_id: str) -> list[CourseRow]:
        """동기화할 과목. 수강을 뺀 과목(`is_active` false)은 더 받지 않는다."""
        rows = await self._rows(
            "select id, canvas_course_id, name from lms_courses"
            " where user_id = %s and coalesce(is_active, true)",
            (user_id,),
        )
        courses = [
            CourseRow(
                id=str(row["id"]),
                canvas_course_id=row["canvas_course_id"],
                short_name=course_name(row["name"]).short_name,
            )
            for row in rows
        ]
        return sorted(courses, key=lambda one: (one.short_name, one.canvas_course_id))

    async def save_assignments(
        self, user_id: str, course_id: str, items: list[CanvasAssignment], *, now: datetime
    ) -> AssignmentChanges:
        """한 과목의 과제를 저장하고 바뀐 것을 돌려준다.

        먼저 저장된 것을 한 번에 읽어 두고 비교한다. 새 과제·마감 변경·이번에 제출을 가려내려면
        예전 값이 필요한데, upsert의 `returning`은 바뀐 뒤 값만 준다.
        """
        before = {
            row["canvas_assignment_id"]: row
            for row in await self._rows(
                "select canvas_assignment_id, due_at, submission_state::text as submission_state,"
                " removed_at from lms_assignments where user_id = %s and lms_course_id = %s",
                (user_id, course_id),
            )
        }
        changes = AssignmentChanges()
        for item in items:
            row = await self._row(
                _UPSERT_ASSIGNMENT,
                {
                    "uid": user_id,
                    "course": course_id,
                    "canvas": item.canvas_assignment_id,
                    "title": item.title,
                    "due": item.due_at,
                    "url": item.html_url,
                    "state": item.submission_state,
                    "submitted": item.submitted_at,
                    "now": now,
                },
            )
            assert row is not None  # insert ... returning은 늘 한 행이다
            saved = SavedAssignment(
                id=str(row["id"]),
                title=item.title,
                due_at=item.due_at,
                submitted=item.submitted,
            )
            old = before.get(item.canvas_assignment_id)
            # 사라졌다 다시 나타난 과제도 "새 과제"다. 그 사이 할 일·알림이 없었다
            if old is None or old["removed_at"] is not None:
                changes.created.append(saved)
                continue
            if old["due_at"] != item.due_at:
                changes.due_changed.append(saved)
                if old["due_at"] is None:  # 마감이 없다가 생겼다 → 할 일이 있을 수 없다
                    changes.new_deadline.append(saved)
            if item.submitted and old["submission_state"] not in SUBMITTED:
                changes.submitted.append(saved.id)
        # 이번 목록에 없던 과제는 지운 것으로 본다(목록이 비어 와도 찍는다, 머리말)
        fetched = [item.canvas_assignment_id for item in items]
        cursor = await self.conn.execute(
            "update lms_assignments set removed_at = %(now)s"
            " where user_id = %(uid)s and lms_course_id = %(course)s and removed_at is null"
            " and not (canvas_assignment_id = any(%(ids)s::bigint[]))",
            {"uid": user_id, "course": course_id, "ids": fetched, "now": now},
        )
        return changes + AssignmentChanges(removed=max(cursor.rowcount, 0))

    async def sync_planner(self, user_id: str, changes: AssignmentChanges, *, now: datetime) -> int:
        """과제 할 일을 맞춘다(F-51·F-43). 만든 할 일 수를 돌려준다.

        - **이미 낸 과제는 할 일을 만들지 않는다**(SQL에서도 한 번 더 막는다). 연결하고 처음 받을 때
          지난 과제가 한꺼번에 들어온다
        - 새 과제와 **마감이 없다가 생긴 과제**는 할 일을 만든다(마감이 없으면 못 만든다 — `due_date`가
          not null). 마감이 값에서 값으로 바뀐 과제는 만들지 않는다 — PRD F-51은 "마감 변경 시 기존
          일정 수정"이고, 학생이 지운 할 일을 마감이 바뀔 때마다 되살리면 지울 수가 없다
        - 마감이 바뀌면 아직 끝내지 않은 할 일의 날짜만 고친다. 끝낸 할 일은 그대로 둔다
        - 제출한 과제의 할 일은 자동 완료다(PRD F-51)
        """
        # 거를 조건(마감 있음·아직 안 냄·사라지지 않음)은 아래 SQL 한 곳에만 둔다. 파이썬에서 한 번
        # 더 거르면 둘 중 하나가 틀려도 테스트가 알아채지 못한다
        fresh = [one.id for one in changes.created + changes.new_deadline]
        created = 0
        if fresh:
            cursor = await self.conn.execute(
                "insert into planner_tasks (user_id, source, lms_assignment_id, title, due_date)"
                " select a.user_id, 'lms_assignment', a.id, a.title,"
                " (a.due_at at time zone 'Asia/Seoul')::date from lms_assignments a"
                " where a.user_id = %(uid)s and a.id = any(%(ids)s::uuid[]) and a.due_at is not null"
                " and a.submission_state = 'unsubmitted' and a.removed_at is null"
                " and not exists (select 1 from planner_tasks t"
                "   where t.lms_assignment_id = a.id and t.user_id = a.user_id)",
                {"uid": user_id, "ids": fresh},
            )
            created = max(cursor.rowcount, 0)
        moved = [one.id for one in changes.due_changed if one.due_at is not None]
        if moved:
            await self.conn.execute(
                "update planner_tasks t set due_date = (a.due_at at time zone 'Asia/Seoul')::date,"
                " title = a.title from lms_assignments a"
                " where a.id = t.lms_assignment_id and a.user_id = t.user_id"
                " and t.user_id = %(uid)s"
                " and t.lms_assignment_id = any(%(ids)s::uuid[])"
                " and coalesce(t.is_done, false) = false and a.due_at is not null",
                {"uid": user_id, "ids": moved},
            )
        if changes.submitted:
            await self.conn.execute(
                "update planner_tasks set is_done = true, done_at = %(now)s"
                " where user_id = %(uid)s and lms_assignment_id = any(%(ids)s::uuid[])"
                " and coalesce(is_done, false) = false",
                {"uid": user_id, "ids": changes.submitted, "now": now},
            )
        return created

    async def claim_sync(self, user_id: str, *, now: datetime, before: datetime) -> bool:
        """동기화를 시작한다고 한 문장으로 못 박는다. 이미 누가 가져갔으면 False다.

        `last_synced_at`을 **시작할 때** 찍는다. 두 가지를 한꺼번에 막는다 —
        대시보드를 두 탭에서 열어 같은 사용자를 동시에 동기화하는 것(둘째는 False를 받는다),
        그리고 늘 실패하는 사용자가 배치 앞자리를 영구히 차지하는 것(실패해도 시각이 밀린다).
        성공·실패는 `status`·`last_error`로 본다(명세 9장).
        """
        cursor = await self.conn.execute(
            "update lms_connections set last_synced_at = %(now)s"
            " where user_id = %(uid)s and status <> 'disconnected'"
            " and (last_synced_at is null or last_synced_at <= %(before)s)",
            {"uid": user_id, "now": now, "before": before},
        )
        return cursor.rowcount > 0

    async def touch_synced(self, user_id: str, *, now: datetime) -> None:
        """잘 받았다고 적는다. 오류 표시를 지운다.

        시각을 **뒤로 돌리지 않는다** — 느린 동기화가 뒤에 시작한 동기화의 자리(`claim_sync`)를
        지워 버리면 같은 사용자를 또 동기화하게 되고, 그 사이 찍힌 오류 표시도 사라진다.
        해제한 연결은 건드리지 않는다.
        """
        await self.conn.execute(
            "update lms_connections set last_synced_at = %(now)s, status = 'active',"
            " last_error = null"
            " where user_id = %(uid)s and status <> 'disconnected'"
            " and (last_synced_at is null or last_synced_at <= %(now)s)",
            {"uid": user_id, "now": now},
        )

    async def connected_users(self, *, before: datetime, limit: int) -> list[str]:
        """동기화할 사용자(30분 배치). 오래 안 한 사람부터 본다.

        `before` 뒤에 이미 동기화한(또는 동기화를 시작한) 사람은 건너뛴다. 오류 상태도 넣는다 —
        토큰이 되살아나면 거기서 풀린다. 해제한 사람은 토큰이 없어 빠진다. 실패해도 `claim_sync`가
        시각을 밀어 두므로 한 사람이 앞자리를 계속 차지하지 않는다.
        """
        rows = await self._rows(
            "select user_id from lms_connections"
            " where status <> 'disconnected'"
            " and (last_synced_at is null or last_synced_at <= %(before)s)"
            " order by coalesce(last_synced_at, to_timestamp(0)), user_id limit %(limit)s",
            {"before": before, "limit": limit},
        )
        return [str(row["user_id"]) for row in rows]

    async def assignments(
        self, user_id: str, *, state: str = "open", course_id: str | None = None
    ) -> list[AssignmentItem]:
        """과제 목록(명세 9장). LMS에서 사라진 과제는 어느 state에도 넣지 않는다."""
        query = _ASSIGNMENTS + _STATE_FILTERS[state]
        params: dict[str, Any] = {"uid": user_id}
        if course_id is not None:
            query += " and a.lms_course_id = %(course)s"
            params["course"] = course_id
        return by_due([_assignment(row) for row in await self._rows(query, params)])

    async def courses(self, user_id: str, *, now: datetime) -> list[CourseItem]:
        rows = await self._rows(_COURSES, {"uid": user_id, "now": now})
        return ordered([_course(row) for row in rows])

    # ── 조회 ────────────────────────────────────────────────────────────────

    async def _rows(self, query: str, params: Any) -> list[dict[str, Any]]:
        return await (await self.conn.execute(query, params)).fetchall()

    async def _row(self, query: str, params: Any) -> dict[str, Any] | None:
        return await (await self.conn.execute(query, params)).fetchone()


def ordered(items: list[CourseItem]) -> list[CourseItem]:
    """화면 이름 순. 같은 이름이면 과목명으로 가른다.

    DB에 `order by`를 맡기지 않는다 — 정렬 규칙(collation)이 환경마다 달라서 한글과 숫자의 앞뒤가
    바뀐다(2026-10-16 CI에서 걸렸다). 파이썬 글자 코드 순으로 정하면 어디서나 같다.
    """
    return sorted(items, key=lambda one: (one.short_name, one.name))


def by_due(items: list[AssignmentItem]) -> list[AssignmentItem]:
    """마감이 가까운 순. 마감이 없는 과제는 뒤로 보낸다.

    `ordered()`와 같은 이유로 DB에 맡기지 않는다(정렬 규칙이 환경마다 다르다).
    """
    return sorted(
        items, key=lambda one: (one.due_at is None, one.due_at or _FAR, one.title, one.id)
    )


def _assignment(row: dict[str, Any]) -> AssignmentItem:
    return AssignmentItem(
        id=str(row["id"]),
        course=AssignmentCourse(
            id=str(row["course_id"]), short_name=course_name(row["course_name"]).short_name
        ),
        title=row["title"],
        due_at=row["due_at"].astimezone(KST) if row["due_at"] else None,
        submission_state=row["submission_state"],
        html_url=row["html_url"],
        planner_task_id=str(row["planner_task_id"]) if row["planner_task_id"] else None,
        calendar_registered=row["calendar_registered"],
    )


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
