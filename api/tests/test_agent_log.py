from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app import pricing
from app.agent_log import AgentRun, abandon_run, agent_run, error_text, scrub, start_run, using
from app.engines import ENGINES
from app.errors import ApiError
from app.pricing import Price, cost_usd
from tests.fakes import CHILD_RUN_ID, FakeLogConnection

TEST_PRICES = {
    ("test", "model-a"): (
        Price(date(2026, 1, 1), Decimal("1.00"), Decimal("5.00")),
        Price(date(2026, 11, 1), Decimal("0.50"), Decimal("2.50")),
    )
}


def test_scrub_hides_secrets() -> None:
    value = {
        "access_token": "a",
        "nested": {"API_KEY": "b", "items": [{"password": "c", "page": 2}]},
        "query": "장학금",
    }
    assert scrub(value) == {
        "access_token": "[REDACTED]",
        "nested": {"API_KEY": "[REDACTED]", "items": [{"password": "[REDACTED]", "page": 2}]},
        "query": "장학금",
    }


def test_scrub_hides_profile_values() -> None:
    """프로필 값은 tool_calls에 남기지 않는다 (PRD 6장)."""
    value = {
        "notice": "장학 공고",
        "profile": {"gpa_last_semester": 3.9, "birth_date": "2000-01-01", "Income_Bracket": 3},
    }
    assert scrub(value) == {
        "notice": "장학 공고",
        "profile": {
            "gpa_last_semester": "[REDACTED]",
            "birth_date": "[REDACTED]",
            "Income_Bracket": "[REDACTED]",
        },
    }


@pytest.mark.anyio
async def test_agent_run_requires_autocommit_connection() -> None:
    class TransactionConnection:
        autocommit = False

    with pytest.raises(RuntimeError):
        using(TransactionConnection())  # type: ignore[arg-type]


def test_cost_uses_price_effective_on_date() -> None:
    assert cost_usd("test", "model-a", 1200, 300, date(2026, 10, 7), TEST_PRICES) == Decimal(
        "0.002700"
    )
    assert cost_usd("test", "model-a", 1200, 300, date(2026, 11, 1), TEST_PRICES) == Decimal(
        "0.001350"
    )
    with pytest.raises(KeyError):
        cost_usd("test", "unknown", 1, 1, date(2026, 10, 7), TEST_PRICES)
    with pytest.raises(KeyError):
        cost_usd("test", "model-a", 1, 1, date(2025, 12, 31), TEST_PRICES)  # 단가 시작 전


class RecordingConnection:
    """빌린 횟수까지 세는 가짜 로그 연결. connect()가 공급자다."""

    autocommit = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.borrows = 0

    async def execute(self, query: str, params: Any = None) -> None:
        self.calls.append((query, params))

    def connect(self) -> Any:
        connection = self

        @asynccontextmanager
        async def borrow() -> AsyncIterator["RecordingConnection"]:
            connection.borrows += 1
            yield connection

        return borrow()


@pytest.mark.anyio
async def test_record_llm_prices_from_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(pricing.PRICES, ("test", "model-a"), TEST_PRICES[("test", "model-a")])
    conn = RecordingConnection()
    run = AgentRun(connect=conn.connect, id="run-1")
    await run.record_llm(
        provider="test",
        model="model-a",
        input_tokens=1200,
        output_tokens=300,
        latency_ms=10,
        priced_on=date(2026, 10, 7),
    )
    await run.record_llm(  # 비용을 직접 넘기면 그 값을 쓴다
        provider="test",
        model="model-a",
        input_tokens=1000,
        output_tokens=0,
        latency_ms=10,
        cost_usd=0.001,
    )
    assert conn.calls[0][1][6] == Decimal("0.002700")
    assert (run.input_tokens, run.output_tokens, run.cost_usd) == (2200, 300, Decimal("0.003700"))
    assert conn.borrows == 2  # 한 줄 쓸 때마다 빌렸다 돌려준다(쥐고 있지 않는다)


