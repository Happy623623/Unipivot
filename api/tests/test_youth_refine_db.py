"""서술형 자격 요건화(F-11b)를 붙인 청년정책 수집을 실제 스키마에 대고 본다: 저장되는 요건, 자식 실행의 엔진 도장과
모델 비용, 바뀌지 않은 정책은 모델을 다시 부르지 않음, 모델이 실패하면 기타 조건 그대로 저장하고 다음 수집이 다시
시도함, 끄면 기타 조건으로 되돌아감. DATABASE_URL이 있을 때만 돈다.

공고·출처 행은 트랜잭션을 되돌려 지우고, 실행 로그는 이 파일만 쓰는 scenario_code로 골라 지운다."""

import os
import uuid
from datetime import date
from typing import Any

import psycopg
import pytest

from app.agent_log import using
from app.youth.convert import PolicyRecord, convert
from app.youth.importer import CollectResult, collect
from app.youth.refine import ENGINE, SUBMIT, YouthRefiner, refined_hash
from app.youth.regions import region_table
from tests.db_world import connect
from tests.llm_fakes import ScriptedLlm, call
from tests.youth_samples import FakeClient, policy, skip_if_other_youth_policies

DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]
TODAY = date(2026, 11, 28)
SCENARIO = f"test-{uuid.uuid4().hex[:12]}"
PREFIX = f"R{uuid.uuid4().hex[:8]}-"
MODEL = "gemini-3.8-flash"
EXTRA = "만 19세 이상 34세 이하 미취업 청년"


def item(name: str, **values: Any) -> dict[str, Any]:
    return policy(plcyNo=PREFIX + name, plcyNm=f"서술형 {name}", **values)


def answer() -> Any:
    """추가 자격을 빠짐없이 옮긴 모델 답(나이·취업 상태)."""
    return call(
        SUBMIT,
        conditions=[
            {
                "source": "추가 자격",
                "clause_no": 1,
                "field": "age",
                "operator": "between",
                "value_json": '{"min": 19, "max": 34}',
                "evidence_text": "만 19세 이상 34세 이하",
            },
            {
                "source": "추가 자격",
                "clause_no": 2,
                "field": "job_status",
                "operator": "in",
                "value_json": '["unemployed"]',
                "evidence_text": "미취업 청년",
            },
        ],
        covered=["추가 자격"],
    )


async def run(
    conn: psycopg.AsyncConnection,
    log_conn: psycopg.AsyncConnection,
    *items: dict[str, Any],
    refiner: YouthRefiner | None,
) -> CollectResult:
    return await collect(
        conn,
        using(log_conn),
        FakeClient(list(items)),
        today=TODAY,
        scenario=SCENARIO,
        refiner=refiner,
    )


async def saved(conn: psycopg.AsyncConnection, name: str) -> dict[str, Any]:
    row = await (
        await conn.execute(
            "select id, content_hash, requirements_version from opportunities"
            " where external_id = %s and source_type = 'youth_policy'",
            (PREFIX + name,),
        )
    ).fetchone()
    assert row is not None
    found = await (
        await conn.execute(
            "select clause_no, field, value, evidence_text from requirements"
            " where opportunity_id = %s order by clause_no, created_at",
            (row["id"],),
        )
    ).fetchall()
    return {**row, "requirements": [(r["clause_no"], r["field"], r["value"]) for r in found]}


async def cleanup(conn: psycopg.AsyncConnection, log_conn: psycopg.AsyncConnection) -> None:
    await conn.rollback()
    await conn.close()
    await log_conn.execute("delete from agent_runs where scenario_code = %s", (SCENARIO,))
    await log_conn.close()


