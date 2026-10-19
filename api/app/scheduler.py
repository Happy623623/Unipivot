"""서버 안 스케줄러 (PRD 9장 "스케줄러"). 켜 두면 정기 작업이 알아서 돈다.

`POST /internal/jobs/*`를 사람이 부를 때와 **같은 함수**(`app/jobs.py`)를 부른다. 바깥 크론
(GitHub Actions·pg_cron)을 쓰려면 이것을 끄고 그 주소를 부르면 된다 — 둘을 같이 켜지 않는다.

도는 것:

| 작업 | 주기 | 서버를 켤 때 |
| --- | --- | --- |
| 알림 발송 | 5분 | **바로 한 번** 돈다(서버가 꺼져 있던 동안 밀린 알림을 바로 보낸다) |
| LMS 동기화 | 30분 | 안 돈다(첫 30분은 기다린다) |
| 공고 알림 예약 | 하루 한 번 KST 08:30 | 안 돈다 |
| 청년정책 수집 | 하루 한 번 KST 04:00 | 안 돈다. `YOUTH_API_KEY`가 없으면 목록에 넣지 않는다 |

청년정책 수집이 **04:00**인 것은 예약(08:30) 전에 끝나 그날 새 정책이 그날 예약에 들어가게 하려는
것이다. 처음 넣을 때 1~3분 걸리는 일이라 새벽에 둔다(온통청년 호출 600번 상한).

지키는 것:
- **일 하나가 터져도 로그만 남기고 다음 차례에 다시 돈다.** 한 번 실패로 스케줄러가 죽지 않는다
- 일이 주기보다 오래 걸려도 **겹쳐 돌지 않는다**(한 작업은 한 줄로 돈다: 돌고 → 자고 → 돌고)
- 예약은 **KST 08:30**이다. 공고 알림 시각이 KST 09:00이고 지난 시각은 만들지 않아서,
  그 전에 돌아야 그날 알림이 생긴다(PRD F-33)
- 서버를 끌 때 돌던 일은 취소한다. 작업은 모두 다시 돌려도 되는 것들이다
- **워커는 하나여야 한다.** 여러 프로세스로 띄우면 같은 일이 여러 번 돈다
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from app.clock import current_time
from app.eligibility import KST
from app.jobs import fetch_policies_fresh, lms_sync, schedule_notifications, send_notifications
from app.llm.deps import llm_for
from app.lms.sync import lms_sync_service_for
from app.push.deps import push_sender_for
from app.repositories.notifications import NotificationRepository
from app.repositories.push import PushRepository
from app.youth.client import YouthPolicyClient

logger = logging.getLogger(__name__)

SEND_EVERY = timedelta(minutes=5)
LMS_EVERY = timedelta(minutes=30)
SCHEDULE_AT = time(8, 30)  # KST. 알림 시각(09:00)보다 앞이어야 한다
FETCH_AT = time(4, 0)  # KST. 예약(08:30) 전에 끝나야 그날 새 정책이 예약에 들어간다


@dataclass(frozen=True)
class Job:
    """도는 일 하나. `every`(간격)나 `daily_at`(KST 하루 한 번) 중 하나를 준다."""

    name: str
    run: Callable[[], Awaitable[Any]]
    every: timedelta | None = None
    daily_at: time | None = None
    at_start: bool = False  # 서버를 켜자마자 한 번 도는가


def seconds_until(now: datetime, at: time) -> float:
    """KST로 다음 `at`까지 남은 초. 지금이 딱 그 시각이면 내일까지 기다린다(두 번 돌지 않는다)."""
    here = now.astimezone(KST)
    target = here.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    if target <= here:
        target += timedelta(days=1)
    return (target - here).total_seconds()


class Scheduler:
    """작업마다 asyncio 줄 하나. 시험에서 `sleep`·`now`를 바꿔 시간 없이 돌린다."""

    def __init__(
        self,
        jobs: list[Job],
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] = current_time,
    ) -> None:
        self._jobs = jobs
        self._sleep = sleep
        self._now = now
        self._tasks: list[asyncio.Task[None]] = []

    def start(self) -> None:
        for job in self._jobs:
            self._tasks.append(asyncio.create_task(self._loop(job), name=f"scheduler:{job.name}"))
        logger.info("스케줄러를 켰어요: %s", ", ".join(job.name for job in self._jobs))

    async def stop(self, timeout: float = 5.0) -> None:
        """작업을 취소하고 멈출 때까지 기다린다(TaskRunner.drain과 같이 시간을 끊는다).

        제때 멈추지 않은 줄은 그대로 들고 있는다 — 서버를 끄는 길이 여기서 영영 막히면 안 된다.
        """
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            _, pending = await asyncio.wait(set(self._tasks), timeout=timeout)
            if pending:
                logger.warning("정기 작업 %d개가 제때 멈추지 않았어요", len(pending))
            self._tasks = list(pending)

    @property
    def running(self) -> int:
        return len([task for task in self._tasks if not task.done()])

    async def _loop(self, job: Job) -> None:
        if not job.at_start:
            await self._sleep(self._wait_for(job))
        while True:
            await self._run_once(job)
            await self._sleep(self._wait_for(job))

    def _wait_for(self, job: Job) -> float:
        if job.daily_at is not None:
            return seconds_until(self._now(), job.daily_at)
        assert job.every is not None, f"{job.name}에 주기가 없어요"
        return job.every.total_seconds()

    async def _run_once(self, job: Job) -> None:
        started = self._now()
        try:
            result = await job.run()
        except Exception:  # 취소(CancelledError)는 Exception이 아니라 그대로 올라간다
            logger.exception("정기 작업 %s이(가) 실패했어요. 다음 차례에 다시 해요", job.name)
            return
        seconds = (self._now() - started).total_seconds()
        logger.info("정기 작업 %s 끝 (%.1f초): %s", job.name, seconds, result)


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
        async with state.pool.connection() as conn:
            return await schedule_notifications(NotificationRepository(conn), now=now())

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
        Job(name="알림 발송", run=send, every=SEND_EVERY, at_start=True),
        Job(name="LMS 동기화", run=sync, every=LMS_EVERY),
        Job(name="공고 알림 예약", run=schedule, daily_at=SCHEDULE_AT),
    ]
    if state.settings.youth_api_key.strip():
        jobs.append(Job(name="청년정책 수집", run=fetch, daily_at=FETCH_AT))
    else:
        logger.warning("청년정책 수집은 YOUTH_API_KEY가 없어 돌리지 않아요(api/.env)")
    return jobs
