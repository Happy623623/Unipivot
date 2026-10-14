"""에이전트 실행 로깅: agent_runs → tool_calls → llm_calls (ERD 로깅 도메인, PRD 8장 지표의 원천).

async with agent_run(connect, trigger="poster_upload", user_id=user.id) as run:
    async with run.tool("extract_from_image", {"file_id": file_id}) as call:
        result = await llm.extract(...)
        await run.record_llm(provider="anthropic", model="...", input_tokens=...,
                             output_tokens=..., latency_ms=..., tool_call=call)
        call.output = {"title": result.title}

connect는 autocommit 연결을 주는 공급자다(app/db.py의 get_log_connect, 풀이 없으면 using(conn)).
한 줄 쓸 때마다 빌렸다 바로 돌려준다. 실행이 끝날 때까지 연결을 쥐면 로그 풀(max_size) 수만큼만
동시에 돌 수 있고, 모델을 기다리는 동안 다른 실행이 연결을 못 얻는다.

cost_usd를 빼면 단가표(app/pricing.py)로 비용을 계산한다.

202와 run_id를 먼저 돌려주는 작업(준비하기)은 start_run으로 실행 행만 만들고, 뒤에서
agent_run(run_id=...)으로 이어서 기록한다. 실패 이유가 ApiError면 "코드: 문구"로 남겨
GET /runs/{id}가 학생에게 그대로 보여 준다. 그 밖의 예외는 내부 기록이라 보여 주지 않는다.
"""

import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.errors import ApiError
from app.pricing import cost_usd as priced_cost
from app.schemas.me import PROFILE_FIELDS

# autocommit 연결을 주는 공급자. 풀이면 pool.connection, 풀이 없으면 using(conn)이다
LogConnect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]

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


def using(conn: AsyncConnection) -> LogConnect:
    """이미 연 autocommit 연결 하나를 그대로 쓰는 공급자. 풀이 없는 곳(CLI·테스트)에서 쓴다."""
    _require_autocommit(conn)

    @asynccontextmanager
    async def connect() -> AsyncIterator[AsyncConnection]:
        yield conn

    return connect


@dataclass
class AgentRun:
    connect: LogConnect
    id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    _seq: int = 0

    @asynccontextmanager
    async def tool(self, name: str, input: dict[str, Any] | None = None) -> AsyncIterator[ToolCall]:
        self._seq += 1
        started = time.perf_counter()
        async with self.connect() as conn:
            cursor = await conn.execute(
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
            async with self.connect() as conn:
                await conn.execute(
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
        async with self.connect() as conn:
            await conn.execute(
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


async def start_run(
    connect: LogConnect,
    *,
    trigger: str,
    user_id: str | None = None,
    scenario_code: str | None = None,
) -> str:
    """실행 행만 만든다(status running). 이어서 agent_run(run_id=...)으로 기록하거나 abandon_run으로 닫는다."""
    async with connect() as conn:
        _require_autocommit(conn)
        cursor = await conn.execute(
            "insert into agent_runs (user_id, trigger_type, scenario_code) values (%s, %s, %s)"
            " returning id",
            (user_id, trigger, scenario_code),
        )
        return str((await cursor.fetchone())["id"])


async def abandon_run(connect: LogConnect, run_id: str, error: ApiError) -> None:
    """시작하지 않을 실행을 실패로 닫는다(같은 공고를 그새 다른 요청이 준비하기 시작했을 때 등)."""
    async with connect() as conn:
        await conn.execute(
            "update agent_runs set status = 'failed', finished_at = now(), latency_ms = 0,"
            " error_message = %s where id = %s and status = 'running'",
            (error_text(error), run_id),
        )


@asynccontextmanager
async def agent_run(
    connect: LogConnect,
    *,
    trigger: str,
    user_id: str | None = None,
    scenario_code: str | None = None,
    run_id: str | None = None,
) -> AsyncIterator[AgentRun]:
    """실행 하나를 기록한다. connect는 autocommit 연결 공급자다(db.get_log_connect, 또는 using(conn)).

    한 줄 쓸 때마다 빌렸다 돌려주므로, 모델을 기다리는 동안 로그 연결을 쥐지 않는다.
    autocommit이어야 실패한 실행도 남는다. run_id를 주면 start_run으로 만든 행을 이어서 쓴다
    (latency_ms는 여기부터 잰다).
    """
    started = time.perf_counter()
    if run_id is None:
        run_id = await start_run(
            connect, trigger=trigger, user_id=user_id, scenario_code=scenario_code
        )
    else:
        async with connect() as conn:
            _require_autocommit(conn)
    run = AgentRun(connect=connect, id=run_id)
    try:
        yield run
    except Exception as exc:
        await _finish(run, started, "failed", error_text(exc))
        raise
    await _finish(run, started, "succeeded", None)


def error_text(exc: BaseException) -> str:
    """agent_runs.error_message. ApiError는 "코드: 문구", 그 밖은 내부 기록(repr)이다."""
    if isinstance(exc, ApiError):
        return f"{exc.code}: {exc.message}"[:500]
    return repr(exc)[:500]


def _require_autocommit(conn: AsyncConnection) -> None:
    if not conn.autocommit:
        raise RuntimeError("agent_run에는 autocommit 연결 공급자(get_log_connect)를 넘겨야 해요.")


async def _finish(run: AgentRun, started: float, status: str, error: str | None) -> None:
    async with run.connect() as conn:
        await conn.execute(
            "update agent_runs set status = %s, finished_at = now(), latency_ms = %s,"
            " input_tokens = %s, output_tokens = %s, cost_usd = %s, error_message = %s"
            " where id = %s",
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
