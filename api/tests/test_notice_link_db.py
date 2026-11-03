"""학교 공지 링크 가져오기(B안) 통합 테스트: POST /notices/link → 뒤에서 도는 실행 → DB → GET /runs/{id}.

뒤에서 도는 일은 자기 연결(풀)을 열어 다른 연결이 쓴 행을 봐야 한다. 그래서 사용자·공고를 커밋하고 끝나면 지운다.
일은 InlineRunner로 응답 전에 끝까지 돌린다(동시에 붙이는 시험은 TaskRunner로 같이 돌린다). 모델은 가짜
(ScriptedLlm), 학교 사이트도 가짜(FakeSchool)다. 요청 간격(1초)은 0으로 바꿔 둔다 — 간격은
tests/test_crawl_link.py가 본다. 요건 추출 실행에는 이 파일의 시나리오 표시(TAG)를 붙여 끝나면 그것만 지운다.
"""

import asyncio
import random
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest

from app.background import InlineRunner, TaskRunner
from app.config import Settings, get_settings
from app.crawl.hanyang import BOARD_URL
from app.crawl.importer import ImportOptions, ensure_source
from app.crawl.link import FILES_FAILED, LinkGate
from app.crawl.service import (
    DAILY_LINK_LIMIT,
    IMPORTS_AT_ONCE,
    OPTIONS,
    SEOUL,
    UNJUDGED,
    LinkDesk,
    get_link_options,
    get_school_transport,
)
from app.db import create_pools
from app.eligibility import KST
from app.extraction.prompt import READ_TEXT, SUBMIT
from app.llm import ToolResultTurn
from app.llm.deps import get_llm
from app.main import create_app
from app.repositories.runs import FAILED_MESSAGES
from app.uploads import day_start
from tests import hanyang_pages, samples
from tests.conftest import make_token
from tests.db_world import DATABASE_URL, connect, make_user
from tests.hanyang_pages import POSTER
from tests.llm_fakes import ScriptedLlm, call
from tests.school_fakes import SITE, FakeSchool, download, permalink, view_link

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

TAG = f"test-notice-link-{uuid.uuid4().hex[:8]}"  # 이 시험이 만든 요건 추출 실행(agent_runs.scenario_code)
GUIDE = samples.hwpx(samples.hp("가. 직전 학기 평점평균 3.0 이상인 재학생"))
IMAGE = "/documents/20122/0/poster.jpg/0f1e-2d3c?t=1759"
TODAY = datetime.now(KST).date()
# 게시일은 오늘, 마감은 30일 뒤 18:00. 날짜를 박아 두면 그날이 지나 깨진다(추출이 게시일과 먼 마감을 버린다)
POSTED = f"{TODAY.year}. {TODAY.month}. {TODAY.day}"
DEADLINE = f"{(TODAY + timedelta(days=30)).isoformat()}T18:00"
STEPS = ["공지 페이지 읽기", "첨부 파일 받기", "AI로 지원 자격 정리"]


def read_and_submit() -> list[Any]:
    """첨부 1(선발요강)을 읽고 제출한다. 근거 문장이 읽은 원문에 있어야 제출이 통과한다."""
    return [
        call(READ_TEXT, attachment_no=1, reason="자격이 선발요강에 있어서 읽음"),
        call(
            SUBMIT,
            requirements=[
                {
                    "clause_no": 1,
                    "field": "gpa_last_semester",
                    "operator": "gte",
                    "value_json": "3.0",
                    "evidence_text": "직전 학기 평점평균 3.0 이상",
                    "is_ambiguous": False,
                }
            ],
            documents=[],
            deadline=DEADLINE,
            confidence=0.9,
            needs_review=False,
        ),
    ]


def no_requirements() -> Any:
    return call(SUBMIT, requirements=[], documents=[], confidence=0.8, needs_review=False)


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """링크 가져오기를 연 서버. 여는 시각은 test_notice_link_api.py가 본다."""
    return settings.model_copy(update={"notice_link_opens_at": None})


