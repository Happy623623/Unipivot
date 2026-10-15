"""캘린더 등록 기록 SQL (F-32, ERD calendar_events).

사용자 것만 읽고 쓴다. 같은 공고를 두 번 눌러도 등록은 하나다((user_id, provider, opportunity_id) 유니크).
Google access token은 oauth_tokens에 암호화해 두고, 만료가 가까우면 갱신해 다시 넣는다.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends
from psycopg import AsyncConnection

from app.db import get_conn
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
class OpportunityDeadline:
    id: str
    title: str
    deadline_at: datetime | None


def _event(row: dict) -> CalendarEventView:
    return CalendarEventView(
        id=row["id"],
        provider=row["provider"],
        external_event_id=row["external_event_id"],
        title=row["title"],
        starts_at=row["starts_at"],
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

    async def event_for(
        self, user_id: str, opportunity_id: str, provider: str
    ) -> CalendarEventView | None:
        row = await (
            await self.conn.execute(
                _EVENT + " where user_id = %s and opportunity_id = %s and provider = %s",
                (user_id, opportunity_id, provider),
            )
        ).fetchone()
        return None if row is None else _event(row)

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
        opportunity_id: str,
        title: str,
        starts_at: datetime,
    ) -> CalendarEventView:
        """Google을 부르기 전에 자리를 먼저 잡는다(external_event_id는 아직 비어 있다).

        Google에 넣고 나서 기록하면, 넣은 응답을 받지 못했을 때 기록이 없어 다시 누르면 캘린더에 일정이
        두 개가 된다. 자리를 먼저 잡으면 그 행의 id로 Google 일정 번호를 정할 수 있어, 다시 눌러도 같은
        번호로 들어간다(두 요청이 겹쳐도 진 쪽이 이긴 쪽의 행을 그대로 쓴다).
        """
        row = await (
            await self.conn.execute(
                "insert into calendar_events (user_id, provider, opportunity_id, title,"
                " starts_at, all_day) values (%s, %s, %s, %s, %s, false)"
                " on conflict (user_id, provider, opportunity_id) where opportunity_id is not null"
                " do nothing returning id::text as id",
                (user_id, provider, opportunity_id, title, starts_at),
            )
        ).fetchone()
        if row is None:  # 그새 다른 요청이 잡았다(또는 앞 요청이 끝내지 못하고 남겼다)
            existing = await self.event_for(user_id, opportunity_id, provider)
            assert existing is not None
            return existing
        found = await self.one(user_id, row["id"])
        assert found is not None
        return found

    async def attach(self, user_id: str, event_id: str, external_event_id: str) -> None:
        """Google에 넣고 나서 그 번호를 기록에 붙인다."""
        await self.conn.execute(
            "update calendar_events set external_event_id = %s, synced_at = now()"
            " where id = %s and user_id = %s",
            (external_event_id, event_id, user_id),
        )

    async def remove(self, user_id: str, event_id: str) -> None:
        await self.conn.execute(
            "delete from calendar_events where id = %s and user_id = %s", (event_id, user_id)
        )


def get_calendar_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> CalendarRepository:
    return CalendarRepository(conn)


CalendarRepoDep = Annotated[CalendarRepository, Depends(get_calendar_repo)]
