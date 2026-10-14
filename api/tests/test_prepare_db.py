"""준비하기 통합 테스트(F-30·F-31): 라우터 → 판정 → 뒤에서 도는 실행 → DB. DATABASE_URL이 있을 때만 돈다.

뒤에서 도는 일은 자기 연결(풀)을 열어 다른 연결이 쓴 행을 봐야 한다. 그래서 사용자·공고를 커밋하고
끝나면 지운다. 일은 InlineRunner로 응답 전에 끝까지 돌린다. 모델은 가짜(ScriptedLlm)다.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.background import InlineRunner, TaskRunner
from app.config import Settings, get_settings
from app.db import create_pools
from app.eligibility import KST
from app.llm import ModelTurn
from app.llm.deps import get_llm
from app.main import create_app
from app.prepare.guide import TOOL_NAME
from app.prepare.service import PrepareService
from app.repositories.prepare import PrepareRepository
from tests.conftest import make_token
from tests.db_world import DATABASE_URL, connect, make_user
from tests.llm_fakes import Request, ScriptedLlm, call

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

YOUTH_RAW = (
    "정책 설명: 청년 월세를 지원해요\n"
    "제출 서류: 1) 신청서\n2) 주민등록등본\n"
    "신청 사이트: www.example.go.kr"
)
GUIDES = {  # 가짜 모델이 아는 서류 안내
    "참가 확인서": {"issuer": "주최측", "how_to": "주최측 누리집에서 출력", "lead_days": 2},
    "신청서": {"issuer": "모델이 쓴 곳", "how_to": "모델이 쓴 방법", "lead_days": 3},
    "주민등록등본": {"issuer": "모델이 쓴 곳", "how_to": "모델이 쓴 방법", "lead_days": 3},
}


def guide_reply(request: Request) -> ModelTurn:
    """물어본 이름(1. …)이나 제출 서류 글(1) …)의 서류를 GUIDES에서 찾아 낸다."""
    text = request.turns[0].text  # type: ignore[union-attr]
    names = [name for name in GUIDES if name in text]
    return call(TOOL_NAME, documents=[{"name": name, **GUIDES[name]} for name in names])


def failing_reply(request: Request) -> ModelTurn:
    raise RuntimeError("모델 서버가 응답하지 않음")


@dataclass
class Fixture:
    now: datetime
    user: str
    other: str
    ids: dict[str, str] = field(default_factory=dict)
    run_ids: list[str] = field(default_factory=list)


@asynccontextmanager
async def committed() -> AsyncIterator[Fixture]:
    """사용자 둘과 공고 다섯을 커밋한다. 끝나면 실행·공고·사용자를 지운다."""
    setup = await connect()
    user = await make_user(setup, credits_last_semester=10)
    other = await make_user(setup)
    row = await (
        await setup.execute(
            "insert into agent_runs (trigger_type, status) values ('batch_crawl', 'succeeded')"
            " returning id, started_at"
        )
    ).fetchone()
    assert row is not None
    world = Fixture(row["started_at"], user, other, run_ids=[str(row["id"])])

    async def add(title: str, days: float | None, **columns: Any) -> str:
        values = {
            "source_type": "school_notice",
            "category": "scholarship",
            "title": title,
            "organizer": "학생지원팀",
            "deadline_at": None if days is None else world.now + timedelta(days=days),
            "extraction_run_id": world.run_ids[0],
            **columns,
        }
        names, marks = ", ".join(values), ", ".join(["%s"] * len(values))
        inserted = await (
            await setup.execute(
                f"insert into opportunities ({names}) values ({marks}) returning id",
                tuple(values.values()),
            )
        ).fetchone()
        assert inserted is not None
        world.ids[title] = str(inserted["id"])
        return world.ids[title]

    school = await add("준비 장학", 10)
    for name, form in (
        ("장학금 신청서", "https://www.hanyang.ac.kr/form.hwp"),
        ("재학증명서", None),
        ("참가 확인서", None),
    ):
        await setup.execute(
            "insert into opportunity_documents (opportunity_id, name, form_url) values (%s, %s, %s)",
            (school, name, form),
        )
    await add(
        "월세 지원", None, source_type="youth_policy", category="youth_policy", raw_text=YOUTH_RAW
    )
    await add(
        "서류 없는 정책",
        5,
        source_type="youth_policy",
        category="youth_policy",
        raw_text="정책 설명: 상담을 지원해요",
    )
    hard = await add("어려운 장학", 10)
    await setup.execute(
        "insert into requirements (opportunity_id, clause_no, field, operator, value)"
        " values (%s, 1, 'credits_last_semester', 'gte', '12')",
        (hard,),
    )
    await add("지난 장학", -0.01)
    await setup.commit()
    try:
        yield world
    finally:
        await setup.rollback()
        runs = await (
            await setup.execute(
                "select id::text as id from agent_runs where user_id = any(%s::uuid[])",
                ([user, other],),
            )
        ).fetchall()
        await setup.execute(
            "delete from agent_runs where id = any(%s::uuid[])",
            ([r["id"] for r in runs] + world.run_ids,),
        )
        await setup.execute(
            "delete from opportunities where id = any(%s::uuid[])", (list(world.ids.values()),)
        )
        await setup.execute("delete from auth.users where id = any(%s::uuid[])", ([user, other],))
        await setup.commit()
        await setup.close()


@asynccontextmanager
async def api(settings: Settings, llm: Any) -> AsyncIterator[Callable[[str], httpx.AsyncClient]]:
    """실제 풀을 단 앱. 사용자마다 로그인 헤더를 붙인 클라이언트를 만든다."""
    app = create_app(settings)
    pool, log_pool = create_pools(DATABASE_URL)
    await pool.open()
    await log_pool.open()
    app.state.pool, app.state.log_pool, app.state.runner = pool, log_pool, InlineRunner()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_llm] = lambda: llm
    clients: list[httpx.AsyncClient] = []

    def client(user_id: str) -> httpx.AsyncClient:
        http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {make_token(sub=user_id)}"},
        )
        clients.append(http)
        return http

    try:
        yield client
    finally:
        for http in clients:
            await http.aclose()
        await pool.close()
        await log_pool.close()


async def rows(query: str, *params: Any) -> list[dict[str, Any]]:
    conn = await connect()
    try:
        return await (await conn.execute(query, params)).fetchall()
    finally:
        await conn.close()


def kst_date(value: datetime) -> date:
    return value.astimezone(KST).date()


async def test_prepare_fills_guides_and_counts_back(settings: Settings) -> None:
    llm = ScriptedLlm(guide_reply)
    async with committed() as world, api(settings, llm) as client:
        http, oid = client(world.user), world.ids["준비 장학"]
        res = await http.post(f"/api/v1/opportunities/{oid}/prepare", json={})
        assert res.status_code == 202 and res.json()["status"] == "running"
        run_id = res.json()["run_id"]
        run = (await http.get(f"/api/v1/runs/{run_id}")).json()
        assert run["status"] == "succeeded" and run["error"] is None
        assert [(s["label"], s["status"]) for s in run["steps"]] == [
            ("필요 서류 확인", "succeeded"),
            ("마감일에서 거꾸로 일정 짜기", "succeeded"),
        ]
        docs = {d["name"]: d for d in run["result"]["documents"]}
        assert (docs["재학증명서"]["issuer"], docs["재학증명서"]["lead_days"]) == ("한양인 포털", 0)
        assert docs["장학금 신청서"]["lead_days"] == 0  # 사전(신청서)
        assert (docs["참가 확인서"]["issuer"], docs["참가 확인서"]["lead_days"]) == ("주최측", 2)
        deadline = kst_date(world.now + timedelta(days=10))
        tasks = {t["title"]: t for t in run["result"]["tasks"]}
        assert {title: t["due_date"] for title, t in tasks.items()} == {
            "장학금 신청서 준비": str(deadline - timedelta(days=2)),
            "재학증명서 준비": str(deadline - timedelta(days=2)),
            "참가 확인서 준비": str(deadline - timedelta(days=4)),
            "신청 제출": str(deadline - timedelta(days=1)),
        }
        assert run["result"]["tasks"][-1]["title"] == "신청 제출"
        assert {d["task_id"] for d in docs.values()} == {
            t["id"] for t in tasks.values() if t["document_id"]
        }
        # 사전에 없는 서류만 모델에 한 번 물었고, 그 호출이 실행 기록에 남았다
        assert len(llm.requests) == 1 and "1. 참가 확인서" in llm.requests[0].turns[0].text  # type: ignore[union-attr]
        logged = await rows(
            "select t.tool_name, t.output, (select count(*) from llm_calls l where l.tool_call_id = t.id)"
            " as llm from tool_calls t where t.run_id = %s order by t.seq",
            run_id,
        )
        assert [(r["tool_name"], r["llm"]) for r in logged] == [
            ("get_document_guide", 1),
            ("build_prep_plan", 0),
        ]
        assert logged[0]["output"] == {
            "documents": 3,
            "dictionary": 2,
            "model": 1,
            "unknown": 0,
            "listed": 0,
        }
        # 상세·피드는 준비한 공고로 본다. 다시 누르면 같은 실행이다
        detail = (await http.get(f"/api/v1/opportunities/{oid}")).json()
        assert detail["prep"]["prepared"] and detail["prep"]["tasks_total"] == 4
        assert detail["process"]["prepare_run_id"] == run_id
        assert all(d["task_id"] for d in detail["documents"])
        feed = (await http.get("/api/v1/opportunities")).json()
        assert [i["prepared"] for i in feed["items"] if i["id"] == oid] == [True]
        again = await http.post(f"/api/v1/opportunities/{oid}/prepare", json={})
        assert (again.status_code, again.json()) == (200, {"run_id": run_id, "status": "succeeded"})
        # 다른 학생은 저장된 안내를 써서 모델을 다시 부르지 않는다
        other = await client(world.other).post(f"/api/v1/opportunities/{oid}/prepare", json={})
        assert other.status_code == 202 and len(llm.requests) == 1


async def test_youth_policy_lists_documents_from_its_text(settings: Settings) -> None:
    llm = ScriptedLlm(guide_reply)
    async with committed() as world, api(settings, llm) as client:
        http, oid = client(world.user), world.ids["월세 지원"]
        res = await http.post(f"/api/v1/opportunities/{oid}/prepare", json={})
        assert res.status_code == 422  # 상시 공고는 목표일이 필요하다
        target = kst_date(world.now) + timedelta(days=6)
        res = await http.post(
            f"/api/v1/opportunities/{oid}/prepare", json={"target_date": str(target)}
        )
        assert res.status_code == 202
        result = (await http.get(f"/api/v1/runs/{res.json()['run_id']}")).json()["result"]
        docs = {d["name"]: d for d in result["documents"]}
        # 모델이 글에서 고른 서류다. 사전에 있는 서류는 사전 안내를 쓴다
        assert set(docs) == {"신청서", "주민등록등본"}
        assert (docs["주민등록등본"]["issuer"], docs["주민등록등본"]["lead_days"]) == ("정부24", 0)
        assert docs["신청서"]["issuer"] == "공고 첨부 양식·신청 사이트"
        assert "제출 서류' 글" in llm.requests[0].turns[0].text  # type: ignore[union-attr]
        assert {t["title"]: t["due_date"] for t in result["tasks"]} == {
            "신청서 준비": str(target - timedelta(days=2)),
            "주민등록등본 준비": str(target - timedelta(days=2)),
            "신청 제출": str(target - timedelta(days=1)),
        }
        stored = await rows("select name from opportunity_documents where opportunity_id = %s", oid)
        assert {r["name"] for r in stored} == {"신청서", "주민등록등본"}


async def test_posting_without_documents_makes_one_submission(settings: Settings) -> None:
    async with committed() as world, api(settings, ScriptedLlm()) as client:
        http, oid = client(world.user), world.ids["서류 없는 정책"]
        res = await http.post(f"/api/v1/opportunities/{oid}/prepare", json={})
        result = (await http.get(f"/api/v1/runs/{res.json()['run_id']}")).json()["result"]
        deadline = kst_date(world.now + timedelta(days=5))
        assert result["documents"] == []
        assert [(t["title"], t["due_date"]) for t in result["tasks"]] == [
            ("신청 제출", str(deadline - timedelta(days=1)))
        ]


async def test_ineligible_and_closed_postings(settings: Settings) -> None:
    async with committed() as world, api(settings, ScriptedLlm()) as client:
        http = client(world.user)
        hard = f"/api/v1/opportunities/{world.ids['어려운 장학']}/prepare"
        res = await http.post(hard, json={})
        assert (res.status_code, res.json()["error"]["code"]) == (409, "NOT_ELIGIBLE")
        forced = await http.post(hard, json={"force": True})
        assert forced.status_code == 202
        run = (await http.get(f"/api/v1/runs/{forced.json()['run_id']}")).json()
        assert run["status"] == "succeeded"
        res = await http.post(f"/api/v1/opportunities/{world.ids['지난 장학']}/prepare", json={})
        assert (res.status_code, res.json()["error"]["code"]) == (409, "DEADLINE_PASSED")


@pytest.mark.parametrize("llm", [ScriptedLlm(failing_reply), None])
async def test_failed_guide_leaves_nothing_and_can_retry(
    settings: Settings, llm: ScriptedLlm | None
) -> None:
    async with committed() as world:
        oid = world.ids["준비 장학"]
        async with api(settings, llm) as client:
            http = client(world.user)
            res = await http.post(f"/api/v1/opportunities/{oid}/prepare", json={})
            assert res.status_code == 202
            run = (await http.get(f"/api/v1/runs/{res.json()['run_id']}")).json()
            assert run["status"] == "failed" and run["result"] is None
            assert run["error"] == {
                "code": "LLM_ERROR",
                "message": "필요 서류를 확인하지 못했어요. 잠시 후 다시 눌러 주세요.",
            }
            assert [s["status"] for s in run["steps"]] == ["failed"]
            # 계획·할 일·서류 안내가 남지 않아 준비하지 않은 공고다
            assert await rows("select 1 from prep_plans where opportunity_id = %s", oid) == []
            guides = await rows(
                "select lead_days from opportunity_documents where opportunity_id = %s", oid
            )
            assert {r["lead_days"] for r in guides} == {None}
            detail = (await http.get(f"/api/v1/opportunities/{oid}")).json()
            assert not detail["prep"]["prepared"]
        async with api(settings, ScriptedLlm(guide_reply)) as client:  # 다시 누르면 된다
            http = client(world.user)
            res = await http.post(f"/api/v1/opportunities/{oid}/prepare", json={})
            assert res.status_code == 202
            run = (await http.get(f"/api/v1/runs/{res.json()['run_id']}")).json()
            assert run["status"] == "succeeded"


async def test_running_plan_is_not_prepared_and_a_stuck_one_restarts(settings: Settings) -> None:
    async with committed() as world, api(settings, ScriptedLlm(guide_reply)) as client:
        http, oid = client(world.user), world.ids["준비 장학"]
        conn = await connect(autocommit=True)
        try:
            row = await (
                await conn.execute(
                    "insert into agent_runs (user_id, trigger_type, started_at)"
                    " values (%s, 'prepare', now()) returning id",
                    (world.user,),
                )
            ).fetchone()
            assert row is not None
            running = str(row["id"])
            await conn.execute(
                "insert into prep_plans (user_id, opportunity_id, agent_run_id) values (%s, %s, %s)",
                (world.user, oid, running),
            )
            detail = (await http.get(f"/api/v1/opportunities/{oid}")).json()
            assert not detail["prep"]["prepared"] and detail["prep"]["prep_plan_id"] is None
            feed = (await http.get("/api/v1/opportunities")).json()
            assert [i["prepared"] for i in feed["items"] if i["id"] == oid] == [False]
            res = await http.post(f"/api/v1/opportunities/{oid}/prepare", json={})
            assert (res.status_code, res.json()) == (200, {"run_id": running, "status": "running"})
            # 5분이 넘게 실행 중이면 멈춘 실행이다. 지우고 새로 만든다
            await conn.execute(
                "update agent_runs set started_at = now() - interval '6 minutes' where id = %s",
                (running,),
            )
            res = await http.post(f"/api/v1/opportunities/{oid}/prepare", json={})
            assert res.status_code == 202 and res.json()["run_id"] != running
            old = await rows("select status::text as status from agent_runs where id = %s", running)
            assert old == [{"status": "failed"}]
            assert (await http.get(f"/api/v1/opportunities/{oid}")).json()["prep"]["prepared"]
        finally:
            await conn.close()


async def test_double_press_makes_one_plan(settings: Settings) -> None:
    async with committed() as world, api(settings, ScriptedLlm(guide_reply)) as client:
        oid = world.ids["준비 장학"]
        first, second = client(world.user), client(world.user)
        responses = await asyncio.gather(
            first.post(f"/api/v1/opportunities/{oid}/prepare", json={}),
            second.post(f"/api/v1/opportunities/{oid}/prepare", json={}),
        )
        assert sorted(r.status_code for r in responses) == [200, 202]
        assert len({r.json()["run_id"] for r in responses}) == 1
        plans = await rows(
            "select agent_run_id::text as run_id from prep_plans where opportunity_id = %s", oid
        )
        assert [p["run_id"] for p in plans] == [responses[0].json()["run_id"]]
        tasks = await rows(
            "select count(*) as n from planner_tasks t join prep_plans p on p.id = t.prep_plan_id"
            " where p.opportunity_id = %s",
            oid,
        )
        assert tasks == [{"n": 4}]


async def test_stale_rows_are_judged_by_run_status(settings: Settings) -> None:
    """실행 기록이 없는 옛 계획(실행 id null)은 준비한 공고다(db_world의 장학 A처럼)."""
    async with committed() as world, api(settings, ScriptedLlm()) as client:
        http, oid = client(world.user), world.ids["준비 장학"]
        conn = await connect(autocommit=True)
        try:
            await conn.execute(
                "insert into prep_plans (user_id, opportunity_id) values (%s, %s)",
                (world.user, oid),
            )
        finally:
            await conn.close()
        assert (await http.get(f"/api/v1/opportunities/{oid}")).json()["prep"]["prepared"]
        res = await http.post(f"/api/v1/opportunities/{oid}/prepare", json={})
        assert (res.status_code, res.json()) == (200, {"run_id": None, "status": "succeeded"})


def _can_lock(opportunity_id: str) -> bool:
    """다른 연결이 공고 행을 바로 잠글 수 있나(준비하기가 잠금을 쥔 채 모델을 부르지 않는지)."""
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        try:
            conn.execute(
                "select 1 from opportunities where id = %s for no key update nowait",
                (opportunity_id,),
            )
        except psycopg.errors.LockNotAvailable:
            return False
        return True


async def test_the_model_is_asked_outside_the_opportunity_lock(settings: Settings) -> None:
    """모델에 묻는 동안 공고 행을 잠그지 않는다(느린 모델이 같은 공고의 다른 준비를 막지 않게)."""
    free: list[bool] = []

    async with committed() as world:
        oid = world.ids["준비 장학"]

        def watching_reply(request: Request) -> ModelTurn:
            free.append(_can_lock(oid))
            return guide_reply(request)

        async with api(settings, ScriptedLlm(watching_reply)) as client:
            http = client(world.user)
            res = await http.post(f"/api/v1/opportunities/{oid}/prepare", json={})
            assert res.status_code == 202
            run = (await http.get(f"/api/v1/runs/{res.json()['run_id']}")).json()
            assert run["status"] == "succeeded"
    assert free == [True]


async def test_a_guide_filled_while_we_asked_is_kept(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """묻는 사이에 다른 학생이 채운 안내는 덮지 않는다(모델 호출이 잠금 밖이라 생기는 겹침)."""
    original = PrepareService._ask_guides

    async def fill_then_ask(self: PrepareService, run: Any, call: Any, job: Any) -> Any:
        asked = await original(self, run, call, job)
        conn = await connect(autocommit=True)
        try:  # 다른 학생의 준비하기가 먼저 커밋했다
            await conn.execute(
                "update opportunity_documents set issuer = %s, how_to = %s, lead_days = %s"
                " where opportunity_id = %s and name = %s",
                ("먼저 채운 곳", "먼저 채운 방법", 4, job.opportunity_id, "참가 확인서"),
            )
        finally:
            await conn.close()
        return asked

    monkeypatch.setattr(PrepareService, "_ask_guides", fill_then_ask)
    async with committed() as world, api(settings, ScriptedLlm(guide_reply)) as client:
        http, oid = client(world.user), world.ids["준비 장학"]
        res = await http.post(f"/api/v1/opportunities/{oid}/prepare", json={})
        assert res.status_code == 202
        run = (await http.get(f"/api/v1/runs/{res.json()['run_id']}")).json()
        assert run["status"] == "succeeded"
        document = next(d for d in run["result"]["documents"] if d["name"] == "참가 확인서")
        assert (document["issuer"], document["how_to"], document["lead_days"]) == (
            "먼저 채운 곳",
            "먼저 채운 방법",
            4,
        )
        # 먼저 채운 소요 일수로 역산한다(모델 답 2일이 아니라 4일)
        deadline = kst_date(world.now + timedelta(days=10))
        tasks = {t["title"]: t["due_date"] for t in run["result"]["tasks"]}
        assert tasks["참가 확인서 준비"] == str(deadline - timedelta(days=6))


async def test_a_job_that_cannot_log_closes_its_plan_and_run(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실행 기록을 열지 못해 agent_run 밖에서 끝나도 계획을 지우고 실행을 닫는다."""

    def no_log(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("실행 로그 연결을 얻지 못했다")

    monkeypatch.setattr("app.prepare.service.agent_run", no_log)
    async with committed() as world, api(settings, ScriptedLlm()) as client:
        http, oid = client(world.user), world.ids["준비 장학"]
        res = await http.post(f"/api/v1/opportunities/{oid}/prepare", json={})
        assert res.status_code == 202
        run = (await http.get(f"/api/v1/runs/{res.json()['run_id']}")).json()
        assert run["status"] == "failed" and run["steps"] == []
        assert run["error"] == {
            "code": "INTERNAL_ERROR",
            "message": "준비 일정을 만들다 멈췄어요. 다시 눌러 주세요.",
        }
        assert await rows("select 1 from prep_plans where opportunity_id = %s", oid) == []
        assert not (await http.get(f"/api/v1/opportunities/{oid}")).json()["prep"]["prepared"]


async def test_a_plan_that_vanishes_in_a_race_asks_for_another_press(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """동시 요청이 먼저 만든 계획이 그새 지워졌으면 500이고, 이 요청의 실행은 닫는다."""

    async def taken(*args: Any, **kwargs: Any) -> None:
        return None  # 계획 행은 다른 요청이 먼저 만들었다(그리고 그새 실패해 지워졌다)

    monkeypatch.setattr(PrepareRepository, "create_plan", taken)
    async with committed() as world, api(settings, ScriptedLlm()) as client:
        http, oid = client(world.user), world.ids["준비 장학"]
        res = await http.post(f"/api/v1/opportunities/{oid}/prepare", json={})
        assert (res.status_code, res.json()["error"]["code"]) == (500, "INTERNAL_ERROR")
        assert res.json()["error"]["message"] == "준비 일정을 만들다 멈췄어요. 다시 눌러 주세요."
        runs = await rows(
            "select status::text as status, error_message from agent_runs where user_id = %s",
            world.user,
        )
        assert runs == [
            {
                "status": "failed",
                "error_message": "INTERNAL_ERROR: 같은 공고를 이미 준비하고 있어요.",
            }
        ]


async def test_a_plan_deleted_while_we_asked_stops_the_write(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """묻는 사이에 다음 누름이 계획을 지웠으면 쓰지 않고 그 요청에 넘긴다(할 일이 겹쳐 들어가지 않는다)."""
    original = PrepareService._ask_guides

    async def drop_then_ask(self: PrepareService, run: Any, call: Any, job: Any) -> Any:
        asked = await original(self, run, call, job)
        conn = await connect(autocommit=True)
        try:  # 멈춘 실행으로 보고 지운 상황
            await conn.execute("delete from prep_plans where id = %s", (job.plan_id,))
        finally:
            await conn.close()
        return asked

    monkeypatch.setattr(PrepareService, "_ask_guides", drop_then_ask)
    async with committed() as world, api(settings, ScriptedLlm(guide_reply)) as client:
        http, oid = client(world.user), world.ids["준비 장학"]
        res = await http.post(f"/api/v1/opportunities/{oid}/prepare", json={})
        assert res.status_code == 202
        run = (await http.get(f"/api/v1/runs/{res.json()['run_id']}")).json()
        assert run["status"] == "failed"
        assert run["error"]["message"] == "준비 일정을 만들다 멈췄어요. 다시 눌러 주세요."
        assert await rows("select 1 from planner_tasks where user_id = %s", world.user) == []
        guides = await rows(
            "select lead_days from opportunity_documents where opportunity_id = %s", oid
        )
        assert {row["lead_days"] for row in guides} == {None}  # 서류 안내도 함께 되돌린다


async def test_a_document_guided_without_lead_days_is_not_asked_again(
    settings: Settings,
) -> None:
    """모델이 소요 일수를 숫자로 주지 않아도 안내를 채웠으면 다음 학생이 다시 묻지 않는다."""

    def sloppy_reply(request: Request) -> ModelTurn:
        return call(
            TOOL_NAME,
            documents=[
                {
                    "name": "참가 확인서",
                    "issuer": "주최측",
                    "how_to": "주최측 누리집에서 출력",
                    "lead_days": "이틀",  # 숫자가 아니라 쓸 수 없다
                }
            ],
        )

    llm = ScriptedLlm(sloppy_reply)
    async with committed() as world, api(settings, llm) as client:
        oid = world.ids["준비 장학"]
        first = await client(world.user).post(f"/api/v1/opportunities/{oid}/prepare", json={})
        assert first.status_code == 202
        document = await rows(
            "select issuer, lead_days from opportunity_documents where opportunity_id = %s"
            " and name = %s",
            oid,
            "참가 확인서",
        )
        assert document == [{"issuer": "주최측", "lead_days": None}]
        second = await client(world.other).post(f"/api/v1/opportunities/{oid}/prepare", json={})
        assert second.status_code == 202 and len(llm.requests) == 1  # 다시 묻지 않았다
        run = (await client(world.other).get(f"/api/v1/runs/{second.json()['run_id']}")).json()
        assert run["status"] == "succeeded"


@asynccontextmanager
async def narrow_api(
    settings: Settings, llm: Any
) -> AsyncIterator[Callable[[str], httpx.AsyncClient]]:
    """로그 풀이 1칸이고 일을 진짜로 띄우는(TaskRunner) 앱. 로그 연결 경합을 본다."""
    app = create_app(settings)
    pool = AsyncConnectionPool(
        DATABASE_URL,
        min_size=1,
        max_size=10,
        open=False,
        kwargs={"row_factory": dict_row, "prepare_threshold": None},
    )
    log_pool = AsyncConnectionPool(
        DATABASE_URL,
        min_size=1,
        max_size=1,
        open=False,
        kwargs={"row_factory": dict_row, "autocommit": True, "prepare_threshold": None},
    )
    await pool.open()
    await log_pool.open()
    runner = TaskRunner()
    app.state.pool, app.state.log_pool, app.state.runner = pool, log_pool, runner
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_llm] = lambda: llm
    clients: list[httpx.AsyncClient] = []

    def client(user_id: str) -> httpx.AsyncClient:
        http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {make_token(sub=user_id)}"},
        )
        clients.append(http)
        return http

    try:
        yield client
    finally:
        await runner.drain(timeout=10)
        for http in clients:
            await http.aclose()
        await pool.close()
        await log_pool.close()


class GatedLlm(ScriptedLlm):
    """첫 호출은 풀어 줄 때까지 모델 안에서 기다린다(느린 모델)."""

    def __init__(self, *replies: Any) -> None:
        super().__init__(*replies)
        self.asked = asyncio.Event()  # 모델에 들어왔다
        self.release = asyncio.Event()  # 이제 답해도 된다

    async def generate(self, **kwargs: Any) -> Any:
        self.asked.set()
        await self.release.wait()
        return await super().generate(**kwargs)


async def test_a_slow_model_does_not_block_another_student(settings: Settings) -> None:
    """모델을 기다리는 실행이 로그 연결을 쥐지 않아, 로그 풀이 1칸이어도 다른 학생이 바로 시작한다.

    실행이 연결을 들고 있으면 둘째 요청의 start_run이 연결을 못 얻어 기다리다 500이 된다.
    """
    llm = GatedLlm(guide_reply, guide_reply)
    async with committed() as world, narrow_api(settings, llm) as client:
        oid = world.ids["준비 장학"]
        started = await client(world.user).post(f"/api/v1/opportunities/{oid}/prepare", json={})
        assert started.status_code == 202
        await asyncio.wait_for(llm.asked.wait(), timeout=5)  # 첫 실행이 모델 안에서 기다린다

        other = await asyncio.wait_for(  # 그 사이 다른 학생이 같은 공고를 준비한다
            client(world.other).post(f"/api/v1/opportunities/{oid}/prepare", json={}), timeout=5
        )
        assert other.status_code == 202

        llm.release.set()
        for user_id, response in ((world.user, started), (world.other, other)):
            http, run_id = client(user_id), response.json()["run_id"]
            for _ in range(100):
                run = (await http.get(f"/api/v1/runs/{run_id}")).json()
                if run["status"] != "running":
                    break
                await asyncio.sleep(0.1)
            assert run["status"] == "succeeded"  # 둘 다 끝까지 간다