def test_error_text_keeps_api_errors_for_students() -> None:
    """ApiError는 "코드: 문구"(GET /runs/{id}가 보여 준다), 그 밖은 내부 기록이다."""
    assert (
        error_text(ApiError(502, "LLM_ERROR", "다시 눌러 주세요."))
        == "LLM_ERROR: 다시 눌러 주세요."
    )
    assert error_text(ValueError("x")) == "ValueError('x')"
    assert len(error_text(ValueError("가" * 900))) == 500


@pytest.mark.anyio
async def test_agent_run_continues_a_started_run() -> None:
    """start_run으로 만든 실행은 run_id로 이어 쓴다(새 행을 만들지 않는다). 실패하면 이유를 남긴다."""
    conn = RecordingConnection()
    with pytest.raises(ApiError):
        async with agent_run(conn.connect, trigger="prepare", run_id="run-7") as run:
            assert run.id == "run-7"
            assert conn.borrows == 1  # autocommit 확인만 하고 돌려준다. 실행 내내 쥐지 않는다
            raise ApiError(502, "LLM_ERROR", "다시 눌러 주세요.")
    assert len(conn.calls) == 1 and conn.calls[0][0].startswith("update agent_runs")
    status, *_, error, run_id = conn.calls[0][1]
    assert (status, error, run_id) == ("failed", "LLM_ERROR: 다시 눌러 주세요.", "run-7")


@pytest.mark.anyio
async def test_abandon_run_closes_a_run_that_never_started() -> None:
    conn = RecordingConnection()
    await abandon_run(
        conn.connect, "run-8", ApiError(409, "INTERNAL_ERROR", "이미 준비하고 있어요.")
    )
    query, params = conn.calls[0]
    assert "status = 'failed'" in query and "status = 'running'" in query
    assert params == ("INTERNAL_ERROR: 이미 준비하고 있어요.", "run-8")


# ── 실행 트리(O1): 자식 실행 ─────────────────────────────────────────────────


def _closed(log: FakeLogConnection, run_id: str) -> list[Any]:
    """그 실행을 닫은 문장의 값들(status, latency, input, output, cost, model, review_codes, error, id)."""
    return [
        params
        for query, params in log.statements
        if query.startswith("update agent_runs set status") and params[-1] == run_id
    ]


@pytest.mark.anyio
async def test_a_child_run_hangs_under_its_parent_and_adds_its_cost() -> None:
    """자식은 부모 행을 가리키고(trigger·시나리오는 DB가 부모에서 옮긴다), 끝나면 토큰·비용이 부모에 더해진다."""
    log = FakeLogConnection()
    parent = AgentRun(connect=using(log), id=log.run_id)  # type: ignore[arg-type]
    async with parent.child() as child:
        await child.record_llm(
            provider="test",
            model="model-a",
            input_tokens=100,
            output_tokens=20,
            latency_ms=5,
            cost_usd=0.002,
        )

    assert child.id == CHILD_RUN_ID
    assert log.children() == [
        {"user": None, "scenario": None, "parent": log.run_id, "engine": None, "version": None}
    ]
    assert (parent.input_tokens, parent.output_tokens, parent.cost_usd) == (
        100,
        20,
        Decimal("0.002"),
    )
    (closed,) = _closed(log, CHILD_RUN_ID)
    assert (closed[0], closed[2], closed[3], closed[4]) == ("succeeded", 100, 20, Decimal("0.002"))
    assert (closed[5], closed[6]) == ("model-a", [])  # 자식이 부른 모델(O2)
    assert parent.model is None  # 부모는 모델을 부르지 않았다
    assert _closed(log, log.run_id) == []  # 부모를 닫는 것은 부모를 연 쪽이다


