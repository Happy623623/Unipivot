"""스케줄러 배선 (PRD 9장). DATABASE_URL이 있을 때만 돈다.

요청 밖에서(의존성 주입 없이) 저장소와 발송기를 만들어 실제 DB에 대고 도는지 본다 — 여기가
어긋나면 서버는 뜨지만 정기 작업만 조용히 죽는다.

**지난 시각을 준다.** 보낼 것이 없어서 공용 시험 DB의 줄을 하나도 건드리지 않는다. 예약·LMS
동기화 작업은 여기서 돌리지 않는다 — 예약은 모든 사용자에게 알림을 만들고, 동기화는 바깥
LearningX를 부른다. 그 둘의 알맹이는 `/internal/jobs/*` 시험이 본다.
"""

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.main import create_app, lifespan
from app.scheduler import app_jobs
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
        result = await jobs["알림 발송"].run()
    assert (result.due, result.sent, result.pushed, result.push_dropped) == (0, 0, 0, 0)
    assert await _notification_counts() == before  # 공용 DB를 건드리지 않았다


async def test_the_scheduler_starts_with_three_lines_when_turned_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """켜면 작업마다 줄이 하나씩 뜨고, 끌 때 모두 멈춘다.

    실제 작업 대신 아무 일도 하지 않는 줄로 바꿔 띄운다 — 켜자마자 도는 발송이 공용 DB를
    건드리지 않게 한다(도는 모양 자체는 test_scheduler.py가 본다).
    """
    from app import main
    from app.scheduler import Job

    async def nothing() -> str:
        return "아무것도 안 함"

    names = ["알림 발송", "LMS 동기화", "공고 알림 예약"]
    monkeypatch.setattr(
        main, "app_jobs", lambda app: [Job(name=name, run=nothing, every=HOUR) for name in names]
    )
    settings = Settings(
        database_url=DATABASE_URL,
        supabase_jwt_secret="scheduler-db-secret-scheduler-db-secret",
        token_encryption_key=Fernet.generate_key().decode(),
        scheduler_enabled=True,
    )
    app = create_app(settings)
    async with lifespan(app):
        assert app.state.scheduler is not None
        assert app.state.scheduler.running == 3
    assert app.state.scheduler.running == 0  # 끌 때 멈춘다


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
