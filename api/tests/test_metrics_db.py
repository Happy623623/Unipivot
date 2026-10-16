"""지표 집계 통합 테스트(명세 12장, PRD 8장). DATABASE_URL이 있을 때만 돈다.

시나리오를 실제로 돌린 뒤 집계가 같은 수를 내는지 보고, 제품 지표 5개는 자료를 넣어 센다.
실제 Supabase DB로는 돌리지 않는다(사용자·공고를 만들고 지운다).
"""

import uuid
from datetime import date, timedelta
from typing import Any

import pytest

from app.clock import current_time
from app.eligibility import to_kst_date
from app.eval.models import percentile
from app.eval.runner import run_scenarios
from app.eval.scenarios import SCENARIOS, pick
from app.eval.world import EvalWorld, Scenario, connect
from app.repositories.metrics import RETURN_DAYS, TOP_MISSING, MetricsRepository
from tests.db_world import DATABASE_URL

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

WIDE = (date(2026, 1, 1), date(2027, 12, 31))  # 시나리오 실행을 모두 담는 기간


async def aggregate(period: tuple[date, date] = WIDE) -> Any:
    conn = await connect(DATABASE_URL)
    try:
        return await MetricsRepository(conn).metrics(period)
    finally:
        await conn.close()


async def sql(query: str, *params: Any) -> list[dict[str, Any]]:
    conn = await connect(DATABASE_URL)
    try:
        return await (await conn.execute(query, params)).fetchall()
    finally:
        await conn.close()


async def clear_runs() -> None:
    """앞선 시나리오 실행을 치운다. 집계는 DB 전체를 보므로 이 시험만의 수를 보려면 비워야 한다."""
    conn = await connect(DATABASE_URL)
    try:
        await conn.execute("delete from agent_runs where scenario_code is not null")
    finally:
        await conn.close()


async def test_the_aggregate_matches_the_run_it_came_from() -> None:
    await clear_runs()
    report = await run_scenarios(DATABASE_URL, list(SCENARIOS))
    assert report.passed == report.total

    found = await aggregate()
    assert found.scenarios.runs == report.total
    assert found.scenarios.passed == report.passed
    assert found.scenarios.success_rate == report.success_rate
    assert found.scenarios.cost_usd == float(report.cost_usd)
    assert found.scenarios.llm_calls == report.llm_calls
    # 백분위수는 러너와 같은 방법이어야 한다(실제로 잰 값 중 하나를 고른다)
    latencies = [
        row["latency_ms"]
        for row in await sql("select latency_ms from agent_runs where trigger_type = 'eval'")
    ]
    assert found.scenarios.latency.p50_ms == percentile(latencies, 50)
    assert found.scenarios.latency.p95_ms == percentile(latencies, 95)

    codes = [item.code for item in found.scenarios.by_scenario]
    assert codes == sorted(result.code for result in report.results)
    per_code = {item.code: item for item in found.scenarios.by_scenario}
    for result in report.results:
        assert per_code[result.code].cost_usd == float(result.cost_usd)
        assert per_code[result.code].llm_calls == result.llm_calls
        assert per_code[result.code].latency.p50_ms == result.latency_ms


async def test_the_confusion_matrix_reads_the_judgment_checks() -> None:
    await clear_runs()
    await run_scenarios(DATABASE_URL, list(SCENARIOS))
    matrix = (await aggregate()).eligibility

    assert [row.expected for row in matrix.rows] == ["eligible", "undetermined", "ineligible"]
    assert matrix.checks == sum(row.total for row in matrix.rows) > 0
    assert matrix.checks == matrix.correct  # 모두 통과했으니 대각선뿐이다
    assert matrix.accuracy == 1.0
    # 핵심 목표(PRD 8장): 실제 적격 → 부적격 0건
    assert matrix.eligible_to_ineligible == 0
    assert matrix.ineligible_to_eligible == 0
    assert all(set(row.counts) <= {row.expected} for row in matrix.rows)
    assert matrix.run_started_at is not None
    assert matrix.run_started_at.utcoffset() == timedelta(hours=9)  # 화면에 KST로 보여 준다


async def test_only_the_latest_run_of_each_scenario_is_in_the_matrix() -> None:
    """같은 시나리오를 다시 돌리면 마지막 결과만 행렬에 들어간다(저장소 머리말)."""
    await clear_runs()

    async def wrong(world: EvalWorld) -> None:
        await world.judged("일부러 틀림", expected="eligible", actual="ineligible")

    await run_scenarios(DATABASE_URL, [Scenario("S01", "틀린 판정", "P0", wrong)])
    first = (await aggregate()).eligibility
    assert (first.checks, first.correct, first.eligible_to_ineligible) == (1, 0, 1)
    assert first.accuracy == 0.0

    await run_scenarios(DATABASE_URL, pick(["S01"]))  # 같은 번호를 제대로 다시 돌린다
    again = (await aggregate()).eligibility
    # 앞의 틀린 결과는 세지 않는다. S01의 판정 확인은 한 줄이다
    assert (again.checks, again.correct, again.eligible_to_ineligible) == (1, 1, 0)
    assert again.accuracy == 1.0