class WatchedGate(LinkGate):
    """간격 0인 문지기. 몇 번 지나갔는지, 한 번에 몇이 안에 있었는지 적어 둔다."""

    def __init__(self) -> None:
        super().__init__(0)
        self.turns = 0
        self.inside = 0
        self.most = 0

    @asynccontextmanager
    async def turn(self) -> AsyncIterator[None]:
        async with super().turn():
            self.turns += 1
            self.inside += 1
            self.most = max(self.most, self.inside)
            try:
                yield
            finally:
                self.inside -= 1


class Answering(ScriptedLlm):
    """요청을 보고 답한다: 첨부를 아직 안 읽었으면 읽고, 읽었으면 제출한다(여러 실행이 같이 써도 된다).
    동시에 답하는 수를 적어 둔다."""

    def __init__(self) -> None:
        super().__init__()
        self.inside = 0
        self.most = 0

    async def generate(self, **kwargs: Any) -> Any:
        self.inside += 1
        self.most = max(self.most, self.inside)
        try:
            await asyncio.sleep(0.2)  # 다른 실행이 그사이 들어올 만큼
            read, submit = read_and_submit()
            done = any(isinstance(turn, ToolResultTurn) for turn in kwargs["turns"])
            self.replies = [submit if done else read]
            return await super().generate(**kwargs)
        finally:
            self.inside -= 1


@dataclass
class World:
    user: str
    other: str
    stranger: str  # 로그인만 하고 동의하지 않은 사람(프로필 없음)
    started: datetime
    entries: list[int] = field(default_factory=list)

    def entry(self) -> int:
        """이 시험만 쓰는 글 번호. 다른 시험·실제 공지와 겹치지 않게 크게 고른다."""
        number = random.randrange(9_000_000_000, 9_900_000_000)
        self.entries.append(number)
        return number


@asynccontextmanager
async def committed() -> AsyncIterator[World]:
    setup = await connect()
    user, other = await make_user(setup), await make_user(setup)
    stranger = str(uuid.uuid4())
    await setup.execute("insert into auth.users (id) values (%s)", (stranger,))
    row = await (await setup.execute("select now() as now")).fetchone()
    source = await (
        await setup.execute(
            "select id from sources where type = 'school_notice' and base_url = %s", (BOARD_URL,)
        )
    ).fetchone()
    await setup.commit()
    world = World(user, other, stranger, row["now"])
    try:
        yield world
    finally:
        await setup.rollback()
        ids = [str(number) for number in world.entries]
        await setup.execute(
            "delete from agent_runs where id in (select extraction_run_id from opportunities"
            " where source_type = 'school_notice' and external_id = any(%s))",
            (ids,),
        )
        await setup.execute(
            "delete from opportunities where source_type = 'school_notice' and external_id = any(%s)",
            (ids,),
        )
        # 학생의 실행, 그리고 공고를 남기지 못한 요건 추출 실행(이 파일의 표시)
        await setup.execute(
            "delete from agent_runs where user_id = any(%s::uuid[]) or scenario_code = %s",
            ([user, other], TAG),
        )
        if source is None:  # 이 시험이 출처 행을 만들었으면 지운다
            await setup.execute(
                "delete from sources s where s.type = 'school_notice' and s.base_url = %s"
                " and not exists (select 1 from opportunities o where o.source_id = s.id)",
                (BOARD_URL,),
            )
        await setup.execute(
            "delete from auth.users where id = any(%s::uuid[])", ([user, other, stranger],)
        )
        await setup.commit()
        await setup.close()


@dataclass
class Api:
    client: Callable[[str], httpx.AsyncClient]
    desk: LinkDesk
    app: Any

    @property
    def runner(self) -> Any:
        return self.app.state.runner

    @runner.setter
    def runner(self, value: Any) -> None:
        self.app.state.runner = value


