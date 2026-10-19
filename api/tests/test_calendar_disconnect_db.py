"""캘린더 연결 해제 SQL (F-06). DATABASE_URL이 있을 때만 돈다.

토큰 행을 지우면 `GET /me`의 `calendar_connected`가 false가 되고, 남의 토큰은 건드리지 않으며,
없는 행을 지워도 조용하다(두 번 눌러도 같다). 트랜잭션을 되돌려 흔적을 남기지 않는다.
"""

from typing import Any

import pytest

from app.repositories.calendar import CalendarRepository
from app.repositories.profiles import ProfileRepository
from tests.db_world import DATABASE_URL, connect, make_user

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


@pytest.fixture
async def connected() -> Any:
    """캘린더를 연결한 사용자 둘."""
    conn = await connect()
    try:
        profiles = ProfileRepository(conn)
        user = await make_user(conn)
        other = await make_user(conn)
        for someone in (user, other):
            await profiles.save_google_tokens(someone, "enc-access", "enc-refresh")
        yield CalendarRepository(conn), profiles, user, other
    finally:
        await conn.rollback()
        await conn.close()


async def _connected(profiles: ProfileRepository, user_id: str) -> bool:
    me = await profiles.get_me(user_id)
    assert me is not None
    return me.calendar_connected


async def test_deleting_tokens_disconnects_only_that_user(connected: Any) -> None:
    calendar, profiles, user, other = connected
    assert await _connected(profiles, user) and await _connected(profiles, other)

    assert await calendar.delete_tokens(user) is True
    assert await calendar.tokens(user) is None
    assert not await _connected(profiles, user)
    assert await _connected(profiles, other)  # 남의 연결은 그대로다

    assert await calendar.delete_tokens(user) is False  # 두 번째는 지울 것이 없다
