"""내부 지표 집계 SQL (API 명세 12장 `GET /internal/metrics`, PRD 8장).

**이 파일의 조회에는 user_id 조건이 없다.** 다른 저장소와 다른 점이고, 일부러 그렇다 — 운영자가
전체를 보는 집계라서 좁힐 사용자가 없다(명세 12장: 사용자 토큰이 아니라 서비스 키로만 부른다).
돌려주는 값은 모두 센 수와 비율이고, 사용자 한 명을 가리키는 값(이름·프로필)은 담지 않는다.

기간은 KST 날짜 양 끝을 포함한다. `agent_runs.started_at`·`usage_events.occurred_on`처럼 기준이 되는
시각을 KST 날짜로 바꿔 비교한다.

응답시간 백분위수는 `percentile_disc`(실제로 잰 값 중 하나를 고른다)다. 시나리오 러너의
`app/eval/models.percentile`과 같은 방법이어야 한다 — DB 테스트가 두 값이 같은지 본다.

**두 번 세지 않는 규칙**(오케스트레이션 명세 v1 3.6). 시나리오 지표는 흐름 단위라 뿌리 실행(`parent_run_id is
null`)만 세고, 엔진 지표는 엔진 단위라 엔진 도장이 있는 실행(`engine is not null`)만 센다. 엔진 하나뿐인 흐름의
뿌리는 두 쪽에 다 들지만 서로 다른 질문이다. 비용은 어느 쪽이든 `llm_calls`를 더한다.
"""

from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection

from app.db import get_conn
from app.eligibility import KST
from app.schemas.metrics import (
    CHECK_TOOL,
    ELIGIBILITY_CHECK,
    STATUSES,
    EligibilityMatrix,
    EngineMetric,
    Latency,
    MatrixRow,
    Metrics,
    MissingField,
    ProductMetrics,
    Ratio,
    ScenarioMetric,
    ScenarioMetrics,
    TokensPerRun,
    UndeterminedRate,
)

TOP_MISSING = 3  # 판정 불가 원인 항목 상위 몇 개를 보여 줄지(PRD 8장)
RETURN_DAYS = 7  # 주간 재방문: 가입 다음 7일 안에 앱을 한 번이라도 열었나
_EVAL = "eval"
# KST 날짜로 바꿔 기간과 비교한다. 기간은 양 끝을 포함한다
_IN_PERIOD = "(%s at time zone 'Asia/Seoul')::date between %%(from)s and %%(to)s"
_RUN_PERIOD = _IN_PERIOD % "r.started_at"
# 시나리오 실행은 뿌리만 센다(실행 트리 O1). 자식 실행은 부모의 trigger·scenario_code를 그대로 받아, 조건이
# 없으면 같은 시나리오를 두 번 센다. 비용은 llm_calls를 scenario_code로 묶어 더하므로 자식도 한 번씩 들어간다
_EVAL_ROOT = (
    f"r.trigger_type = '{_EVAL}' and r.scenario_code is not null and r.parent_run_id is null"
)
# 엔진 지표(명세 v1 7.2, O3)는 엔진 도장이 있는 **운영** 실행만, 끝난 것만 센다. 시나리오 실행 안에서 돈 엔진은
# 녹화 응답이라 모델·비용이 진짜가 아니다(scenario_code가 붙는다). 아직 도는 실행은 응답시간이 없다
_ENGINE_RUN = "r.engine is not null and r.scenario_code is null and r.status <> 'running'"
_ENGINE_KEY = "r.engine, r.engine_version, r.model"


def rate(numerator: int, denominator: int) -> Ratio:
    """분모가 0이면 rate는 null이다(0.0과 구분한다 — 아직 아무도 안 했다는 뜻)."""
    found = round(numerator / denominator, 4) if denominator else None
    return Ratio(numerator=numerator, denominator=denominator, rate=found)


def _latency(row: dict[str, Any] | None) -> Latency:
    if row is None:
        return Latency(p50_ms=0, p95_ms=0)
    return Latency(p50_ms=int(row["p50"] or 0), p95_ms=int(row["p95"] or 0))


class MetricsRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def metrics(self, period: tuple[date, date]) -> Metrics:
        start, end = period
        window = {"from": start, "to": end}
        return Metrics(
            from_date=start,
            to_date=end,
            scenarios=await self.scenarios(window),
            eligibility=await self.eligibility(window),
            product=await self.product(window),
            engines=await self.engines(window),
        )

    # ── 시나리오 실행: 성공률·응답시간·호출비용 ──────────────────────────────

    async def scenarios(self, window: dict[str, date]) -> ScenarioMetrics:
        """기간 안의 시나리오 실행. 비용은 같은 scenario_code가 붙은 실행의 llm_calls 합이다."""
        rows = await self._rows(
            "select r.scenario_code as code, count(*) as runs,"
            " count(*) filter (where r.status = 'succeeded') as passed,"
            " percentile_disc(0.5) within group (order by coalesce(r.latency_ms, 0)) as p50,"
            " percentile_disc(0.95) within group (order by coalesce(r.latency_ms, 0)) as p95"
            f" from agent_runs r where {_EVAL_ROOT}"
            f" and {_RUN_PERIOD} group by 1 order by 1",
            window,
        )
        spend = {
            row["code"]: row
            for row in await self._rows(
                "select r.scenario_code as code, coalesce(sum(l.cost_usd), 0) as cost,"
                " count(l.id) as calls from agent_runs r"
                " left join llm_calls l on l.run_id = r.id"
                f" where r.scenario_code is not null and {_RUN_PERIOD} group by 1",
                window,
            )
        }
        overall = await self._row(
            "select count(*) as runs, count(*) filter (where r.status = 'succeeded') as passed,"
            " percentile_disc(0.5) within group (order by coalesce(r.latency_ms, 0)) as p50,"
            " percentile_disc(0.95) within group (order by coalesce(r.latency_ms, 0)) as p95"
            f" from agent_runs r where {_EVAL_ROOT}"
            f" and {_RUN_PERIOD}",
            window,
        )
        by_scenario = [
            ScenarioMetric(
                code=row["code"],
                runs=row["runs"],
                passed=row["passed"],
                success_rate=rate(row["passed"], row["runs"]).rate or 0.0,
                latency=_latency(row),
                cost_usd=float(spend.get(row["code"], {}).get("cost", 0)),
                llm_calls=int(spend.get(row["code"], {}).get("calls", 0)),
            )
            for row in rows
        ]
        runs = int(overall["runs"]) if overall else 0
        passed = int(overall["passed"]) if overall else 0
        return ScenarioMetrics(
            runs=runs,
            passed=passed,
            success_rate=rate(passed, runs).rate or 0.0,
            latency=_latency(overall),
            cost_usd=round(sum(item.cost_usd for item in by_scenario), 6),
            llm_calls=sum(item.llm_calls for item in by_scenario),
            by_scenario=by_scenario,
        )

    # ── 판정 혼동행렬 ───────────────────────────────────────────────────────

    async def eligibility(self, window: dict[str, date]) -> EligibilityMatrix:
        """판정 정확도 3×3. **시나리오 번호마다 가장 최근 실행** 하나씩만 센다.

        한 번 돌린 묶음을 가리키는 번호가 없어서(실행 행에 묶음 id가 없다) 번호별 최신 실행으로 정했다.
        같은 시나리오를 여러 번 돌려도 마지막 결과만 행렬에 들어간다.
        """
        latest = (
            "select distinct on (r.scenario_code) r.id, r.started_at from agent_runs r"
            f" where {_EVAL_ROOT} and {_RUN_PERIOD}"
            " order by r.scenario_code, r.started_at desc"
        )
        rows = await self._rows(
            f"with latest as ({latest})"
            " select c.input->>'expected' as expected, c.output->>'actual' as actual,"
            " count(*) as count from latest join tool_calls c on c.run_id = latest.id"
            " where c.tool_name = %(tool)s and c.input->>'kind' = %(kind)s group by 1, 2",
            {**window, "tool": CHECK_TOOL, "kind": ELIGIBILITY_CHECK},
        )
        started = await self._row(f"select min(started_at) as first from ({latest}) latest", window)
        counts: dict[str, dict[str, int]] = {status: {} for status in STATUSES}
        for row in rows:
            if row["expected"] in counts:  # judged가 세 상태만 받지만 옛 기록이 섞일 수 있다
                counts[row["expected"]][row["actual"]] = int(row["count"])
        matrix = [
            MatrixRow(expected=status, counts=found, total=sum(found.values()))
            for status, found in counts.items()
        ]
        checks = sum(row.total for row in matrix)
        correct = sum(row.counts.get(row.expected, 0) for row in matrix)
        first = started["first"] if started else None
        return EligibilityMatrix(
            run_started_at=first.astimezone(KST) if first and checks else None,
            checks=checks,
            correct=correct,
            accuracy=rate(correct, checks).rate or 0.0,
            rows=matrix,
            eligible_to_ineligible=counts["eligible"].get("ineligible", 0),
            ineligible_to_eligible=counts["ineligible"].get("eligible", 0),
        )

    # ── 엔진별 지표 ─────────────────────────────────────────────────────────

    async def engines(self, window: dict[str, date]) -> list[EngineMetric]:
        """엔진·버전·모델마다 실행 수·성공률·원문 확인 비율·이유 코드·응답시간·토큰·비용(명세 v1 7.2).

        모델이 바뀌면(설정을 바꿔 비교) 같은 엔진·버전이라도 줄이 갈린다. 이유 코드는 실행마다 한 번씩 센다
        (agent_runs.review_codes는 같은 코드를 한 번만 담는다).
        """
        rows = await self._rows(
            "with runs as ("
            "  select r.id, r.engine, r.engine_version, r.model, r.status, r.latency_ms,"
            "  r.review_codes from agent_runs r"
            f"  where {_ENGINE_RUN} and {_RUN_PERIOD}"
            "), spent as ("
            "  select l.run_id, sum(l.cost_usd) as cost, sum(l.input_tokens) as input_tokens,"
            "  sum(l.output_tokens) as output_tokens from llm_calls l"
            "  join runs on runs.id = l.run_id group by l.run_id"
            ")"
            " select r.engine, r.engine_version, r.model, count(*) as runs,"
            " count(*) filter (where r.status = 'succeeded') as succeeded,"
            " count(*) filter (where cardinality(r.review_codes) > 0) as flagged,"
            " percentile_disc(0.5) within group (order by coalesce(r.latency_ms, 0)) as p50,"
            " percentile_disc(0.95) within group (order by coalesce(r.latency_ms, 0)) as p95,"
            " coalesce(sum(s.cost), 0) as cost, coalesce(sum(s.input_tokens), 0) as input_tokens,"
            " coalesce(sum(s.output_tokens), 0) as output_tokens"
            " from runs r left join spent s on s.run_id = r.id"
            f" group by {_ENGINE_KEY} order by {_ENGINE_KEY}",
            window,
        )
        codes: dict[tuple[str, int, str | None], dict[str, int]] = {}
        for row in await self._rows(
            f"select {_ENGINE_KEY}, code, count(*) as runs from agent_runs r"
            " cross join unnest(r.review_codes) as code"
            f" where {_ENGINE_RUN} and {_RUN_PERIOD}"
            f" group by {_ENGINE_KEY}, code order by count(*) desc, code",
            window,
        ):
            key = (row["engine"], row["engine_version"], row["model"])
            codes.setdefault(key, {})[row["code"]] = int(row["runs"])
        return [
            _engine(row, codes.get((row["engine"], row["engine_version"], row["model"]), {}))
            for row in rows
        ]

    # ── 제품 지표 5개 ───────────────────────────────────────────────────────

    async def product(self, window: dict[str, date]) -> ProductMetrics:
        return ProductMetrics(
            undetermined=await self.undetermined(),
            profile_prompt=await self._events(
                window, "profile_prompt_shown", "profile_prompt_submitted"
            ),
            prepare_conversion=await self.prepare_conversion(window),
            lms_connect=await self._events(window, "lms_guide_opened", "lms_connected"),
            weekly_return=await self.weekly_return(window),
        )

    async def undetermined(self) -> UndeterminedRate:
        """판정 불가 비율과 원인 항목 상위 3개. 기간이 아니라 **지금 저장된 판정** 기준이다.

        판정은 프로필이 바뀔 때마다 덮어써서 지난 기간의 값이 남지 않는다(eligibility_results는 사용자
        ×공고마다 한 줄이다). 그래서 기간으로 자르지 않고 활성 공고의 지금 판정을 센다.
        """
        row = await self._row(
            "select count(*) as pairs,"
            " count(*) filter (where e.status = 'undetermined') as undetermined"
            " from eligibility_results e join opportunities o on o.id = e.opportunity_id"
            " where o.status = 'active'",
            {},
        )
        causes = await self._rows(
            "select field, count(*) as count from eligibility_results e"
            " join opportunities o on o.id = e.opportunity_id"
            " cross join unnest(e.missing_fields) as field"
            " where o.status = 'active' and e.status = 'undetermined'"
            " group by 1 order by count(*) desc, field limit %(limit)s",
            {"limit": TOP_MISSING},
        )
        pairs = int(row["pairs"]) if row else 0
        found = int(row["undetermined"]) if row else 0
        return UndeterminedRate(
            **rate(found, pairs).model_dump(),
            top_missing_fields=[
                MissingField(field=cause["field"], count=int(cause["count"])) for cause in causes
            ],
        )

    async def prepare_conversion(self, window: dict[str, date]) -> Ratio:
        """준비하기 전환율: 기간 안에 처음 본 **적격** 공고 중 준비하기까지 간 비율(PRD 8장)."""
        row = await self._row(
            "select count(*) as viewed, count(p.user_id) as prepared from opportunity_views v"
            " join eligibility_results e"
            " on e.user_id = v.user_id and e.opportunity_id = v.opportunity_id"
            " left join prep_plans p"
            " on p.user_id = v.user_id and p.opportunity_id = v.opportunity_id"
            f" where e.status = 'eligible' and {_IN_PERIOD % 'v.first_viewed_at'}",
            window,
        )
        return rate(int(row["prepared"]) if row else 0, int(row["viewed"]) if row else 0)

    async def weekly_return(self, window: dict[str, date]) -> Ratio:
        """주간 재방문율: 기간 안에 가입한 사용자 중 가입 다음 7일에 앱을 한 번이라도 연 비율.

        아직 7일이 지나지 않은 사용자는 분모에서 뺀다(열 기회가 없었다).
        """
        row = await self._row(
            "select count(*) as signed_up, count(*) filter (where exists ("
            "   select 1 from usage_events u where u.user_id = p.id and u.event = 'app_open'"
            "   and u.occurred_on between joined.day + 1 and joined.day + %(days)s"
            " )) as returned from profiles p"
            " cross join lateral (select (p.created_at at time zone 'Asia/Seoul')::date as day)"
            " as joined"
            " where joined.day between %(from)s and %(to)s"
            " and joined.day + %(days)s <= (now() at time zone 'Asia/Seoul')::date",
            {**window, "days": RETURN_DAYS},
        )
        return rate(int(row["returned"]) if row else 0, int(row["signed_up"]) if row else 0)

    async def _events(self, window: dict[str, date], shown: str, done: str) -> Ratio:
        """사용 이벤트 두 개의 비율(노출 → 완료). 기간은 occurred_on(KST 날짜)으로 자른다."""
        row = await self._row(
            "select count(*) filter (where event = %(shown)s) as shown,"
            " count(*) filter (where event = %(done)s) as done from usage_events"
            " where occurred_on between %(from)s and %(to)s",
            {**window, "shown": shown, "done": done},
        )
        return rate(int(row["done"]) if row else 0, int(row["shown"]) if row else 0)

    # ── 조회 ────────────────────────────────────────────────────────────────

    async def _rows(self, query: str, params: dict[str, Any]) -> Sequence[dict[str, Any]]:
        return await (await self.conn.execute(query, params)).fetchall()

    async def _row(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        return await (await self.conn.execute(query, params)).fetchone()


def _engine(row: dict[str, Any], codes: dict[str, int]) -> EngineMetric:
    runs = int(row["runs"])
    cost = float(row["cost"])
    return EngineMetric(
        engine=row["engine"],
        version=int(row["engine_version"]),
        model=row["model"],
        runs=runs,
        succeeded=int(row["succeeded"]),
        success_rate=rate(int(row["succeeded"]), runs).rate or 0.0,
        needs_review_rate=rate(int(row["flagged"]), runs).rate or 0.0,
        review_codes=codes,
        latency=_latency(row),
        tokens_per_run=TokensPerRun(
            input=round(int(row["input_tokens"]) / runs, 1),
            output=round(int(row["output_tokens"]) / runs, 1),
        ),
        cost_usd=round(cost, 6),
        cost_usd_per_run=round(cost / runs, 6),
    )


def get_metrics_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> MetricsRepository:
    return MetricsRepository(conn)


MetricsRepoDep = Annotated[MetricsRepository, Depends(get_metrics_repo)]