async def test_a_scenario_run_twice_keeps_a_measured_latency() -> None:
    """백분위수는 평균이 아니다. 같은 번호를 두 번 돌리면 실제로 잰 값 중 하나를 고른다."""
    await clear_runs()
    await run_scenarios(DATABASE_URL, pick(["S02"]))
    await run_scenarios(DATABASE_URL, pick(["S02"]))
    item = (await aggregate()).scenarios.by_scenario[0]
    assert (item.code, item.runs, item.passed) == ("S02", 2, 2)
    measured = sorted(
        row["latency_ms"]
        for row in await sql("select latency_ms from agent_runs where trigger_type = 'eval'")
    )
    assert len(measured) == 2
    assert item.latency.p50_ms == percentile(measured, 50) == measured[0]
    assert item.latency.p95_ms == percentile(measured, 95) == measured[1]


async def test_the_cost_of_a_run_outside_the_period_is_not_counted() -> None:
    """같은 번호를 기간 안과 밖에서 돌렸으면 기간 안의 비용만 센다."""
    await clear_runs()
    await run_scenarios(DATABASE_URL, pick(["S01"]))  # 이 실행만 옛날로 옮긴다
    old = [row["id"] for row in await sql("select id::text as id from agent_runs")]
    conn = await connect(DATABASE_URL)
    try:
        await conn.execute(
            "update agent_runs set started_at = '2020-01-01 00:00+09' where id = any(%s::uuid[])",
            (old,),
        )
    finally:
        await conn.close()
    await run_scenarios(DATABASE_URL, pick(["S01"]))  # 기간 안의 실행

    today = (await aggregate((date(2026, 1, 1), date(2027, 12, 31)))).scenarios
    assert (today.runs, today.llm_calls) == (1, 1)
    assert today.cost_usd > 0
    past = (await aggregate((date(2020, 1, 1), date(2020, 1, 1)))).scenarios
    assert (past.runs, past.llm_calls) == (1, 1)
    assert past.cost_usd == today.cost_usd  # 두 실행의 비용이 각자 자기 기간에만 들어간다


async def test_runs_outside_the_period_are_left_out() -> None:
    await clear_runs()
    report = await run_scenarios(DATABASE_URL, pick(["S02", "S05"]))
    assert report.passed == 2
    assert (await aggregate()).scenarios.runs == 2

    past = date(2020, 1, 1)
    narrow = (await aggregate((past, past))).scenarios
    assert (narrow.runs, narrow.passed, narrow.cost_usd) == (0, 0, 0.0)
    assert narrow.latency.p50_ms == 0 and narrow.by_scenario == []
    assert (await aggregate((past, past))).eligibility.run_started_at is None


