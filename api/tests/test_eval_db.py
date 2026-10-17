"""시나리오 실행 통합 테스트(PRD 8장). DATABASE_URL이 있을 때만 돈다.

시나리오를 모두 실제로 돌려 다 통과하는지 보고, 실행 기록(agent_runs·tool_calls·llm_calls)이 지표를
낼 수 있는 모양으로 남는지 본다. 실제 Supabase DB로는 돌리지 않는다(사용자·공고를 만들고 지운다).
"""

from datetime import timedelta
from typing import Any

import pytest

from app.eval.fakes import tool_reply, youth_policy
from app.eval.models import CheckFailed
from app.eval.runner import TRIGGER, run_scenarios
from app.eval.scenarios import SCENARIOS
from app.eval.world import DEFAULT_NOW, EvalWorld, Rule, Scenario, connect
from app.youth.importer import ensure_source
from tests.db_world import DATABASE_URL

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


async def rows(query: str, *params: Any) -> list[dict[str, Any]]:
    conn = await connect(DATABASE_URL)
    try:
        return await (await conn.execute(query, params)).fetchall()
    finally:
        await conn.close()


async def test_every_scenario_reaches_its_expected_result() -> None:
    report = await run_scenarios(DATABASE_URL, list(SCENARIOS))
    failed = {result.code: result.error for result in report.results if not result.ok}
    assert failed == {}
    assert report.passed == report.total == len(SCENARIOS)
    assert report.success_rate == 1.0
    assert all(result.checks for result in report.results)  # 확인 없이 통과한 시나리오는 없다
    assert all(result.latency_ms > 0 for result in report.results)

    # 포스터·준비하기는 모델을 부른다 → 비용이 0이 아니다(토큰 × 단가, PRD 8장 호출비용)
    costs = {result.code: result.cost_usd for result in report.results}
    assert costs["S01"] > 0 and costs["S11"] > 0 and costs["S12"] > 0
    assert costs["S02"] == 0  # 판정만 하는 시나리오는 모델을 부르지 않는다


async def test_a_different_clock_gives_the_same_result() -> None:
    """--now는 아무 날이어도 된다. 마감일·생일·포스터 날짜를 모두 그 시각에서 세기 때문이다."""
    later = DEFAULT_NOW + timedelta(days=174)
    report = await run_scenarios(DATABASE_URL, list(SCENARIOS), now=later)
    assert {result.code: result.error for result in report.results if not result.ok} == {}


async def test_the_run_is_recorded_so_the_metrics_can_be_counted() -> None:
    report = await run_scenarios(DATABASE_URL, [SCENARIOS[0]], now=DEFAULT_NOW)
    result = report.results[0]
    assert result.ok and result.run_id is not None

    run = (await rows("select * from agent_runs where id = %s", result.run_id))[0]
    assert (run["trigger_type"], run["scenario_code"], run["status"]) == (
        TRIGGER,
        "S01",
        "succeeded",
    )
    assert run["latency_ms"] > 0

    checks = await rows(
        "select input, output from tool_calls where run_id = %s and tool_name = 'check'"
        " order by seq",
        result.run_id,
    )
    assert len(checks) == len(result.checks)
    assert all(row["output"]["ok"] for row in checks)
    assert checks[0]["input"]["what"] == result.checks[0].what

    # 시나리오가 뒤에서 만든 실행에도 같은 번호가 붙어, 비용을 한 시나리오로 셀 수 있다
    children = await rows(
        "select r.id::text as id, r.trigger_type, r.scenario_code, r.user_id,"
        " count(l.id) as calls from agent_runs r"
        " left join llm_calls l on l.run_id = r.id where r.id = any(%s::uuid[])"
        " group by 1, 2, 3, 4",
        result.child_run_ids,
    )
    # 공고에는 따로 만든 수집 실행이 붙는다. 시나리오 실행을 붙이면 확인(check) 줄이 공고 상세의
    # 처리 과정(F-42)에 단계로 보인다
    assert sorted(row["trigger_type"] for row in children) == ["batch_crawl", "prepare"]
    assert [(row["scenario_code"], row["calls"]) for row in children if row["calls"]] == [
        ("S01", 1)
    ]
    assert all(row["scenario_code"] == "S01" for row in children)
    # 사용자를 지워도 그 실행 기록은 남는다(ERD: agent_runs.user_id on delete set null)
    assert all(row["user_id"] is None for row in children)
    steps = await rows(
        "select tool_name from tool_calls where run_id = any(%s::uuid[])",
        [row["id"] for row in children if row["trigger_type"] == "batch_crawl"],
    )
    assert steps == []  # 수집 실행에는 도구 기록이 없다 → 처리 과정이 비어 있다


