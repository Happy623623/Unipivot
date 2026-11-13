"""DATABASE_URL이 있을 때만 도는 통합 테스트. CI는 Postgres 컨테이너에 마이그레이션을 적용해서 돌린다.

실제 Supabase DB를 DATABASE_URL로 주고 돌리지 않는다(auth.users에 테스트 행을 넣는다).
"""

import os
import uuid
from datetime import timedelta

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.agent_log import AgentRun, abandon_run, agent_run, start_run, using
from app.db import create_pools
from app.errors import ApiError
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
        # 항목 19개: 유학생 여부로 16, 학위과정으로 17, 취업 상태·본인 연 소득으로 19(F-21)
        assert (me.profile_completion.filled, me.profile_completion.total) == (0, 19)

        result = await repo.save_consent(user_id, "2026-10-07", agree_income_info=False)
        assert (result.consent_version, result.income_info_agreed_at) == ("2026-10-07", None)
        me = await repo.get_me(user_id)
        assert me is not None and me.consent_version == "2026-10-07"
        assert await meta.department_exists("인공지능학과")
        assert not await meta.department_exists("없는학과")
        changes = {
            "department": "인공지능학과",
            "degree_program": "master",
            "gpa_last_semester": 3.9,
            "is_international": False,
        }
        await repo.update_profile(user_id, changes)
        profile = await repo.get_profile(user_id)
        assert profile is not None
        assert (
            profile.department,
            profile.degree_program,
            profile.gpa_last_semester,
            profile.gpa_scale,
            profile.is_international,
        ) == ("인공지능학과", "master", 3.9, 4.5, False)
        # 학위과정은 네 값만 (DB 제약 profiles_degree_program_chk)
        with pytest.raises(psycopg.errors.CheckViolation):
            async with conn.transaction():
                await repo.update_profile(user_id, {"degree_program": "graduate"})

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
        assert (me.profile_completion.filled, me.unread_notifications) == (4, 0)
    finally:
        await conn.rollback()
        await conn.close()


async def test_consenting_again_keeps_the_income_values_only_when_agreed() -> None:
    """약관이 바뀌어 다시 동의한다(F-02). 버전과 세 동의 시각이 이번 동의를 가리키고, 소득은 고른 대로다."""
    conn = await connect()
    try:
        user_id = str(uuid.uuid4())
        await conn.execute("insert into auth.users (id) values (%s)", (user_id,))
        repo = ProfileRepository(conn)
        await repo.ensure(user_id, "테스트 학생")
        await repo.save_consent(user_id, "2026-10-07", agree_income_info=True)
        await repo.update_profile(user_id, {"income_bracket": 3, "annual_income": 1200})
        await conn.execute(
            "update profiles set terms_agreed_at = terms_agreed_at - interval '1 day',"
            " privacy_agreed_at = privacy_agreed_at - interval '1 day',"
            " income_info_agreed_at = income_info_agreed_at - interval '1 day' where id = %s",
            (user_id,),
        )

        result = await repo.save_consent(user_id, "2026-11-03", agree_income_info=True)
        assert result.consent_version == "2026-11-03"
        assert result.income_info_agreed_at == result.terms_agreed_at  # 이번 동의의 시각
        profile = await repo.get_profile(user_id)
        assert profile is not None and (profile.income_bracket, profile.annual_income) == (3, 1200)

        # 설정에서 다시 켜도(이미 켜져 있으면) 처음 시각은 그대로다
        await conn.execute(
            "update profiles set income_info_agreed_at = income_info_agreed_at - interval '1 hour'"
            " where id = %s",
            (user_id,),
        )
        again = await repo.set_income_consent(user_id, True)
        assert again.income_info_agreed_at == result.income_info_agreed_at - timedelta(hours=1)

        result = await repo.save_consent(user_id, "2026-11-03", agree_income_info=False)
        assert result.income_info_agreed_at is None
        profile = await repo.get_profile(user_id)
        assert profile is not None and (profile.income_bracket, profile.annual_income) == (
            None,
            None,
        )
        me = await repo.get_me(user_id)
        assert me is not None and (me.consent_version, me.income_info_consented) == (
            "2026-11-03",
            False,
        )
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
        async with agent_run(using(conn), trigger="eval", scenario_code="TEST-LOG") as run:
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
            async with agent_run(using(conn), trigger="eval", scenario_code="TEST-LOG") as failed:
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