@asynccontextmanager
async def api(
    settings: Settings, llm: Any, school: FakeSchool, options: ImportOptions = OPTIONS
) -> AsyncIterator[Api]:
    app = create_app(settings)
    pool, log_pool = create_pools(DATABASE_URL)
    await pool.open()
    await log_pool.open()
    app.state.pool, app.state.log_pool, app.state.runner = pool, log_pool, InlineRunner()
    app.state.link_desk = LinkDesk(gate=LinkGate(0))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_school_transport] = lambda: school.transport
    app.dependency_overrides[get_link_options] = lambda: replace(options, scenario=TAG)
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
        yield Api(client, app.state.link_desk, app)
    finally:
        for http in clients:
            await http.aclose()
        await pool.close()
        await log_pool.close()


def school_with(entry: int, *, campus: str = "ERICA", guide: bytes | None = GUIDE) -> FakeSchool:
    school = FakeSchool()
    poster = f'<p><img alt="포스터" src="{IMAGE}"></p>'
    school.notice(
        entry,
        hanyang_pages.detail(
            entry_id=entry,
            posted=POSTED,
            campus=campus,
            body=f"<p>신청 기간은 첨부를 보세요.</p>{poster}",
            files=("1. 선발요강.hwpx",),
        ),
    )
    if guide is not None:
        school.file(download("1. 선발요강.hwpx", "uuid-1"), guide)
    school.file(f"{SITE}{IMAGE}", POSTER, "image/jpeg")
    return school


async def link(http: httpx.AsyncClient, url: str) -> httpx.Response:
    return await http.post("/api/v1/notices/link", json={"url": url})


async def rows(sql: str, *params: object) -> list[dict[str, Any]]:
    conn = await connect()
    try:
        return await (await conn.execute(sql, params)).fetchall()
    finally:
        await conn.close()


async def notice_row(entry: int) -> dict[str, Any] | None:
    found = await rows(
        "select o.*, r.trigger_type as run_trigger, r.user_id as run_user from opportunities o"
        " left join agent_runs r on r.id = o.extraction_run_id"
        " where o.source_type = 'school_notice' and o.external_id = %s",
        str(entry),
    )
    return found[0] if found else None


async def test_a_linked_notice_becomes_a_school_notice_everyone_sees(settings: Settings) -> None:
    async with committed() as world:
        entry = world.entry()
        school = school_with(entry)
        async with api(settings, ScriptedLlm(*read_and_submit()), school) as server:
            http = server.client(world.user)
            started = await link(http, permalink(entry))
            assert started.status_code == 202, started.text
            body = started.json()
            assert body["status"] == "running" and body["opportunity_id"] is None
            assert started.headers["location"] == f"/api/v1/runs/{body['run_id']}"
            run = (await http.get(f"/api/v1/runs/{body['run_id']}")).json()
            assert run["status"] == "succeeded" and run["error"] is None
            assert [(step["label"], step["status"]) for step in run["steps"]] == [
                (label, "succeeded") for label in STEPS
            ]
            result = run["result"]
            assert result["kind"] == "notice_link" and result["status"] == "new"
            assert result["title"] == "2026학년도 2학기 ○○장학생 선발 안내"
            opportunity_id = result["opportunity_id"]
            asked = len(school.requests)
            assert asked == 3  # 페이지·첨부·본문 이미지

            # 다른 학생: 상세가 보이고(모든 학생), 같은 공지를 붙이면 학교에 묻지 않고 그 공고를 준다
            other = server.client(world.other)
            detail = await other.get(f"/api/v1/opportunities/{opportunity_id}")
            assert detail.status_code == 200, detail.text
            labels = [step["label"] for step in detail.json()["process"]["extraction"]]
            assert labels == ["첨부 '1. 선발요강.hwpx' 읽기", "지원 자격 정리"]  # 요건 추출 실행만
            again = await link(other, view_link(entry))
            assert again.status_code == 200
            assert again.json() == {
                "status": "existing",
                "run_id": None,
                "opportunity_id": opportunity_id,
            }
            assert len(school.requests) == asked

        row = await notice_row(entry)
        assert row is not None and str(row["id"]) == opportunity_id
        assert (row["category"], row["organizer"], row["original_url"]) == (
            "scholarship",
            "학생지원팀",
            permalink(entry),
        )
        # 요건 추출은 사용자 없는 실행(batch_crawl)이다. 누가 붙였는지는 학생의 실행에만 있다
        assert (row["run_trigger"], row["run_user"]) == ("batch_crawl", None)
        (user_run,) = await rows(
            "select r.user_id::text as user_id,"
            " (select count(*) from llm_calls l where l.run_id = r.id) as llm"
            " from agent_runs r where r.id = %s",
            body["run_id"],
        )
        assert (user_run["user_id"], user_run["llm"]) == (world.user, 0)
        inputs = await rows(
            "select tool_name, input from tool_calls where run_id = %s order by seq", body["run_id"]
        )
        assert inputs[0]["input"] == {"entry_id": str(entry), "url": permalink(entry)}
        attachments = await rows(
            "select seq, file_name, source_url, extract_error from opportunity_attachments"
            " where opportunity_id = %s order by seq",
            opportunity_id,
        )
        assert [(a["seq"], a["file_name"], a["extract_error"]) for a in attachments] == [
            (1, "1. 선발요강.hwpx", None),
            (2, "poster.jpg", None),
        ]
        assert attachments[0]["source_url"] == download("1. 선발요강.hwpx", "uuid-1")


