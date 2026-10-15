"""캘린더 기록 SQL(F-32)을 실제 스키마에 대고 확인한다: 토큰, 준비한 공고, 등록·중복·취소·격리.

트랜잭션을 되돌려 지운다. DATABASE_URL이 있을 때만 돈다.
"""

from datetime import timedelta
from typing import Any

import pytest

from app.eligibility import KST
from app.repositories.calendar import CalendarRepository
from app.repositories.opportunities import OpportunityRepository
from tests.db_world import DATABASE_URL, World, connect, make_user

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


@pytest.fixture
async def calendar() -> Any:
    """준비를 마친 공고 하나와 준비하지 않은 공고 하나, 사용자 둘."""
    conn = await connect()
    try:
        world = await World.start(conn)
        prepared = await world.add("준비한 장학", days=9)
        bare = await world.add("준비 안 한 장학", days=9)
        user = await make_user(conn, grade=3)
        other = await make_user(conn, grade=3)
        run = await (
            await conn.execute(
                "insert into agent_runs (user_id, trigger_type, status)"
                " values (%s, 'prepare', 'succeeded') returning id",
                (user,),
            )
        ).fetchone()
        await conn.execute(
            "insert into prep_plans (user_id, opportunity_id, agent_run_id) values (%s, %s, %s)",
            (user, prepared, run["id"]),
        )
        yield CalendarRepository(conn), user, other, prepared, bare, world.now
    finally:
        await conn.rollback()
        await conn.close()


async def test_only_a_prepared_opportunity_is_offered(calendar: Any) -> None:
    repo, user, other, prepared, bare, now = calendar
    found = await repo.prepared_opportunity(user, prepared)
    assert found is not None and found.title == "준비한 장학"
    assert found.deadline_at is not None
    assert await repo.prepared_opportunity(user, bare) is None  # 준비하지 않은 공고
    assert await repo.prepared_opportunity(other, prepared) is None  # 남의 계획


async def test_a_running_plan_is_not_prepared_yet(calendar: Any) -> None:
    """상세·플래너와 같은 기준(PREP_DONE)이다. 실행 중인 계획은 캘린더에도 넣지 못한다."""
    repo, user, _, prepared, _, _ = calendar
    await repo.conn.execute(
        "update agent_runs set status = 'running' where id ="
        " (select agent_run_id from prep_plans where user_id = %s and opportunity_id = %s)",
        (user, prepared),
    )
    assert await repo.prepared_opportunity(user, prepared) is None


async def test_reserve_is_one_per_opportunity(calendar: Any) -> None:
    """자리는 공고마다 하나다. 두 번째 요청은 같은 행을 돌려받아 같은 Google 번호를 쓴다."""
    repo, user, _, prepared, _, now = calendar
    ends_at = (now + timedelta(days=9)).astimezone(KST)
    event = await repo.reserve(
        user,
        provider="google",
        opportunity_id=prepared,
        title="[마감] 준비한 장학",
        starts_at=ends_at - timedelta(hours=1),
    )
    assert (event.provider, event.external_event_id, event.all_day) == ("google", None, False)
    again = await repo.reserve(
        user,
        provider="google",
        opportunity_id=prepared,
        title="[마감] 준비한 장학",
        starts_at=ends_at - timedelta(hours=1),
    )
    assert again.id == event.id
    await repo.attach(user, event.id, "gcal-1")
    done = await repo.one(user, event.id)
    assert done is not None and done.external_event_id == "gcal-1"
    rows = await (
        await repo.conn.execute(
            "select count(*) as n from calendar_events where user_id = %s", (user,)
        )
    ).fetchone()
    assert rows["n"] == 1


async def test_find_and_remove(calendar: Any) -> None:
    repo, user, other, prepared, _, now = calendar
    ends_at = (now + timedelta(days=9)).astimezone(KST)
    event = await repo.reserve(
        user,
        provider="google",
        opportunity_id=prepared,
        title="[마감] 준비한 장학",
        starts_at=ends_at - timedelta(hours=1),
    )
    await repo.attach(user, event.id, "gcal-1")
    assert (await repo.event_for(user, prepared, "google")).id == event.id
    assert await repo.event_for(user, prepared, "ics") is None
    assert await repo.one(other, event.id) is None  # 남의 일정은 안 보인다
    await repo.remove(other, event.id)  # 남의 일정은 못 지운다
    assert await repo.one(user, event.id) is not None
    await repo.remove(user, event.id)
    assert await repo.one(user, event.id) is None


async def test_tokens_are_read_and_the_access_token_is_replaced(calendar: Any) -> None:
    repo, user, _, _, _, _ = calendar
    assert await repo.tokens(user) is None  # 연결 전
    await repo.conn.execute(
        "insert into oauth_tokens (user_id, provider, access_token, refresh_token, expires_at)"
        " values (%s, 'google', 'enc-access', 'enc-refresh', now() + interval '55 minutes')",
        (user,),
    )
    tokens = await repo.tokens(user)
    assert tokens is not None
    assert (tokens.access_token, tokens.refresh_token) == ("enc-access", "enc-refresh")
    await repo.save_access_token(user, "enc-new", 3599)
    after = await repo.tokens(user)
    assert after is not None
    assert after.access_token == "enc-new"
    assert after.refresh_token == "enc-refresh"  # refresh token은 그대로 둔다
    assert after.expires_at is not None and not after.expired(after.expires_at - timedelta(hours=1))


async def test_a_reserved_event_is_not_shown_as_registered(calendar: Any) -> None:
    """Google에 넣기 전의 자리는 공고 상세에서 '등록됨'으로 보이지 않는다(F-32).

    보이면 학생이 "캘린더에서 빼기"만 누를 수 있고, 실제로는 캘린더에 아무것도 없다.
    """
    repo, user, _, prepared, _, now = calendar
    ends_at = (now + timedelta(days=9)).astimezone(KST)
    event = await repo.reserve(
        user,
        provider="google",
        opportunity_id=prepared,
        title="[마감] 준비한 장학",
        starts_at=ends_at - timedelta(hours=1),
    )
    detail = await OpportunityRepository(repo.conn).detail(
        user, prepared, now=now, display_name="테스트 학생"
    )
    assert detail is not None and detail.prep.calendar_events == []
    await repo.attach(user, event.id, "gcal-1")
    after = await OpportunityRepository(repo.conn).detail(
        user, prepared, now=now, display_name="테스트 학생"
    )
    assert after is not None
    assert [ref.id for ref in after.prep.calendar_events] == [event.id]