async def test_a_long_run_does_not_hold_a_log_connection() -> None:
    """모델을 기다리는 동안 로그 연결을 쥐지 않는다. 쥐면 풀만큼만 동시에 돌 수 있다.

    로그 풀을 1칸으로 만들고, 실행 한가운데(모델을 부르는 자리)에서 다른 쪽이 연결을 빌려 본다.
    실행이 연결을 들고 있으면 여기서 PoolTimeout이 난다.
    """
    pool = AsyncConnectionPool(
        DATABASE_URL,
        min_size=1,
        max_size=1,
        open=False,
        kwargs={"row_factory": dict_row, "autocommit": True, "prepare_threshold": None},
    )
    await pool.open()
    run_ids: list[str] = []
    try:
        async with agent_run(pool.connection, trigger="eval", scenario_code="TEST-POOL") as run:
            run_ids.append(run.id)
            async with run.tool("get_document_guide", {"opportunity_id": "x"}) as call:
                # 모델에 묻는 중이라고 치고, 그 사이 다른 요청이 로그 연결을 빌린다
                async with pool.connection(timeout=2) as other:
                    assert (await (await other.execute("select 1 as ok")).fetchone())["ok"] == 1
                call.output = {"documents": 0}
        async with pool.connection() as conn:
            (row,) = await (
                await conn.execute(
                    "select status::text as status from agent_runs where id = %s", (run_ids[0],)
                )
            ).fetchall()
            assert row["status"] == "succeeded"
    finally:
        async with pool.connection() as conn:
            await conn.execute("delete from agent_runs where id = any(%s::uuid[])", (run_ids,))
        await pool.close()


async def test_start_run_and_finish_share_no_connection() -> None:
    """start_run으로 만든 실행을 나중에 이어 써도(준비하기) 그 사이 연결을 쥐지 않는다."""
    pool = AsyncConnectionPool(
        DATABASE_URL,
        min_size=1,
        max_size=1,
        open=False,
        kwargs={"row_factory": dict_row, "autocommit": True, "prepare_threshold": None},
    )
    await pool.open()
    run_id = ""
    try:
        run_id = await start_run(pool.connection, trigger="prepare")
        async with pool.connection(timeout=2) as other:  # 202를 돌려주고 일을 띄우기 전
            (row,) = await (
                await other.execute(
                    "select status::text as status from agent_runs where id = %s", (run_id,)
                )
            ).fetchall()
            assert row["status"] == "running"
        await abandon_run(pool.connection, run_id, ApiError(500, "INTERNAL_ERROR", "멈췄어요."))
        async with pool.connection() as conn:
            (row,) = await (
                await conn.execute(
                    "select status::text as status, error_message from agent_runs where id = %s",
                    (run_id,),
                )
            ).fetchall()
            assert row["status"] == "failed"
            assert row["error_message"] == "INTERNAL_ERROR: 멈췄어요."
    finally:
        async with pool.connection() as conn:
            await conn.execute("delete from agent_runs where id = %s", (run_id,))
        await pool.close()


async def test_the_pools_replace_a_connection_the_server_closed() -> None:
    """서버(풀러)가 끊은 연결을 빌려주지 않는다 — 11/12 00:50 알림 발송이 끊긴 연결을 받아 실패했다.

    두 풀 모두 연결 하나를 빌려 그 서버 프로세스를 끊은 뒤 다시 빌린다. 풀이 빌려주기 전에 보지 않으면
    끊긴 연결이 그대로 나와 첫 문장에서 OperationalError가 난다.
    """
    pool, log_pool = create_pools(DATABASE_URL)
    for each in (pool, log_pool):
        await each.open()
    try:
        for each in (pool, log_pool):
            await each.wait(timeout=10)
            async with each.connection() as conn:
                row = await (await conn.execute("select pg_backend_pid() as pid")).fetchone()
                closed = row["pid"]
            admin = await connect(autocommit=True)
            try:
                await admin.execute("select pg_terminate_backend(%s)", (closed,))
            finally:
                await admin.close()
            async with each.connection(timeout=5) as conn:
                row = await (await conn.execute("select pg_backend_pid() as pid")).fetchone()
                assert row["pid"] != closed
    finally:
        for each in (pool, log_pool):
            await each.close()


