"""시나리오를 차례로 돌리고 성공률·응답시간·비용을 모은다(PRD 8장 지표).

시나리오 하나 = `agent_runs` 한 줄(trigger `eval`, scenario_code `S01`). 그 아래 `tool_calls`에
확인한 것을 `check` 한 줄씩 남긴다 — 다음 PR의 판정 혼동행렬이 이 줄을 읽는다.

시나리오가 뒤에서 만든 실행(준비하기·포스터 추출)은 끝난 뒤 같은 scenario_code를 붙인다. 비용과 LLM
호출 수는 **그 실행들의 `llm_calls`를 더해서** 센다. 시나리오 실행 행 자신의 cost_usd는 0으로 둔다
(제 손으로 모델을 부르지 않는다). 집계하는 쪽은 `agent_runs.cost_usd`를 다시 더하지 말고
scenario_code로 묶은 `llm_calls`를 본다 — 그러지 않으면 같은 비용을 두 번 센다.

시나리오는 한 번에 하나만 돈다. 사용자·공고를 만들고 지우는 동안 다른 시나리오가 끼어들면 피드에
남의 공고가 섞인다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

import psycopg

from app.agent_log import agent_run, using
from app.config import Settings
from app.eligibility import KST
from app.eval.fakes import RecordedCalendar, RecordedLlm, RecordedStorage
from app.eval.models import CheckFailed, Report, ScenarioResult
from app.eval.world import (
    DEFAULT_NOW,
    EvalWorld,
    Scenario,
    connect,
    eval_settings,
    managed_database,
    open_app,
)

logger = logging.getLogger(__name__)
TRIGGER = "eval"
DRAIN_SECONDS = 60.0  # 뒤에서 도는 일을 기다리는 상한(app/main.py의 종료와 같은 뜻)


async def run_scenarios(
    database_url: str,
    scenarios: Sequence[Scenario],
    *,
    now: datetime = DEFAULT_NOW,
) -> Report:
    """시나리오를 차례로 돌린다. 하나가 실패해도 나머지를 돈다(성공률을 재는 것이 목적이다)."""
    if problem := managed_database(database_url):
        raise RuntimeError(problem)
    settings = eval_settings(database_url)
    setup = await connect(database_url)
    log_conn = await connect(database_url)
    # 단가는 돌린 날로 고른다(app/agent_log.py의 record_llm). 베이스라인을 비교할 때 이 날짜를 본다
    report = Report(now=now, priced_on=datetime.now(KST).date())
    try:
        for scenario in scenarios:
            result = await _one(scenario, settings=settings, setup=setup, log=log_conn, now=now)
            report.results.append(result)
    finally:
        for conn in (setup, log_conn):
            try:
                await conn.close()
            except Exception:
                logger.exception("연결을 닫지 못했어요")
    return report


async def _one(
    scenario: Scenario,
    *,
    settings: Settings,
    setup: psycopg.AsyncConnection,
    log: psycopg.AsyncConnection,
    now: datetime,
) -> ScenarioResult:
    llm, storage, calendar = RecordedLlm(), RecordedStorage(), RecordedCalendar()
    world: EvalWorld | None = None
    run_id: str | None = None
    children: list[str] = []
    elapsed_ms = 0
    ok, error = True, None
    try:
        app, pool, log_pool = await open_app(
            settings, now=now, llm=llm, storage=storage, calendar=calendar
        )
        try:
            async with agent_run(using(log), trigger=TRIGGER, scenario_code=scenario.code) as run:
                run_id = run.id
                world = EvalWorld(
                    conn=setup,
                    app=app,
                    settings=settings,
                    now=now,
                    run=run,
                    scenario_code=scenario.code,
                    llm=llm,
                    storage=storage,
                    calendar=calendar,
                )
                started = time.perf_counter()
                try:
                    await scenario.run(world)
                    await _finished(world)
                finally:
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    # 뒤에서 도는 일(준비하기·포스터 추출)을 먼저 끝낸다. 확인이 틀려 중간에 멈췄으면
                    # 아직 도는 일이 있고, 그 일이 쥔 연결을 두고 풀을 닫으면 안 된다
                    await app.state.runner.drain(timeout=DRAIN_SECONDS)
                    children = world.extra_runs + await _tag_children(
                        setup, scenario.code, run.id, world.users
                    )
                    await world.cleanup()
                    _check_drained(app.state.runner.running, scenario.code)
        finally:
            await pool.close()
            await log_pool.close()
    except CheckFailed as exc:
        ok, error = False, str(exc)
    except Exception as exc:  # 시나리오가 터져도 나머지 시나리오를 돈다
        logger.exception("시나리오 %s가 터졌어요", scenario.code)
        ok, error = False, f"{type(exc).__name__}: {exc}"
    cost, calls = await _usage(setup, [run_id, *children] if run_id else children)
    return ScenarioResult(
        code=scenario.code,
        title=scenario.title,
        ok=ok,
        latency_ms=elapsed_ms,
        api_ms=round(world.api_ms, 1) if world else 0.0,
        run_id=run_id,
        child_run_ids=children,
        cost_usd=cost,
        llm_calls=calls,
        checks=list(world.checks) if world else [],
        error=error,
    )


async def _finished(world: EvalWorld) -> None:
    """시나리오가 끝났을 때 맞아야 하는 것. 조용히 통과하는 시나리오를 막는다."""
    if not world.checks:
        raise AssertionError("확인(check)이 하나도 없는 시나리오예요")
    if world.llm.replies:
        # 서류 사전이 늘어 모델을 안 부르게 되면 비용이 0이 되는데, 확인은 다 통과한다
        raise AssertionError(f"쓰지 않은 녹화 답이 {len(world.llm.replies)}개 남았어요")


def _check_drained(running: int, code: str) -> None:
    """뒤에서 도는 일을 못 끝냈으면 그 시나리오는 실패다. 비용이 빠지고 기록도 반쪽이 된다."""
    if running:
        raise TimeoutError(
            f"{code}: 뒤에서 도는 일 {running}개가 {DRAIN_SECONDS}초 안에 안 끝났어요"
        )


async def _tag_children(
    conn: psycopg.AsyncConnection, code: str, run_id: str, users: Sequence[str]
) -> list[str]:
    """시나리오가 돌면서 생긴 실행에 시나리오 번호를 붙인다. 붙인 실행 번호를 돌려준다.

    치우기 전에 불러야 한다. 사용자를 지우면 agent_runs.user_id가 null이 되어 더는 찾을 수 없다.
    실패해도 올리지 않는다(치우기를 막지 않게). 그 실행의 비용은 0으로 보인다.
    """
    if not users:
        return []
    try:
        rows = await (
            await conn.execute(
                # 시나리오 실행 자신은 user_id가 없어 걸리지 않지만 분명히 해 둔다
                "update agent_runs set scenario_code = %s where id <> %s and scenario_code is null"
                " and user_id = any(%s::uuid[]) returning id::text as id",
                (code, run_id, list(users)),
            )
        ).fetchall()
    except Exception:
        logger.exception("자식 실행에 시나리오 번호를 붙이지 못했어요: %s", code)
        return []
    return [row["id"] for row in rows]


async def _usage(conn: psycopg.AsyncConnection, run_ids: Sequence[str]) -> tuple[Decimal, int]:
    """시나리오 1회의 LLM 비용과 호출 수(실행 로그의 토큰 × 단가로 이미 계산된 값)."""
    if not run_ids:
        return Decimal(0), 0
    row = await (
        await conn.execute(
            "select coalesce(sum(cost_usd), 0) as cost, count(*) as calls from llm_calls"
            " where run_id = any(%s::uuid[])",
            (list(run_ids),),
        )
    ).fetchone()
    assert row is not None
    return Decimal(str(row["cost"])), int(row["calls"])
