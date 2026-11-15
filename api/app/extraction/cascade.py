"""요건 추출 캐스케이드(O4, 오케스트레이션 명세 4.3 — 피드백 "여러 개가 돌아가면서 비용 효율적").

    agent = CascadeAgent(lite_agent, standard_agent, on=MODEL_CAUSED)
    result = await agent.run(notice, run)        # ExtractionAgent와 같은 모양

싼 모델(lite)로 먼저 돌리고, 결과에 **원인이 모델인 원문 확인 이유**(제출 못 함·코드가 고침·확신 낮음·첨부를
읽지 않음)가 있을 때만 위 모델(standard)로 **처음부터** 한 번 더 돈다 — 첫 대화를 넘기지 않는다(생각 서명이 모델마다
다르고, 틀린 첫 제출에 끌려가지 않게). 둘 다 같은 실행 기록(run) 안에서 돌아 비용·토큰이 한 실행에 더해지고,
실행의 model은 마지막으로 부른 모델이 된다(올렸으면 standard). 올릴 때는 도구 기록 하나(escalate_model)를 남긴다 —
무엇에서 무엇으로, 왜(첫 결과의 코드), 어느 쪽을 골랐는지.

고르기: 받은 제출이 있는 쪽 > 원인이 모델인 이유가 적은 쪽 > 위 모델. 첫 모델이 답하지 않으면(예외) 위 모델로 가고,
위 모델이 답하지 않으면 첫 결과를 쓴다(둘 다 답하지 않으면 위 모델의 예외를 올린다). budget_s를 주면(학생이 기다리는
학교 공지 링크) 첫 실행에 쓴 시간을 빼고 남은 시간만 위 모델을 기다리고, 남은 시간이 MIN_ESCALATE_S보다 적으면
올리지 않는다 — 바깥의 시간 상한(asyncio.timeout)에 걸려 이미 받은 첫 결과까지 잃지 않게.
"""

import asyncio
import time
from collections.abc import Callable, Iterable
from typing import Any

from app.extraction.agent import Extractor, RunLog
from app.extraction.models import ExtractionResult, NoticeInput

ESCALATE = "escalate_model"  # 도구 기록 이름(tool_calls.tool_name). 모델에 보이는 도구는 아니다
MIN_ESCALATE_S = 20.0  # 위 모델에 줄 시간이 이보다 적으면 올리지 않는다


class CascadeAgent:
    def __init__(
        self,
        first: Extractor,
        second: Extractor,
        *,
        on: Iterable[str],
        budget_s: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.first = first
        self.second = second
        self.on = frozenset(str(code) for code in on)
        self.budget_s = budget_s
        self.clock = clock
        self.model = f"{first.model}→{second.model}"  # 화면·로그 표시용. 실행의 model은 마지막 모델

    def reasons(self, result: ExtractionResult) -> tuple[str, ...]:
        """위로 올릴 이유 — 결과의 코드 중 원인이 모델인 것(순서는 결과 그대로)."""
        return tuple(code for code in result.review_codes if code in self.on)

    async def run(self, notice: NoticeInput, log: RunLog) -> ExtractionResult:
        started = self.clock()
        first: ExtractionResult | None
        try:
            first = await self.first.run(notice, log)
        except Exception as exc:  # 모델이 답하지 않았다. 위 모델로 한 번 더
            first, codes = None, (f"ERROR:{type(exc).__name__}",)
        else:
            codes = self.reasons(first)
            if not codes:
                return first
        wait = None if self.budget_s is None else self.budget_s - (self.clock() - started)
        if first is not None and wait is not None and wait < MIN_ESCALATE_S:
            async with log.tool(ESCALATE, self._input(codes)) as call:
                call.output = {"chosen": "first", "skipped": "time"}
            return first
        async with log.tool(ESCALATE, self._input(codes)) as call:
            try:
                async with asyncio.timeout(wait):
                    second = await self.second.run(notice, log)
            except Exception as exc:  # 위 모델이 답하지 않으면 첫 결과를 쓴다
                if first is None:
                    raise
                call.output = {"chosen": "first", "error": type(exc).__name__}
                return first
            better = first is None or self._rank(second) <= self._rank(first)
            call.output = {
                "chosen": "second" if better else "first",
                "second_codes": list(self.reasons(second)),
            }
            return second if better or first is None else first

    def _input(self, codes: tuple[str, ...]) -> dict[str, Any]:
        return {"from": self.first.model, "to": self.second.model, "codes": list(codes)}

    def _rank(self, result: ExtractionResult) -> tuple[bool, int]:
        """작을수록 낫다: 받은 제출이 있는 쪽, 그다음 원인이 모델인 이유가 적은 쪽. 같으면 위 모델을 고른다."""
        return (not result.succeeded, len(self.reasons(result)))
