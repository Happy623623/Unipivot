"""탈퇴 SQL (ERD 1장). DATABASE_URL이 있을 때만 돈다.

profiles 행 하나를 지우면 딸린 행(토큰·설정·파일 기록·알림·플래너·구독·판정)이 cascade로 사라지고,
공유 포스터 공고는 남되 업로더가 null이 되며, 실행 로그는 남되 사용자가 null이 된다. 남의 행은 그대로다.
트랜잭션을 되돌려 흔적을 남기지 않는다. 탈퇴 중 잠금은 연결 둘로 보고, 만든 사용자를 지운다.
로그인 계정 지우기는 Supabase처럼 다른 연결에서 auth.users를 지우는 가짜로 본다 — 탈퇴가 확정하기 전에
부르면 그 연결이 profiles 잠금을 기다리다 시간이 다 된다.
"""

import asyncio
from typing import Any

import psycopg
import pytest

from app.account import delete_account
from app.auth_admin import SupabaseAuthAdmin
from app.calendar.service import CalendarService
from app.config import Settings
from app.errors import ApiError
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

    async def list_paths(self, folder: str) -> list[str]:
        return []  # 기록 없는 파일은 없다(이 시험은 기록으로 찾는 것만 본다)


class AuthUsersAdmin(SupabaseAuthAdmin):
    """Supabase 관리자 API처럼 **다른 연결**에서 auth.users 행을 지운다(profiles로 cascade). 잠금을 3초까지만
    기다린다 — 탈퇴가 확정하기 전에 부르면 여기서 LockNotAvailable이 난다."""

    def __init__(self) -> None:
        super().__init__(base_url="https://abcdefghijklmnopqrst.supabase.co", service_key="k")
        self.deleted: list[str] = []

    async def delete_user(self, user_id: str) -> None:
        other = await connect()
        try:
            await other.execute("set lock_timeout = '3s'")
            await other.execute("delete from auth.users where id = %s", (user_id,))
            await other.commit()
        finally:
            await other.close()
        self.deleted.append(user_id)


SETTINGS = Settings(
    supabase_url="https://abcdefghijklmnopqrst.supabase.co",
    supabase_secret_key="sb_secret_" + "Tq7" * 10 + "x",  # 시험용 값이다
)


async def _delete(
    conn: Any, user_id: str, storage: SupabaseStorage, admin: SupabaseAuthAdmin
) -> bool:
    return await delete_account(
        user_id,
        files=FileRepository(conn),
        storage=storage,
        calendar=CalendarService(CalendarRepository(conn), None, SETTINGS.token_encryption_key),  # type: ignore[arg-type]
        profiles=ProfileRepository(conn),
        auth_admin=admin,
        settings=SETTINGS,
    )


async def test_deletion_also_removes_a_file_recorded_while_it_ran() -> None:
    """탈퇴 전체(실제 SQL): 처음 목록을 지우는 사이 들어온 파일도, 잠근 뒤 다시 받은 목록으로 지운다."""
    setup = await connect()
    me = await make_user(setup)
    await setup.execute(INSERT_FILE, (me, f"{me}/poster/one.png", "e" * 64))
    await setup.commit()
    conn = await connect()
    storage = LateUploadStorage(me)
    admin = AuthUsersAdmin()
    try:
        deleted = await _delete(conn, me, storage, admin)
        await conn.commit()
        assert deleted is True
        assert storage.removed == [f"{me}/poster/one.png", f"{me}/poster/late.png"]
        assert await _count(setup, "files", "user_id", me) == 0
        assert admin.deleted == [me]
    finally:
        await conn.rollback()
        await conn.close()
        await setup.execute("delete from auth.users where id = %s", (me,))
        await setup.commit()
        await setup.close()


class EmptyStorage(SupabaseStorage):
    """파일이 하나도 없는 저장소(폴더 훑기도 빈 목록)."""

    def __init__(self) -> None:
        super().__init__(
            base_url="https://storage.test/storage/v1", bucket="uploads", service_key="k"
        )

    async def list_paths(self, folder: str) -> list[str]:
        return []


async def _row(conn: Any, query: str, *params: Any) -> Any:
    return await (await conn.execute(query, params)).fetchone()


async def test_run_logs_stay_with_only_the_user_cleared_after_the_login_is_deleted() -> None:
    """탈퇴 전체 + 로그인 계정 지우기(실제 SQL): auth.users·profiles는 사라지고, 실행 로그(agent_runs)는
    user_id만 null이 되어 남는다. 딸린 도구·LLM 호출과 지표 값(시간·토큰·비용)도 그대로다."""
    setup = await connect()
    me = await make_user(setup)
    run = await _row(
        setup,
        "insert into agent_runs (user_id, trigger_type, status, latency_ms, input_tokens,"
        " output_tokens, cost_usd) values (%s, 'prepare', 'succeeded', 1234, 50, 7, 0.0021)"
        " returning id",
        me,
    )
    run_id = run["id"]
    await setup.execute(
        "insert into tool_calls (run_id, seq, tool_name, status) values (%s, 1, 'build_prep_plan', 'succeeded')",
        (run_id,),
    )
    await setup.execute(
        "insert into llm_calls (run_id, provider, model, input_tokens, output_tokens)"
        " values (%s, 'google', 'gemini-3.5-flash-lite', 50, 7)",
        (run_id,),
    )
    await setup.commit()
    conn = await connect()
    admin = AuthUsersAdmin()
    try:
        assert await _delete(conn, me, EmptyStorage(), admin) is True
        await conn.commit()
        assert admin.deleted == [me]
        assert await _row(setup, "select 1 from auth.users where id = %s", me) is None
        assert await _row(setup, "select 1 from profiles where id = %s", me) is None

        kept = await _row(
            setup,
            "select user_id, status::text, latency_ms, input_tokens, output_tokens, cost_usd"
            " from agent_runs where id = %s",
            run_id,
        )
        assert kept is not None and kept["user_id"] is None  # 사용자만 비었다
        assert (
            kept["status"],
            kept["latency_ms"],
            kept["input_tokens"],
            kept["output_tokens"],
        ) == (
            "succeeded",
            1234,
            50,
            7,
        )
        assert float(kept["cost_usd"]) == pytest.approx(0.0021)
        for table in ("tool_calls", "llm_calls"):
            assert await _count(setup, table, "run_id", run_id) == 1, table
    finally:
        await conn.rollback()
        await conn.close()
        await setup.rollback()
        await setup.execute(
            "delete from agent_runs where id = %s", (run_id,)
        )  # 도구·LLM 호출은 cascade
        await setup.execute("delete from auth.users where id = %s", (me,))
        await setup.commit()
        await setup.close()


async def test_a_token_left_after_the_login_was_deleted_cannot_recreate_the_profile() -> None:
    """로그인 계정을 지운 뒤에도 다른 탭의 토큰은 만료까지 살아 있다. 그 토큰으로 프로필을 다시 만들려 하면
    (GET /me) 외래 키 오류 대신 401이다 — 웹이 로그인 화면으로 보낸다."""
    conn = await connect()
    try:
        me = await make_user(conn)
        await conn.execute(
            "delete from auth.users where id = %s", (me,)
        )  # 탈퇴(profiles는 cascade)
        with pytest.raises(ApiError) as caught:
            await ProfileRepository(conn).ensure(me, "테스트 학생")
        assert (caught.value.status, caught.value.code) == (401, "UNAUTHORIZED")
    finally:
        await conn.rollback()
        await conn.close()
