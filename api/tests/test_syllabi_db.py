"""계획서 추출 통합 테스트(F-14): 라우터 → 뒤에서 도는 실행 → 저장소·모델 → DB → `GET /runs/{id}`.

뒤에서 도는 일은 자기 연결(풀)을 열어 다른 연결이 쓴 행을 봐야 한다. 그래서 사용자·과목·파일을
커밋하고 끝나면 지운다. 일은 InlineRunner로 응답 전에 끝까지 돌린다. 모델은 가짜(ScriptedLlm)이고
Supabase Storage도 가짜다. 계획서 PDF는 reportlab으로 만든다(tests/samples.pdf).
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
from app.eligibility import KST
from app.llm.deps import get_llm
from app.main import create_app
from app.repositories.syllabi import SyllabusRepository
from app.schemas.syllabi import EXTRACT_TOOL
from app.uploads.storage import StorageError, get_storage
from tests import samples
from tests.conftest import make_token
from tests.db_world import DATABASE_URL, connect, make_user
from tests.llm_fakes import ScriptedLlm, call

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

SYLLABUS_TEXT = """2026학년도 2학기 강의계획서
교과목명: 데이터베이스 (202620HY23525)

주차별 계획
8주차 10/20(화) 중간고사 10:30~12:00
15주차 12/08 팀 프로젝트 발표
16주차 12/15 기말고사 10:30~12:00
"""
PDF = samples.pdf([SYLLABUS_TEXT])
ITEMS = [
    {
        "item_type": "midterm",
        "title": "중간고사",
        "date": "2026-10-20",
        "time": "10:30",
        "evidence_text": "8주차 10/20(화) 중간고사 10:30~12:00",
    },
    {
        "item_type": "presentation",
        "title": "팀 프로젝트 발표",
        "date": "2026-12-08",
        "evidence_text": "15주차 12/08 팀 프로젝트 발표",
    },
]


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

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        self.objects[path] = data

    async def remove(self, path: str) -> None:
        self.objects.pop(path, None)


@dataclass
class Fixture:
    user: str
    other: str
    courses: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    paths: dict[str, str] = field(default_factory=dict)


@asynccontextmanager
async def committed() -> AsyncIterator[Fixture]:
    """사용자 둘, 과목 둘, 계획서 파일 둘을 커밋한다. 끝나면 지운다."""
    setup = await connect()
    user = await make_user(setup)
    other = await make_user(setup)
    world = Fixture(user, other)

    async def add_course(name: str, owner: str, canvas: int, *, active: bool = True) -> str:
        row = await (
            await setup.execute(
                "insert into lms_courses (user_id, canvas_course_id, name, is_active)"
                " values (%s, %s, %s, %s) returning id::text as id",
                (owner, canvas, name, active),
            )
        ).fetchone()
        assert row is not None
        world.courses[name] = row["id"]
        return row["id"]

    async def add_file(name: str, owner: str, *, kind: str = "syllabus") -> str:
        file_id = str(uuid4())
        path = f"{owner}/{kind}/{file_id}.pdf"
        await setup.execute(
            "insert into files (id, user_id, kind, origin, storage_path, mime_type, sha256)"
            " values (%s, %s, %s, 'upload', %s, 'application/pdf', %s)",
            (file_id, owner, kind, path, f"{abs(hash(name)):064d}"[:64]),
        )
        world.files[name] = file_id
        world.paths[file_id] = path
        return file_id

    await add_course("202620HY23525_데이터베이스", user, 9_900_101)
    await add_course("202620HY23534_기계학습", user, 9_900_102, active=False)
    await add_course("202620HY23599_남의과목", other, 9_900_103)
    await add_file("내 계획서", user)
    await add_file("남의 계획서", other)
    await add_file("내 포스터", user, kind="poster")
    await setup.commit()  # 뒤에서 도는 일은 자기 연결로 본다. 커밋해야 보인다
    try:
        yield world
    finally:
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


async def extract(
    world: Fixture,
    settings: Settings,
    llm: Any,
    *,
    body: dict[str, Any] | None = None,
    storage: FakeStorage | None = None,
    name: str = "내 계획서",
    user: str | None = None,
) -> dict[str, Any]:
    """`POST /syllabi/extract` → `GET /runs/{id}`. InlineRunner라 응답 전에 실행이 끝나 있다."""
    store = storage or FakeStorage()
    file_id = world.files[name]
    store.objects.setdefault(world.paths[file_id], PDF)
    async with api(settings, llm, store) as client:
        http = client(user or world.user)
        started = await http.post(
            "/api/v1/syllabi/extract", json={"file_id": file_id, **(body or {})}
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        return (await http.get(f"/api/v1/runs/{run_id}")).json()


async def test_a_syllabus_becomes_items_the_confirm_screen_can_show(settings: Settings) -> None:
    llm = ScriptedLlm(
        call(EXTRACT_TOOL, items=ITEMS, course_name="데이터베이스", semester="2026-2")
    )
    async with committed() as world:
        course = world.courses["202620HY23525_데이터베이스"]
        run = await extract(world, settings, llm, body={"lms_course_id": course})

    assert run["status"] == "succeeded", run
    result = run["result"]
    assert result["kind"] == "syllabus_extract"
    assert result["course_name"] == "데이터베이스"
    assert [(one["item_type"], one["title"]) for one in result["items"]] == [
        ("midterm", "중간고사"),
        ("presentation", "팀 프로젝트 발표"),
    ]
    assert result["items"][0]["starts_at"] == "2026-10-20T10:30:00+09:00"  # KST로 나간다
    assert result["items"][0]["is_confirmed"] is False  # 확인 화면에서 고른 것만 등록한다
    # 실행 기록: PDF 읽기 → 저장(명세 11장의 처리 과정). 화면에는 한국어 이름으로 보인다
    assert [step["tool"] for step in run["steps"]] == ["read_syllabus_pdf", "save_syllabus"]
    assert [step["label"] for step in run["steps"]] == ["계획서 글자 읽기", "시험·발표 일정 저장"]


async def test_the_model_sees_the_text_and_the_semester_of_that_course(
    settings: Settings,
) -> None:
    """연도 없는 날짜를 읽는 기준은 **과목명에서 센 학기 시작일**이다(2026-2 → 9/1)."""
    llm = ScriptedLlm(call(EXTRACT_TOOL, items=[]))
    async with committed() as world:
        course = world.courses["202620HY23525_데이터베이스"]
        await extract(world, settings, llm, body={"lms_course_id": course})

    sent = str(llm.requests[0].turns[0].text)
    assert "학기 범위(KST): 2026-09-01 ~ 2027-01-29" in sent
    assert "8주차 10/20(화) 중간고사" in sent  # PDF에서 뽑은 글자가 그대로 간다


async def test_items_are_saved_unconfirmed_and_only_once_per_course(settings: Settings) -> None:
    llm = ScriptedLlm(
        call(EXTRACT_TOOL, items=ITEMS, course_name="데이터베이스"),
        call(EXTRACT_TOOL, items=ITEMS[:1], course_name="데이터베이스"),
    )
    async with committed() as world:
        course = world.courses["202620HY23525_데이터베이스"]
        first = await extract(world, settings, llm, body={"lms_course_id": course})
        again = await extract(world, settings, llm, body={"lms_course_id": course, "replace": True})
        conn = await connect()
        try:
            rows = await (
                await conn.execute(
                    "select s.id::text as id, s.course_name, s.semester, count(i.id) as items"
                    " from syllabi s left join syllabus_items i on i.syllabus_id = s.id"
                    " where s.user_id = %s group by s.id, s.course_name, s.semester",
                    (world.user,),
                )
            ).fetchall()
            confirmed = await (
                await conn.execute(
                    "select bool_or(is_confirmed) as any_confirmed from syllabus_items i"
                    " join syllabi s on s.id = i.syllabus_id where s.user_id = %s",
                    (world.user,),
                )
            ).fetchone()
        finally:
            await conn.close()

    assert first["result"]["syllabus_id"] != again["result"]["syllabus_id"]
    assert len(rows) == 1  # 과목당 하나다. 다시 올리면 갈아 끼운다
    assert rows[0]["items"] == 1  # 옛 일정은 함께 지워졌다
    assert confirmed is not None and confirmed["any_confirmed"] is False


async def test_a_second_syllabus_for_the_same_course_needs_replace(settings: Settings) -> None:
    llm = ScriptedLlm(call(EXTRACT_TOOL, items=ITEMS))
    async with committed() as world:
        course = world.courses["202620HY23525_데이터베이스"]
        await extract(world, settings, llm, body={"lms_course_id": course})
        store = FakeStorage()
        file_id = world.files["내 계획서"]
        store.objects[world.paths[file_id]] = PDF
        async with api(settings, llm, store) as client:
            response = await client(world.user).post(
                "/api/v1/syllabi/extract", json={"file_id": file_id, "lms_course_id": course}
            )
    assert (response.status_code, response.json()["error"]["code"]) == (409, "SYLLABUS_EXISTS")


async def test_a_syllabus_without_a_course_is_saved_too(settings: Settings) -> None:
    """LMS를 연결하지 않은 학생도 올릴 수 있다. 과목 연결 없이 저장한다."""
    llm = ScriptedLlm(call(EXTRACT_TOOL, items=ITEMS[:1], course_name="데이터베이스"))
    async with committed() as world:
        run = await extract(world, settings, llm)
        conn = await connect()
        try:
            row = await (
                await conn.execute(
                    "select lms_course_id, course_name from syllabi where user_id = %s",
                    (world.user,),
                )
            ).fetchone()
        finally:
            await conn.close()
    assert run["status"] == "succeeded"
    assert row is not None and row["lms_course_id"] is None
    # 과목이 없으면 학기 범위는 올린 날 기준이다(그래도 10/20은 그 범위 안이다)
    assert run["result"]["items"][0]["title"] == "중간고사"


async def test_someone_elses_course_is_not_found(settings: Settings) -> None:
    llm = ScriptedLlm(call(EXTRACT_TOOL, items=[]))
    async with committed() as world:
        store = FakeStorage()
        file_id = world.files["내 계획서"]
        store.objects[world.paths[file_id]] = PDF
        async with api(settings, llm, store) as client:
            theirs = await client(world.user).post(
                "/api/v1/syllabi/extract",
                json={"file_id": file_id, "lms_course_id": world.courses["202620HY23599_남의과목"]},
            )
            dropped = await client(world.user).post(
                "/api/v1/syllabi/extract",
                json={"file_id": file_id, "lms_course_id": world.courses["202620HY23534_기계학습"]},
            )
    assert theirs.status_code == 404  # 남의 과목
    assert dropped.status_code == 404  # 수강을 뺀 과목


async def test_another_students_file_is_not_found(settings: Settings) -> None:
    llm = ScriptedLlm(call(EXTRACT_TOOL, items=[]))
    async with committed() as world:
        store = FakeStorage()
        async with api(settings, llm, store) as client:
            response = await client(world.user).post(
                "/api/v1/syllabi/extract", json={"file_id": world.files["남의 계획서"]}
            )
    assert (response.status_code, response.json()["error"]["code"]) == (404, "NOT_FOUND")


async def test_a_poster_is_not_a_syllabus(settings: Settings) -> None:
    """같은 사용자의 파일이어도 종류가 다르면 안 된다."""
    llm = ScriptedLlm(call(EXTRACT_TOOL, items=[]))
    async with committed() as world:
        store = FakeStorage()
        async with api(settings, llm, store) as client:
            response = await client(world.user).post(
                "/api/v1/syllabi/extract", json={"file_id": world.files["내 포스터"]}
            )
    assert response.status_code == 404


async def test_a_scanned_pdf_fails_with_a_clear_reason(settings: Settings) -> None:
    """글자가 없는 PDF(사진을 감싼 것)는 모델을 부르지 않고 끝낸다."""
    llm = ScriptedLlm(call(EXTRACT_TOOL, items=[]))
    async with committed() as world:
        store = FakeStorage()
        store.objects[world.paths[world.files["내 계획서"]]] = samples.pdf([None])
        run = await extract(world, settings, llm, storage=store)
    assert run["status"] == "failed"
    assert run["error"]["code"] == "SYLLABUS_READ_FAILED"
    assert llm.requests == []


async def test_a_broken_storage_fails_the_run(settings: Settings) -> None:
    llm = ScriptedLlm(call(EXTRACT_TOOL, items=[]))
    async with committed() as world:
        store = FakeStorage()
        store.broken = True
        run = await extract(world, settings, llm, storage=store)
    assert run["status"] == "failed" and run["error"]["code"] == "STORAGE_API_ERROR"


async def test_without_a_model_nothing_is_saved(settings: Settings) -> None:
    async with committed() as world:
        run = await extract(world, settings, None)
        conn = await connect()
        try:
            rows = await (
                await conn.execute(
                    "select count(*) as count from syllabi where user_id = %s", (world.user,)
                )
            ).fetchone()
        finally:
            await conn.close()
    assert run["status"] == "failed" and run["error"]["code"] == "LLM_ERROR"
    assert rows is not None and rows["count"] == 0


async def test_the_repository_reads_only_my_rows(settings: Settings) -> None:
    async with committed() as world:
        conn = await connect()
        try:
            repo = SyllabusRepository(conn)
            assert await repo.syllabus_file(world.user, world.files["내 계획서"]) is not None
            assert await repo.syllabus_file(world.user, world.files["남의 계획서"]) is None
            assert await repo.syllabus_file(world.other, world.files["내 계획서"]) is None
            mine = await repo.course(world.user, world.courses["202620HY23525_데이터베이스"])
            assert mine is not None
            assert (mine.short_name, mine.semester_start.isoformat()) == (
                "데이터베이스",
                "2026-09-01",
            )
            assert await repo.course(world.other, mine.id) is None
        finally:
            await conn.close()


async def test_the_model_cannot_invent_an_exam_date(settings: Settings) -> None:
    """근거 줄이 계획서에 없는 일정은 저장하지 않는다(DB까지 확인한다)."""
    llm = ScriptedLlm(
        call(
            EXTRACT_TOOL,
            items=[
                {
                    "item_type": "final",
                    "title": "기말고사",
                    "date": "2026-12-22",
                    "evidence_text": "계획서에 없는 줄",
                },
                ITEMS[0],
            ],
        )
    )
    async with committed() as world:
        run = await extract(world, settings, llm)
        conn = await connect()
        try:
            rows = await (
                await conn.execute(
                    "select i.title, i.starts_at from syllabus_items i"
                    " join syllabi s on s.id = i.syllabus_id where s.user_id = %s",
                    (world.user,),
                )
            ).fetchall()
        finally:
            await conn.close()
    assert [row["title"] for row in rows] == ["중간고사"]
    assert rows[0]["starts_at"].astimezone(KST).isoformat() == "2026-10-20T10:30:00+09:00"
    assert run["result"]["items"] == [
        {
            "id": run["result"]["items"][0]["id"],
            "item_type": "midterm",
            "title": "중간고사",
            "starts_at": "2026-10-20T10:30:00+09:00",
            "is_confirmed": False,
        }
    ]


async def test_nothing_found_keeps_the_old_syllabus(settings: Settings) -> None:
    """일정을 하나도 못 찾았으면 **먼저 올린 계획서를 그대로 둔다**.

    덮어쓰면 그 일정으로 만든 할 일·캘린더 기록까지 cascade로 사라진다.
    """
    llm = ScriptedLlm(
        call(EXTRACT_TOOL, items=ITEMS, course_name="데이터베이스"),
        call(EXTRACT_TOOL, items=[]),  # 두 번째 PDF에서는 아무것도 못 찾았다
    )
    async with committed() as world:
        course = world.courses["202620HY23525_데이터베이스"]
        first = await extract(world, settings, llm, body={"lms_course_id": course})
        again = await extract(world, settings, llm, body={"lms_course_id": course, "replace": True})
        conn = await connect()
        try:
            rows = await (
                await conn.execute(
                    "select s.id::text as id, count(i.id) as items from syllabi s"
                    " left join syllabus_items i on i.syllabus_id = s.id"
                    " where s.user_id = %s group by s.id",
                    (world.user,),
                )
            ).fetchall()
        finally:
            await conn.close()

    assert again["status"] == "failed"
    assert again["error"]["code"] == "SYLLABUS_READ_FAILED"
    assert "그대로 두었으니" in again["error"]["message"]
    assert [(row["id"], row["items"]) for row in rows] == [
        (first["result"]["syllabus_id"], len(ITEMS))
    ]


async def test_a_syllabus_with_no_items_is_still_saved_the_first_time(
    settings: Settings,
) -> None:
    """시험 일정이 안 적힌 계획서도 있다. 처음 올리는 것은 그대로 저장한다(일정 0개)."""
    llm = ScriptedLlm(call(EXTRACT_TOOL, items=[], course_name="데이터베이스"))
    async with committed() as world:
        course = world.courses["202620HY23525_데이터베이스"]
        run = await extract(world, settings, llm, body={"lms_course_id": course})
    assert run["status"] == "succeeded"
    assert run["result"]["items"] == []


async def test_a_model_without_the_tool_fails_the_run(settings: Settings) -> None:
    """모델이 도구를 안 부르면 학생에게 다시 올리라고 한다."""
    llm = ScriptedLlm("일정을 찾지 못했습니다")
    async with committed() as world:
        run = await extract(world, settings, llm)
    assert run["status"] == "failed"
    assert run["error"]["code"] == "SYLLABUS_READ_FAILED"
    assert "PDF로 저장해 올려 주세요" in run["error"]["message"]


async def test_a_model_that_breaks_is_an_llm_error(settings: Settings) -> None:
    class Broken:
        provider = "google"

        async def generate(self, **_: Any) -> Any:
            raise RuntimeError("모델이 터졌다")

    async with committed() as world:
        run = await extract(world, settings, Broken())
    assert run["status"] == "failed" and run["error"]["code"] == "LLM_ERROR"


async def test_a_model_that_is_too_slow_is_a_timeout(settings: Settings) -> None:
    class Slow:
        provider = "google"

        async def generate(self, **_: Any) -> Any:
            raise TimeoutError("늦었다")

    async with committed() as world:
        run = await extract(world, settings, Slow())
    assert run["status"] == "failed" and run["error"]["code"] == "LLM_TIMEOUT"


async def test_a_broken_pdf_in_the_storage_fails_with_a_clear_reason(
    settings: Settings,
) -> None:
    """업로드는 지나갔지만 저장소의 파일이 깨졌을 때(글자를 못 뽑는다)."""
    llm = ScriptedLlm(call(EXTRACT_TOOL, items=[]))
    async with committed() as world:
        store = FakeStorage()
        store.objects[world.paths[world.files["내 계획서"]]] = b"%PDF-1.4 broken"
        run = await extract(world, settings, llm, storage=store)
    assert run["status"] == "failed" and run["error"]["code"] == "SYLLABUS_READ_FAILED"
    assert llm.requests == []
