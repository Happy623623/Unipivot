"""DATABASE_URL이 있을 때만 도는 통합 테스트. CI는 Postgres 컨테이너에 마이그레이션을 적용해서 돌린다.

실제 Supabase DB를 DATABASE_URL로 주고 돌리지 않는다(auth.users에 테스트 행을 넣는다).
"""

import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from app.agent_log import agent_run
from app.repositories.meta import MetaRepository
from app.repositories.profiles import ProfileRepository

DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


async def connect(autocommit: bool = False) -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(
        DATABASE_URL, row_factory=dict_row, autocommit=autocommit, prepare_threshold=None
    )


async def test_profile_repository_roundtrip() -> None:
    conn = await connect()
    try:
        user_id = str(uuid.uuid4())
        await conn.execute("insert into auth.users (id) values (%s)", (user_id,))
        await conn.execute(
            "insert into departments (name, college, field_group)"
            " values ('인공지능학과', '테스트대학', '공학계열') on conflict do nothing"
        )
        repo, meta = ProfileRepository(conn), MetaRepository(conn)
        await repo.ensure(user_id, "테스트 학생")

        me = await repo.get_me(user_id)
        assert me is not None
        assert (me.consented, me.income_info_consented, me.calendar_connected) == (
            False,
            False,
            False,
        )
        assert (me.profile_completion.filled, me.profile_completion.total) == (0, 16)

        result = await repo.save_consent(user_id, "2026-10-07", agree_income_info=False)
        assert (result.consent_version, result.income_info_agreed_at) == ("2026-10-07", None)
        assert await meta.department_exists("인공지능학과")
        assert not await meta.department_exists("없는학과")
        changes = {
            "department": "인공지능학과",
            "gpa_last_semester": 3.9,
            "is_international": False,
        }
        await repo.update_profile(user_id, changes)
        profile = await repo.get_profile(user_id)
        assert profile is not None
        assert (
            profile.department,
            profile.gpa_last_semester,
            profile.gpa_scale,
            profile.is_international,
        ) == ("인공지능학과", 3.9, 4.5, False)

        # 소득·수급 값은 선택 동의가 있어야 저장된다 (DB 제약도 같은 규칙)
        with pytest.raises(psycopg.errors.CheckViolation):
            async with conn.transaction():
                await repo.update_profile(user_id, {"welfare_status": "none"})
        assert (await repo.set_income_consent(user_id, True)).income_info_agreed_at is not None
        await repo.update_profile(user_id, {"welfare_status": "none", "income_bracket": 6})
        assert (await repo.get_consents(user_id)).income_info
        # 철회하면 시각과 소득 값이 한 번에 지워진다
        assert (await repo.set_income_consent(user_id, False)).income_info_agreed_at is None
        profile = await repo.get_profile(user_id)
        assert profile is not None
        assert (profile.welfare_status, profile.income_bracket) == (None, None)

        await repo.save_google_tokens(user_id, "encrypted-access", "encrypted-refresh")
        me = await repo.get_me(user_id)
        assert me is not None
        assert me.consented and me.calendar_connected and not me.income_info_consented
        assert (me.profile_completion.filled, me.unread_notifications) == (3, 0)
    finally:
        await conn.rollback()
        await conn.close()


async def test_meta_repository() -> None:
    conn = await connect()
    try:
        user_id = str(uuid.uuid4())
        await conn.execute("insert into auth.users (id) values (%s)", (user_id,))
        await conn.execute(
            "insert into departments (name, college, field_group, sort_order, is_active) values"
            " ('나중학과', '테스트대학', '공학계열', 2, true),"
            " ('먼저학과', '테스트대학', '인문계열', 1, true),"
            " ('폐지학과', '테스트대학', '공학계열', 0, false)"
        )
        meta = MetaRepository(conn)
        names = [department.name for department in await meta.list_departments()]
        assert names.index("먼저학과") < names.index("나중학과") and "폐지학과" not in names
        assert not await meta.department_exists("폐지학과")

        await meta.record_event(user_id, "app_open")  # 프로필 행이 없으면 남기지 않는다
        await ProfileRepository(conn).ensure(user_id, "테스트 학생")
        for _ in range(2):
            await meta.record_event(user_id, "app_open")  # 같은 날은 1건
        await meta.record_event(user_id, "profile_prompt_shown", uuid.uuid4())  # 없는 공고 id
        rows = await (
            await conn.execute(
                "select event, opportunity_id from usage_events where user_id = %s order by id",
                (user_id,),
            )
        ).fetchall()
        assert [(row["event"], row["opportunity_id"]) for row in rows] == [
            ("app_open", None),
            ("profile_prompt_shown", None),
        ]
    finally:
        await conn.rollback()
        await conn.close()


async def test_agent_run_logs_success_and_failure() -> None:
    conn = await connect(autocommit=True)
    run_ids: list[str] = []
    try:
        async with agent_run(conn, trigger="eval", scenario_code="TEST-LOG") as run:
            run_ids.append(run.id)
            async with run.tool(
                "extract_requirements",
                {"notice": "n1", "access_token": "x", "gpa_last_semester": 3.9},
            ) as call:
                await run.record_llm(
                    provider="anthropic",
                    model="test-model",
                    input_tokens=1200,
                    output_tokens=300,
                    cost_usd=0.0012,
                    latency_ms=850,
                    tool_call=call,
                )
                call.output = {"requirements": 3}

        with pytest.raises(ValueError):
            async with agent_run(conn, trigger="eval", scenario_code="TEST-LOG") as failed:
                run_ids.append(failed.id)
                async with failed.tool("crawl_board", {"board": "scholarship"}):
                    raise ValueError("게시판 응답 없음")

        runs = {
            str(row["id"]): row
            for row in await (
                await conn.execute(
                    "select * from agent_runs where id = any(%s::uuid[])", (run_ids,)
                )
            ).fetchall()
        }
        ok, bad = runs[run_ids[0]], runs[run_ids[1]]
        assert (ok["status"], ok["input_tokens"], ok["output_tokens"]) == ("succeeded", 1200, 300)
        assert float(ok["cost_usd"]) == pytest.approx(0.0012)
        assert ok["latency_ms"] is not None and ok["finished_at"] is not None
        assert bad["status"] == "failed" and "게시판 응답 없음" in bad["error_message"]

        tools = await (
            await conn.execute(
                "select run_id, status, input, output from tool_calls"
                " where run_id = any(%s::uuid[]) order by seq",
                (run_ids,),
            )
        ).fetchall()
        by_run = {str(row["run_id"]): row for row in tools}
        assert by_run[run_ids[0]]["status"] == "succeeded"
        assert by_run[run_ids[0]]["input"]["access_token"] == "[REDACTED]"
        assert by_run[run_ids[0]]["input"]["gpa_last_semester"] == "[REDACTED]"
        assert by_run[run_ids[0]]["output"] == {"requirements": 3}
        assert by_run[run_ids[1]]["status"] == "failed"

        llm = await (
            await conn.execute(
                "select count(*) as n from llm_calls where run_id = %s", (run_ids[0],)
            )
        ).fetchone()
        assert llm is not None and llm["n"] == 1
    finally:
        await conn.execute("delete from agent_runs where id = any(%s::uuid[])", (run_ids,))
        await conn.close()
