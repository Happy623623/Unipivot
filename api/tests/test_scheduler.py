"""서버 안 스케줄러 (PRD 9장, 오케스트레이션 2단계 2.8·3단계 4.5). 시간을 쓰지 않고 돈다 — `sleep`과 `now`를
바꿔 넣고, 예약표는 메모리 표(`FakeTable`)로 바꾼다. 예약표 SQL 자체는 `test_scheduler_db.py`가 실제 DB로 본다.

보는 것: 다음 차례 계산(KST 08:30·04:00, 간격), 때가 된 줄만 집어 따로 띄우는가, 며칠 밀려도 한 번, 서버가 둘이어도
한 번, 이 서버에서 도는 작업은 다시 집지 않음, 실패하면 늦춤(날짜 작업)·간격 뒤(간격 작업), 끄면 임대를 푼다,
설정이 꺼져 있으면 tick이 돌지 않는다.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings
from app.eligibility import KST
from app.main import create_app
from app.repositories.job_schedule import Failed
from app.repositories.notifications import NOTIFY_HOUR
from app.scheduler import (
    LEASE,
    LMS_EVERY,
    SCHEDULE_AT,
    SEND_EVERY,
    TICK_EVERY,
    WARN_AFTER,
    Job,
    Scheduler,
    app_jobs,
    first_run,
    next_after,
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


def kst(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=KST)


class Clock:
    """손으로 옮기는 시계. 부를 때마다 1초씩 간다(걸린 시간 로그가 음수가 되지 않게)."""

    def __init__(self, start: datetime = KST_NOON) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@dataclass
class Row:
    next_run_at: datetime
    lease_until: datetime | None = None
    attempts: int = 0
    last_finished_at: datetime | None = None
    last_error: str | None = None


@dataclass
class FakeTable:
    """예약표(`JobScheduleRepository`)의 메모리 흉내. SQL과 같은 규칙으로 집고·끝내고·늦춘다."""

    rows: dict[str, Row] = field(default_factory=dict)
    broken: bool = False  # 예약표를 읽지 못하는 때(DB 오류)

    def __call__(self, conn: Any) -> "FakeTable":
        return self

    async def ensure(self, firsts: dict[str, datetime]) -> None:
        if self.broken:
            raise RuntimeError("DB 오류")
        for name, at in firsts.items():
            self.rows.setdefault(name, Row(at))

    async def claim(self, names: list[str], *, now: datetime, lease: timedelta) -> list[str]:
        picked = [
            name
            for name in names
            if name in self.rows
            and self.rows[name].next_run_at <= now
            and (self.rows[name].lease_until is None or self.rows[name].lease_until <= now)
        ]
        for name in picked:
            self.rows[name].lease_until = now + lease
            self.rows[name].attempts += 1
        return sorted(picked, key=lambda name: (self.rows[name].next_run_at, name))

    async def finish(self, name: str, *, now: datetime, next_run_at: datetime) -> None:
        row = self.rows[name]
        row.next_run_at, row.lease_until, row.attempts = next_run_at, None, 0
        row.last_finished_at, row.last_error = now, None

    async def fail(
        self, name: str, *, now: datetime, error: str, first: timedelta, cap: datetime
    ) -> Failed:
        row = self.rows[name]
        row.next_run_at = min(now + first * 2 ** (max(row.attempts, 1) - 1), cap)
        row.lease_until, row.last_error = None, error
        return Failed(attempts=row.attempts, next_run_at=row.next_run_at)

    async def release(self, name: str) -> None:
        self.rows[name].lease_until = None


@asynccontextmanager
async def _no_conn() -> AsyncIterator[None]:
    yield None


def _scheduler(
    jobs: list[Job], table: FakeTable, clock: Clock, sleep: Any = asyncio.sleep
) -> Scheduler:
    return Scheduler(jobs, connect=_no_conn, table_for=table, now=clock, sleep=sleep)  # type: ignore[arg-type]


def _job(
    name: str,
    run: Callable[[], Awaitable[Any]],
    *,
    every: timedelta | None = None,
    daily_at: time | None = None,
) -> Job:
    return Job(name=name, label=name, run=run, every=every, daily_at=daily_at)


class Counter:
    def __init__(self) -> None:
        self.runs = 0

    async def __call__(self) -> str:
        self.runs += 1
        return "끝"


# ── 다음 차례 ─────────────────────────────────────────────────────────────


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


def test_the_next_turn_and_the_first_turn() -> None:
    """간격 작업은 끝난 때 + 간격이고 처음엔 바로, 날짜 작업은 지금 이후 첫 KST 시각이다."""
    interval = _job("간격", Counter(), every=SEND_EVERY)
    daily = _job("날짜", Counter(), daily_at=SCHEDULE_AT)
    at = kst(18, 12)
    assert next_after(interval, at) == at + SEND_EVERY
    assert next_after(daily, at) == kst(19, 8, 30)
    assert first_run(interval, at) == at
    assert first_run(daily, at) == kst(19, 8, 30)
    assert first_run(daily, kst(18, 7)) == kst(18, 8, 30)


# ── tick: 집고 띄우고 다음 차례 ─────────────────────────────────────────────


async def test_a_tick_runs_only_due_jobs_and_writes_their_next_turn() -> None:
    """처음 tick은 줄을 넣는다 — 간격 작업은 바로 돌고, 날짜 작업은 다음 KST 시각을 기다린다."""
    table, clock = FakeTable(), Clock(kst(18, 12))
    send, schedule = Counter(), Counter()
    jobs = [
        _job("send", send, every=SEND_EVERY),
        _job("schedule", schedule, daily_at=SCHEDULE_AT),
    ]
    scheduler = _scheduler(jobs, table, clock)

    assert await scheduler.tick() == ["send"]
    await scheduler.wait()

    assert (send.runs, schedule.runs) == (1, 0)
    row = table.rows["send"]
    assert row.next_run_at == row.last_finished_at + SEND_EVERY  # type: ignore[operator]
    assert (row.lease_until, row.attempts) == (None, 0)
    assert table.rows["schedule"].next_run_at == kst(19, 8, 30)
    assert await scheduler.tick() == []  # 다음 차례 전에는 아무것도 집지 않는다


async def test_a_daily_job_missed_for_days_runs_once_and_moves_to_the_next_turn() -> None:
    """서버가 사흘 꺼져 있었어도 깨어나 한 번만 돌고, 다음 차례는 지금 이후 첫 08:30이다."""
    table, clock = FakeTable(), Clock(kst(18, 14))
    table.rows["schedule"] = Row(kst(15, 8, 30))  # 사흘 전 차례
    schedule = Counter()
    scheduler = _scheduler([_job("schedule", schedule, daily_at=SCHEDULE_AT)], table, clock)

    assert await scheduler.tick() == ["schedule"]
    await scheduler.wait()
    assert await scheduler.tick() == []

    assert schedule.runs == 1
    assert table.rows["schedule"].next_run_at == kst(19, 8, 30)


async def test_two_servers_on_one_table_run_a_job_once() -> None:
    """콜드 스타트로 서버가 둘 떠도(또는 서버 안 tick과 바깥 크론을 같이 켜도) 작업은 한 번이다."""
    table, clock = FakeTable(), Clock(kst(18, 8, 31))
    table.rows["schedule"] = Row(kst(18, 8, 30))
    schedule = Counter()
    job = _job("schedule", schedule, daily_at=SCHEDULE_AT)
    first, second = _scheduler([job], table, clock), _scheduler([job], table, clock)

    assert await first.tick() == ["schedule"]
    assert await second.tick() == []  # 임대 중
    await first.wait()
    assert await second.tick() == []  # 끝나고 다음 차례로 갔다
    assert schedule.runs == 1


async def test_a_job_still_running_here_is_not_claimed_again() -> None:
    """임대(30분)가 끝나도 이 서버에서 아직 도는 작업은 다시 집지 않는다 — 같은 서버에서 겹쳐 돌지 않는다."""
    table, clock = FakeTable(), Clock(kst(18, 12))
    gate = asyncio.Event()
    runs: list[int] = []

    async def slow() -> str:
        runs.append(1)
        await gate.wait()
        return "끝"

    scheduler = _scheduler([_job("sync", slow, every=LMS_EVERY)], table, clock)
    assert await scheduler.tick() == ["sync"]
    await asyncio.sleep(0)
    clock.now += LEASE + timedelta(minutes=1)
    assert await scheduler.tick() == []
    assert scheduler.running == 1
    gate.set()
    await scheduler.wait()
    assert len(runs) == 1


async def test_a_long_job_does_not_hold_up_the_others() -> None:
    table, clock = FakeTable(), Clock(kst(18, 12))
    gate = asyncio.Event()
    quick = Counter()

    async def slow() -> str:
        await gate.wait()
        return "끝"

    jobs = [_job("sync", slow, every=LMS_EVERY), _job("send", quick, every=SEND_EVERY)]
    scheduler = _scheduler(jobs, table, clock)
    assert sorted(await scheduler.tick()) == ["send", "sync"]
    for _ in range(3):
        await asyncio.sleep(0)
    assert quick.runs == 1 and table.rows["send"].last_finished_at is not None
    assert scheduler.running == 1  # 느린 작업만 남았다
    gate.set()
    await scheduler.wait()


# ── 실패 ───────────────────────────────────────────────────────────────────


async def test_a_failing_daily_job_waits_longer_but_never_skips_its_next_turn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """날짜 작업은 30분 → 1시간 → 2시간 → 4시간 → 8시간으로 늦추되 다음 08:30을 넘기지 않는다.
    잇달아 5번 실패하면 경고한다."""
    table, clock = FakeTable(), Clock(kst(18, 8, 29))
    table.rows["schedule"] = Row(kst(18, 8, 30))

    async def boom() -> str:
        raise RuntimeError("예약 실패 token=secret-value")

    scheduler = _scheduler([_job("schedule", boom, daily_at=SCHEDULE_AT)], table, clock)
    turns: list[datetime] = []
    with caplog.at_level("WARNING", logger="app.scheduler"):
        for _ in range(6):
            clock.now = table.rows["schedule"].next_run_at
            assert await scheduler.tick() == ["schedule"]
            await scheduler.wait()
            turns.append(table.rows["schedule"].next_run_at)

    assert [turn.astimezone(KST).strftime("%d %H:%M") for turn in turns] == [
        "18 09:00",
        "18 10:00",
        "18 12:00",
        "18 16:00",
        "19 00:00",
        "19 08:30",  # 16시간 뒤 대신 다음 정해진 차례
    ]
    assert table.rows["schedule"].attempts == 6
    assert f"{WARN_AFTER}번 잇달아 실패했어요" in caplog.text
    assert "secret-value" not in (table.rows["schedule"].last_error or "")  # 실패 이유는 가려 둔다


async def test_a_failing_interval_job_tries_again_after_its_interval(
    caplog: pytest.LogCaptureFixture,
) -> None:
    table, clock = FakeTable(), Clock(kst(18, 12))

    async def boom() -> str:
        raise RuntimeError("발송 실패")

    scheduler = _scheduler([_job("send", boom, every=SEND_EVERY)], table, clock)
    with caplog.at_level("WARNING", logger="app.scheduler"):
        for _ in range(WARN_AFTER + 1):
            clock.now = table.rows["send"].next_run_at if table.rows else clock.now
            assert await scheduler.tick() == ["send"]
            await scheduler.wait()
            row = table.rows["send"]
            assert row.next_run_at - clock.now <= SEND_EVERY  # 늘 간격 뒤
    assert "잇달아 실패" not in caplog.text  # 간격 작업은 다음 차례에 다시 돈다(전과 같다)


async def test_a_table_error_only_waits_for_the_next_tick(
    caplog: pytest.LogCaptureFixture,
) -> None:
    table, clock = FakeTable(broken=True), Clock(kst(18, 12))
    send = Counter()
    scheduler = _scheduler([_job("send", send, every=SEND_EVERY)], table, clock)
    with caplog.at_level("ERROR", logger="app.scheduler"):
        assert await scheduler.tick() == []
    assert "예약표를 보지 못했어요" in caplog.text
    table.broken = False
    assert await scheduler.tick() == ["send"]  # 다음 tick에 다시 본다
    await scheduler.wait()
    assert send.runs == 1


# ── 켜고 끄기 ──────────────────────────────────────────────────────────────


class Sleeper:
    """잔 시간을 적어 두고, 정해진 횟수를 넘으면 줄을 끊는다(무한 반복을 멈추는 방법)."""

    def __init__(self, limit: int) -> None:
        self.slept: list[float] = []
        self.limit = limit

    async def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)
        if len(self.slept) >= self.limit:
            raise asyncio.CancelledError


async def test_the_tick_runs_at_start_and_then_every_minute() -> None:
    table, clock, sleeper = FakeTable(), Clock(kst(18, 12)), Sleeper(limit=2)
    send = Counter()
    scheduler = _scheduler([_job("send", send, every=SEND_EVERY)], table, clock, sleep=sleeper)
    with pytest.raises(asyncio.CancelledError):
        await scheduler._tick_forever()
    await scheduler.wait()
    assert sleeper.slept == [TICK_EVERY.total_seconds()] * 2
    assert send.runs == 1  # 켜자마자 한 번. 1분 뒤 tick에는 아직 차례가 아니다


async def test_stopping_cancels_running_jobs_and_frees_their_lease() -> None:
    """서버를 끌 때 돌던 작업은 취소하고 임대를 푼다 — 다음 서버가 30분을 기다리지 않고 바로 집는다."""
    table, clock = FakeTable(), Clock(kst(18, 12))

    async def forever() -> str:
        await asyncio.Event().wait()
        return "안 끝남"

    scheduler = _scheduler([_job("sync", forever, every=LMS_EVERY)], table, clock)
    scheduler.start()
    for _ in range(3):
        await asyncio.sleep(0)
    assert scheduler.ticking and scheduler.running == 1
    assert table.rows["sync"].lease_until is not None
    await scheduler.stop()
    assert not scheduler.ticking and scheduler.running == 0
    assert table.rows["sync"].lease_until is None
    assert table.rows["sync"].attempts == 1  # 그 시도도 한 번으로 센다


# ── 앱에 묶기 ──────────────────────────────────────────────────────────────


def test_the_app_has_three_jobs_named_after_their_internal_paths() -> None:
    """예약표 줄 이름은 /internal/jobs/* 주소의 끝과 같다. 키가 없으면 청년정책 수집은 목록에 없다."""
    app = create_app(_settings())
    jobs = {job.name: job for job in app_jobs(app)}
    assert set(jobs) == {"send-notifications", "lms-sync", "schedule-notifications"}
    assert jobs["send-notifications"].every == SEND_EVERY
    assert jobs["lms-sync"].every == LMS_EVERY
    assert jobs["schedule-notifications"].daily_at == SCHEDULE_AT
    assert [job.label for job in jobs.values()] == ["알림 발송", "LMS 동기화", "공고 알림 예약"]
    paths = set(app.openapi()["paths"])
    assert all(f"/api/v1/internal/jobs/{name}" in paths for name in jobs)


def test_the_policy_job_joins_when_there_is_a_key() -> None:
    app = create_app(_settings(youth_api_key="key"))
    jobs = {job.name: job for job in app_jobs(app)}
    assert jobs["fetch-policies"].daily_at == time(4, 0)


async def test_the_schedule_job_judges_and_schedules_on_one_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """예약 작업은 연결 하나로 판정 다시 계산(OpportunityRepository)과 예약(NotificationRepository)을
    한다. 배선이 어긋나면 서버는 뜨지만 매일 08:30에만 조용히 터진다."""
    import app.scheduler as scheduler_module
    from app.repositories.notifications import NotificationRepository
    from app.repositories.opportunities import OpportunityRepository

    conn = object()

    class Pool:
        @asynccontextmanager
        async def connection(self) -> AsyncIterator[object]:
            yield conn

    calls: list[tuple[object, object, datetime]] = []

    async def schedule(repo: object, opportunities: object, *, now: datetime) -> str:
        calls.append((repo, opportunities, now))
        return "예약함"

    monkeypatch.setattr(scheduler_module, "schedule_notifications", schedule)
    app = create_app(_settings())
    app.state.pool = Pool()
    jobs = {job.name: job for job in app_jobs(app, now=lambda: KST_NOON)}
    assert await jobs["schedule-notifications"].run() == "예약함"
    [(repo, opportunities, now)] = calls
    assert isinstance(repo, NotificationRepository) and repo.conn is conn
    assert isinstance(opportunities, OpportunityRepository) and opportunities.conn is conn
    assert now == KST_NOON


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


def test_the_tick_endpoint_needs_the_key_and_a_database() -> None:
    from app.config import get_settings

    settings = _settings(internal_api_key="k")
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        assert client.post("/api/v1/internal/jobs/tick").status_code == 403
        response = client.post("/api/v1/internal/jobs/tick", headers={"X-Internal-Key": "k"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DB_UNAVAILABLE"


def test_turning_it_on_without_a_database_only_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"), TestClient(create_app(_settings(scheduler_enabled=True))) as c:
        assert c.app.state.scheduler is None  # type: ignore[attr-defined]
    assert any("DATABASE_URL" in record.message for record in caplog.records)
