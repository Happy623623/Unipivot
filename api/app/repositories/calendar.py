"""캘린더 등록 기록 SQL (F-32, ERD calendar_events).

사용자 것만 읽고 쓴다. 같은 공고를 두 번 눌러도 등록은 하나다((user_id, provider, opportunity_id) 유니크).
Google access token은 oauth_tokens에 암호화해 두고, 만료가 가까우면 갱신해 다시 넣는다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends
from psycopg import AsyncConnection, sql

from app.db import get_conn
from app.eligibility import KST
from app.lms.parse import course_name
from app.repositories.opportunities import PREP_DONE
from app.schemas.calendar import CalendarEventView

# 남은 시간이 이보다 적으면 미리 갱신한다(요청 도중에 만료되지 않게)
REFRESH_MARGIN_SECONDS = 120


@dataclass(frozen=True)
class GoogleTokens:
    access_token: str | None  # 암호화된 값
    refresh_token: str | None
    expires_at: datetime | None

    def expired(self, now: datetime) -> bool:
        if not self.access_token or self.expires_at is None:
            return True
        return (self.expires_at - now).total_seconds() <= REFRESH_MARGIN_SECONDS


@dataclass(frozen=True)
class AssignmentDeadline:
    """캘린더에 넣을 LMS 과제(F-51). 제목에 과목 이름을 붙이려고 함께 읽는다."""

    id: str
    title: str
    course: str  # 과목 화면 이름(`short_name`)
    due_at: datetime | None


@dataclass(frozen=True)
class SyllabusDeadline:
    """캘린더에 넣을 계획서 일정(F-14). 제목에 과목 이름을 붙이려고 함께 읽는다."""

    id: str
    title: str
    course: str | None  # 과목을 붙이지 않은 계획서면 None이다
    item_type: str
    starts_at: datetime | None


@dataclass(frozen=True)
class OpportunityDeadline:
    id: str
    title: str
    deadline_at: datetime | None


def _target(
    opportunity_id: str | None,
    lms_assignment_id: str | None,
    syllabus_item_id: str | None = None,
) -> tuple[str, str]:
    """일정이 가리키는 대상 한 개(칸 이름, 값). 둘 이상 주거나 다 비우면 코드 잘못이다."""
    given = [
        ("opportunity_id", opportunity_id),
        ("lms_assignment_id", lms_assignment_id),
        ("syllabus_item_id", syllabus_item_id),
    ]
    found = [(column, value) for column, value in given if value is not None]
    if len(found) != 1:
        raise ValueError("일정 대상은 공고·LMS 과제·계획서 일정 중 하나여야 해요")
    return found[0]


def _event(row: dict) -> CalendarEventView:
    return CalendarEventView(
        id=row["id"],
        provider=row["provider"],
        external_event_id=row["external_event_id"],
        title=row["title"],
        starts_at=row["starts_at"].astimezone(KST),  # 화면은 KST다(명세 1장)
        all_day=row["all_day"],
    )


_EVENT = (
    "select id::text as id, provider::text as provider, external_event_id, title, starts_at,"
    " coalesce(all_day, false) as all_day from calendar_events"
)


class CalendarRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def tokens(self, user_id: str) -> GoogleTokens | None:
        row = await (
            await self.conn.execute(
                "select access_token, refresh_token, expires_at from oauth_tokens"
                " where user_id = %s and provider = 'google'",
                (user_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return GoogleTokens(row["access_token"], row["refresh_token"], row["expires_at"])

    async def save_access_token(self, user_id: str, encrypted: str, expires_in: int) -> None:
        """갱신한 access token. refresh token은 그대로 둔다(Google이 다시 주지 않는다)."""
        await self.conn.execute(
            "update oauth_tokens set access_token = %s,"
            " expires_at = now() + make_interval(secs => %s)"
            " where user_id = %s and provider = 'google'",
            (encrypted, expires_in, user_id),
        )

    async def prepared_opportunity(
        self, user_id: str, opportunity_id: str
    ) -> OpportunityDeadline | None:
        """준비를 마친 공고만 캘린더에 넣는다. 아니면 None(화면이 준비하기를 먼저 시킨다)."""
        row = await (
            await self.conn.execute(
                "select o.id::text as id, o.title, o.deadline_at from prep_plans p"
                " join opportunities o on o.id = p.opportunity_id"
                " where p.user_id = %(uid)s and p.opportunity_id = %(oid)s and " + PREP_DONE,
                {"uid": user_id, "oid": opportunity_id},
            )
        ).fetchone()
        if row is None:
            return None
        return OpportunityDeadline(row["id"], row["title"], row["deadline_at"])

    async def assignment_deadline(
        self, user_id: str, assignment_id: str
    ) -> AssignmentDeadline | None:
        """내 과제의 마감. LMS에서 사라진 과제와 수강을 뺀 과목은 None이다(F-51)."""
        row = await (
            await self.conn.execute(
                "select a.id::text as id, a.title, c.name as course_name, a.due_at"
                " from lms_assignments a"
                " join lms_courses c on c.id = a.lms_course_id and c.user_id = a.user_id"
                " where a.id = %(aid)s and a.user_id = %(uid)s and a.removed_at is null"
                "   and coalesce(c.is_active, true)",
                {"aid": assignment_id, "uid": user_id},
            )
        ).fetchone()
        if row is None:
            return None
        return AssignmentDeadline(
            id=row["id"],
            title=row["title"],
            course=course_name(row["course_name"]).short_name,
            due_at=row["due_at"],
        )

    async def syllabus_deadline(self, user_id: str, item_id: str) -> SyllabusDeadline | None:
        """내 계획서 일정 하나(F-14). 남의 계획서·없는 일정은 None이다.

        **확인한 일정만** 캘린더에 넣을 수 있다 — 아직 확인 전인 추출 결과는 날짜가 틀릴 수 있다.
        """
        row = await (
            await self.conn.execute(
                "select i.id::text as id, i.title, i.starts_at, i.item_type::text as item_type,"
                # 과목 이름은 **LMS 과목명을 먼저** 쓴다. 확정 경로(repositories/syllabi.py의 one)와
                # 같은 기준이어야 같은 일정이 어느 길로 들어와도 제목이 같다
                " coalesce(c.name, s.course_name) as course_name"
                " from syllabus_items i"
                " join syllabi s on s.id = i.syllabus_id"
                " left join lms_courses c on c.id = s.lms_course_id and c.user_id = s.user_id"
                " where i.id = %(iid)s and s.user_id = %(uid)s and coalesce(i.is_confirmed, false)",
                {"iid": item_id, "uid": user_id},
            )
        ).fetchone()
        if row is None:
            return None
        return SyllabusDeadline(
            id=row["id"],
            title=row["title"],
            course=course_name(row["course_name"]).short_name if row["course_name"] else None,
            item_type=row["item_type"],
            starts_at=row["starts_at"],
        )

    async def event_for(
        self,
        user_id: str,
        provider: str,
        *,
        opportunity_id: str | None = None,
        lms_assignment_id: str | None = None,
        syllabus_item_id: str | None = None,
    ) -> CalendarEventView | None:
        """그 대상에 이미 잡아 둔 일정. 대상은 공고·과제·계획서 일정 하나다."""
        column, target = _target(opportunity_id, lms_assignment_id, syllabus_item_id)
        row = await (
            await self.conn.execute(
                sql.SQL(
                    _EVENT + " where user_id = %(uid)s and {column} = %(target)s"
                    " and provider = %(provider)s"
                ).format(column=sql.Identifier(column)),
                {"uid": user_id, "target": target, "provider": provider},
            )
        ).fetchone()
        return None if row is None else _event(row)

    async def events_for_assignments(
        self, user_id: str, assignment_ids: Sequence[str], provider: str = "google"
    ) -> dict[str, CalendarEventView]:
        """과제 id → 이미 잡아 둔 일정(마감이 바뀐 과제의 시각을 고칠 때 쓴다)."""
        if not assignment_ids:
            return {}
        rows = await (
            await self.conn.execute(
                "select id::text as id, provider::text as provider, external_event_id, title,"
                " starts_at, coalesce(all_day, false) as all_day,"
                " lms_assignment_id::text as assignment_id from calendar_events"
                " where user_id = %(uid)s and provider = %(provider)s"
                "   and lms_assignment_id = any(%(ids)s::uuid[])",
                {"uid": user_id, "provider": provider, "ids": list(assignment_ids)},
            )
        ).fetchall()
        return {row["assignment_id"]: _event(row) for row in rows}

    async def one(self, user_id: str, event_id: str) -> CalendarEventView | None:
        row = await (
            await self.conn.execute(_EVENT + " where id = %s and user_id = %s", (event_id, user_id))
        ).fetchone()
        return None if row is None else _event(row)

    async def reserve(
        self,
        user_id: str,
        *,
        provider: str,
        title: str,
        starts_at: datetime,
        opportunity_id: str | None = None,
        lms_assignment_id: str | None = None,
        syllabus_item_id: str | None = None,
    ) -> CalendarEventView:
        """Google을 부르기 전에 자리를 먼저 잡는다(external_event_id는 아직 비어 있다).

        Google에 넣고 나서 기록하면, 넣은 응답을 받지 못했을 때 기록이 없어 다시 누르면 캘린더에 일정이
        두 개가 된다. 자리를 먼저 잡으면 그 행의 id로 Google 일정 번호를 정할 수 있어, 다시 눌러도 같은
        번호로 들어간다(두 요청이 겹쳐도 진 쪽이 이긴 쪽의 행을 그대로 쓴다).
        """
        column, target = _target(opportunity_id, lms_assignment_id, syllabus_item_id)
        row = await (
            await self.conn.execute(
                sql.SQL(
                    "insert into calendar_events (user_id, provider, {column}, title,"
                    " starts_at, all_day) values (%(uid)s, %(provider)s, %(target)s, %(title)s,"
                    " %(starts)s, false)"
                    " on conflict (user_id, provider, {column}) where {column} is not null"
                    # 넣다 만 자리는 제목·시각을 새로 맞춘다. 이미 Google에 들어간 일정은
                    # 여기서 바꾸면 기록과 캘린더가 어긋나므로 그대로 두고 아래에서 읽어 온다
                    " do update set title = excluded.title, starts_at = excluded.starts_at"
                    "   where calendar_events.external_event_id is null"
                    " returning id::text as id"
                ).format(column=sql.Identifier(column)),
                {
                    "uid": user_id,
                    "provider": provider,
                    "target": target,
                    "title": title,
                    "starts": starts_at,
                },
            )
        ).fetchone()
        if row is None:  # 그새 다른 요청이 잡았다(또는 앞 요청이 끝내지 못하고 남겼다)
            existing = await self.event_for(
                user_id,
                provider,
                opportunity_id=opportunity_id,
                lms_assignment_id=lms_assignment_id,
                syllabus_item_id=syllabus_item_id,
            )
            assert existing is not None
            return existing
        found = await self.one(user_id, row["id"])
        assert found is not None
        return found

    async def commit_reservation(self) -> None:
        """잡아 둔 자리를 먼저 확정한다. Google 호출 **전에** 부른다.

        요청 커넥션은 예외가 나면 통째로 롤백된다. 그대로 두면 Google이 502일 때 자리까지 사라져서,
        다시 누르면 새 행·새 일정 번호가 되고 캘린더에 같은 마감이 두 개 들어간다.
        """
        await self.conn.commit()

    async def unfinished_assignment_events(
        self, user_id: str, provider: str = "google"
    ) -> list[AssignmentDeadline]:
        """자리는 잡았는데 Google에 넣지 못한 과제 일정(다음 동기화가 다시 시도한다).

        앞 동기화에서 Google이 잠깐 막혔으면 `external_event_id`가 빈 행만 남는다. 그 과제는
        다음부터 "새 과제"도 "마감 바뀐 과제"도 아니라서, 여기서 줍지 않으면 영영 들어가지 않는다.
        사라진 과제·수강을 뺀 과목·마감이 없어진 과제는 뺀다.
        """
        rows = await (
            await self.conn.execute(
                "select a.id::text as id, a.title, c.name as course_name, a.due_at"
                " from calendar_events e"
                " join lms_assignments a on a.id = e.lms_assignment_id and a.user_id = e.user_id"
                " join lms_courses c on c.id = a.lms_course_id and c.user_id = a.user_id"
                " where e.user_id = %(uid)s and e.provider = %(provider)s"
                "   and e.lms_assignment_id is not null and e.external_event_id is null"
                "   and a.removed_at is null and coalesce(c.is_active, true)"
                "   and a.due_at is not null",
                {"uid": user_id, "provider": provider},
            )
        ).fetchall()
        return [
            AssignmentDeadline(
                id=row["id"],
                title=row["title"],
                course=course_name(row["course_name"]).short_name,
                due_at=row["due_at"],
            )
            for row in rows
        ]

    async def attach(self, user_id: str, event_id: str, external_event_id: str) -> None:
        """Google에 넣고 나서 그 번호를 기록에 붙인다."""
        await self.conn.execute(
            "update calendar_events set external_event_id = %s, synced_at = now()"
            " where id = %s and user_id = %s",
            (external_event_id, event_id, user_id),
        )

    async def move(
        self, user_id: str, event_id: str, *, starts_at: datetime, title: str | None = None
    ) -> None:
        """마감이 바뀌어 일정 시각을 고쳤다(Google에 고친 뒤 기록도 맞춘다).

        제목까지 달라졌으면(계획서 일정을 고쳐 다시 확정) 함께 맞춘다. 비우면 제목은 그대로다.
        """
        await self.conn.execute(
            "update calendar_events set starts_at = %(starts)s,"
            " title = coalesce(%(title)s, title), synced_at = now()"
            " where id = %(id)s and user_id = %(uid)s",
            {"starts": starts_at, "title": title, "id": event_id, "uid": user_id},
        )

    async def auto_lms(self, user_id: str) -> bool:
        """LMS 과제 마감을 자동으로 넣을지(설정, 기본 켬). 설정 행이 없으면 기본값이다."""
        row = await (
            await self.conn.execute(
                "select calendar_auto_lms from user_settings where user_id = %s", (user_id,)
            )
        ).fetchone()
        return True if row is None else bool(row["calendar_auto_lms"])

    async def remove(self, user_id: str, event_id: str) -> None:
        await self.conn.execute(
            "delete from calendar_events where id = %s and user_id = %s", (event_id, user_id)
        )


def get_calendar_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> CalendarRepository:
    return CalendarRepository(conn)


CalendarRepoDep = Annotated[CalendarRepository, Depends(get_calendar_repo)]
