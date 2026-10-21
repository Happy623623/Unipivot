"""강의자료 요약 통합 테스트(F-15 축소판): 라우터 → 뒤에서 도는 실행 → 저장소·모델 → DB → `GET /runs/{id}`.

뒤에서 도는 일은 자기 연결(풀)을 열어 다른 연결이 쓴 행을 봐야 한다. 그래서 사용자·과목·파일을 커밋하고
끝나면 지운다. 일은 InlineRunner로 응답 전에 끝까지 돌린다. 모델은 가짜(ScriptedLlm), 저장소도 가짜다.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.background import InlineRunner
from app.config import Settings, get_settings
from app.db import create_pools
from app.llm.deps import get_llm
from app.main import create_app
from app.repositories.files import FileRepository
from app.repositories.materials import MaterialRepository
from app.uploads.storage import StorageError, StorageMissing, get_storage
from tests import samples
from tests.conftest import make_token
from tests.db_world import DATABASE_URL, connect, make_user
from tests.llm_fakes import ScriptedLlm

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

LECTURE = ["8주차 고유값과 고유벡터", "Eigenvalue: Av = λv 를 만족하는 λ", "대각화와 응용"]
PDF = samples.pdf(LECTURE)
SUMMARY = "## 전체 요약\n고유값을 다룬다.\n## 핵심 개념\n- 고유값\n## 시험 대비 포인트\n- 정의"


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
            raise StorageMissing("그 파일이 없어요")
        return self.objects[path]


@dataclass
class Fixture:
    user: str
    other: str
    courses: dict[str, str] = field(default_factory=dict)
    items: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    paths: dict[str, str] = field(default_factory=dict)


@asynccontextmanager
async def committed() -> AsyncIterator[Fixture]:
    """사용자 둘, 과목 둘, 주차 항목 둘, 파일 여럿을 커밋한다. 끝나면 지운다."""
    setup = await connect()
    user = await make_user(setup)
    other = await make_user(setup)
    world = Fixture(user, other)
    canvas = 9_800_000 + int(uuid4().int % 90_000)

    async def add_course(name: str, owner: str, canvas_id: int) -> None:
        row = await (
            await setup.execute(
                "insert into lms_courses (user_id, canvas_course_id, name) values (%s, %s, %s)"
                " returning id::text as id",
                (owner, canvas_id, name),
            )
        ).fetchone()
        assert row is not None
        world.courses[name] = row["id"]

    async def add_item(name: str, canvas_id: int) -> None:
        row = await (
            await setup.execute(
                "insert into lms_module_items (canvas_course_id, canvas_item_id, module_name, title)"
                " values (%s, %s, '8주차', %s) returning id::text as id",
                (canvas_id, canvas_id * 10 + len(world.items), name),
            )
        ).fetchone()
        assert row is not None
        world.items[name] = row["id"]

    async def add_file(
        name: str,
        owner: str,
        *,
        kind: str = "lecture_material",
        course: str | None = None,
        origin: str = "upload",
        pages: int | None = 3,
    ) -> None:
        file_id = str(uuid4())
        path = f"{owner}/{kind}/{file_id}.pdf"
        await setup.execute(
            "insert into files (id, user_id, kind, origin, external_ref, storage_path, mime_type,"
            " sha256, original_name, page_count, lms_course_id)"
            " values (%s, %s, %s, %s, %s, %s, 'application/pdf', %s, %s, %s, %s)",
            (
                file_id,
                owner,
                kind,
                origin,
                file_id if origin == "lms_attachment" else None,
                path,
                uuid4().hex * 2,
                f"{name}.pdf",
                pages,
                world.courses.get(course or ""),
            ),
        )
        world.files[name] = file_id
        world.paths[file_id] = path

    await add_course("202620HY23525_선형대수", user, canvas)
    await add_course("202620HY23599_남의과목", other, canvas + 1)
    await add_item("8주차 자료", canvas)
    await add_item("남의 주차 자료", canvas + 1)
    await add_file("08_eigen", user, course="202620HY23525_선형대수")
    await add_file("09_svd", user)
    await add_file("공지 첨부", user, origin="lms_attachment", pages=None)
    await add_file("남의 자료", other)
    await add_file("내 포스터", user, kind="poster")
    await setup.commit()  # 뒤에서 도는 일은 자기 연결로 본다. 커밋해야 보인다
    try:
        yield world
    finally:
        await setup.execute(
            "delete from lms_module_items where id = any(%s::uuid[])", (list(world.items.values()),)
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
            headers={"Authorization": f"Bearer {make_token(user_id)}"},
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


def stored(world: Fixture, *names: str, data: bytes = PDF) -> FakeStorage:
    storage = FakeStorage()
    for name in names:
        storage.objects[world.paths[world.files[name]]] = data
    return storage


async def material_row(file_id: str) -> dict[str, Any] | None:
    conn = await connect()
    try:
        return await (
            await conn.execute(
                "select status::text as status, over_limit, text_tokens, total_pages, page_start,"
                " page_end, agent_run_id::text as run_id, overall_summary"
                " from materials where file_id = %s",
                (file_id,),
            )
        ).fetchone()
    finally:
        await conn.close()


async def test_a_material_is_summarized_once_and_then_served_from_the_cache(
    settings: Settings,
) -> None:
    llm = ScriptedLlm(SUMMARY)
    async with committed() as world:
        file_id = world.files["08_eigen"]
        async with api(settings, llm, stored(world, "08_eigen")) as client:
            http = client(world.user)
            pending = (await http.get(f"/api/v1/materials/{file_id}")).json()
            started = await http.post("/api/v1/materials", json={"file_id": file_id})
            assert started.status_code == 202, started.text
            run_id = started.json()["run_id"]
            run = (await http.get(f"/api/v1/runs/{run_id}")).json()
            detail = (await http.get(f"/api/v1/materials/{file_id}")).json()
            again = await http.post("/api/v1/materials", json={"file_id": file_id})
            listed = (await http.get("/api/v1/materials")).json()

        assert (pending["status"], pending["overall_summary"], pending["total_pages"]) == (
            "pending",
            None,
            3,
        )
        assert run["status"] == "succeeded", run
        assert run["result"] == {
            "kind": "material_summary",
            "file_id": file_id,
            "overall_summary": SUMMARY,
        }
        assert [step["label"] for step in run["steps"]] == ["강의자료 글자 읽기", "전체 요약"]
        assert detail["status"] == "succeeded" and detail["overall_summary"] == SUMMARY
        assert detail["course"] == {
            "lms_course_id": world.courses["202620HY23525_선형대수"],
            "name": "선형대수",
        }
        assert detail["processed_range"] == {"start": 1, "end": 3}
        assert (detail["over_limit"], detail["run_id"]) == (False, run_id)
        # 같은 자료를 다시 요청하면 저장해 둔 요약(200). 모델은 한 번만 불렀다
        assert again.status_code == 200 and again.json()["overall_summary"] == SUMMARY
        assert len(llm.requests) == 1
        request = llm.requests[0]
        assert request.model == settings.summary_model == "gemini-3.5-flash-lite"
        assert request.turns[0].text.startswith("<material>")  # type: ignore[union-attr]
        assert "고유값과 고유벡터" in request.turns[0].text  # type: ignore[union-attr]
        assert [item["file_id"] for item in listed["items"]] == [file_id]

        conn = await connect()
        try:
            tools = await (
                await conn.execute(
                    "select tool_name, input, output from tool_calls where run_id = %s order by seq",
                    (run_id,),
                )
            ).fetchall()
            calls = await (
                await conn.execute("select model from llm_calls where run_id = %s", (run_id,))
            ).fetchall()
        finally:
            await conn.close()
        # 자료 본문은 기록에 남기지 않는다(파일 id와 크기만)
        assert [tool["input"] for tool in tools] == [{"file_id": file_id}, {"file_id": file_id}]
        assert "고유값" not in str([tool["output"] for tool in tools])
        assert tools[1]["output"]["saved"] is True
        assert [one["model"] for one in calls] == ["gemini-3.5-flash-lite"]


async def test_a_material_over_the_token_limit_is_refused_and_recorded(
    settings: Settings,
) -> None:
    llm = ScriptedLlm()
    tight = settings.model_copy(update={"material_max_tokens": 10})
    async with committed() as world:
        file_id = world.files["08_eigen"]
        async with api(tight, llm, stored(world, "08_eigen")) as client:
            http = client(world.user)
            refused = await http.post("/api/v1/materials", json={"file_id": file_id})
            detail = (await http.get(f"/api/v1/materials/{file_id}")).json()
        assert refused.status_code == 413
        error = refused.json()["error"]
        assert error["code"] == "MATERIAL_TOO_LONG"
        assert "나눠서 올려" in error["message"]
        assert error["details"]["total_pages"] == 3 and error["details"]["limit_tokens"] == 10
        assert error["details"]["text_tokens"] > 10
        assert (detail["status"], detail["over_limit"], detail["run_id"]) == ("failed", True, None)
        assert llm.requests == []  # 모델을 부르지 않는다
        row = await material_row(file_id)
        assert row is not None and row["text_tokens"] == error["details"]["text_tokens"]
        conn = await connect()
        try:
            runs = await (
                await conn.execute(
                    "select count(*) as n from agent_runs where user_id = %s", (world.user,)
                )
            ).fetchone()
        finally:
            await conn.close()
        assert runs == {"n": 0}  # 실행을 만들지 않는다


async def test_a_failed_summary_can_be_asked_again(settings: Settings) -> None:
    llm = ScriptedLlm("", SUMMARY)  # 처음엔 빈 답
    async with committed() as world:
        file_id = world.files["09_svd"]
        async with api(settings, llm, stored(world, "09_svd")) as client:
            http = client(world.user)
            first = (await http.post("/api/v1/materials", json={"file_id": file_id})).json()
            failed = (await http.get(f"/api/v1/runs/{first['run_id']}")).json()
            detail = (await http.get(f"/api/v1/materials/{file_id}")).json()
            second = await http.post("/api/v1/materials", json={"file_id": file_id})
            done = (await http.get(f"/api/v1/materials/{file_id}")).json()
        assert failed["status"] == "failed"
        assert failed["error"]["code"] == "LLM_ERROR"
        assert "다시 눌러" in failed["error"]["message"]
        assert detail["status"] == "failed" and detail["overall_summary"] is None
        assert second.status_code == 202 and second.json()["run_id"] != first["run_id"]
        assert done["status"] == "succeeded" and done["course"] is None  # 과목 없이 올린 자료


async def test_a_summary_still_running_is_not_started_twice_and_a_stopped_one_restarts(
    settings: Settings,
) -> None:
    llm = ScriptedLlm(SUMMARY)
    async with committed() as world:
        file_id = world.files["08_eigen"]
        conn = await connect()
        try:
            running = await (
                await conn.execute(
                    "insert into agent_runs (trigger_type, user_id, status)"
                    " values ('material_upload', %s, 'running') returning id::text as id",
                    (world.user,),
                )
            ).fetchone()
            assert running is not None
            await MaterialRepository(conn).start(
                file_id, run_id=running["id"], pages=3, text_tokens=40
            )
            await conn.commit()
            async with api(settings, llm, stored(world, "08_eigen")) as client:
                http = client(world.user)
                same = await http.post("/api/v1/materials", json={"file_id": file_id})
                assert (same.status_code, same.json()["run_id"]) == (202, running["id"])
                assert llm.requests == []
                runs = await (
                    await conn.execute(
                        "select count(*) as n from agent_runs where user_id = %s", (world.user,)
                    )
                ).fetchone()
                assert runs == {"n": 1}  # 새 실행을 만들지 않고 도는 실행을 알려 준다
                # 그 실행이 멈췄다(서버 재시작 등). 요약은 running으로 남았지만 실패로 보이고 다시 시작한다
                await conn.execute(
                    "update agent_runs set status = 'failed' where id = %s", (running["id"],)
                )
                await conn.commit()
                stopped = (await http.get(f"/api/v1/materials/{file_id}")).json()
                course = world.courses["202620HY23525_선형대수"]
                detail = (await http.get(f"/api/v1/lms/courses/{course}")).json()
                restarted = await http.post("/api/v1/materials", json={"file_id": file_id})
            assert stopped["status"] == "failed"
            # 과목 상세의 자료 목록도 같은 기준이다(멈춘 요약을 "요약 중"으로 두지 않는다)
            assert [(m["file_id"], m["status"]) for m in detail["materials"]] == [
                (file_id, "failed")
            ]
            assert restarted.status_code == 202 and restarted.json()["run_id"] != running["id"]
            assert len(llm.requests) == 1
        finally:
            await conn.close()


@pytest.mark.parametrize(
    "name",
    [
        "남의 자료",  # 남의 자료
        "내 포스터",  # 강의자료가 아니다
    ],
)
async def test_only_my_lecture_materials_can_be_summarized(settings: Settings, name: str) -> None:
    async with committed() as world:
        async with api(settings, ScriptedLlm(), stored(world, name)) as client:
            response = await client(world.user).post(
                "/api/v1/materials", json={"file_id": world.files[name]}
            )
            read = await client(world.user).get(f"/api/v1/materials/{world.files[name]}")
        assert (response.status_code, response.json()["error"]["code"]) == (404, "NOT_FOUND")
        assert read.status_code == 404


async def test_storage_and_format_problems_are_told_before_starting(settings: Settings) -> None:
    async with committed() as world:
        mine = world.files["08_eigen"]
        attachment = world.files["공지 첨부"]
        broken = stored(world, "08_eigen")
        broken.broken = True
        not_pdf = stored(world, "공지 첨부", data=samples.JPEG)
        async with api(settings, ScriptedLlm(), FakeStorage()) as client:
            gone = await client(world.user).post("/api/v1/materials", json={"file_id": mine})
        async with api(settings, ScriptedLlm(), broken) as client:
            down = await client(world.user).post("/api/v1/materials", json={"file_id": mine})
        async with api(settings, ScriptedLlm(), not_pdf) as client:
            image = await client(world.user).post("/api/v1/materials", json={"file_id": attachment})
        scanned = stored(world, "08_eigen", data=samples.pdf([None, None]))
        async with api(settings, ScriptedLlm(), scanned) as client:
            blank = await client(world.user).post("/api/v1/materials", json={"file_id": mine})
        assert (gone.status_code, gone.json()["error"]["code"]) == (404, "NOT_FOUND")
        assert "다시 올려" in gone.json()["error"]["message"]
        assert (down.status_code, down.json()["error"]["code"]) == (502, "STORAGE_API_ERROR")
        assert (image.status_code, image.json()["error"]["code"]) == (400, "UNSUPPORTED_FILE_TYPE")
        assert (blank.status_code, blank.json()["error"]["code"]) == (400, "UNSUPPORTED_FILE_TYPE")
        assert await material_row(mine) is None  # 시작하지 않았다


async def test_an_attachment_without_a_page_count_gets_it_from_the_pdf(settings: Settings) -> None:
    """공지 첨부(F-54)는 저장할 때 쪽수를 세지 않았다. 요약할 때 PDF에서 센다."""
    async with committed() as world:
        attachment = world.files["공지 첨부"]
        async with api(settings, ScriptedLlm(SUMMARY), stored(world, "공지 첨부")) as client:
            started = await client(world.user).post(
                "/api/v1/materials", json={"file_id": attachment}
            )
            detail = (await client(world.user).get(f"/api/v1/materials/{attachment}")).json()
        assert started.status_code == 202
        assert (detail["total_pages"], detail["processed_range"]) == (3, {"start": 1, "end": 3})


async def test_the_list_filters_by_course_and_pages_with_a_cursor(settings: Settings) -> None:
    async with committed() as world:
        names = ("08_eigen", "09_svd")
        async with api(settings, ScriptedLlm(SUMMARY, SUMMARY), stored(world, *names)) as client:
            http = client(world.user)
            for name in names:
                await http.post("/api/v1/materials", json={"file_id": world.files[name]})
            course = world.courses["202620HY23525_선형대수"]
            first = (await http.get("/api/v1/materials", params={"limit": 1})).json()
            second = (
                await http.get(
                    "/api/v1/materials", params={"limit": 1, "cursor": first["next_cursor"]}
                )
            ).json()
            by_course = (
                await http.get("/api/v1/materials", params={"lms_course_id": course})
            ).json()
            others = (await client(world.other).get("/api/v1/materials")).json()
            bad = await http.get("/api/v1/materials", params={"cursor": "망가짐"})
        assert [item["file_id"] for item in first["items"] + second["items"]] == [
            world.files["09_svd"],  # 최신순
            world.files["08_eigen"],
        ]
        assert second["next_cursor"] is None
        assert [item["file_id"] for item in by_course["items"]] == [world.files["08_eigen"]]
        assert others["items"] == []
        assert bad.status_code == 422


async def test_a_summary_from_an_older_run_does_not_overwrite_a_newer_one() -> None:
    async with committed() as world:
        file_id = world.files["08_eigen"]
        conn = await connect()
        try:
            # 앞 실행은 멈춘 것으로 본다(10분 전에 시작) — 그래야 뒤 실행이 이어받는다
            runs = [
                await new_run(conn, world.user, started_ago="10 minutes"),
                await new_run(conn, world.user),
            ]
            repo = MaterialRepository(conn)
            await repo.start(file_id, run_id=runs[0], pages=3, text_tokens=40)
            await repo.start(file_id, run_id=runs[1], pages=3, text_tokens=40)
            assert await repo.save_summary(file_id, run_id=runs[0], summary="옛 요약") is False
            await repo.fail(file_id, run_id=runs[0])  # 다른 실행이 이어받았으니 그대로 둔다
            row = await material_row_in(conn, file_id)
            assert (row["status"], row["run_id"]) == ("running", runs[1])
            assert await repo.save_summary(file_id, run_id=runs[1], summary="새 요약") is True
        finally:
            await conn.rollback()
            await conn.close()


async def material_row_in(conn: Any, file_id: str) -> dict[str, Any]:
    row = await (
        await conn.execute(
            "select status::text as status, agent_run_id::text as run_id from materials"
            " where file_id = %s",
            (file_id,),
        )
    ).fetchone()
    assert row is not None
    return row


async def test_a_material_is_placed_only_in_my_course_or_module_item() -> None:
    async with committed() as world:
        conn = await connect()
        try:
            repo = FileRepository(conn)
            mine = world.courses["202620HY23525_선형대수"]
            item = world.items["8주차 자료"]
            place = repo.material_place
            assert await place(world.user, course_id=None, module_item_id=None) == (None, None)
            assert await place(world.user, course_id=mine, module_item_id=None) == (mine, None)
            assert await place(world.user, course_id=None, module_item_id=item) == (mine, item)
            assert await place(world.user, course_id=mine, module_item_id=item) == (mine, item)
            theirs = world.courses["202620HY23599_남의과목"]
            assert await place(world.user, course_id=theirs, module_item_id=None) is None
            other_item = world.items["남의 주차 자료"]
            assert await place(world.user, course_id=None, module_item_id=other_item) is None
            assert await place(world.user, course_id=theirs, module_item_id=item) is None
        finally:
            await conn.close()


async def new_run(conn: Any, user: str, *, started_ago: str = "0 minutes") -> str:
    row = await (
        await conn.execute(
            "insert into agent_runs (trigger_type, user_id, status, started_at)"
            " values ('material_upload', %s, 'running', now() - %s::interval)"
            " returning id::text as id",
            (user, started_ago),
        )
    ).fetchone()
    assert row is not None
    return row["id"]


async def test_a_run_left_running_too_long_counts_as_stopped(settings: Settings) -> None:
    """서버를 끄는 사이 끊긴 실행은 running으로 남는다. 5분이 지나면 멈춘 것으로 보고 다시 요약하며 닫는다."""
    llm = ScriptedLlm(SUMMARY)
    async with committed() as world:
        file_id = world.files["08_eigen"]
        conn = await connect()
        try:
            dead = await new_run(conn, world.user, started_ago="6 minutes")
            await MaterialRepository(conn).start(file_id, run_id=dead, pages=3, text_tokens=40)
            await conn.commit()
            async with api(settings, llm, stored(world, "08_eigen")) as client:
                http = client(world.user)
                before = (await http.get(f"/api/v1/materials/{file_id}")).json()
                course = world.courses["202620HY23525_선형대수"]
                listed = (await http.get(f"/api/v1/lms/courses/{course}")).json()
                restarted = await http.post("/api/v1/materials", json={"file_id": file_id})
                after = (await http.get(f"/api/v1/materials/{file_id}")).json()
            closed = await (
                await conn.execute(
                    "select status::text as s from agent_runs where id = %s", (dead,)
                )
            ).fetchone()
        finally:
            await conn.close()
        assert before["status"] == "failed"
        assert [m["status"] for m in listed["materials"]] == ["failed"]
        assert restarted.status_code == 202 and restarted.json()["run_id"] != dead
        assert after["status"] == "succeeded"
        assert closed == {"s": "failed"}  # 멈춘 실행을 닫았다(running으로 남지 않는다)


async def test_a_second_start_while_one_runs_keeps_the_first() -> None:
    """두 탭에서 동시에 눌러도 요약 실행은 하나다 — 늦은 쪽은 먼저 시작한 실행의 id를 받는다."""
    async with committed() as world:
        file_id = world.files["08_eigen"]
        conn = await connect()
        try:
            first, second = await new_run(conn, world.user), await new_run(conn, world.user)
            repo = MaterialRepository(conn)
            assert await repo.start(file_id, run_id=first, pages=3, text_tokens=40) == first
            assert await repo.start(file_id, run_id=second, pages=3, text_tokens=40) == first
            dead = await new_run(conn, world.user, started_ago="10 minutes")
            other = world.files["09_svd"]
            await repo.start(other, run_id=dead, pages=3, text_tokens=40)
            assert await repo.start(other, run_id=second, pages=3, text_tokens=40) == second
        finally:
            await conn.rollback()
            await conn.close()


async def test_a_superseded_run_has_no_result_and_a_slow_model_times_out(
    settings: Settings,
) -> None:
    def slow(_request: Any) -> str:
        raise TimeoutError

    async with committed() as world:
        file_id = world.files["08_eigen"]
        async with api(settings, ScriptedLlm(slow), stored(world, "08_eigen")) as client:
            http = client(world.user)
            started = (await http.post("/api/v1/materials", json={"file_id": file_id})).json()
            run = (await http.get(f"/api/v1/runs/{started['run_id']}")).json()
        assert run["status"] == "failed" and run["error"]["code"] == "LLM_TIMEOUT"
        assert run["result"] is None
        async with api(settings, ScriptedLlm(SUMMARY), stored(world, "08_eigen")) as client:
            http = client(world.user)
            again = (await http.post("/api/v1/materials", json={"file_id": file_id})).json()
            done = (await http.get(f"/api/v1/runs/{again['run_id']}")).json()
            old = (await http.get(f"/api/v1/runs/{started['run_id']}")).json()
        assert done["result"]["overall_summary"] == SUMMARY
        assert old["result"] is None  # 지난 실행의 결과는 이제 그 실행의 요약이 아니다


async def test_without_a_model_no_run_is_started(settings: Settings) -> None:
    async with committed() as world:
        file_id = world.files["08_eigen"]
        async with api(settings, None, stored(world, "08_eigen")) as client:
            response = await client(world.user).post("/api/v1/materials", json={"file_id": file_id})
        assert (response.status_code, response.json()["error"]["code"]) == (502, "LLM_ERROR")
        conn = await connect()
        try:
            runs = await (
                await conn.execute(
                    "select count(*) as n from agent_runs where user_id = %s", (world.user,)
                )
            ).fetchone()
        finally:
            await conn.close()
        assert runs == {"n": 0}


async def test_text_cut_at_the_character_cap_counts_as_too_long(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """글자 상한에서 잘린 글로 요약하지 않는다(어림 토큰이 상한 안이어도)."""
    monkeypatch.setattr("app.materials.service.TEXT_MAX_CHARS", 20)
    async with committed() as world:
        file_id = world.files["08_eigen"]
        async with api(settings, ScriptedLlm(), stored(world, "08_eigen")) as client:
            response = await client(world.user).post("/api/v1/materials", json={"file_id": file_id})
        assert (response.status_code, response.json()["error"]["code"]) == (
            413,
            "MATERIAL_TOO_LONG",
        )


async def test_an_attachment_past_the_page_cap_is_refused(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """공지 첨부는 올릴 때 쪽수를 안 봤다. 요약할 때 본다."""
    monkeypatch.setattr("app.uploads.LECTURE_MAX_PAGES", 2)
    async with committed() as world:
        attachment = world.files["공지 첨부"]
        async with api(settings, ScriptedLlm(), stored(world, "공지 첨부")) as client:
            response = await client(world.user).post(
                "/api/v1/materials", json={"file_id": attachment}
            )
        assert (response.status_code, response.json()["error"]["code"]) == (
            413,
            "PAGE_LIMIT_EXCEEDED",
        )


async def test_attaching_fills_only_an_empty_place() -> None:
    async with committed() as world:
        conn = await connect()
        try:
            repo = FileRepository(conn)
            course = world.courses["202620HY23525_선형대수"]
            item = world.items["8주차 자료"]
            empty, placed = world.files["09_svd"], world.files["08_eigen"]
            await repo.attach_place(world.user, empty, course_id=course, module_item_id=item)
            await repo.attach_place(world.user, placed, course_id=None, module_item_id=item)
            await repo.attach_place(world.other, empty, course_id=None, module_item_id=None)
            rows = await (
                await conn.execute(
                    "select id::text as id, lms_course_id::text as c, lms_module_item_id::text as i"
                    " from files where id = any(%s::uuid[]) order by original_name",
                    ([placed, empty],),
                )
            ).fetchall()
        finally:
            await conn.rollback()
            await conn.close()
        assert [(r["c"], r["i"]) for r in rows] == [(course, item), (course, item)]
