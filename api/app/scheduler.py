"""서버 안 정기 작업 (PRD 9장 "스케줄러") — 예약표(`job_schedule`)를 1분마다 보는 `tick` 하나.

`POST /internal/jobs/*`를 사람이 부를 때와 **같은 함수**(`app/jobs.py`)를 부른다.

| 작업(예약표 줄 이름) | 차례 | 처음 차례 |
| --- | --- | --- |
| 알림 발송(`send-notifications`) | 끝난 때부터 5분 | 바로 — 서버가 꺼져 있던 동안 밀린 알림을 보낸다 |
| LMS 동기화(`lms-sync`) | 끝난 때부터 30분 | 바로 |
| 공고 알림 예약(`schedule-notifications`) | 하루 한 번 KST 08:30 | 다음 08:30 |
| 청년정책 수집(`fetch-policies`) | 하루 한 번 KST 04:00 | 다음 04:00. `YOUTH_API_KEY`가 없으면 집지 않는다 |

**다음 차례는 DB에 있다**(오케스트레이션 2단계 2.8·3단계 4.5). 전에는 작업마다 "돌고 → 자고 → 돈다"의 잘 시간이
메모리에만 있어서, 서버가 08:30에 꺼져 있으면 그날 예약을 잊었고(11/4–11/11 예약 0번), 콜드 스타트로 서버가 둘
뜨면 날짜 작업이 두 번 돌았다.

- **잊지 않는다**: 깨어나 처음 도는 tick이 지난 차례의 줄을 집는다
- **며칠 밀려도 한 번**: 끝나면 지금 이후 첫 차례로 건너뛴다. 예약은 지난 알림 시각을 만들지 않고 수집은 지금
  목록을 받으니, 지난 날을 하나씩 재연하지 않는다
- **몇 대가 떠도 한 번**: 줄을 집는 것이 조건부 갱신 한 문장(임대 30분)이다. 콜드 스타트로 서버가 둘 떠도,
  서버 안 tick과 바깥 크론(`POST /internal/jobs/tick`)을 같이 켜도 작업마다 한 번만 돈다
- **따로 띄운다**: 집은 작업은 각자 돈다 — 한 작업이 길어도 다른 작업이 밀리지 않는다. 이 서버에서 아직 도는
  작업은 다시 집지 않는다
- **실패하면**: 간격 작업은 간격 뒤에 다시(전과 같다). 날짜 작업은 30분 → 1시간 → 2시간 …으로 늦추되 다음 정해진
  차례를 넘기지 않고, 잇달아 5번 실패하면 경고 한 줄을 남긴다. 예약표를 읽지 못하면 다음 tick에 다시 본다
- 서버를 끌 때 돌던 작업은 취소하고 임대를 푼다 — 다음 서버가 바로 다시 집는다. 작업은 모두 다시 돌려도 된다
- 예약이 **KST 08:30**인 것은 알림 시각이 09:00이고 지난 시각은 만들지 않아서다(PRD F-33). 수집이 **04:00**인
  것은 예약 전에 끝나 그날 새 정책이 그날 예약에 들어가게 하려는 것이다(처음 넣을 때 1~3분, 온통청년 600번 상한)
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from psycopg import AsyncConnection

from app.clock import current_time
from app.eligibility import KST
from app.jobs import fetch_policies_fresh, lms_sync, schedule_notifications, send_notifications
from app.llm.deps import llm_for
from app.lms.sync import lms_sync_service_for
from app.logging_redact import redact
from app.push.deps import push_sender_for
from app.repositories.job_schedule import JobScheduleRepository
from app.repositories.notifications import NotificationRepository
from app.repositories.opportunities import OpportunityRepository
from app.repositories.push import PushRepository
from app.youth.client import YouthPolicyClient

logger = logging.getLogger(__name__)
# 블록이 끝나면 커밋하는 연결 공급자(요청 풀의 pool.connection)
Connect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]

TICK_EVERY = timedelta(minutes=1)
SEND_EVERY = timedelta(minutes=5)
LMS_EVERY = timedelta(minutes=30)
SCHEDULE_AT = time(8, 30)  # KST. 알림 시각(09:00)보다 앞이어야 한다
FETCH_AT = time(4, 0)  # KST. 예약(08:30) 전에 끝나야 그날 새 정책이 예약에 들어간다
# 집은 작업을 다른 tick이 못 집는 시간. 가장 긴 작업(청년정책 첫 수집 1~3분, LMS 50명 배치)보다 넉넉히
LEASE = timedelta(minutes=30)
RETRY_FIRST = timedelta(minutes=30)  # 날짜 작업이 실패하면 처음 늦추는 시간. 실패할 때마다 두 배
WARN_AFTER = 5  # 날짜 작업이 잇달아 이만큼 실패하면 경고한다
ERROR_MAX = 500  # 예약표에 남기는 실패 이유 길이


@dataclass(frozen=True)
class Job:
    """도는 일 하나. `every`(간격)나 `daily_at`(KST 하루 한 번) 중 하나를 준다."""

    name: str  # 예약표 줄 이름 = /internal/jobs/* 주소의 끝
    label: str  # 로그에 쓰는 이름
    run: Callable[[], Awaitable[Any]]
    every: timedelta | None = None
    daily_at: time | None = None

    @property
    def daily(self) -> bool:
        return self.daily_at is not None


def next_daily(now: datetime, at: time) -> datetime:
    """KST로 `now` 다음의 `at`. 지금이 딱 그 시각이면 내일이다(두 번 돌지 않는다)."""
    here = now.astimezone(KST)
    target = here.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    if target <= here:
        target += timedelta(days=1)
    return target


def seconds_until(now: datetime, at: time) -> float:
    """KST로 다음 `at`까지 남은 초."""
    return (next_daily(now, at) - now.astimezone(KST)).total_seconds()


def next_after(job: Job, now: datetime) -> datetime:
    """`now`에 끝났을 때 다음 차례. 간격 작업은 끝난 때 + 간격, 날짜 작업은 지금 이후 첫 KST 시각."""
    if job.daily_at is not None:
        return next_daily(now, job.daily_at)
    assert job.every is not None, f"{job.label}에 주기가 없어요"
    return now + job.every


def first_run(job: Job, now: datetime) -> datetime:
    """예약표에 처음 넣는 차례. 간격 작업은 바로, 날짜 작업은 다음 KST 시각."""
    return next_daily(now, job.daily_at) if job.daily_at is not None else now


class Scheduler:
    """예약표를 보는 tick 하나와, 집은 작업마다 띄운 asyncio 작업들. 시험에서 `sleep`·`now`를 바꿔 넣는다."""

    def __init__(
        self,
        jobs: list[Job],
        *,
        connect: Connect,
        table_for: Callable[[AsyncConnection], JobScheduleRepository] = JobScheduleRepository,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] = current_time,
    ) -> None:
        self._jobs = {job.name: job for job in jobs}
        self._connect = connect
        self._table_for = table_for  # 시험은 메모리 예약표를 넣는다(SQL은 DB 시험이 본다)
        self._sleep = sleep
        self._now = now
        self._ticker: asyncio.Task[None] | None = None
        self._running: dict[str, asyncio.Task[None]] = {}

    @property
    def names(self) -> list[str]:
        return list(self._jobs)

    @property
    def ticking(self) -> bool:
        """서버 안 tick이 도는가(SCHEDULER_ENABLED)."""
        return self._ticker is not None and not self._ticker.done()

    @property
    def running(self) -> int:
        """지금 이 서버에서 도는 작업 수(tick 줄은 세지 않는다)."""
        return len(self._busy())

    def start(self) -> None:
        self._ticker = asyncio.create_task(self._tick_forever(), name="scheduler:tick")
        logger.info(
            "스케줄러를 켰어요: %s (1분마다 예약표를 봐요)",
            ", ".join(job.label for job in self._jobs.values()),
        )

    async def stop(self, timeout: float = 5.0) -> None:
        """tick과 도는 작업을 취소하고 멈출 때까지 기다린다(TaskRunner.drain과 같이 시간을 끊는다).

        취소된 작업은 임대를 풀고 멈춘다. 제때 멈추지 않은 것은 그대로 두고 넘어간다 — 서버를 끄는 길이
        여기서 영영 막히면 안 된다.
        """
        tasks = [task for task in (self._ticker, *self._running.values()) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(set(tasks), timeout=timeout)
            if pending:
                logger.warning("정기 작업 %d개가 제때 멈추지 않았어요", len(pending))
        self._ticker = None

    async def wait(self) -> None:
        """이 서버에서 도는 작업이 모두 끝날 때까지 기다린다(시험·끄기 전에 쓴다)."""
        tasks = [task for task in self._running.values() if not task.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def tick(self) -> list[str]:
        """때가 된 줄을 집어 작업마다 따로 띄운다. 띄운 작업 이름을 이른 차례부터 돌려준다.

        없는 줄은 먼저 넣는다(간격 작업은 바로, 날짜 작업은 다음 KST 시각). 이 서버에서 아직 도는 작업은 집지
        않는다. 예약표를 보지 못하면 로그만 남기고 빈 목록이다(다음 tick에 다시 본다).
        """
        now = self._now()
        busy = self._busy()
        free = [job for name, job in self._jobs.items() if name not in busy]
        if not free:
            return []
        try:
            # 집는 문장을 담은 트랜잭션은 블록이 끝나면 바로 확정한다 — 그래야 임대가 다른 서버에 보인다
            async with self._connect() as conn:
                table = self._table_for(conn)
                await table.ensure({job.name: first_run(job, now) for job in free})
                claimed = await table.claim([job.name for job in free], now=now, lease=LEASE)
        except Exception:
            logger.exception("예약표를 보지 못했어요. 다음 tick에 다시 봐요")
            return []
        for name in claimed:
            job = self._jobs[name]
            self._running[name] = asyncio.create_task(self._run(job), name=f"scheduler:{name}")
        return claimed

    def _busy(self) -> set[str]:
        return {name for name, task in self._running.items() if not task.done()}

    async def _tick_forever(self) -> None:
        while True:  # 켜자마자 한 번 — 꺼져 있던 동안 지난 차례를 바로 따라잡는다
            await self.tick()
            await self._sleep(TICK_EVERY.total_seconds())

    async def _run(self, job: Job) -> None:
        started = self._now()
        try:
            result = await job.run()
        except asyncio.CancelledError:  # 서버를 끈다. 임대를 풀어 다음 서버가 바로 집게 한다
            await self._release(job)
            raise
        except Exception as exc:
            logger.exception("정기 작업 %s이(가) 실패했어요", job.label)
            await self._failed(job, exc)
            return
        finished = self._now()
        seconds = (finished - started).total_seconds()
        logger.info("정기 작업 %s 끝 (%.1f초): %s", job.label, seconds, result)
        await self._finished(job, finished)

    async def _finished(self, job: Job, at: datetime) -> None:
        try:
            async with self._connect() as conn:
                await self._table_for(conn).finish(
                    job.name, now=at, next_run_at=next_after(job, at)
                )
        except Exception:
            logger.exception(
                "정기 작업 %s의 다음 차례를 적지 못했어요. 임대가 끝나면(%d분) 다시 돌아요",
                job.label,
                LEASE.total_seconds() // 60,
            )

    async def _failed(self, job: Job, exc: Exception) -> None:
        """간격 작업은 간격 뒤에 다시. 날짜 작업은 늦추되(30분·1시간·2시간 …) 다음 정해진 차례를 넘기지 않는다."""
        now = self._now()
        if job.daily_at is not None:
            first, cap = RETRY_FIRST, next_daily(now, job.daily_at)
        else:
            assert job.every is not None
            first, cap = job.every, now + job.every
        error = redact(f"{type(exc).__name__}: {exc}")[:ERROR_MAX]
        try:
            async with self._connect() as conn:
                failed = await self._table_for(conn).fail(
                    job.name, now=now, error=error, first=first, cap=cap
                )
        except Exception:
            logger.exception("정기 작업 %s의 실패를 적지 못했어요", job.label)
            return
        if failed is None:
            return
        logger.info(
            "정기 작업 %s은(는) %s에 다시 돌아요",
            job.label,
            failed.next_run_at.astimezone(KST).strftime("%m-%d %H:%M"),
        )
        if job.daily and failed.attempts >= WARN_AFTER:
            logger.warning(
                "정기 작업 %s이(가) %d번 잇달아 실패했어요. 예약표의 last_error를 보세요",
                job.label,
                failed.attempts,
            )

    async def _release(self, job: Job) -> None:
        try:
            async with self._connect() as conn:
                await self._table_for(conn).release(job.name)
        except Exception:
            logger.warning(
                "정기 작업 %s의 임대를 풀지 못했어요. %d분 뒤에 다시 집혀요",
                job.label,
                LEASE.total_seconds() // 60,
            )


def app_jobs(app: Any, *, now: Callable[[], datetime] = current_time) -> list[Job]:
    """앱 상태에 묶인 작업 목록. 매번 새 연결로 저장소를 만든다(연결을 오래 쥐지 않는다).

    `now`를 바꿀 수 있게 둔 것은 시험 때문이다 — 지난 시각을 주면 보낼 것이 없어서 DB를 건드리지
    않고 배선만 확인할 수 있다.
    """
    state = app.state

    async def send() -> Any:
        settings = state.settings
        sender = push_sender_for(state, settings)
        async with state.pool.connection() as conn:
            return await send_notifications(
                NotificationRepository(conn), PushRepository(conn), sender, now=now()
            )

    async def schedule() -> Any:
        # 판정 다시 계산과 예약을 한 연결에서 한다(블록이 끝나면 함께 커밋)
        async with state.pool.connection() as conn:
            return await schedule_notifications(
                NotificationRepository(conn), OpportunityRepository(conn), now=now()
            )

    async def sync() -> Any:
        service = lms_sync_service_for(
            state, settings=state.settings, llm=llm_for(state), runner=state.runner
        )
        return await lms_sync(service, now=now())

    async def fetch() -> Any:
        settings = state.settings
        return await fetch_policies_fresh(
            database_url=settings.database_url,
            api_key=settings.youth_api_key,
            log_connect=state.log_pool.connection,
            make_client=YouthPolicyClient,
            today=now().astimezone(KST).date(),
        )

    jobs = [
        Job(name="send-notifications", label="알림 발송", run=send, every=SEND_EVERY),
        Job(name="lms-sync", label="LMS 동기화", run=sync, every=LMS_EVERY),
        Job(
            name="schedule-notifications",
            label="공고 알림 예약",
            run=schedule,
            daily_at=SCHEDULE_AT,
        ),
    ]
    if state.settings.youth_api_key.strip():
        jobs.append(Job(name="fetch-policies", label="청년정책 수집", run=fetch, daily_at=FETCH_AT))
    else:
        logger.warning("청년정책 수집은 YOUTH_API_KEY가 없어 돌리지 않아요(api/.env)")
    return jobs