async def test_a_failing_scenario_is_recorded_and_does_not_stop_the_rest() -> None:
    async def fails(world: EvalWorld) -> None:
        await world.user()
        await world.check("일부러", expected="이것", actual="저것")
        raise AssertionError("여기까지 오면 안 된다")

    async def passes(world: EvalWorld) -> None:
        await world.check("되는 것", expected=1, actual=1)

    report = await run_scenarios(
        DATABASE_URL,
        [Scenario("S00", "일부러 실패", "P0", fails), Scenario("S00", "되는 것", "P0", passes)],
    )
    broken, fine = report.results
    assert not broken.ok and fine.ok
    assert report.success_rate == 0.5
    assert broken.error is not None and "일부러" in broken.error
    assert [check.ok for check in broken.checks] == [False]

    run = (await rows("select * from agent_runs where id = %s", broken.run_id))[0]
    assert (run["status"], run["scenario_code"]) == ("failed", "S00")
    assert str(CheckFailed.__name__) in (run["error_message"] or "")
    call = (await rows("select * from tool_calls where run_id = %s", broken.run_id))[0]
    assert (call["tool_name"], call["status"]) == ("check", "failed")
    assert call["output"] == {"actual": "저것", "ok": False}


async def test_nothing_the_scenarios_made_is_left_behind() -> None:
    counts = (
        "select (select count(*) from auth.users) as users,"
        " (select count(*) from opportunities) as opportunities,"
        " (select count(*) from departments) as departments,"
        " (select count(*) from files) as files,"
        " (select count(*) from calendar_events) as events"
    )
    before = (await rows(counts))[0]
    report = await run_scenarios(DATABASE_URL, list(SCENARIOS))
    assert report.passed == report.total
    assert (await rows(counts))[0] == before
    left = await rows(
        "select scenario_code from agent_runs where scenario_code = any(%s) and status = 'running'",
        [result.code for result in report.results],
    )
    assert left == []  # 끝나지 않은 실행이 남으면 다음 실행이 멈춘 실행으로 본다


async def test_the_checks_do_not_become_the_process_of_an_opportunity() -> None:
    """공고에 시나리오 실행을 붙이면 확인(check) 줄이 공고 상세의 처리 과정(F-42)에 단계로 보인다."""

    async def reads_the_process(world: EvalWorld) -> None:
        student = await world.user(grade=3)
        opportunity = await world.add(
            "처리 과정 공고", days=5, requirements=(Rule(1, "grade", "gte", 1),)
        )
        client = world.client(student)
        first = await client.get(world.path(f"/opportunities/{opportunity}"))
        await world.check("판정", expected="eligible", actual=first.json()["eligibility"]["status"])
        again = await client.get(world.path(f"/opportunities/{opportunity}"))
        await world.check("처리 과정", expected=[], actual=again.json()["process"]["extraction"])

    report = await run_scenarios(
        DATABASE_URL, [Scenario("S00", "처리 과정", "P0", reads_the_process)]
    )
    assert report.results[0].error is None


async def test_a_judgment_check_only_takes_the_three_statuses() -> None:
    """화면 라벨(4가지)을 넣으면 3×3 혼동행렬에 담기지 않는다."""

    async def uses_a_display_label(world: EvalWorld) -> None:
        await world.judged("화면 라벨", expected="missing_info", actual="missing_info")

    report = await run_scenarios(
        DATABASE_URL, [Scenario("S00", "라벨", "P0", uses_a_display_label)]
    )
    assert not report.results[0].ok
    assert "판정 확인의 기대값" in (report.results[0].error or "")


