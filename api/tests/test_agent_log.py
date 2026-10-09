from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app import pricing
from app.agent_log import AgentRun, agent_run, scrub
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
        async with agent_run(TransactionConnection(), trigger="eval"):  # type: ignore[arg-type]
            pass


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
    autocommit = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def execute(self, query: str, params: Any = None) -> None:
        self.calls.append((query, params))


@pytest.mark.anyio
async def test_record_llm_prices_from_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(pricing.PRICES, ("test", "model-a"), TEST_PRICES[("test", "model-a")])
    conn = RecordingConnection()
    run = AgentRun(conn=conn, id="run-1")  # type: ignore[arg-type]
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