async def test_seoul_notices_stop_before_files(settings: Settings) -> None:
    async with committed() as world:
        entry = world.entry()
        school = school_with(entry, campus="서울")
        async with api(settings, ScriptedLlm(), school) as server:
            http = server.client(world.user)
            started = await link(http, permalink(entry))
            assert started.status_code == 202
            run = (await http.get(f"/api/v1/runs/{started.json()['run_id']}")).json()
        assert run["status"] == "failed" and run["result"] is None
        assert run["error"] == {"code": "SEOUL_NOTICE", "message": SEOUL}
        assert [(s["label"], s["status"]) for s in run["steps"]] == [("공지 페이지 읽기", "failed")]
        assert school.asked() == [permalink(entry)]  # 첨부는 받지 않았다
        assert await notice_row(entry) is None


async def test_a_hidden_seoul_notice_is_not_read_again(settings: Settings) -> None:
    async with committed() as world:
        entry = world.entry()
        setup = await connect()
        try:
            source_id = await ensure_source(setup)
            await setup.execute(
                "insert into opportunities (source_id, source_type, external_id, category, title,"
                " status) values (%s, 'school_notice', %s, 'scholarship', '서울 공지', 'hidden')",
                (source_id, str(entry)),
            )
            await setup.commit()
        finally:
            await setup.close()
        school = school_with(entry)
        async with api(settings, ScriptedLlm(), school) as server:
            answer = await link(server.client(world.user), permalink(entry))
        assert answer.status_code == 422
        assert answer.json()["error"]["code"] == "SEOUL_NOTICE"
        assert school.requests == []


async def test_the_daily_limit_counts_new_reads_only(settings: Settings) -> None:
    async with committed() as world:
        known, fresh, other_fresh = world.entry(), world.entry(), world.entry()
        setup = await connect()
        try:
            midnight = day_start(datetime.now(KST))
            # 어제 1건 + 오늘 한도보다 하나 적게. 어제 것은 세지 않아서 하나 더 읽을 수 있다
            await setup.execute(
                "insert into agent_runs (user_id, trigger_type, status, started_at)"
                " values (%s, 'notice_link', 'failed', %s)",
                (world.user, midnight - timedelta(minutes=1)),
            )
            for _ in range(DAILY_LINK_LIMIT - 1):
                await setup.execute(
                    "insert into agent_runs (user_id, trigger_type, status)"
                    " values (%s, 'notice_link', 'failed')",
                    (world.user,),
                )
            await setup.commit()
        finally:
            await setup.close()
        school = school_with(known)
        async with api(settings, ScriptedLlm(*read_and_submit()), school) as server:
            http = server.client(world.user)
            last = await link(http, permalink(known))  # 오늘 열 번째
            assert last.status_code == 202, last.text
            blocked = await link(http, permalink(fresh))
            assert blocked.status_code == 429
            error = blocked.json()["error"]
            assert error["code"] == "DAILY_LINK_LIMIT"
            assert (
                error["message"] == "오늘 가져올 수 있는 10개를 다 썼어요. 내일 다시 붙여 주세요."
            )
            assert error["details"]["reset_at"] == (midnight + timedelta(days=1)).isoformat()
            existing = await link(http, permalink(known))  # 이미 가져온 공지는 한도와 상관없다
            assert existing.status_code == 200 and existing.json()["status"] == "existing"
            other = await link(server.client(world.other), permalink(other_fresh))
            assert other.status_code == 202  # 다른 학생은 따로 센다


