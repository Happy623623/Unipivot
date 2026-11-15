"""요건 추출 캐스케이드(O4, 오케스트레이션 명세 4.3): 싼 모델로 먼저, 원인이 모델인 이유가 나오면 위 모델로 처음부터.

가짜 에이전트로 올릴지·무엇을 고를지·시간 예산을, 가짜 LLM으로 실제 에이전트 둘이 한 실행 기록에 남는 것을 본다.
"""

import asyncio
import json
from datetime import date
from typing import Any

import pytest

from app.config import Settings
from app.crawl import service as notice_service
from app.engines import MODEL_CAUSED
from app.extraction import ExtractionAgent, ExtractionResult, NoticeInput
from app.extraction import cascade as cascade_module
from app.extraction.cascade import ESCALATE, CascadeAgent
from app.extraction.prompt import SUBMIT
from app.extraction.setup import make_extractor
from tests.llm_fakes import MemoryRunLog, ScriptedLlm, call

pytestmark = pytest.mark.anyio

LITE, STANDARD = "gemini-3.5-flash-lite", "gemini-3.8-flash"
NOTICE = NoticeInput(
    title="○○장학생 선발 안내",
    body="1. 지원 자격: 직전 학기 평점평균 3.0 이상(4.5 만점)\n2. 신청 기간: 10. 13.(월) ~ 10. 24.(금)",
    posted_on=date(2026, 10, 8),
)


def result(*codes: str, succeeded: bool = True) -> ExtractionResult:
    return ExtractionResult(
        succeeded=succeeded, needs_review=bool(codes), review_reasons=codes, review_codes=codes
    )


class FakeAgent:
    """정해 둔 결과(또는 예외)를 돌려주고, 불린 횟수와 걸린 시간(가짜 시계)을 남긴다."""

    def __init__(
        self, model: str, outcome: ExtractionResult | Exception, *, clock: Any = None, takes=0.0
    ):
        self.model, self.outcome, self.clock, self.takes = model, outcome, clock, takes
        self.calls = 0

    async def run(self, notice: NoticeInput, log: Any) -> ExtractionResult:
        self.calls += 1
        if self.clock is not None:
            self.clock.now += self.takes
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def climb(
    first: ExtractionResult | Exception,
    second: ExtractionResult | Exception,
    **options: Any,
) -> tuple[ExtractionResult, FakeAgent, FakeAgent, MemoryRunLog]:
    one, two = FakeAgent(LITE, first), FakeAgent(STANDARD, second)
    log = MemoryRunLog()
    picked = await CascadeAgent(one, two, on=MODEL_CAUSED, **options).run(NOTICE, log)
    return picked, one, two, log


def escalations(log: MemoryRunLog) -> list[tuple[Any, Any]]:
    return [(tool.input, tool.output) for tool in log.tools if tool.name == ESCALATE]


async def test_a_clean_or_cap_only_first_answer_is_kept_and_the_upper_model_is_not_called() -> None:
    """상한·원문 탓 이유(READ_CAP·AMBIGUOUS)는 모델을 바꿔도 풀리지 않는다 — 올리지 않는다."""
    for codes in ((), ("AMBIGUOUS", "READ_CAP", "MODEL_FLAG", "PARTIAL_READ", "MISSING_FILE")):
        first = result(*codes)
        picked, one, two, log = await climb(first, result())
        assert picked is first and (one.calls, two.calls) == (1, 0)
        assert escalations(log) == []


async def test_a_model_caused_code_climbs_and_the_better_answer_wins() -> None:
    first, second = result("AMBIGUOUS", "REPAIRED", "LOW_CONFIDENCE"), result("AMBIGUOUS")
    picked, one, two, log = await climb(first, second)

    assert picked is second and (one.calls, two.calls) == (1, 1)
    # 왜 올렸는지는 원인이 모델인 코드만, 결과에 나온 순서대로 남는다
    assert escalations(log) == [
        (
            {"from": LITE, "to": STANDARD, "codes": ["REPAIRED", "LOW_CONFIDENCE"]},
            {"chosen": "second", "second_codes": []},
        )
    ]


