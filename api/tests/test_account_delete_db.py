"""탈퇴 SQL (ERD 7장). DATABASE_URL이 있을 때만 돈다.

profiles 행 하나를 지우면 딸린 행(토큰·설정·파일 기록·알림·플래너·구독·판정)이 cascade로 사라지고,
공유 포스터 공고는 남되 업로더가 null이 되며, 실행 로그는 남되 사용자가 null이 된다. 남의 행은 그대로다.
트랜잭션을 되돌려 흔적을 남기지 않는다.
"""

from typing import Any

import pytest

from app.repositories.files import FileRepository
from app.repositories.profiles import ProfileRepository
from tests.db_world import DATABASE_URL, World, connect, make_user

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


async def _count(conn: Any, table: str, column: str, user_id: str) -> int:
    row = await (
        await conn.execute(f"select count(*) from {table} where {column} = %s", (user_id,))  # noqa: S608
    ).fetchone()
    return row["count"]


@pytest.fixture
async def seeded() -> Any:
    """탈퇴할 사용자와 남을 사용자. 탈퇴할 사용자에게 딸린 행을 종류별로 하나씩 둔다."""
    conn = await connect()
    try:
        world = await World.start(conn)
        me = await make_user(conn, grade=3)
        other = await make_user(conn, grade=3)
        profiles = ProfileRepository(conn)
        for someone in (me, other):
            await profiles.save_google_tokens(someone, "enc-a", "enc-r")
            await conn.execute(
                "insert into files (user_id, kind, origin, storage_path, sha256)"
                " values (%s, 'poster', 'upload', %s, %s)",
                (someone, f"{someone}/poster/one.png", "a" * 64),
            )
            await conn.execute(
                "insert into push_subscriptions (user_id, endpoint, p256dh, auth)"
                " values (%s, %s, 'p', 'a')",
                (someone, f"https://push.example/{someone}"),
            )
            await conn.execute(
                "insert into planner_tasks (user_id, title, due_date, source)"
                " values (%s, '할 일', '2026-11-01', 'manual')",
                (someone,),
            )
        await conn.execute(  # 탈퇴할 사용자는 파일이 둘이다(경로를 전부 주는지 본다)
            "insert into files (user_id, kind, origin, storage_path, sha256)"
            " values (%s, 'syllabus', 'upload', %s, %s)",
            (me, f"{me}/syllabus/two.pdf", "b" * 64),
        )
        poster = await world.add("내 포스터", days=20, source_type="poster", uploaded_by=me)
        run = await (
            await conn.execute(
                "insert into agent_runs (user_id, trigger_type, status)"
                " values (%s, 'prepare', 'succeeded') returning id",
                (me,),
            )
        ).fetchone()
        yield conn, profiles, me, other, poster, run["id"]
    finally:
        await conn.rollback()
        await conn.close()


async def test_deleting_a_profile_takes_its_rows_and_leaves_shared_things(seeded: Any) -> None:
    conn, profiles, me, other, poster, run_id = seeded
    assert await FileRepository(conn).storage_paths(me) == [
        f"{me}/poster/one.png",
        f"{me}/syllabus/two.pdf",
    ]
    assert await FileRepository(conn).storage_paths(other) == [f"{other}/poster/one.png"]

    assert await profiles.delete(me) is True
    assert await profiles.get_me(me) is None
    seeded_tables = ("oauth_tokens", "files", "push_subscriptions", "planner_tasks")
    for table in (*seeded_tables, "eligibility_results", "user_settings"):
        assert await _count(conn, table, "user_id", me) == 0, table
    for table in seeded_tables:
        assert await _count(conn, table, "user_id", other) == 1, table  # 남의 행은 그대로다

    # 공유 포스터 공고는 남되 업로더가 비고, 실행 로그는 남되 사용자가 빈다
    row = await (
        await conn.execute(
            "select uploaded_by, status::text from opportunities where id = %s", (poster,)
        )
    ).fetchone()
    assert row["uploaded_by"] is None and row["status"] == "active"
    run = await (
        await conn.execute("select user_id from agent_runs where id = %s", (run_id,))
    ).fetchone()
    assert run is not None and run["user_id"] is None

    assert await profiles.get_me(other) is not None  # 남은 사용자는 그대로다
    assert await profiles.delete(me) is False  # 두 번째는 지울 것이 없다
