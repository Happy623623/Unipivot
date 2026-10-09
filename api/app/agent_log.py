"""에이전트 실행 로깅: agent_runs → tool_calls → llm_calls (ERD 로깅 도메인, PRD 8장 지표의 원천).

async with agent_run(log_conn, trigger="poster_upload", user_id=user.id) as run:
    async with run.tool("extract_from_image", {"file_id": file_id}) as call:
        result = await llm.extract(...)
        await run.record_llm(provider="anthropic", model="...", input_tokens=...,
                             output_tokens=..., latency_ms=..., tool_call=call)
        call.output = {"title": result.title}

cost_usd를 빼면 단가표(app/pricing.py)로 비용을 계산한다.
"""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.pricing import cost_usd as priced_cost
from app.schemas.me import PROFILE_FIELDS

SECRET_HINTS = ("token", "secret", "password", "authorization", "api_key")
# 프로필 값은 LLM에도 로그에도 넣지 않는다(PRD 6장). 실수로 들어와도 여기서 지운다
PROFILE_KEYS = frozenset(PROFILE_FIELDS)
_KST = timezone(timedelta(hours=9))


def _hidden(key: str) -> bool:
    lowered = key.lower()
    return lowered in PROFILE_KEYS or any(hint in lowered for hint in SECRET_HINTS)


def scrub(value: Any) -> Any:
    """비밀값이나 프로필 항목 이름의 키는 값을 지운다. tool_calls에 남지 않게 하는 마지막 안전장치."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _hidden(str(key)) else scrub(item) for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


@dataclass
class ToolCall:
    id: str
    output: Any = None


@dataclass
class AgentRun:
    conn: AsyncConnection
    id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    _seq: int = 0

    @asynccontextmanager
    async def tool(self, name: str, input: dict[str, Any] | None = None) -> AsyncIterator[ToolCall]:
        self._seq += 1
        started = time.perf_counter()
        cursor = await self.conn.execute(
            "insert into tool_calls (run_id, seq, tool_name, input, status)"
            " values (%s, %s, %s, %s, 'running') returning id",
            (self.id, self._seq, name, Jsonb(scrub(input or {}))),
        )
        call = ToolCall(id=str((await cursor.fetchone())["id"]))
        status = "failed"
        try:
            yield call
            status = "succeeded"
        finally:
            output = Jsonb(scrub(call.output)) if call.output is not None else None
            await self.conn.execute(
                "update tool_calls set output = %s, status = %s, latency_ms = %s where id = %s",
                (output, status, _elapsed_ms(started), call.id),
            )

    async def record_llm(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        cost_usd: Decimal | float | None = None,
        tool_call: ToolCall | None = None,
        priced_on: date | None = None,
    ) -> None:
        """LLM 호출 1건. cost_usd를 빼면 priced_on(기본: 오늘 KST)의 단가로 계산한다."""
        if cost_usd is None:
            on = priced_on or datetime.now(_KST).date()
            cost = priced_cost(provider, model, input_tokens, output_tokens, on)
        else:
            cost = Decimal(str(cost_usd))
        await self.conn.execute(
            "insert into llm_calls (run_id, tool_call_id, provider, model, input_tokens,"
            " output_tokens, cost_usd, latency_ms) values (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                self.id,
                tool_call.id if tool_call else None,
                provider,
                model,
                input_tokens,
                output_tokens,
                cost,
                latency_ms,
            ),
        )
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_usd += cost


@asynccontextmanager
async def agent_run(
    conn: AsyncConnection,
    *,
    trigger: str,
    user_id: str | None = None,
    scenario_code: str | None = None,
) -> AsyncIterator[AgentRun]:
    """실행 하나를 기록한다. conn은 autocommit이어야 실패한 실행도 남는다(db.get_log_conn)."""
    if not conn.autocommit:
        raise RuntimeError("agent_run에는 autocommit 연결(get_log_conn)을 넘겨야 해요.")
    started = time.perf_counter()
    cursor = await conn.execute(
        "insert into agent_runs (user_id, trigger_type, scenario_code) values (%s, %s, %s)"
        " returning id",
        (user_id, trigger, scenario_code),
    )
    run = AgentRun(conn=conn, id=str((await cursor.fetchone())["id"]))
    try:
        yield run
    except Exception as exc:
        await _finish(run, started, "failed", repr(exc)[:500])
        raise
    await _finish(run, started, "succeeded", None)


async def _finish(run: AgentRun, started: float, status: str, error: str | None) -> None:
    await run.conn.execute(
        "update agent_runs set status = %s, finished_at = now(), latency_ms = %s,"
        " input_tokens = %s, output_tokens = %s, cost_usd = %s, error_message = %s where id = %s",
        (
            status,
            _elapsed_ms(started),
            run.input_tokens,
            run.output_tokens,
            run.cost_usd,
            error,
            run.id,
        ),
    )