async def test_each_model_caused_code_alone_climbs() -> None:
    for code in sorted(MODEL_CAUSED):
        first = result(code, succeeded=code != "NO_SUBMISSION")
        picked, _one, two, _log = await climb(first, result())
        assert two.calls == 1 and picked.review_codes == (), code


async def test_a_tie_goes_to_the_upper_model() -> None:
    first, second = result("LOW_CONFIDENCE"), result("NOT_READ")
    picked, *_ = await climb(first, second)
    assert picked is second


async def test_a_submission_beats_none_and_fewer_model_codes_beat_more() -> None:
    first = result("REPAIRED")
    picked, _one, _two, log = await climb(first, result("NO_SUBMISSION", succeeded=False))
    assert picked is first
    assert escalations(log)[0][1] == {"chosen": "first", "second_codes": ["NO_SUBMISSION"]}

    first = result("REPAIRED")
    picked, *_ = await climb(first, result("REPAIRED", "LOW_CONFIDENCE"))
    assert picked is first


async def test_when_the_lite_model_fails_the_upper_model_answers() -> None:
    second = result()
    picked, _one, two, log = await climb(TimeoutError("느림"), second)
    assert picked is second and two.calls == 1
    assert escalations(log) == [
        (
            {"from": LITE, "to": STANDARD, "codes": ["ERROR:TimeoutError"]},
            {"chosen": "second", "second_codes": []},
        )
    ]


async def test_when_the_upper_model_fails_the_first_answer_is_kept() -> None:
    first = result("LOW_CONFIDENCE")
    picked, _one, _two, log = await climb(first, RuntimeError("모델 서버 오류"))
    assert picked is first
    assert escalations(log)[0][1] == {"chosen": "first", "error": "RuntimeError"}


async def test_when_both_fail_the_upper_models_error_is_raised() -> None:
    with pytest.raises(RuntimeError, match="위"):
        await climb(TimeoutError("아래"), RuntimeError("위"))


async def test_no_time_left_in_the_budget_keeps_the_first_answer() -> None:
    """학교 공지 링크(학생이 기다림): 첫 실행이 예산을 거의 다 쓰면 올리지 않는다 — 바깥 상한에 첫 결과까지 잃지 않게."""
    clock = Clock()
    one = FakeAgent(LITE, result("LOW_CONFIDENCE"), clock=clock, takes=100.0)
    two = FakeAgent(STANDARD, result(), clock=clock)
    log = MemoryRunLog()
    agent = CascadeAgent(one, two, on=MODEL_CAUSED, budget_s=115.0, clock=clock)

    picked = await agent.run(NOTICE, log)

    assert picked is one.outcome and two.calls == 0  # 남은 15초 < MIN_ESCALATE_S(20초)
    assert escalations(log) == [
        (
            {"from": LITE, "to": STANDARD, "codes": ["LOW_CONFIDENCE"]},
            {"chosen": "first", "skipped": "time"},
        )
    ]


async def test_the_upper_model_only_gets_the_rest_of_the_budget(monkeypatch) -> None:
    monkeypatch.setattr(cascade_module, "MIN_ESCALATE_S", 0.0)
    first = result("LOW_CONFIDENCE")

    class Slow(FakeAgent):
        async def run(self, notice: NoticeInput, log: Any) -> ExtractionResult:
            self.calls += 1
            await asyncio.sleep(5)
            return result()

    log = MemoryRunLog()
    agent = CascadeAgent(
        FakeAgent(LITE, first), Slow(STANDARD, result()), on=MODEL_CAUSED, budget_s=0.05
    )
    picked = await asyncio.wait_for(agent.run(NOTICE, log), timeout=2)

    assert picked is first
    assert escalations(log)[0][1] == {"chosen": "first", "error": "TimeoutError"}


