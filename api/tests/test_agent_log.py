from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app import pricing
from app.agent_log import AgentRun, abandon_run, agent_run, error_text, scrub, using
from app.errors import ApiError
from app.pricing import Price, cost_usd

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
