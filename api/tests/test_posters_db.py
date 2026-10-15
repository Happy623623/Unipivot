"""포스터 추출 통합 테스트(F-16): 라우터 → 뒤에서 도는 실행 → 저장소·DB → GET /runs/{id}.

뒤에서 도는 일은 자기 연결(풀)을 열어 다른 연결이 쓴 행을 봐야 한다. 그래서 사용자·파일·공고를 커밋하고
끝나면 지운다. 일은 InlineRunner로 응답 전에 끝까지 돌린다. 모델은 가짜(ScriptedLlm)이고 Supabase
Storage도 가짜다. 초안은 tool_calls.output에 남고 GET /runs/{id}가 그것을 다시 읽는다.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.background import InlineRunner
from app.config import Settings, get_settings
from app.db import create_pools
from app.extraction.store import content_hash
from app.extraction.validate import LOW_CONFIDENCE as LOW_CONFIDENCE_REASON
from app.llm.deps import get_llm
from app.main import create_app
from app.posters.prompt import SUBMIT
from app.repositories.posters import AMBIGUOUS_REASON, PosterRepository
from app.uploads.storage import StorageError, get_storage
from tests.conftest import make_token
from tests.db_world import DATABASE_URL, connect, make_user
from tests.llm_fakes import ScriptedLlm, call
from tests.test_posters_extract import TEXT, args

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

POSTER_BYTES = b"\xff\xd8\xff" + b"poster".ljust(40, b"\x00")
# 실패한 실행으로 등록을 눌러 볼 때 보내는 몸통(초안 모양만 맞으면 된다)
DRAFT_BODY: dict[str, Any] = {
    "title": "손으로 적은 제목",
    "organizer": None,
    "category": "contest",
    "apply_start_at": None,
    "deadline_at": None,
    "easy_summary": None,
    "requirements": [],
    "documents": [],
    "extraction_confidence": 0.5,
    "low_confidence_fields": [],
}


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.asked: list[str] = []
        self.broken = False

    async def download(self, path: str) -> bytes:
        self.asked.append(path)
        if self.broken:
            raise StorageError("저장소가 거절했어요")
        if path not in self.objects:
            raise StorageError("그 파일이 없어요")
        return self.objects[path]


@dataclass
class Fixture:
    now: datetime
    user: str
    other: str
    files: dict[str, str] = field(default_factory=dict)  # 이름 → file_id
    paths: dict[str, str] = field(default_factory=dict)  # file_id → storage_path
    ids: dict[str, str] = field(default_factory=dict)  # 공고 제목 → id
    run_ids: list[str] = field(default_factory=list)
    add: Any = None  # 공고를 더 넣는 함수(테스트에서 쓴다). 넣은 뒤 commit을 부른다
    commit: Any = None


@asynccontextmanager
async def committed() -> AsyncIterator[Fixture]:
    """사용자 둘, 포스터 파일 셋, 공고 둘을 커밋한다. 끝나면 지운다."""
    setup = await connect()
    user = await make_user(setup)
    other = await make_user(setup)
    row = await (
        await setup.execute(
            "insert into agent_runs (trigger_type, status) values ('batch_crawl', 'succeeded')"
            " returning id, started_at"
        )
    ).fetchone()
    assert row is not None
    world = Fixture(row["started_at"], user, other, run_ids=[str(row["id"])])

    async def add_file(
        name: str, owner: str, *, kind: str = "poster", origin: str = "upload"
    ) -> str:
        file_id = str(uuid4())
        path = f"{owner}/{kind}/{file_id}.jpg"
        await setup.execute(
            "insert into files (id, user_id, kind, origin, storage_path, mime_type, sha256)"
            " values (%s, %s, %s, %s, %s, 'image/jpeg', %s)",
            (file_id, owner, kind, origin, path, f"{abs(hash(name)):064d}"[:64]),
        )
        world.files[name] = file_id
        world.paths[file_id] = path
        return file_id

    await add_file("내 포스터", user)
    await add_file("남의 포스터", other)
    await add_file("계획서", user, kind="syllabus")

    async def add_opportunity(title: str, days: float | None, **columns: Any) -> str:
        values: dict[str, Any] = {
            "source_type": "school_notice",
            "category": "contest",
            "title": title,
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

    await setup.commit()
    world.add = add_opportunity
    world.commit = setup.commit
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
            "delete from opportunities where id = any(%s::uuid[])",
            ([v for v in world.ids.values() if v],),
        )
        await setup.execute("delete from auth.users where id = any(%s::uuid[])", ([user, other],))
        await setup.commit()
        await setup.close()


@asynccontextmanager
async def api(
    settings: Settings, llm: Any, storage: FakeStorage
) -> AsyncIterator[Callable[[str], httpx.AsyncClient]]:
    app = create_app(settings)
    pool, log_pool = create_pools(DATABASE_URL)
    await pool.open()
    await log_pool.open()
    app.state.pool, app.state.log_pool, app.state.runner = pool, log_pool, InlineRunner()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_storage] = lambda: storage
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


async def extract(
    world: Fixture,
    settings: Settings,
    llm: Any,
    *,
    name: str = "내 포스터",
    storage: FakeStorage | None = None,
    user: str | None = None,
) -> dict[str, Any]:
    """POST /posters/extract → GET /runs/{id}. InlineRunner라 응답 전에 실행이 끝나 있다."""
    store = storage or FakeStorage()
    file_id = world.files[name]
    store.objects.setdefault(world.paths[file_id], POSTER_BYTES)
    async with api(settings, llm, store) as client:
        http = client(user or world.user)
        started = await http.post("/api/v1/posters/extract", json={"file_id": file_id})
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        return (await http.get(f"/api/v1/runs/{run_id}")).json()


async def test_a_poster_becomes_a_draft_the_confirm_screen_can_show(settings: Settings) -> None:
    llm = ScriptedLlm(call(SUBMIT, **args()))
    async with committed() as world:
        run = await extract(world, settings, llm)
    assert run["status"] == "succeeded" and run["error"] is None
    assert [(s["label"], s["status"]) for s in run["steps"]] == [
        ("포스터에서 글자·날짜 읽기", "succeeded")
    ]
    result = run["result"]
    assert result["kind"] == "poster_extract"
    assert result["draft"]["title"] == "2026 전국 대학생 SW 창업 아이디어톤"
    assert result["draft"]["requirements"][0]["condition_text"]
    assert result["duplicate_candidate"] is None


async def test_the_transcribed_text_is_kept_for_registering_later(settings: Settings) -> None:
    llm = ScriptedLlm(call(SUBMIT, **args()))
    async with committed() as world:
        run = await extract(world, settings, llm)
        output = await saved_output(run["id"])
    assert output["poster_text"] == TEXT  # 등록(F-16 2차)에서 공고 원문으로 쓴다
    assert output["draft"]["title"]


async def test_the_model_and_its_cost_are_logged(settings: Settings) -> None:
    llm = ScriptedLlm(call(SUBMIT, **args()))
    async with committed() as world:
        run = await extract(world, settings, llm)
        calls = await rows(
            "select provider, model, input_tokens, output_tokens from llm_calls where run_id = %s",
            run["id"],
        )
    assert len(calls) == 1 and calls[0]["provider"] == "google"
    assert calls[0]["input_tokens"] and calls[0]["output_tokens"]


async def test_a_poster_with_no_text_fails_with_what_to_do(settings: Settings) -> None:
    llm = ScriptedLlm("포스터가 흐려요")
    async with committed() as world:
        run = await extract(world, settings, llm)
    assert run["status"] == "failed"
    assert run["error"]["code"] == "POSTER_READ_FAILED"
    assert "다시 찍어" in run["error"]["message"]
    assert run["result"] is None


@pytest.mark.parametrize(
    ("boom", "code"),
    [
        (TimeoutError("느림"), "LLM_TIMEOUT"),
        (RuntimeError("모델 서버가 응답하지 않음"), "LLM_ERROR"),
    ],
)
async def test_a_model_that_fails_tells_the_student_to_try_again(
    settings: Settings, boom: Exception, code: str
) -> None:
    def failing(request: Any) -> Any:
        raise boom

    async with committed() as world:
        run = await extract(world, settings, ScriptedLlm(failing))
    assert run["status"] == "failed" and run["error"]["code"] == code
    assert "다시 눌러 주세요" in run["error"]["message"]


async def test_without_a_model_nothing_is_fetched_from_the_storage(settings: Settings) -> None:
    """모델이 없으면 저장소에서 파일을 받지도 않고 바로 실패한다."""
    storage = FakeStorage()
    async with committed() as world:
        run = await extract(world, settings, None, storage=storage)
    assert run["status"] == "failed" and run["error"]["code"] == "LLM_ERROR"
    assert storage.asked == []


async def test_a_storage_that_cannot_be_reached_fails_the_run(settings: Settings) -> None:
    storage = FakeStorage()
    storage.broken = True
    llm = ScriptedLlm(call(SUBMIT, **args()))
    async with committed() as world:
        run = await extract(world, settings, llm, storage=storage)
    assert run["status"] == "failed" and run["error"]["code"] == "STORAGE_API_ERROR"


async def test_someone_elses_poster_and_a_syllabus_are_not_found(settings: Settings) -> None:
    llm = ScriptedLlm(call(SUBMIT, **args()))
    async with committed() as world:
        store = FakeStorage()
        async with api(settings, llm, store) as client:
            http = client(world.user)
            for name in ("남의 포스터", "계획서"):
                res = await http.post(
                    "/api/v1/posters/extract", json={"file_id": world.files[name]}
                )
                assert res.status_code == 404, name


async def test_a_duplicate_is_found_by_title_and_the_same_deadline_day(settings: Settings) -> None:
    llm = ScriptedLlm(call(SUBMIT, **args()))
    async with committed() as world:
        add = world.add
        # 초안 마감일은 2026-10-20 18:00 KST다. 제목은 띄어쓰기를 지워 비교한다
        same = await add(
            "2026전국대학생SW창업아이디어톤",
            None,
            deadline_at=datetime.fromisoformat("2026-10-20T09:00:00+00:00"),
        )
        await add(
            "다른 공고", None, deadline_at=datetime.fromisoformat("2026-10-20T09:00:00+00:00")
        )
        await world.commit()
        run = await extract(world, settings, llm)
    assert run["result"]["duplicate_candidate"]["opportunity_id"] == same


async def test_the_same_title_on_another_day_is_not_a_duplicate(settings: Settings) -> None:
    llm = ScriptedLlm(call(SUBMIT, **args()))
    async with committed() as world:
        add = world.add
        await add(
            "2026 전국 대학생 SW 창업 아이디어톤",
            None,
            deadline_at=datetime.fromisoformat("2026-10-21T09:00:00+00:00"),
        )
        await world.commit()
        run = await extract(world, settings, llm)
    assert run["result"]["duplicate_candidate"] is None


async def test_another_students_poster_opportunity_is_not_a_duplicate(settings: Settings) -> None:
    llm = ScriptedLlm(call(SUBMIT, **args()))
    async with committed() as world:
        add = world.add
        await add(
            "2026 전국 대학생 SW 창업 아이디어톤",
            None,
            source_type="poster",
            uploaded_by=world.other,
            deadline_at=datetime.fromisoformat("2026-10-20T09:00:00+00:00"),
        )
        await world.commit()
        run = await extract(world, settings, llm)
    assert run["result"]["duplicate_candidate"] is None  # 남이 올린 포스터 공고는 내게 안 보인다


async def test_a_poster_with_no_deadline_matches_an_open_opportunity(settings: Settings) -> None:
    llm = ScriptedLlm(call(SUBMIT, **args(deadline=None)))
    async with committed() as world:
        add = world.add
        open_one = await add("2026 전국 대학생 SW 창업 아이디어톤", None)  # 마감일 없는 상시 공고
        await world.commit()
        run = await extract(world, settings, llm)
    assert run["result"]["duplicate_candidate"]["opportunity_id"] == open_one


async def test_the_poster_file_lookup_only_finds_my_uploaded_poster() -> None:
    conn = await connect()
    try:
        async with committed() as world:
            repo = PosterRepository(conn)
            mine = world.files["내 포스터"]
            found = await repo.poster_file(world.user, mine)
            assert found is not None and found.storage_path == world.paths[mine]
            assert await repo.poster_file(world.other, mine) is None
            assert await repo.poster_file(world.user, world.files["남의 포스터"]) is None
            assert await repo.poster_file(world.user, world.files["계획서"]) is None
    finally:
        await conn.close()


async def confirm(
    world: Fixture, settings: Settings, llm: Any, *, edit: Any = None, user: str | None = None
) -> dict[str, Any]:
    """추출 → (고치기) → POST /posters/confirm. 응답 본문을 돌려준다."""
    store = FakeStorage()
    file_id = world.files["내 포스터"]
    store.objects[world.paths[file_id]] = POSTER_BYTES
    async with api(settings, llm, store) as client:
        http = client(user or world.user)
        started = await http.post("/api/v1/posters/extract", json={"file_id": file_id})
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        run = (await http.get(f"/api/v1/runs/{run_id}")).json()
        assert run["status"] == "succeeded", run
        draft = run["result"]["draft"]
        if edit is not None:
            draft = edit(draft)
        res = await http.post("/api/v1/posters/confirm", json={"run_id": run_id, "draft": draft})
        assert res.status_code in (200, 201), res.text
        return {"status": res.status_code, **res.json(), "run_id": run_id}


async def test_confirming_makes_a_poster_opportunity_only_i_can_see(settings: Settings) -> None:
    llm = ScriptedLlm(call(SUBMIT, **args()))
    async with committed() as world:
        done = await confirm(world, settings, llm)
        oid = done["opportunity_id"]
        world.ids[f"__poster_{oid}"] = oid  # 끝나면 지운다
        rows_ = await rows(
            "select source_type::text as source_type, category::text as category, title, organizer,"
            " raw_text, uploaded_by::text as uploaded_by, poster_file_id::text as poster_file_id,"
            " extraction_run_id::text as extraction_run_id, easy_summary, extraction_confidence,"
            " deadline_at from opportunities where id = %s",
            oid,
        )
        requirements = await rows(
            "select clause_no, field, operator, value, is_ambiguous, evidence_text"
            " from requirements where opportunity_id = %s order by clause_no, created_at",
            oid,
        )
        documents = await rows(
            "select name from opportunity_documents where opportunity_id = %s order by name",
            oid,
        )
        judged = await rows(
            "select status::text as status from eligibility_results"
            " where opportunity_id = %s and user_id = %s",
            oid,
            world.user,
        )
    assert done["status"] == 201 and done["merged"] is False
    (row,) = rows_
    assert (row["source_type"], row["category"]) == ("poster", "contest")
    assert row["title"] == "2026 전국 대학생 SW 창업 아이디어톤"
    assert row["uploaded_by"] == world.user  # 올린 본인에게만 보인다
    assert row["poster_file_id"] == world.files["내 포스터"]
    assert row["extraction_run_id"] == done["run_id"]  # 상세·피드가 판정을 쓰려면 있어야 한다
    assert row["raw_text"] == TEXT  # 옮겨 적은 글이 공고 원문이 된다
    assert row["easy_summary"] and row["extraction_confidence"] is not None
    assert row["deadline_at"] is not None
    assert [(r["clause_no"], r["field"], r["operator"]) for r in requirements] == [
        (1, "enrollment_status", "in")
    ]
    assert requirements[0]["value"] == ["enrolled", "on_leave"]
    assert requirements[0]["evidence_text"] == "국내 대학 재학생 및 휴학생"
    assert {r["name"] for r in documents} == {"아이디어 제안서", "재학증명서"}
    assert len(judged) == 1  # 등록 즉시 본인 판정을 계산한다


async def test_the_basis_and_the_step_label_survive_registration(settings: Settings) -> None:
    """학과 기준(basis)이 요건 행까지 가고, 상세의 처리 과정에 내부 도구 이름이 보이지 않는다."""
    with_basis = args(
        poster_text=TEXT + "\n모집 대상: 공과대학 재학생",
        requirements=[
            {
                "clause_no": 1,
                "field": "department",
                "operator": "in",
                "value_json": '["공과대학"]',
                "basis": "college",
                "evidence_text": "모집 대상: 공과대학 재학생",
                "is_ambiguous": False,
            }
        ],
    )
    llm = ScriptedLlm(call(SUBMIT, **with_basis))
    async with committed() as world:
        store = FakeStorage()
        file_id = world.files["내 포스터"]
        store.objects[world.paths[file_id]] = POSTER_BYTES
        async with api(settings, llm, store) as client:
            mine = client(world.user)
            started = await mine.post("/api/v1/posters/extract", json={"file_id": file_id})
            run_id = started.json()["run_id"]
            draft = (await mine.get(f"/api/v1/runs/{run_id}")).json()["result"]["draft"]
            assert draft["requirements"][0]["basis"] == "college"  # 화면도 받아서 돌려보낸다
            made = await mine.post(
                "/api/v1/posters/confirm", json={"run_id": run_id, "draft": draft}
            )
            oid = made.json()["opportunity_id"]
            world.ids["__poster_basis"] = oid
            detail = (await mine.get(f"/api/v1/opportunities/{oid}")).json()
            mine_only = await client(world.other).get(f"/api/v1/opportunities/{oid}")
        saved = await rows(
            "select basis::text as basis from requirements where opportunity_id = %s", oid
        )
    assert saved[0]["basis"] == "college"  # 없으면 학과 조건을 학과 이름으로 비교해 판정이 틀린다
    labels = [step["label"] for step in detail["process"]["extraction"]]
    assert labels == ["포스터에서 글자·날짜 읽기"]  # 도구 이름이 그대로 보이지 않는다
    assert mine_only.status_code == 404  # 남이 올린 포스터 공고는 보이지 않는다


async def test_a_low_confidence_poster_gets_the_review_badge(settings: Settings) -> None:
    llm = ScriptedLlm(call(SUBMIT, **args(confidence=0.3)))
    async with committed() as world:
        done = await confirm(world, settings, llm)
        world.ids["__poster_low"] = done["opportunity_id"]
        found = await rows(
            "select needs_review, review_reasons from opportunities where id = %s",
            done["opportunity_id"],
        )
    assert found[0]["needs_review"] is True
    assert LOW_CONFIDENCE_REASON in found[0]["review_reasons"]


async def test_an_ambiguous_condition_puts_the_review_badge_on_the_opportunity(
    settings: Settings,
) -> None:
    """포스터에서 읽은 조건이 모호하면 상세에 '원문 확인 필요'가 붙는다."""
    vague = args(
        requirements=[
            {
                "clause_no": 1,
                "field": "other",
                "operator": "eq",
                "value_json": '{"text": "성적 우수자"}',
                "evidence_text": "국내 대학 재학생 및 휴학생",
                "is_ambiguous": True,
            }
        ]
    )
    llm = ScriptedLlm(call(SUBMIT, **vague))
    async with committed() as world:
        done = await confirm(world, settings, llm)
        world.ids["__poster_vague"] = done["opportunity_id"]
        found = await rows(
            "select needs_review, review_reasons, content_hash, raw_text from opportunities"
            " where id = %s",
            done["opportunity_id"],
        )
    (row,) = found
    assert row["needs_review"] is True
    assert row["review_reasons"] == [AMBIGUOUS_REASON]
    # 원문 해시는 옮겨 적은 글에서 만든다(나중에 같은 포스터를 다시 읽을 때 바뀜을 본다)
    assert row["content_hash"] == content_hash(row["raw_text"], ())


async def test_a_failed_run_cannot_be_confirmed(settings: Settings) -> None:
    """글자를 읽지 못한 실행으로는 등록할 수 없다."""
    async with committed() as world:
        store = FakeStorage()
        file_id = world.files["내 포스터"]
        store.objects[world.paths[file_id]] = POSTER_BYTES
        async with api(settings, ScriptedLlm("포스터가 흐려요"), store) as client:
            http = client(world.user)
            started = await http.post("/api/v1/posters/extract", json={"file_id": file_id})
            run_id = started.json()["run_id"]
            run = (await http.get(f"/api/v1/runs/{run_id}")).json()
            assert run["status"] == "failed"
            res = await http.post(
                "/api/v1/posters/confirm",
                json={"run_id": run_id, "draft": DRAFT_BODY},
            )
    assert res.status_code == 404


async def test_confirming_twice_leaves_one_opportunity(settings: Settings) -> None:
    llm = ScriptedLlm(call(SUBMIT, **args()), call(SUBMIT, **args()))
    async with committed() as world:
        first = await confirm(world, settings, llm)
        world.ids["__poster_1"] = first["opportunity_id"]
        again = await confirm(world, settings, llm)
        made = await rows(
            "select count(*) as n from opportunities where uploaded_by = %s", world.user
        )
    assert first["status"] == 201 and again["status"] == 200
    assert again["merged"] is True and again["opportunity_id"] == first["opportunity_id"]
    assert made[0]["n"] == 1


async def test_a_requirement_the_student_deleted_is_not_saved(settings: Settings) -> None:
    llm = ScriptedLlm(call(SUBMIT, **args()))
    async with committed() as world:
        done = await confirm(world, settings, llm, edit=lambda d: {**d, "requirements": []})
        world.ids["__poster_2"] = done["opportunity_id"]
        requirements = await rows(
            "select field from requirements where opportunity_id = %s", done["opportunity_id"]
        )
    assert requirements == []


async def test_a_requirement_the_student_rewrote_is_not_saved(settings: Settings) -> None:
    """화면에서 값을 지어내 보내도 판정 규칙이 되지 않는다."""
    llm = ScriptedLlm(call(SUBMIT, **args()))

    def tamper(draft: dict[str, Any]) -> dict[str, Any]:
        rewritten = {
            **draft["requirements"][0],
            "field": "gpa_total",
            "operator": "gte",
            "value": 0,
        }
        return {**draft, "requirements": [rewritten]}

    async with committed() as world:
        done = await confirm(world, settings, llm, edit=tamper)
        world.ids["__poster_3"] = done["opportunity_id"]
        requirements = await rows(
            "select field from requirements where opportunity_id = %s", done["opportunity_id"]
        )
    assert requirements == []


async def test_a_run_that_is_not_mine_cannot_be_confirmed(settings: Settings) -> None:
    llm = ScriptedLlm(call(SUBMIT, **args()))
    async with committed() as world:
        store = FakeStorage()
        file_id = world.files["내 포스터"]
        store.objects[world.paths[file_id]] = POSTER_BYTES
        async with api(settings, llm, store) as client:
            mine = client(world.user)
            started = await mine.post("/api/v1/posters/extract", json={"file_id": file_id})
            run_id = started.json()["run_id"]
            draft = (await mine.get(f"/api/v1/runs/{run_id}")).json()["result"]["draft"]
            res = await client(world.other).post(
                "/api/v1/posters/confirm", json={"run_id": run_id, "draft": draft}
            )
    assert res.status_code == 404


async def saved_output(run_id: str) -> dict[str, Any]:
    found = await rows(
        "select output from tool_calls where run_id = %s and tool_name = %s", run_id, SUBMIT
    )
    assert len(found) == 1
    return found[0]["output"]


async def rows(query: str, *params: Any) -> list[dict[str, Any]]:
    conn = await connect()
    try:
        return await (await conn.execute(query, params)).fetchall()
    finally:
        await conn.close()


async def test_a_draft_that_is_not_the_shape_we_know_is_not_shown(settings: Settings) -> None:
    """실행 기록이 지워졌거나 모양이 달라지면 결과를 주지 않는다(옛 실행을 다시 열어 봤을 때)."""
    llm = ScriptedLlm(call(SUBMIT, **args()))
    async with committed() as world:
        run = await extract(world, settings, llm)
        await execute(
            "update tool_calls set output = %s::jsonb where run_id = %s and tool_name = %s",
            '{"poster_text": "글자만 남았다"}',
            run["id"],
            SUBMIT,
        )
        async with api(settings, llm, FakeStorage()) as client:
            again = (await client(world.user).get(f"/api/v1/runs/{run['id']}")).json()
    assert again["status"] == "succeeded" and again["result"] is None


async def execute(query: str, *params: Any) -> None:
    conn = await connect()
    try:
        await conn.execute(query, params)
        await conn.commit()
    finally:
        await conn.close()