def submission(confidence: float) -> dict[str, Any]:
    return {
        "requirements": [
            {
                "clause_no": 1,
                "field": "gpa_last_semester",
                "operator": "gte",
                "value_json": json.dumps(3.0),
                "evidence_text": "직전 학기 평점평균 3.0 이상(4.5 만점)",
                "is_ambiguous": False,
            }
        ],
        "documents": [],
        "deadline": "2026-10-24",
        "confidence": confidence,
        "needs_review": False,
    }


async def test_real_agents_climb_on_low_confidence_and_log_both_models_in_one_run() -> None:
    """실제 에이전트 둘: Flash-Lite가 확신 낮게 내면(LOW_CONFIDENCE) Flash가 처음부터 돌고, 두 모델 호출이 한 실행에 남는다."""
    llm = ScriptedLlm(call(SUBMIT, **submission(0.4)), call(SUBMIT, **submission(0.9)))
    agent = CascadeAgent(
        ExtractionAgent(llm, model=LITE), ExtractionAgent(llm, model=STANDARD), on=MODEL_CAUSED
    )
    log = MemoryRunLog()

    picked = await agent.run(NOTICE, log)

    assert picked.succeeded and picked.review_codes == () and picked.confidence is not None
    assert [request.model for request in llm.requests] == [LITE, STANDARD]
    assert len(llm.requests[1].turns) == 1  # 위 모델은 첫 대화를 넘겨받지 않고 처음부터
    assert [entry["model"] for entry in log.llm] == [LITE, STANDARD]
    assert [tool.name for tool in log.tools] == [SUBMIT, ESCALATE, SUBMIT]


async def test_real_agents_do_not_climb_on_a_confident_answer() -> None:
    llm = ScriptedLlm(call(SUBMIT, **submission(0.9)))
    agent = CascadeAgent(
        ExtractionAgent(llm, model=LITE), ExtractionAgent(llm, model=STANDARD), on=MODEL_CAUSED
    )
    picked = await agent.run(NOTICE, MemoryRunLog())
    assert picked.succeeded and [request.model for request in llm.requests] == [LITE]


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_the_factory_builds_one_agent_while_the_switch_is_off() -> None:
    agent = make_extractor(ScriptedLlm(), settings())
    assert isinstance(agent, ExtractionAgent)
    assert (agent.model, agent.vision_model) == (STANDARD, "gemini-3.8-flash")


def test_the_factory_builds_the_cascade_when_switched_on() -> None:
    agent = make_extractor(
        ScriptedLlm(),
        settings(extraction_cascade=True, vision_model="gemini-3.8-flash"),
        budget_s=9.0,
    )
    assert isinstance(agent, CascadeAgent)
    assert isinstance(agent.first, ExtractionAgent) and isinstance(agent.second, ExtractionAgent)
    assert (agent.first.model, agent.second.model) == (LITE, STANDARD)
    # 그림 읽기는 두 단계 모두 VISION_MODEL(read.vision 엔진) — 캐스케이드는 글 모델만 바꾼다
    assert agent.first.vision_model == agent.second.vision_model == "gemini-3.8-flash"
    assert agent.on == {str(code) for code in MODEL_CAUSED} and agent.budget_s == 9.0


def test_an_explicit_model_skips_the_cascade() -> None:
    """비교 실험·CLI의 --model은 그 모델 하나로 돈다(모델끼리 견주려고)."""
    agent = make_extractor(ScriptedLlm(), settings(extraction_cascade=True), model=LITE)
    assert isinstance(agent, ExtractionAgent) and agent.model == LITE


def test_the_link_import_leaves_room_under_its_model_timeout() -> None:
    assert 0 < notice_service.CASCADE_SECONDS < notice_service.MODEL_SECONDS
    assert (
        notice_service.CASCADE_SECONDS - cascade_module.MIN_ESCALATE_S > 60
    )  # 첫 실행에 1분은 준다