@pytest.mark.anyio
async def test_a_failed_child_is_closed_as_failed_and_still_charges_its_parent() -> None:
    """블록이 터지면 자식을 실패로 닫고 예외를 그대로 올린다. 이미 쓴 비용은 부모에 더한다."""
    log = FakeLogConnection()
    parent = AgentRun(connect=using(log), id=log.run_id)  # type: ignore[arg-type]
    with pytest.raises(ApiError):
        async with parent.child(user_id="u-1", scenario_code="T-1") as child:
            await child.record_llm(
                provider="test",
                model="model-a",
                input_tokens=10,
                output_tokens=0,
                latency_ms=5,
                cost_usd=0.001,
            )
            raise ApiError(502, "LLM_TIMEOUT", "늦었어요.")

    assert log.children() == [
        {"user": "u-1", "scenario": "T-1", "parent": log.run_id, "engine": None, "version": None}
    ]
    (closed,) = _closed(log, CHILD_RUN_ID)
    assert (closed[0], closed[-2]) == ("failed", "LLM_TIMEOUT: 늦었어요.")
    assert parent.cost_usd == Decimal("0.001")


@pytest.mark.anyio
async def test_an_engine_child_carries_the_engine_name_version_model_and_review_codes() -> None:
    """엔진 도장(O2): 자식 행에 등록부의 엔진 이름·버전을 남기고, 닫을 때 모델과 이유 코드를 남긴다."""
    log = FakeLogConnection()
    parent = AgentRun(connect=using(log), id=log.run_id)  # type: ignore[arg-type]
    async with parent.child(engine="extract.requirements") as child:
        await child.record_llm(
            provider="test",
            model="model-a",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            cost_usd=0,
        )
        await child.record_llm(
            provider="test",
            model="model-b",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            cost_usd=0,
        )
        child.review_codes = ("AMBIGUOUS", "LOW_CONFIDENCE")

    assert log.children() == [
        {
            "user": None,
            "scenario": None,
            "parent": log.run_id,
            "engine": "extract.requirements",
            "version": ENGINES["extract.requirements"].version,
        }
    ]
    (closed,) = _closed(log, CHILD_RUN_ID)
    # 모델은 마지막으로 부른 것이다(캐스케이드면 위 등급, 명세 v1 3.6)
    assert (closed[0], closed[5], closed[6]) == (
        "succeeded",
        "model-b",
        ["AMBIGUOUS", "LOW_CONFIDENCE"],
    )


@pytest.mark.anyio
async def test_a_shared_engine_run_cannot_name_a_student() -> None:
    """결과를 여러 학생이 보는 엔진의 실행에는 user_id를 남기지 못한다(명세 v1 6장 5번). 행도 만들지 않는다."""
    log = FakeLogConnection()
    parent = AgentRun(connect=using(log), id=log.run_id)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="user_id"):
        async with parent.child(engine="classify.announcement", user_id="u-1"):
            pass
    with pytest.raises(ValueError, match="user_id"):
        await start_run(
            using(log),  # type: ignore[arg-type]
            trigger="batch_crawl",
            user_id="u-1",
            engine="extract.requirements",
        )
    assert log.statements == []


@pytest.mark.anyio
async def test_an_unknown_engine_is_refused_before_any_row() -> None:
    log = FakeLogConnection()
    parent = AgentRun(connect=using(log), id=log.run_id)  # type: ignore[arg-type]
    with pytest.raises(KeyError, match="extract.everything"):
        async with parent.child(engine="extract.everything"):
            pass
    assert log.statements == []


@pytest.mark.anyio
async def test_a_single_engine_flow_stamps_its_root_when_the_row_is_made() -> None:
    """포스터처럼 엔진 하나뿐인 흐름은 start_run이 뿌리에 엔진을 남긴다. 이어 쓰는 쪽은 엔진을 다시 주지 않는다."""
    log = FakeLogConnection()
    run_id = await start_run(
        using(log),  # type: ignore[arg-type]
        trigger="poster_upload",
        user_id="u-1",
        engine="extract.poster",
    )
    query, params = log.statements[0]
    assert query.startswith("insert into agent_runs")
    assert params == {
        "user": "u-1",
        "trigger": "poster_upload",
        "scenario": None,
        "engine": "extract.poster",
        "version": ENGINES["extract.poster"].version,
    }
    with pytest.raises(ValueError, match="start_run"):
        async with agent_run(
            using(log),  # type: ignore[arg-type]
            trigger="poster_upload",
            run_id=run_id,
            engine="extract.poster",
        ):
            pass