async def test_child_runs_make_a_tree_and_roll_their_cost_up() -> None:
    """실행 트리(O1): 자식은 부모의 trigger·시나리오 번호를 받고 부모·뿌리를 가리킨다. 손자의 뿌리도 맨 위다.

    자식·손자의 토큰·비용은 끝날 때 위로 더해져 뿌리의 cost_usd가 흐름 전체 비용이 된다. llm_calls를 더하면
    호출마다 한 번씩만 센다(실행 행의 cost_usd를 두 층에서 더하면 두 번 센다).
    """
    conn = await connect(autocommit=True)
    ids: list[str] = []
    try:
        async with agent_run(using(conn), trigger="eval", scenario_code="TEST-TREE") as root:
            ids.append(root.id)
            async with root.child() as child:
                ids.append(child.id)
                await child.record_llm(
                    provider="gemini",
                    model="test-model",
                    input_tokens=100,
                    output_tokens=10,
                    cost_usd=0.002,
                    latency_ms=5,
                )
                async with child.child() as grandchild:
                    ids.append(grandchild.id)
                    await grandchild.record_llm(
                        provider="gemini",
                        model="test-model",
                        input_tokens=50,
                        output_tokens=5,
                        cost_usd=0.001,
                        latency_ms=5,
                    )
            with pytest.raises(ValueError):
                async with root.child(scenario_code="TEST-TREE-OTHER") as failed:
                    ids.append(failed.id)
                    raise ValueError("모델 오류")

        found = {
            str(row["id"]): row
            for row in await (
                await conn.execute(
                    "select id, trigger_type, scenario_code, user_id, status::text as status,"
                    " parent_run_id::text as parent, root_run_id::text as root, input_tokens,"
                    " cost_usd, error_message from agent_runs where id = any(%s::uuid[])",
                    (ids,),
                )
            ).fetchall()
        }
        top, middle, bottom, failed = (found[one] for one in ids)
        assert (top["parent"], top["root"]) == (None, None)
        assert (middle["parent"], middle["root"]) == (ids[0], ids[0])
        assert (bottom["parent"], bottom["root"]) == (ids[1], ids[0])
        assert (failed["parent"], failed["root"]) == (ids[0], ids[0])
        assert {row["trigger_type"] for row in found.values()} == {"eval"}
        assert [row["scenario_code"] for row in (top, middle, bottom, failed)] == [
            "TEST-TREE",
            "TEST-TREE",
            "TEST-TREE",
            "TEST-TREE-OTHER",
        ]
        assert all(row["user_id"] is None for row in found.values())
        assert [row["status"] for row in (top, middle, bottom, failed)] == [
            "succeeded",
            "succeeded",
            "succeeded",
            "failed",
        ]
        assert "모델 오류" in failed["error_message"]
        # 비용·토큰은 아래에서 위로 더한다: 손자 0.001 → 자식 0.003 → 뿌리 0.003
        assert [float(row["cost_usd"]) for row in (top, middle, bottom)] == pytest.approx(
            [0.003, 0.003, 0.001]
        )
        assert [row["input_tokens"] for row in (top, middle, bottom)] == [150, 150, 50]
        total = await (
            await conn.execute(
                "select sum(cost_usd) as cost from llm_calls where run_id = any(%s::uuid[])",
                (ids,),
            )
        ).fetchone()
        assert total is not None and float(total["cost"]) == pytest.approx(0.003)

        # 부모 행이 없으면 자식을 만들지 않는다
        lost = AgentRun(connect=using(conn), id=str(uuid.uuid4()))
        with pytest.raises(RuntimeError):
            async with lost.child():
                pass
    finally:
        await conn.execute("delete from agent_runs where id = any(%s::uuid[])", (ids,))
        await conn.close()


async def test_engine_runs_carry_their_stamp_in_the_database() -> None:
    """엔진 도장(O2): 엔진 이름·버전은 행을 만들 때, 모델·이유 코드는 닫을 때 남는다. 실패한 실행도 엔진이 남는다.

    엔진 이름과 버전은 함께 있거나 함께 없다(검사 제약). 엔진이 여럿인 흐름의 뿌리는 두 칸이 빈다.
    """
    conn = await connect(autocommit=True)
    ids: list[str] = []
    try:
        async with agent_run(using(conn), trigger="lms_sync", scenario_code="TEST-ENGINE") as root:
            ids.append(root.id)
            async with root.child(engine="classify.announcement") as classify:
                ids.append(classify.id)
                await classify.record_llm(
                    provider="google",
                    model="test-lite",
                    input_tokens=10,
                    output_tokens=1,
                    cost_usd=0,
                    latency_ms=5,
                )
            with pytest.raises(ApiError):
                async with root.child(engine="extract.requirements") as extract:
                    ids.append(extract.id)
                    await extract.record_llm(
                        provider="google",
                        model="test-standard",
                        input_tokens=10,
                        output_tokens=1,
                        cost_usd=0,
                        latency_ms=5,
                    )
                    extract.review_codes = ("NO_SUBMISSION",)
                    raise ApiError(502, "LLM_TIMEOUT", "늦었어요.")
        poster = await start_run(
            using(conn), trigger="eval", scenario_code="TEST-ENGINE", engine="extract.poster"
        )
        ids.append(poster)

        found = {
            str(row["id"]): row
            for row in await (
                await conn.execute(
                    "select id, status::text as status, engine, engine_version, model, review_codes"
                    " from agent_runs where id = any(%s::uuid[])",
                    (ids,),
                )
            ).fetchall()
        }
        assert [
            (
                found[one]["status"],
                found[one]["engine"],
                found[one]["engine_version"],
                found[one]["model"],
                found[one]["review_codes"],
            )
            for one in ids
        ] == [
            ("succeeded", None, None, None, []),
            ("succeeded", "classify.announcement", 1, "test-lite", []),
            ("failed", "extract.requirements", 1, "test-standard", ["NO_SUBMISSION"]),
            ("running", "extract.poster", 1, None, []),
        ]
        with pytest.raises(psycopg.errors.CheckViolation):
            await conn.execute(
                "insert into agent_runs (trigger_type, engine) values ('eval', 'extract.poster')"
            )
    finally:
        await conn.execute("delete from agent_runs where id = any(%s::uuid[])", (ids,))
        await conn.close()
