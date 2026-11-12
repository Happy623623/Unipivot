"""스케줄러 배선과 예약표 SQL (PRD 9장, 오케스트레이션 2단계 2.8·3단계 4.5). DATABASE_URL이 있을 때만 돈다.

요청 밖에서(의존성 주입 없이) 저장소와 발송기를 만들어 실제 DB에 대고 도는지 본다 — 여기가
어긋나면 서버는 뜨지만 정기 작업만 조용히 죽는다.

**지난 시각을 준다.** 보낼 것이 없어서 공용 시험 DB의 줄을 하나도 건드리지 않는다. 예약·LMS
동기화 작업은 여기서 돌리지 않는다 — 예약은 모든 사용자에게 알림을 만들고, 동기화는 바깥
LearningX를 부른다. 그 둘의 알맹이는 `/internal/jobs/*` 시험이 본다.

예약표 시험은 이 파일만의 줄 이름(`test-…`)을 쓰고 끝나면 지운다 — 진짜 작업 줄은 건드리지 않는다.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet

from app.config import Settings, get_settings
from app.main import create_app, lifespan
from app.repositories.job_schedule import JobScheduleRepository
from app.scheduler import LEASE, Job, app_jobs
from tests.db_world import DATABASE_URL, connect

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)  # 이때 보낼 알림은 없다
HOUR = timedelta(hours=1)


async def _notification_counts() -> tuple[int, int]:
    conn = await connect()
    try:
        row = await (
            await conn.execute(
                "select count(*) as all_rows,"
                " count(*) filter (where sent_at is not null) as sent_rows from notifications"
            )
        ).fetchone()
        assert row is not None
        return row["all_rows"], row["sent_rows"]
    finally:
        await conn.close()


async def test_the_send_job_runs_outside_a_request() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        supabase_jwt_secret="scheduler-db-secret-scheduler-db-secret",
        token_encryption_key=Fernet.generate_key().decode(),
    )
    app = create_app(settings)
    before = await _notification_counts()
    async with lifespan(app):
        jobs = {job.name: job for job in app_jobs(app, now=lambda: LONG_AGO)}
        result = await jobs["send-notifications"].run()
    assert (result.due, result.sent, result.pushed, result.push_dropped) == (0, 0, 0, 0)
    assert await _notification_counts() == before  # 공용 DB를 건드리지 않았다


async def test_turned_on_the_scheduler_ticks_the_table_at_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """켜면 tick이 바로 한 번 돈다 — 줄을 넣고, 때가 된(간격) 작업을 집어 돌리고, 다음 차례를 적는다.
    끌 때 tick이 멈춘다.

    실제 작업 대신 이 시험만의 줄 이름과 아무 일도 하지 않는 작업으로 바꿔 띄운다 — 공용 DB의 진짜 줄과
    알림을 건드리지 않는다(도는 모양 자체는 test_scheduler.py가 본다).
    """
    from app import main

    name = f"test-{uuid.uuid4().hex[:8]}"
    ran = asyncio.Event()

    async def nothing() -> str:
        ran.set()
        return "아무것도 안 함"

    monkeypatch.setattr(
        main, "app_jobs", lambda app: [Job(name=name, label="시험", run=nothing, every=HOUR)]
    )
    app = create_app(_db_settings(scheduler_enabled=True))
    try:
        async with lifespan(app):
            assert app.state.scheduler is not None and app.state.scheduler.ticking
            await asyncio.wait_for(ran.wait(), timeout=10)
            await app.state.scheduler.wait()
            (row,) = await _rows(name)
            assert row["last_finished_at"] is not None and row["lease_until"] is None
            assert row["next_run_at"] - row["last_finished_at"] == HOUR
        assert not app.state.scheduler.ticking  # 끌 때 멈춘다
    finally:
        await _drop(name)


async def test_the_tick_endpoint_starts_due_jobs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """서버 안 tick이 꺼져 있어도 POST /internal/jobs/tick이 같은 함수로 집는다. 바로 또 부르면 아무것도 없다."""
    from app import main

    name = f"test-{uuid.uuid4().hex[:8]}"
    runs: list[int] = []

    async def count() -> str:
        runs.append(1)
        return "끝"

    monkeypatch.setattr(
        main, "app_jobs", lambda app: [Job(name=name, label="시험", run=count, every=HOUR)]
    )
    settings = _db_settings(internal_api_key="tick-key")
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        async with lifespan(app):
            assert not app.state.scheduler.ticking  # SCHEDULER_ENABLED가 꺼져 있다
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                headers = {"X-Internal-Key": "tick-key"}
                first = await http.post("/api/v1/internal/jobs/tick", headers=headers)
                await app.state.scheduler.wait()
                again = await http.post("/api/v1/internal/jobs/tick", headers=headers)
        assert (first.status_code, first.json()) == (202, {"started": [name]})
        assert again.json() == {"started": []}
        assert runs == [1]
    finally:
        await _drop(name)


# ── 예약표 SQL ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def _table() -> AsyncIterator[tuple[Any, str]]:
    conn = await connect(autocommit=True)
    name = f"test-{uuid.uuid4().hex[:8]}"
    try:
        yield conn, name
    finally:
        await conn.execute(
            "delete from job_schedule where name like 'test-%%' and name = %s", (name,)
        )
        await conn.close()


async def test_a_row_is_claimed_once_and_again_only_after_its_lease() -> None:
    async with _table() as (conn, name):
        table = JobScheduleRepository(conn)
        now = datetime(2026, 11, 18, 0, 0, tzinfo=UTC)
        await table.ensure({name: now})
        await table.ensure({name: now + HOUR})  # 있는 줄은 그대로다

        assert await table.claim([name], now=now, lease=LEASE) == [name]
        assert await table.claim([name], now=now + LEASE - timedelta(seconds=1), lease=LEASE) == []
        assert await table.claim([name], now=now + LEASE, lease=LEASE) == [name]  # 서버가 죽은 셈
        (row,) = await _rows(name)
        assert (row["next_run_at"], row["attempts"]) == (now, 2)
        assert row["lease_until"] == now + 2 * LEASE


async def test_a_row_not_due_yet_is_not_claimed() -> None:
    async with _table() as (conn, name):
        table = JobScheduleRepository(conn)
        now = datetime(2026, 11, 18, 0, 0, tzinfo=UTC)
        await table.ensure({name: now + HOUR})
        assert await table.claim([name], now=now, lease=LEASE) == []
        assert await table.claim([name], now=now + HOUR, lease=LEASE) == [name]


async def test_two_servers_claiming_at_once_get_the_row_once() -> None:
    """뒤쪽은 앞쪽 트랜잭션이 끝날 때까지 기다렸다가 다시 보고 0행을 받는다(조건부 갱신)."""
    async with _table() as (setup, name):
        now = datetime(2026, 11, 18, 0, 0, tzinfo=UTC)
        await JobScheduleRepository(setup).ensure({name: now})
        early, late = await connect(), await connect()
        try:
            first = await JobScheduleRepository(early).claim([name], now=now, lease=LEASE)
            waiting = asyncio.create_task(
                JobScheduleRepository(late).claim([name], now=now, lease=LEASE)
            )
            await asyncio.sleep(0.3)
            assert not waiting.done()  # 앞쪽 잠금을 기다린다
            await early.commit()
            second = await asyncio.wait_for(waiting, timeout=10)
            await late.commit()
            assert (first, second) == ([name], [])
        finally:
            for conn in (early, late):
                await conn.rollback()
                await conn.close()


async def test_finishing_and_failing_set_the_next_turn() -> None:
    async with _table() as (conn, name):
        table = JobScheduleRepository(conn)
        now = datetime(2026, 11, 18, 0, 0, tzinfo=UTC)
        await table.ensure({name: now})
        for _ in range(3):  # 잇달아 세 번 집혔다
            await conn.execute(
                "update job_schedule set lease_until = null where name = %s", (name,)
            )
            await table.claim([name], now=now, lease=LEASE)

        failed = await table.fail(
            name,
            now=now,
            error="RuntimeError: 실패",
            first=timedelta(minutes=30),
            cap=now + 3 * HOUR,
        )
        assert failed is not None
        assert (failed.attempts, failed.next_run_at) == (3, now + 2 * HOUR)  # 30분 × 2^2
        capped = await table.fail(
            name, now=now, error="RuntimeError: 실패", first=timedelta(minutes=30), cap=now + HOUR
        )
        assert (
            capped is not None and capped.next_run_at == now + HOUR
        )  # 정해진 차례를 넘기지 않는다
        (row,) = await _rows(name)
        assert (row["lease_until"], row["last_error"]) == (None, "RuntimeError: 실패")

        await table.finish(name, now=now, next_run_at=now + 5 * HOUR)
        (row,) = await _rows(name)
        assert (row["next_run_at"], row["attempts"], row["last_error"]) == (now + 5 * HOUR, 0, None)
        assert row["last_finished_at"] == now
        assert await table.fail("test-없는-줄", now=now, error="x", first=HOUR, cap=now) is None


async def _rows(name: str) -> list[dict[str, Any]]:
    conn = await connect()
    try:
        return await (
            await conn.execute("select * from job_schedule where name = %s", (name,))
        ).fetchall()
    finally:
        await conn.close()


async def _drop(name: str) -> None:
    conn = await connect(autocommit=True)
    try:
        await conn.execute("delete from job_schedule where name = %s", (name,))
    finally:
        await conn.close()


def _db_settings(**over: Any) -> Settings:
    return Settings(
        database_url=DATABASE_URL,
        supabase_jwt_secret="scheduler-db-secret-scheduler-db-secret",
        token_encryption_key=Fernet.generate_key().decode(),
        **over,
    )


async def test_the_pools_close_even_when_the_app_fails() -> None:
    """뜨는 중이나 도는 중에 터져도 DB 풀을 닫는다.

    안 닫으면 풀의 일꾼 스레드가 남아 프로세스가 끝나지 않는다(서버도, 시험도 멈춘 것처럼 보인다).
    """
    settings = Settings(
        database_url=DATABASE_URL,
        supabase_jwt_secret="scheduler-db-secret-scheduler-db-secret",
        token_encryption_key=Fernet.generate_key().decode(),
    )
    app = create_app(settings)
    try:
        with pytest.raises(RuntimeError, match="일부러"):
            async with lifespan(app):
                raise RuntimeError("일부러 터뜨림")
        assert app.state.pool.closed and app.state.log_pool.closed
    finally:
        # 닫히지 않았으면 여기서 닫는다 — 안 그러면 이 시험 하나가 pytest를 멈춰 세운다
        for pool in (app.state.pool, app.state.log_pool):
            if pool is not None and not pool.closed:
                await pool.close()