async def test_free_text_is_saved_as_conditions_and_stamped_on_a_child_run() -> None:
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        await skip_if_other_youth_policies(conn, PREFIX)
        llm = ScriptedLlm(answer())
        refiner = YouthRefiner(llm=llm, model=MODEL)

        first = await run(
            conn, log_conn, item("A", addAplyQlfcCndCn=EXTRA), item("B"), refiner=refiner
        )

        assert first.counts["new"] == 2 and len(llm.requests) == 1  # 서술형 글이 있는 정책만
        a = await saved(conn, "A")
        assert a["requirements"] == [
            (1, "age", {"min": 19, "max": 34}),
            (2, "job_status", ["unemployed"]),
        ]  # 기타 조건(추가 자격: …)이 빠졌다
        b = await saved(conn, "B")
        assert b["requirements"] == []
        assert b["content_hash"] != a["content_hash"]
        child = await (
            await log_conn.execute(
                "select r.id, r.engine, r.engine_version, r.model, r.user_id, r.cost_usd,"
                " (select count(*) from llm_calls l where l.run_id = r.id) as calls,"
                " (select output from tool_calls t where t.run_id = r.id and t.tool_name = %s)"
                " as output from agent_runs r where r.parent_run_id = %s",
                (SUBMIT, first.run_id),
            )
        ).fetchone()
        assert child is not None
        assert (child["engine"], child["engine_version"], child["model"]) == (ENGINE, 1, MODEL)
        assert child["user_id"] is None and child["calls"] == 1 and child["cost_usd"] > 0
        assert child["output"] == {"conditions": 2, "dropped": 0, "covered": ["추가 자격"]}

        # 다음 수집: 바뀐 것이 없으면 모델을 다시 부르지 않는다(준비한 답이 없어 부르면 시험이 진다)
        again = await run(
            conn, log_conn, item("A", addAplyQlfcCndCn=EXTRA), item("B"), refiner=refiner
        )
        assert again.counts["unchanged"] == 2 and len(llm.requests) == 1
    finally:
        await cleanup(conn, log_conn)


async def test_a_failed_model_keeps_the_review_condition_and_retries_next_time() -> None:
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        await skip_if_other_youth_policies(conn, PREFIX)

        def broken(_request: Any) -> Any:
            raise TimeoutError("모델이 답하지 않음")

        first = await run(
            conn,
            log_conn,
            item("C", addAplyQlfcCndCn=EXTRA),
            refiner=YouthRefiner(llm=ScriptedLlm(broken), model=MODEL),
        )
        assert first.counts["new"] == 1
        c = await saved(conn, "C")
        assert c["requirements"] == [(1, "other", {"text": f"추가 자격: {EXTRA}"})]
        failed = await (
            await log_conn.execute(
                "select status::text from agent_runs where parent_run_id = %s", (first.run_id,)
            )
        ).fetchone()
        assert failed is not None and failed["status"] == "failed"  # 자식 실행은 실패로 남는다

        # 다음 수집이 다시 시도해 이번에는 옮긴다
        llm = ScriptedLlm(answer())
        second = await run(
            conn,
            log_conn,
            item("C", addAplyQlfcCndCn=EXTRA),
            refiner=YouthRefiner(llm=llm, model=MODEL),
        )
        assert second.counts["updated"] == 1 and len(llm.requests) == 1
        c2 = await saved(conn, "C")
        assert [field for _, field, _ in c2["requirements"]] == ["age", "job_status"]
        assert c2["requirements_version"] == c["requirements_version"] + 1
        assert c2["content_hash"] == refined_hash(_base(c["content_hash"]), MODEL)
    finally:
        await cleanup(conn, log_conn)


async def test_turning_it_off_puts_the_review_condition_back() -> None:
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        await skip_if_other_youth_policies(conn, PREFIX)
        refiner = YouthRefiner(llm=ScriptedLlm(answer()), model=MODEL)
        await run(conn, log_conn, item("D", addAplyQlfcCndCn=EXTRA), refiner=refiner)

        off = await run(conn, log_conn, item("D", addAplyQlfcCndCn=EXTRA), refiner=None)

        assert off.counts["updated"] == 1
        d = await saved(conn, "D")
        assert d["requirements"] == [(1, "other", {"text": f"추가 자격: {EXTRA}"})]
    finally:
        await cleanup(conn, log_conn)


def _base(stored: str) -> str:
    """실패하면 변환 결과의 해시 그대로 저장한다(시험용 — 같은 정책을 다시 변환해 견준다)."""
    converted = convert(item("C", addAplyQlfcCndCn=EXTRA), TODAY, region_table())
    assert isinstance(converted, PolicyRecord)
    assert stored == converted.content_hash
    return converted.content_hash