async def test_a_notice_imported_before_reading_is_not_read_again(settings: Settings) -> None:
    """라우터가 본 뒤 실행이 돌기 전에 다른 학생이 같은 공지를 가져왔다 — 학교에 묻지 않고 그 공고를 준다."""
    held: list[Any] = []

    class Later(InlineRunner):
        async def start(self, job: Any) -> None:
            held.append(job)

    async with committed() as world:
        entry = world.entry()
        school = school_with(entry)
        async with api(settings, ScriptedLlm(*read_and_submit()), school) as server:
            server.runner = Later()
            http = server.client(world.user)
            started = await link(http, permalink(entry))
            assert started.status_code == 202 and len(held) == 1
            # 그새 다른 학생이 같은 공지를 가져온다(이번 일은 바로 돈다)
            server.runner = InlineRunner()
            first = await link(server.client(world.other), view_link(entry))
            assert first.status_code == 202
            (made,) = await rows(
                "select id::text as id from opportunities where source_type = 'school_notice'"
                " and external_id = %s",
                str(entry),
            )
            school.requests.clear()
            await held[0]  # 붙잡아 둔 첫 학생의 일을 이제 돌린다
            run = (await http.get(f"/api/v1/runs/{started.json()['run_id']}")).json()
        assert run["status"] == "succeeded", run
        assert run["result"] == {
            "kind": "notice_link",
            "opportunity_id": made["id"],
            "title": "2026학년도 2학기 ○○장학생 선발 안내",
            "status": "existing",
        }
        assert [step["label"] for step in run["steps"]] == ["공지 페이지 읽기"]
        assert school.asked() == []  # 읽기 전에 다시 봐서 페이지도 묻지 않았다


async def test_two_students_pasting_one_new_notice_read_it_once(settings: Settings) -> None:
    """같은 새 공지를 두 학생이 거의 같이 붙인다 — 한 실행이 읽고, 뒤의 실행은 기다렸다가 그 공고를 받는다."""
    async with committed() as world:
        entry = world.entry()
        school = school_with(entry)
        llm = Answering()
        async with api(settings, llm, school) as server:
            runner = TaskRunner()
            server.runner = runner
            first, second = server.client(world.user), server.client(world.other)
            started = [await link(first, permalink(entry)), await link(second, view_link(entry))]
            assert [answer.status_code for answer in started] == [202, 202]  # 실행은 학생마다
            await runner.drain(10)
            runs = [
                (await http.get(f"/api/v1/runs/{answer.json()['run_id']}")).json()
                for http, answer in zip((first, second), started, strict=True)
            ]
        assert [run["status"] for run in runs] == ["succeeded", "succeeded"], runs
        assert [run["result"]["status"] for run in runs] == ["new", "existing"]
        assert runs[0]["result"]["opportunity_id"] == runs[1]["result"]["opportunity_id"]
        assert len(school.requests) == 3  # 페이지·첨부·본문 이미지를 한 번씩
        assert len(llm.requests) == 2  # 요건 추출도 한 번(읽기·제출)
        assert server.desk._reading == {}  # 다 읽은 공지는 차례 표에서 빠진다


