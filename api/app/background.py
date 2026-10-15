"""요청이 끝난 뒤 이어서 할 일(준비하기 실행). API 명세 2장의 202 + run_id 작업이 쓴다.

FastAPI BackgroundTasks는 요청의 의존성(DB 연결·트랜잭션)이 그 일을 마칠 때까지 닫히지 않아 프로필 잠금을
붙잡는다. 그래서 요청과 따로 asyncio 작업으로 돌리고, 일은 자기 연결을 따로 연다.
테스트는 InlineRunner로 바꿔 응답 전에 끝까지 돌린다.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request

logger = logging.getLogger(__name__)


class TaskRunner:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(self, job: Coroutine[Any, Any, None]) -> None:
        """일을 띄우고 바로 돌아온다. 일 안의 예외는 일이 스스로 기록한다(여기서는 로그만)."""
        task = asyncio.create_task(job)
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("뒤에서 돌던 일이 실패했어요: %r", error)

    @property
    def running(self) -> int:
        """아직 돌고 있는 일의 수. drain이 끝나도 0이 아니면 못 끝낸 일이 있다."""
        return len(self._tasks)

    async def drain(self, timeout: float) -> None:
        """서버를 끌 때 돌던 일을 timeout초까지 기다린다. 못 끝낸 일은 다음 요청이 멈춘 실행으로 본다."""
        if self._tasks:
            await asyncio.wait(set(self._tasks), timeout=timeout)


class InlineRunner(TaskRunner):
    """테스트용: 일을 그 자리에서 끝까지 돌린다."""

    async def start(self, job: Coroutine[Any, Any, None]) -> None:
        await job


def get_runner(request: Request) -> TaskRunner:
    return request.app.state.runner


RunnerDep = Annotated[TaskRunner, Depends(get_runner)]