async def test_a_new_department_is_cleaned_up_too() -> None:
    """마이그레이션 seed에 없는 학과를 넣으면 학과 목록에 영원히 남는다."""

    async def adds_a_department(world: EvalWorld) -> None:
        await world.department("평가학과", "평가대학", "공학계열")
        found = await world.rows("select 1 from departments where name = '평가학과'")
        await world.check("넣는 동안 있음", expected=1, actual=len(found))

    conn = await connect(
        DATABASE_URL
    )  # 앞선 실행이 남겼으면 먼저 치운다(이 시험을 다시 돌릴 수 있게)
    try:
        await conn.execute("delete from departments where name = '평가학과'")
    finally:
        await conn.close()
    report = await run_scenarios(DATABASE_URL, [Scenario("S00", "학과", "P0", adds_a_department)])
    assert report.passed == 1
    assert await rows("select 1 from departments where name = '평가학과'") == []


async def test_an_already_collected_policy_is_never_overwritten() -> None:
    """save_policy는 (출처, 번호)로 덮어쓰기다. 실제로 수집해 둔 정책을 고치고 지우면 안 된다."""
    number = youth_policy()["plcyNo"]
    conn = await connect(DATABASE_URL)
    try:
        source_id = await ensure_source(conn)
        run = await (
            await conn.execute(
                "insert into agent_runs (trigger_type, status) values ('batch_crawl','succeeded')"
                " returning id::text as id"
            )
        ).fetchone()
        assert run is not None
        await conn.execute(
            "insert into opportunities (source_id, source_type, external_id, category, title,"
            " extraction_run_id) values (%s, 'youth_policy', %s, 'youth_policy', %s, %s)",
            (source_id, number, "이미 수집해 둔 정책", run["id"]),
        )

        async def reuses_the_number(world: EvalWorld) -> None:
            await world.youth(youth_policy())  # plcyNo를 바꾸지 않았다

        report = await run_scenarios(
            DATABASE_URL, [Scenario("S00", "덮어쓰기", "P0", reuses_the_number)]
        )
        assert not report.results[0].ok
        assert "이미 수집해 둔 정책" in (report.results[0].error or "")
        kept = await rows("select title from opportunities where external_id = %s", number)
        assert [row["title"] for row in kept] == ["이미 수집해 둔 정책"]
    finally:
        await conn.execute("delete from opportunities where external_id = %s", (number,))
        await conn.close()


async def test_a_scenario_that_checks_nothing_or_leaves_replies_fails() -> None:
    """조용히 통과하는 시나리오를 막는다(서류 사전이 늘면 모델을 안 불러 비용이 0이 된다)."""

    async def checks_nothing(world: EvalWorld) -> None:
        await world.user()

    async def leaves_a_reply(world: EvalWorld) -> None:
        world.records(tool_reply("submit_document_guides", documents=[]))
        await world.check("되는 것", expected=1, actual=1)

    report = await run_scenarios(
        DATABASE_URL,
        [
            Scenario("S00", "확인 없음", "P0", checks_nothing),
            Scenario("S00", "남은 답", "P0", leaves_a_reply),
        ],
    )
    assert [result.ok for result in report.results] == [False, False]
    assert "확인(check)이 하나도 없는" in (report.results[0].error or "")
    assert "쓰지 않은 녹화 답" in (report.results[1].error or "")


async def test_the_feed_scenarios_survive_a_database_full_of_other_opportunities() -> None:
    """피드는 한 쪽에 50건까지다(명세 5장). 다른 공고가 많아도 "피드에 없다"가 되면 안 된다."""
    conn = await connect(DATABASE_URL)
    made: list[str] = []
    try:
        run = await (
            await conn.execute(
                "insert into agent_runs (trigger_type, status) values ('batch_crawl','succeeded')"
                " returning id::text as id"
            )
        ).fetchone()
        assert run is not None
        for index in range(60):
            row = await (
                await conn.execute(
                    "insert into opportunities (source_type, category, title, deadline_at,"
                    " extraction_run_id) values ('school_notice', 'scholarship', %s,"
                    " now() + %s * interval '1 minute', %s) returning id::text as id",
                    (f"먼저 마감하는 공고 {index}", index, run["id"]),
                )
            ).fetchone()
            assert row is not None
            made.append(row["id"])
        report = await run_scenarios(
            DATABASE_URL, [scenario for scenario in SCENARIOS if scenario.code in ("S08", "S11")]
        )
        assert {r.code: r.error for r in report.results if not r.ok} == {}
    finally:
        await conn.execute("delete from opportunities where id = any(%s::uuid[])", (made,))
        await conn.close()