async def test_one_student_sending_twice_at_once_gets_one_run(settings: Settings) -> None:
    """같은 학생이 같은 공지를 동시에 두 번 보낸다(두 번 누름·탭 둘) — 실행은 하나다."""
    held: list[Any] = []

    class Later(InlineRunner):
        async def start(self, job: Any) -> None:
            held.append(job)

    async with committed() as world:
        entry = world.entry()
        async with api(settings, ScriptedLlm(), school_with(entry)) as server:
            server.runner = Later()
            http = server.client(world.user)
            answers = await asyncio.gather(
                link(http, permalink(entry)), link(http, view_link(entry))
            )
            for job in held:
                job.close()  # 돌리지 않는다
        codes = sorted(answer.status_code for answer in answers)
        assert codes == [200, 202]
        assert len({answer.json()["run_id"] for answer in answers}) == 1
        assert len(held) == 1
        mine = await rows(
            "select 1 from agent_runs where user_id = %s and trigger_type = 'notice_link'",
            world.user,
        )
        assert len(mine) == 1


async def test_sending_many_at_once_does_not_pass_the_daily_limit(settings: Settings) -> None:
    held: list[Any] = []

    class Later(InlineRunner):
        async def start(self, job: Any) -> None:
            held.append(job)

    async with committed() as world:
        entries = [world.entry() for _ in range(3)]
        setup = await connect()
        try:
            for _ in range(DAILY_LINK_LIMIT - 2):  # 두 건 남았다
                await setup.execute(
                    "insert into agent_runs (user_id, trigger_type, status)"
                    " values (%s, 'notice_link', 'failed')",
                    (world.user,),
                )
            await setup.commit()
        finally:
            await setup.close()
        async with api(settings, ScriptedLlm(), FakeSchool()) as server:
            server.runner = Later()
            http = server.client(world.user)
            answers = await asyncio.gather(*(link(http, permalink(entry)) for entry in entries))
            for job in held:
                job.close()
        assert sorted(answer.status_code for answer in answers) == [202, 202, 429]
        assert len(held) == 2


async def test_only_a_few_notices_are_read_and_sorted_at_once(settings: Settings) -> None:
    """첨부를 받아 요건까지 정리하는 실행은 IMPORTS_AT_ONCE개까지 같이 돈다(한 공지에서 60MB까지 쥔다)."""
    async with committed() as world:
        entries = [world.entry() for _ in range(IMPORTS_AT_ONCE + 1)]
        school = FakeSchool()
        for entry in entries:
            school.routes.update(school_with(entry).routes)
        llm = Answering()
        gate = WatchedGate()
        async with api(settings, llm, school) as server:
            server.desk.gate = gate  # 학교 서버 문지기는 앱에 하나다 — 실행이 여럿이어도 같이 쓴다
            runner = TaskRunner()
            server.runner = runner
            http = server.client(world.user)
            started = [await link(http, permalink(entry)) for entry in entries]
            assert [answer.status_code for answer in started] == [202] * len(entries)
            await runner.drain(10)
            runs = [
                (await http.get(f"/api/v1/runs/{answer.json()['run_id']}")).json()
                for answer in started
            ]
        assert [run["result"]["status"] for run in runs] == ["new"] * len(entries), runs
        assert llm.most == IMPORTS_AT_ONCE
        assert (gate.turns, gate.most) == (
            len(school.requests),
            1,
        )  # 모든 요청이 한 문지기를 한 번에 하나씩


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (
            404,
            "NOTICE_NOT_FOUND",
            "그 주소에서 공지를 찾지 못했어요. 지워졌거나 주소가 잘렸을 수 있어요.",
        ),
        (
            503,
            "NOTICE_FETCH_FAILED",
            "학교 사이트에서 공지를 읽지 못했어요. 잠시 후 다시 붙여 주세요.",
        ),
    ],
)
async def test_school_failures_are_shown_to_the_student(
    settings: Settings, status: int, code: str, message: str
) -> None:
    async with committed() as world:
        entry = world.entry()
        school = FakeSchool()
        school.answer(permalink(entry), status)
        async with api(settings, ScriptedLlm(), school) as server:
            http = server.client(world.user)
            started = await link(http, permalink(entry))
            run = (await http.get(f"/api/v1/runs/{started.json()['run_id']}")).json()
            assert server.desk.running == {}  # 끝난 실행은 표에서 빠진다
        assert run["status"] == "failed"
        assert run["error"] == {"code": code, "message": message}
        assert await notice_row(entry) is None


