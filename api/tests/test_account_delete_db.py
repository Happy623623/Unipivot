"""탈퇴 SQL (ERD 7장). DATABASE_URL이 있을 때만 돈다.

profiles 행 하나를 지우면 딸린 행(토큰·설정·파일 기록·알림·플래너·구독·판정)이 cascade로 사라지고,
공유 포스터 공고는 남되 업로더가 null이 되며, 실행 로그는 남되 사용자가 null이 된다. 남의 행은 그대로다.
트랜잭션을 되돌려 흔적을 남기지 않는다. 탈퇴 중 잠금은 연결 둘로 보고, 만든 사용자를 지운다.
"""

import asyncio
from typing import Any

import psycopg
import pytest

from app.account import delete_account
from app.calendar.service import CalendarService
from app.config import Settings
from app.repositories.calendar import CalendarRepository
from app.repositories.files import FileRepository
from app.repositories.profiles import ProfileRepository
from app.uploads.storage import SupabaseStorage
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


INSERT_FILE = (
    "insert into files (user_id, kind, origin, storage_path, sha256)"
    " values (%s, 'poster', 'upload', %s, %s)"
)


async def test_file_records_arriving_during_deletion_wait_and_then_fail() -> None:
    """탈퇴가 프로필을 잠근 뒤(목록을 받은 뒤) 들어오는 파일 기록은 탈퇴가 끝날 때까지 기다렸다가 프로필이 없어
    실패한다. 그래야 올린 쪽이 파일을 지운다 — 기록이 들어갔다가 cascade로만 지워지면 파일은 저장소에 남는다."""
    setup = await connect()
    me = await make_user(setup)
    await setup.commit()
    deleting, uploading = await connect(), await connect()
    try:
        profiles = ProfileRepository(deleting)
        await profiles.lock_for_delete(me)
        assert await FileRepository(deleting).storage_paths(me) == []
        await uploading.execute("set lock_timeout = '300ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            await uploading.execute(INSERT_FILE, (me, f"{me}/poster/late.png", "c" * 64))
        await uploading.rollback()

        await uploading.execute("set lock_timeout = '10s'")
        waiting = asyncio.create_task(
            uploading.execute(INSERT_FILE, (me, f"{me}/poster/late.png", "c" * 64))
        )
        try:
            await asyncio.sleep(0.3)
            assert not waiting.done()  # 탈퇴가 끝나기를 기다린다
            assert await profiles.delete(me) is True
            await deleting.commit()
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                await waiting
        finally:
            if not waiting.done():
                waiting.cancel()
    finally:
        for conn in (deleting, uploading):
            await conn.rollback()
            await conn.close()
        await setup.execute("delete from auth.users where id = %s", (me,))
        await setup.commit()
        await setup.close()


class LateUploadStorage(SupabaseStorage):
    """첫 파일을 지울 때 다른 연결이 새 파일 기록을 남기고 커밋한다(그사이 업로드·LMS 첨부)."""

    def __init__(self, user_id: str) -> None:
        super().__init__(
            base_url="https://storage.test/storage/v1", bucket="uploads", service_key="k"
        )
        self.user_id = user_id
        self.removed: list[str] = []

    async def remove(self, path: str) -> None:
        if not self.removed:
            other = await connect()
            try:
                await other.execute(
                    INSERT_FILE, (self.user_id, f"{self.user_id}/poster/late.png", "d" * 64)
                )
                await other.commit()
            finally:
                await other.close()
        self.removed.append(path)


async def test_deletion_also_removes_a_file_recorded_while_it_ran() -> None:
    """탈퇴 전체(실제 SQL): 처음 목록을 지우는 사이 들어온 파일도, 잠근 뒤 다시 받은 목록으로 지운다."""
    setup = await connect()
    me = await make_user(setup)
    await setup.execute(INSERT_FILE, (me, f"{me}/poster/one.png", "e" * 64))
    await setup.commit()
    conn = await connect()
    storage = LateUploadStorage(me)
    try:
        settings = Settings(
            supabase_url="https://abcdefghijklmnopqrst.supabase.co",
            supabase_service_role_key="sb_secret_" + "Tq7" * 10 + "x",  # 시험용 값이다
        )
        deleted = await delete_account(
            me,
            files=FileRepository(conn),
            storage=storage,
            calendar=CalendarService(CalendarRepository(conn), None, settings.token_encryption_key),  # type: ignore[arg-type]
            profiles=ProfileRepository(conn),
            settings=settings,
        )
        await conn.commit()
        assert deleted is True
        assert storage.removed == [f"{me}/poster/one.png", f"{me}/poster/late.png"]
        assert await _count(setup, "files", "user_id", me) == 0
    finally:
        await conn.rollback()
        await conn.close()
        await setup.execute("delete from auth.users where id = %s", (me,))
        await setup.commit()
        await setup.close()