async def test_the_product_metrics_count_what_the_prd_asks_for() -> None:
    """사용자 3명을 넣어 다섯 비율을 센다. 넣은 것은 끝나면 지운다."""
    conn = await connect(DATABASE_URL)
    users: list[str] = []
    try:
        run = await (
            await conn.execute(
                "insert into agent_runs (trigger_type, status)"
                " values ('batch_crawl', 'succeeded') returning id::text as id"
            )
        ).fetchone()
        assert run is not None
        opportunity = await (
            await conn.execute(
                "insert into opportunities (source_type, category, title, deadline_at,"
                " extraction_run_id) values ('school_notice', 'scholarship', '지표 공고',"
                " now() + interval '5 days', %s) returning id::text as id",
                (run["id"],),
            )
        ).fetchone()
        assert opportunity is not None
        # 마감된 공고의 판정은 판정 불가 비율에 넣지 않는다(활성 공고만 센다)
        expired = await (
            await conn.execute(
                "insert into opportunities (source_type, category, title, status,"
                " extraction_run_id) values ('school_notice', 'scholarship', '지표 공고',"
                " 'expired', %s) returning id::text as id",
                (run["id"],),
            )
        ).fetchone()
        assert expired is not None
        before = await aggregate()
        for index in range(3):
            user = str(uuid.uuid4())
            users.append(user)
            await conn.execute("insert into auth.users (id) values (%s)", (user,))
            await conn.execute(
                "insert into profiles (id, display_name, created_at) values (%s, '지표 학생',"
                " now() - interval '10 days') on conflict (id)"
                " do update set created_at = excluded.created_at",
                (user,),
            )
            # 즉석 입력: 3명 모두 노출, 2명 완료
            await conn.execute(
                "insert into usage_events (user_id, event) values (%s, 'profile_prompt_shown')",
                (user,),
            )
            if index < 2:
                await conn.execute(
                    "insert into usage_events (user_id, event)"
                    " values (%s, 'profile_prompt_submitted')",
                    (user,),
                )
                # 주간 재방문: 가입 다음 주에 앱 열기
                await conn.execute(
                    "insert into usage_events (user_id, event, occurred_on, occurred_at)"
                    " values (%s, 'app_open', (now() at time zone 'Asia/Seoul')::date - 7,"
                    " now() - interval '7 days')",
                    (user,),
                )
            if index == 0:  # LMS: 1명이 가이드를 열고 연결했다
                for event in ("lms_guide_opened", "lms_connected"):
                    await conn.execute(
                        "insert into usage_events (user_id, event) values (%s, %s)", (user, event)
                    )
            # 적격 2명·판정 불가 1명, 적격 중 1명이 준비하기까지 갔다
            missing = "{}" if index < 2 else "{gpa_last_semester,age}"
            await conn.execute(
                "insert into eligibility_results (user_id, opportunity_id, status,"
                " condition_results, missing_fields) values (%s, %s, %s, '[]'::jsonb, %s)",
                (user, opportunity["id"], "eligible" if index < 2 else "undetermined", missing),
            )
            await conn.execute(
                "insert into opportunity_views (user_id, opportunity_id) values (%s, %s)",
                (user, opportunity["id"]),
            )
            if index == 0:
                await conn.execute(
                    "insert into prep_plans (user_id, opportunity_id) values (%s, %s)",
                    (user, opportunity["id"]),
                )
            await conn.execute(  # 마감 공고의 판정 불가. 비율에 들어가면 안 된다
                "insert into eligibility_results (user_id, opportunity_id, status,"
                " condition_results, missing_fields) values (%s, %s, 'undetermined',"
                " '[]'::jsonb, '{region}')",
                (user, expired["id"]),
            )
        # 오늘 가입한 사용자는 아직 한 주가 지나지 않아 재방문율 분모에서 뺀다
        fresh = str(uuid.uuid4())
        users.append(fresh)
        await conn.execute("insert into auth.users (id) values (%s)", (fresh,))
        await conn.execute(
            "insert into profiles (id, display_name) values (%s, '오늘 가입') on conflict do nothing",
            (fresh,),
        )

        # KST 날짜다. date.today()는 러너의 시간대를 따라서 UTC 러너의 00:00~09:00 KST에 하루 어긋난다
        today = to_kst_date(current_time())
        product = (await aggregate((today - timedelta(days=RETURN_DAYS * 2), today))).product
        assert product.profile_prompt.numerator == 2
        assert product.profile_prompt.denominator == 3
        assert product.profile_prompt.rate == 0.6667
        assert product.weekly_return.numerator == 2  # 가입 +7일 안에 앱을 연 사람
        assert product.weekly_return.denominator == 3  # 오늘 가입한 사람은 빼고 센다
        assert product.lms_connect.rate == 1.0
        # 적격 공고를 본 2명 중 1명이 준비하기까지
        assert (product.prepare_conversion.numerator, product.prepare_conversion.denominator) == (
            1,
            2,
        )
        # 판정 불가 비율은 기간이 아니라 지금 저장된 판정 기준이다
        added = product.undetermined.denominator - before.product.undetermined.denominator
        assert added == 3  # 마감 공고의 판정 3건은 세지 않는다
        assert product.undetermined.numerator >= 1
        causes = {item.field for item in product.undetermined.top_missing_fields}
        assert {"gpa_last_semester", "age"} <= causes
        assert "region" not in causes  # 마감 공고의 원인 항목도 빼고 센다
        assert len(product.undetermined.top_missing_fields) <= TOP_MISSING
    finally:
        await conn.execute("delete from opportunities where title = '지표 공고'")
        await conn.execute("delete from auth.users where id = any(%s::uuid[])", (users,))
        await conn.close()


async def test_nothing_measured_reads_as_null_not_zero() -> None:
    """아무 자료도 없는 기간은 rate가 null이다. 0.0(아무도 안 했다)과 구분한다."""
    product = (await aggregate((date(2020, 1, 1), date(2020, 1, 2)))).product
    assert product.profile_prompt.rate is None
    assert product.prepare_conversion.rate is None
    assert product.lms_connect.rate is None
    assert product.weekly_return.rate is None