async def test_a_file_that_could_not_be_read_is_kept_for_review(settings: Settings) -> None:
    async with committed() as world:
        entry = world.entry()
        school = school_with(entry, campus="안함", guide=None)  # 캠퍼스 표시 없음도 가져온다
        school.answer(download("1. 선발요강.hwpx", "uuid-1"), 410)  # 지워진 파일(다시 해도 같다)
        async with api(settings, ScriptedLlm(no_requirements()), school) as server:
            http = server.client(world.user)
            started = await link(http, permalink(entry))
            run = (await http.get(f"/api/v1/runs/{started.json()['run_id']}")).json()
        assert run["status"] == "succeeded", run
        row = await notice_row(entry)
        assert row is not None and row["needs_review"] is True
        assert "가져오지 못해 읽지 않은 첨부: 1. 선발요강.hwpx" in row["review_reasons"]
        (failed,) = await rows(
            "select extract_error from opportunity_attachments where opportunity_id = %s and seq = 1",
            row["id"],
        )
        assert (
            failed["extract_error"] == "파일을 가져오지 못해 읽지 않았어요(받지 못했어요(HTTP 410))"
        )


async def test_a_school_that_cannot_send_files_now_leaves_no_notice(settings: Settings) -> None:
    """학교 서버가 잠시 첨부를 주지 못했다 — 공고를 넣지 않는다(넣으면 다시 붙여도 다시 읽지 않는다)."""
    async with committed() as world:
        entry = world.entry()
        school = school_with(entry)
        school.answer(download("1. 선발요강.hwpx", "uuid-1"), 503)
        async with api(settings, ScriptedLlm(), school) as server:
            http = server.client(world.user)
            started = await link(http, permalink(entry))
            run = (await http.get(f"/api/v1/runs/{started.json()['run_id']}")).json()
            school.routes.update(school_with(entry).routes)  # 학교가 다시 답한다
            server.app.dependency_overrides[get_llm] = lambda: ScriptedLlm(*read_and_submit())
            again = await link(http, permalink(entry))
            assert again.status_code == 202  # 다시 붙이면 다시 읽는다
            retried = (await http.get(f"/api/v1/runs/{again.json()['run_id']}")).json()
        assert run["status"] == "failed"
        assert run["error"] == {"code": "NOTICE_FETCH_FAILED", "message": FILES_FAILED}
        assert [s["status"] for s in run["steps"]] == ["succeeded", "failed"]
        assert retried["status"] == "succeeded" and retried["result"]["status"] == "new"


@pytest.mark.parametrize(
    ("failure", "code", "message"),
    [
        (RuntimeError("model down"), "INTERNAL_ERROR", FAILED_MESSAGES["notice_link"]),
        (
            TimeoutError(),
            "LLM_TIMEOUT",
            "지원 자격을 정리하는 데 너무 오래 걸렸어요. 잠시 후 다시 붙여 주세요.",
        ),
        (  # 실제 모델 클라이언트(google-genai, httpx)가 내는 시간 초과
            httpx.ReadTimeout("timed out"),
            "LLM_TIMEOUT",
            "지원 자격을 정리하는 데 너무 오래 걸렸어요. 잠시 후 다시 붙여 주세요.",
        ),
    ],
)
async def test_a_model_failure_leaves_no_notice(
    settings: Settings, failure: Exception, code: str, message: str
) -> None:
    def fail(_request: Any) -> Any:
        raise failure

    async with committed() as world:
        entry = world.entry()
        async with api(settings, ScriptedLlm(fail), school_with(entry)) as server:
            http = server.client(world.user)
            started = await link(http, permalink(entry))
            run = (await http.get(f"/api/v1/runs/{started.json()['run_id']}")).json()
        assert run["status"] == "failed"
        assert run["error"] == {"code": code, "message": message}
        assert [s["status"] for s in run["steps"]] == ["succeeded", "succeeded", "failed"]
        assert await notice_row(entry) is None  # 다음에 붙이면 다시 읽는다


