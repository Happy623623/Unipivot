"""서버 안 스케줄러 (PRD 9장). 시간을 쓰지 않고 돈다 — `sleep`과 `now`를 바꿔 넣는다.

보는 것: 언제 자고 언제 도는가, 하루 한 번이 KST 08:30에 맞는가, 한 번 터져도 계속 도는가,
설정이 꺼져 있으면 아예 안 뜨는가.
"""

import asyncio
from datetime import UTC, datetime, time, timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings
from app.eligibility import KST
from app.main import create_app
from app.repositories.notifications import NOTIFY_HOUR
from app.scheduler import (
    LMS_EVERY,
    SCHEDULE_AT,
    SEND_EVERY,
    Job,
    Scheduler,
    app_jobs,
    seconds_until,
)

pytestmark = pytest.mark.anyio

KST_NOON = datetime(2026, 10, 18, 3, 0, tzinfo=UTC)  # KST 정오


def _settings(**over: object) -> Settings:
    return Settings(
        database_url="",
        supabase_jwt_secret="scheduler-test-secret-scheduler-test",
        token_encryption_key=Fernet.generate_key().decode(),
        **over,  # type: ignore[arg-type]
    )


class Clock:
    """부를 때마다 1초씩 가는 시계(걸린 시간 로그가 음수가 되지 않게)."""

    def __init__(self, start: datetime = KST_NOON) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class Sleeper:
    """잔 시간을 적어 두고, 정해진 횟수를 넘으면 줄을 끊는다(무한 반복을 멈추는 방법)."""

    def __init__(self, limit: int) -> None:
        self.slept: list[float] = []
        self.limit = limit

    async def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)
        if len(self.slept) >= self.limit:
            raise asyncio.CancelledError


async def _drive(job: Job, sleeper: Sleeper, clock: Clock | None = None) -> None:
    scheduler = Scheduler([job], sleep=sleeper, now=clock or Clock())
    with pytest.raises(asyncio.CancelledError):
        await scheduler._loop(job)


# ── 다음 차례까지 남은 시간 ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("kst_hour", "kst_minute", "expected_hours"),
    [
        (7, 0, 1.5),  # 아침 7시 → 그날 08:30
        (8, 29, 1 / 60),  # 1분 전
        (9, 0, 23.5),  # 지났으면 다음 날
        (8, 30, 24.0),  # 딱 그 시각이면 내일(두 번 돌지 않는다)
        (23, 30, 9.0),  # 자정을 넘어간다
    ],
)
def test_the_daily_job_waits_until_the_next_kst_time(
    kst_hour: int, kst_minute: int, expected_hours: float
) -> None:
    now = datetime(2026, 10, 18, kst_hour, kst_minute, tzinfo=KST).astimezone(UTC)
    assert seconds_until(now, SCHEDULE_AT) == pytest.approx(expected_hours * 3600, abs=1)


def test_the_daily_job_runs_before_the_notification_hour() -> None:
    """예약은 알림 시각(KST 09:00)보다 앞이어야 그날 알림이 생긴다(지난 시각은 만들지 않는다)."""
    assert SCHEDULE_AT < time(NOTIFY_HOUR, 0)


def test_the_daily_job_crosses_the_month_end() -> None:
    now = datetime(2026, 10, 31, 14, 0, tzinfo=UTC)  # 10/31 23:00 KST
    assert seconds_until(now, time(8, 30)) == pytest.approx(9.5 * 3600, abs=1)


# ── 줄 하나가 도는 모양 ────────────────────────────────────────────────────


async def test_an_interval_job_sleeps_first_when_it_does_not_run_at_start() -> None:
    ran: list[int] = []
    sleeper = Sleeper(limit=2)
    job = Job(name="시험", run=lambda: _count(ran), every=timedelta(seconds=300))
    await _drive(job, sleeper)
    assert sleeper.slept == [300.0, 300.0]
    assert len(ran) == 1  # 자고 → 돌고 → 자다가 끊겼다


async def test_a_start_job_runs_before_sleeping() -> None:
    ran: list[int] = []
    sleeper = Sleeper(limit=1)
    job = Job(name="시험", run=lambda: _count(ran), every=SEND_EVERY, at_start=True)
    await _drive(job, sleeper)
    assert len(ran) == 1
    assert sleeper.slept == [SEND_EVERY.total_seconds()]


async def test_a_failing_job_does_not_stop_the_line() -> None:
    ran: list[int] = []

    async def boom() -> None:
        ran.append(len(ran))
        raise RuntimeError("일부러 터뜨림")

    sleeper = Sleeper(limit=3)
    job = Job(name="시험", run=boom, every=timedelta(seconds=60), at_start=True)
    await _drive(job, sleeper)
    assert len(ran) == 3  # 세 번 다 돌았다(터져도 다음 차례가 온다)


async def test_a_daily_job_sleeps_until_the_next_time() -> None:
    sleeper = Sleeper(limit=1)
    clock = Clock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))  # KST 09:00
    job = Job(name="시험", run=lambda: _count([]), daily_at=SCHEDULE_AT)
    await _drive(job, sleeper, clock)
    assert sleeper.slept[0] == pytest.approx(23.5 * 3600, abs=2)


async def _count(seen: list[int]) -> str:
    seen.append(len(seen))
    return "끝"


# ── 켜고 끄기 ──────────────────────────────────────────────────────────────


async def test_start_and_stop_leaves_nothing_running() -> None:
    forever = Job(name="시험", run=lambda: _count([]), every=timedelta(seconds=3600))
    scheduler = Scheduler([forever])
    scheduler.start()
    await asyncio.sleep(0)  # 작업이 돌기 시작할 틈을 준다
    assert scheduler.running == 1
    await scheduler.stop()
    assert scheduler.running == 0


# ── 앱에 묶기 ──────────────────────────────────────────────────────────────


def test_the_app_has_three_jobs_and_only_sending_runs_at_start() -> None:
    app = create_app(_settings())
    jobs = {job.name: job for job in app_jobs(app)}
    assert set(jobs) == {"알림 발송", "LMS 동기화", "공고 알림 예약"}
    assert jobs["알림 발송"].every == SEND_EVERY and jobs["알림 발송"].at_start
    assert jobs["LMS 동기화"].every == LMS_EVERY and not jobs["LMS 동기화"].at_start
    assert jobs["공고 알림 예약"].daily_at == SCHEDULE_AT
    assert not jobs["공고 알림 예약"].at_start


def test_the_app_logs_are_visible() -> None:
    """정기 작업 결과는 info 로그로만 남는다. uvicorn은 자기 로거만 꾸미므로 앱이 한 번 깔아 준다.

    이게 빠지면 스케줄러가 도는지 끄는지 로그로 알 수 없다(터져도 조용하다).
    """
    import logging

    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    root.handlers.clear()  # pytest가 깔아 둔 것을 잠깐 치운다(서버를 막 켠 상태를 흉내 낸다)
    try:
        create_app(_settings())
        assert root.handlers, "앱이 로그 받는 곳을 깔지 않았어요"
        assert root.level <= logging.INFO
    finally:
        root.handlers[:] = saved
        root.setLevel(level)


def test_the_scheduler_stays_off_unless_it_is_turned_on() -> None:
    with TestClient(create_app(_settings())) as client:
        assert client.app.state.scheduler is None  # type: ignore[attr-defined]


def test_turning_it_on_without_a_database_only_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"), TestClient(create_app(_settings(scheduler_enabled=True))) as c:
        assert c.app.state.scheduler is None  # type: ignore[attr-defined]
    assert any("DATABASE_URL" in record.message for record in caplog.records)
