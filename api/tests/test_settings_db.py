"""알림·캘린더 설정 SQL(명세 4장 `GET`·`PATCH /me/settings`)을 실제 스키마에 대고 확인한다.

설정 행은 없을 수 있다(그때는 DB 기본값이 답이다). 트랜잭션을 되돌려 지운다.
"""

from typing import Any

import psycopg
import pytest

from app.repositories.profiles import ProfileRepository
from tests.db_world import DATABASE_URL, connect, make_user

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


@pytest.fixture
async def world() -> Any:
    conn = await connect()
    try:
        yield {
            "repo": ProfileRepository(conn),
            "conn": conn,
            "me": await make_user(conn),
            "other": await make_user(conn),
        }
    finally:
        await conn.rollback()
        await conn.close()


async def test_settings_without_a_row_are_the_db_defaults(world: dict[str, Any]) -> None:
    """온보딩만 한 사용자는 설정 행이 없다. 그래도 답은 기본값이어야 한다."""
    repo, me, conn = world["repo"], world["me"], world["conn"]
    row = await (
        await conn.execute("select count(*) as n from user_settings where user_id = %s", (me,))
    ).fetchone()
    assert row["n"] == 0

    found = await repo.get_settings(me)
    assert (found.push_enabled, found.calendar_auto_lms) == (True, True)
    assert found.muted_notification_types == []


async def test_the_first_change_creates_the_row(world: dict[str, Any]) -> None:
    repo, me, conn = world["repo"], world["me"], world["conn"]
    changed = await repo.update_settings(me, {"calendar_auto_lms": False})
    assert changed.calendar_auto_lms is False
    assert changed.push_enabled is True  # 나머지는 기본값 그대로다

    row = await (
        await conn.execute(
            "select push_enabled, calendar_auto_lms, muted_notification_types"
            " from user_settings where user_id = %s",
            (me,),
        )
    ).fetchone()
    assert (row["push_enabled"], row["calendar_auto_lms"]) == (True, False)
    assert row["muted_notification_types"] == []


async def test_changes_pile_up(world: dict[str, Any]) -> None:
    repo, me = world["repo"], world["me"]
    await repo.update_settings(me, {"calendar_auto_lms": False})
    await repo.update_settings(me, {"muted_notification_types": ["new_material"]})
    await repo.update_settings(me, {"push_enabled": False})

    found = await repo.get_settings(me)
    assert found.calendar_auto_lms is False
    assert found.muted_notification_types == ["new_material"]
    assert found.push_enabled is False


async def test_an_empty_list_clears_the_muted_kinds(world: dict[str, Any]) -> None:
    repo, me = world["repo"], world["me"]
    await repo.update_settings(me, {"muted_notification_types": ["new_material", "task_due"]})
    cleared = await repo.update_settings(me, {"muted_notification_types": []})
    assert cleared.muted_notification_types == []


async def test_an_unknown_kind_is_refused_by_the_database(world: dict[str, Any]) -> None:
    """라우터가 먼저 막지만, DB의 check 제약도 같은 목록을 본다(둘이 어긋나면 여기서 터진다)."""
    repo, me = world["repo"], world["me"]
    with pytest.raises(psycopg.errors.CheckViolation):
        await repo.update_settings(me, {"muted_notification_types": ["new_friend"]})
    await world["conn"].rollback()


async def test_every_kind_the_api_accepts_is_storable(world: dict[str, Any]) -> None:
    """스키마의 Literal과 DB check 제약이 같은지 한 번에 본다."""
    from app.schemas.me import NotificationType

    kinds = list(NotificationType.__args__)  # type: ignore[attr-defined]
    saved = await world["repo"].update_settings(world["me"], {"muted_notification_types": kinds})
    assert saved.muted_notification_types == kinds


async def test_my_settings_are_not_someone_elses(world: dict[str, Any]) -> None:
    repo, me, other = world["repo"], world["me"], world["other"]
    await repo.update_settings(me, {"push_enabled": False, "calendar_auto_lms": False})

    theirs = await repo.get_settings(other)
    assert (theirs.push_enabled, theirs.calendar_auto_lms) == (True, True)
    await repo.update_settings(other, {"push_enabled": True})
    mine = await repo.get_settings(me)
    assert mine.push_enabled is False  # 남의 변경이 내 설정을 건드리지 않는다