async def test_a_slow_model_is_cut_off(settings: Settings) -> None:
    class Slow(ScriptedLlm):
        async def generate(self, **kwargs: Any) -> Any:
            await asyncio.sleep(5)
            return await super().generate(**kwargs)

    async with committed() as world:
        entry = world.entry()
        hurried = replace(OPTIONS, model_timeout=0.2)
        async with api(settings, Slow(*read_and_submit()), school_with(entry), hurried) as server:
            http = server.client(world.user)
            started = await link(http, permalink(entry))
            run = (await http.get(f"/api/v1/runs/{started.json()['run_id']}")).json()
        assert run["error"]["code"] == "LLM_TIMEOUT"
        assert await notice_row(entry) is None


async def test_a_notice_the_model_could_not_sort_is_not_kept(settings: Settings) -> None:
    """요건을 정리하지 못했으면(제출 없음) 넣지 않는다 — 넣으면 판정 불가로 남고 다시 붙여도 다시 읽지 않는다."""
    async with committed() as world:
        entry = world.entry()
        llm = ScriptedLlm("요건을 못 찾았어요", "그래도 못 찾았어요")  # 글로만 답한다
        async with api(settings, llm, school_with(entry)) as server:
            http = server.client(world.user)
            started = await link(http, permalink(entry))
            run = (await http.get(f"/api/v1/runs/{started.json()['run_id']}")).json()
        assert run["status"] == "failed"
        assert run["error"] == {"code": "LLM_ERROR", "message": UNJUDGED}
        assert [s["status"] for s in run["steps"]] == ["succeeded", "succeeded", "failed"]
        assert await notice_row(entry) is None
        extraction = await rows(
            "select status from agent_runs where scenario_code = %s and trigger_type = 'batch_crawl'",
            TAG,
        )
        assert len(extraction) == 1  # 요건 추출 실행 기록은 남는다(비용·원인을 본다)


async def test_without_a_model_nothing_starts(settings: Settings) -> None:
    async with committed() as world:
        entry = world.entry()
        school = school_with(entry)
        async with api(settings, None, school) as server:
            answer = await link(server.client(world.user), permalink(entry))
        assert answer.status_code == 502
        assert answer.json()["error"]["code"] == "LLM_ERROR"
        assert school.requests == []
        mine = await rows("select 1 from agent_runs where user_id = %s", world.user)
        assert mine == []  # 실행을 만들지 않아 하루 한도도 쓰지 않는다


async def test_the_same_notice_already_being_read_is_not_read_twice(settings: Settings) -> None:
    async with committed() as world:
        entry = world.entry()
        school = school_with(entry)
        async with api(settings, ScriptedLlm(), school) as server:
            server.desk.running[(world.user, str(entry))] = "4b9b4b16-0000-4000-8000-000000000000"
            again = await link(server.client(world.user), view_link(entry))
            assert again.status_code == 200
            assert again.json() == {
                "status": "running",
                "run_id": "4b9b4b16-0000-4000-8000-000000000000",
                "opportunity_id": None,
            }
            other = await link(
                server.client(world.other), view_link(entry)
            )  # 다른 학생은 자기 실행을 받는다(읽기는 차례로 — test_two_students_…)
            assert other.status_code == 202
        assert (
            len(
                await rows(
                    "select 1 from agent_runs where user_id = %s and trigger_type = 'notice_link'",
                    world.user,
                )
            )
            == 0
        )


async def test_links_are_checked_and_consent_comes_first(settings: Settings) -> None:
    async with committed() as world:
        school = FakeSchool()
        async with api(settings, ScriptedLlm(), school) as server:
            bad = await link(server.client(world.user), "https://example.com/notice/1")
            assert bad.status_code == 422
            assert bad.json()["error"]["details"]["fields"] == {
                "url": "한양대 공지사항(www.hanyang.ac.kr)의 글 주소만 가져올 수 있어요."
            }
            stranger = await link(server.client(world.stranger), permalink(world.entry()))
            assert stranger.status_code == 403
            assert stranger.json()["error"]["code"] == "CONSENT_REQUIRED"
            assert server.desk.running == {}
        assert school.requests == []
