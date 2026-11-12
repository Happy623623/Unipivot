"""학교 공지 링크 가져오기 실행(B안, API 명세 6장 POST /notices/link · PRD F-10).

202와 run_id를 먼저 주고 뒤에서 돈다(포스터 추출과 같은 방식). 학생의 실행(trigger notice_link)에는 단계가
셋 남는다: 공지 페이지 읽기 → 첨부 파일 받기 → AI로 지원 자격 정리. 요건 추출은 A안 가져오기와 같은 함수
(import_content)가 마지막 단계 안에서 **학생 실행의 자식 실행**(trigger notice_link, 사용자 없음)으로 돌린다(실행
트리 O1). 공고는 모든 학생이 보는 학교 공지라 공고에서는 누가 가져왔는지와 잇지 않는다 — 공고 상세의 처리
과정은 그 자식 실행만 보여 주고, 자식에서 부모로 거슬러 올라가지 않는다. 누가 어느 공지를 붙였는지는 학생의
실행에만 남는다(하루 한도를 세고 오류를 찾는 데 쓴다). 자식의 비용은 학생의 실행에 더해진다.

- 같은 공지는 한 번만 읽는다: 이미 가져온 공지면 학교 서버에 묻지 않는다(라우터가 먼저 본다). 여러 학생이 같은
  공지를 붙이면 한 실행씩 읽고(LinkDesk.reading), 뒤의 실행은 읽기 전에 다시 봐서 앞 실행이 넣은 공고를 준다
- 서울캠퍼스 공지는 첨부를 받기 전에 멈춘다. 캠퍼스 표시가 없는 공지는 가져온다 — 학생이 ERICA 공지로 보고 붙였다
- 지워졌거나 너무 큰 첨부처럼 다시 해도 못 받는 파일은 실패로 남겨 원문 확인 필요로 넣는다(A안의 --allow-missing).
  학교 서버가 잠시 답하지 않았거나 요건을 정리하지 못했으면 공고를 넣지 않는다 — 다시 붙이면 다시 읽는다
- 모델은 MODEL_SECONDS초까지 기다린다. 첨부를 받아 정리하는 실행은 한 번에 IMPORTS_AT_ONCE개까지다(메모리)
- DB 연결은 짧게만 빌린다(확인·저장). 학교 서버나 모델을 기다리는 동안 쥐지 않는다
- 같은 학생이 같은 공지를 또 붙이면 돌고 있는 실행을 그대로 준다(명세 2장). 이것과 하루 한도는 한 요청씩 보고
  실행을 만든다(LinkDesk.admission). 배포 서버는 인스턴스가 하나라(--max-instances=1) 서버 안 잠금으로 충분하다

실패 이유는 ApiError로 남겨 학생에게 그대로 보인다(학교 사이트 오류·없는 글·서울 공지·모델 시간 초과).
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any

import httpx
import psycopg
from fastapi import Depends, Request
from psycopg import AsyncConnection

from app.agent_log import AgentRun, abandon_run, agent_run, start_run
from app.background import RunnerDep, TaskRunner
from app.config import Settings, get_settings
from app.crawl.hanyang import BOARD_URL, NoticePage
from app.crawl.importer import (
    SOURCE_TYPE,
    ImportOptions,
    ImportResult,
    ensure_source,
    import_content,
)
from app.crawl.link import (
    LinkedNotice,
    LinkError,
    LinkFetcher,
    LinkGate,
    NoticeLink,
    read_files,
    read_page,
    root_cause,
)
from app.errors import ApiError
from app.extraction.agent import ExtractionAgent
from app.extraction.models import Limits
from app.extraction.store import load_departments
from app.llm import LlmClient
from app.llm.deps import LlmDep
from app.schemas.notices import FILES_TOOL, IMPORT_TOOL, PAGE_TOOL

logger = logging.getLogger(__name__)
Connect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]

TRIGGER = "notice_link"
DAILY_LINK_LIMIT = 10  # 사용자당 KST 하루. 이미 가져온 공지를 다시 붙이는 것은 세지 않는다
MODEL_SECONDS = 120  # 요건 추출(모델)을 기다리는 초. 화면은 2분 30초까지 기다린다
IMPORTS_AT_ONCE = 2  # 첨부를 받아 정리하는 실행 수. 한 공지에서 60MB까지 쥔다(서버 메모리 1GiB)
# 학생이 붙인 공지는 학생이 ERICA 공지로 보고 고른 것이라 캠퍼스 표시가 없어도 가져온다. 못 받은 첨부는 실패로
# 둔다. 요건을 정리하지 못한 공지는 넣지 않는다 — 넣으면 다시 붙여도 다시 읽지 않는다(같은 공지는 한 번만)
OPTIONS = ImportOptions(
    include_unmarked=True, allow_missing=True, keep_unjudged=False, model_timeout=MODEL_SECONDS
)
SEOUL = "서울캠퍼스 공지라 가져오지 않아요."
NO_MODEL = "지금은 공지를 가져올 수 없어요. 잠시 후 다시 붙여 주세요."  # 모델 설정이 없다
SLOW = "지원 자격을 정리하는 데 너무 오래 걸렸어요. 잠시 후 다시 붙여 주세요."
UNJUDGED = "지원 자격을 정리하지 못했어요. 잠시 후 다시 붙여 주세요."
STOPPED = "공지를 가져오다 멈췄어요. 다시 붙여 주세요."


@dataclass(frozen=True)
class Existing:
    """이미 가져온 학교 공지."""

    opportunity_id: str  # 병합된 공고면 병합 대상
    hidden: bool  # 서울캠퍼스 공지로 바뀌어 숨긴 공고(가져오기만 숨긴다)
    title: str


class _PerLoop[T]:
    """이벤트 루프마다 하나씩 만드는 asyncio 잠금. 배포 서버는 루프가 하나지만 시험은 루프를 바꿔 가며 쓴다."""

    def __init__(self, make: Callable[[], T]) -> None:
        self._make = make
        self._made: tuple[asyncio.AbstractEventLoop, T] | None = None

    def get(self) -> T:
        loop = asyncio.get_running_loop()
        if self._made is None or self._made[0] is not loop:
            self._made = (loop, self._make())
        return self._made[1]


@dataclass
class _Reading:
    lock: asyncio.Lock
    users: int = 0  # 이 공지를 읽거나 기다리는 실행 수. 0이 되면 표에서 뺀다


@dataclass
class LinkDesk:
    """B안의 서버 상태(앱에 하나, app.state.link_desk): 학교 서버 간격, 돌고 있는 실행, 차례를 지키는 잠금."""

    gate: LinkGate = field(default_factory=LinkGate)
    running: dict[tuple[str, str], str] = field(default_factory=dict)  # (사용자, 글 번호) → run_id
    _admission: _PerLoop[asyncio.Lock] = field(default_factory=lambda: _PerLoop(asyncio.Lock))
    _heavy: _PerLoop[asyncio.Semaphore] = field(
        default_factory=lambda: _PerLoop(lambda: asyncio.Semaphore(IMPORTS_AT_ONCE))
    )
    _source: _PerLoop[asyncio.Lock] = field(default_factory=lambda: _PerLoop(asyncio.Lock))
    _reading: dict[str, _Reading] = field(default_factory=dict)  # 글 번호 → 읽는 차례

    def admission(self) -> asyncio.Lock:
        """새 실행을 받는 차례. 같은 공지를 읽는 중인지·하루 한도를 보고 실행을 만들기까지 한 요청씩."""
        return self._admission.get()

    def heavy(self) -> asyncio.Semaphore:
        """첨부를 받아 요건까지 정리하는 차례(IMPORTS_AT_ONCE개까지)."""
        return self._heavy.get()

    def source(self) -> asyncio.Lock:
        """출처 행을 처음 만들 때 둘이 만들지 않게."""
        return self._source.get()

    @asynccontextmanager
    async def reading(self, entry_id: str) -> AsyncIterator[None]:
        """같은 공지는 한 번에 한 실행만 읽는다(다른 학생이 붙여도). 뒤의 실행은 앞 실행이 끝날 때까지 기다린다."""
        slot = self._reading.get(entry_id)
        if slot is None:
            slot = self._reading[entry_id] = _Reading(asyncio.Lock())
        slot.users += 1
        try:
            async with slot.lock:
                yield
        finally:
            slot.users -= 1
            if slot.users == 0:
                del self._reading[entry_id]


@dataclass(frozen=True)
class LinkJob:
    run_id: str
    user_id: str
    link: NoticeLink


class NoticeLinkService:
    def __init__(
        self,
        *,
        transaction: Connect,
        log_connection: Connect,
        llm: LlmClient | None,
        settings: Settings,
        runner: TaskRunner,
        desk: LinkDesk,
        transport: httpx.AsyncBaseTransport | None = None,
        options: ImportOptions = OPTIONS,
    ) -> None:
        self.transaction = transaction  # 블록이 끝나면 커밋하는 연결(요청 트랜잭션과 따로)
        self.log_connection = log_connection  # autocommit 연결 공급자(agent_run이 쓸 때마다 빌린다)
        self.llm = llm
        self.settings = settings
        self.runner = runner
        self.desk = desk
        self.transport = transport  # 시험은 가짜 학교 서버를 넣는다
        self.options = options  # 시험은 시나리오 표시를 붙여 자기 요건 추출 실행만 지운다

    def has_model(self) -> bool:
        return self.llm is not None

    def admission(self) -> asyncio.Lock:
        return self.desk.admission()

    async def existing(self, entry_id: str) -> Existing | None:
        async with self.transaction() as conn:
            return await _existing(conn, entry_id)

    async def used_since(self, user_id: str, since: datetime) -> int:
        """since 뒤로 이 학생이 시작한 링크 실행 수(실패 포함)."""
        async with self.transaction() as conn:
            row = await (
                await conn.execute(
                    "select count(*) as used from agent_runs"
                    " where user_id = %s and trigger_type = %s and started_at >= %s",
                    (user_id, TRIGGER, since),
                )
            ).fetchone()
        return int(row["used"]) if row else 0

    def running(self, user_id: str, entry_id: str) -> str | None:
        return self.desk.running.get((user_id, entry_id))

    async def begin(self, user_id: str, link: NoticeLink) -> str:
        """실행 행을 만들고 일을 띄운다. run_id를 준다."""
        try:
            run_id = await start_run(self.log_connection, trigger=TRIGGER, user_id=user_id)
        except psycopg.errors.ForeignKeyViolation as exc:
            # 프로필이 없다(동의 전이거나 그새 탈퇴했다). 파일 올리기와 같은 답이다
            raise ApiError(
                403, "CONSENT_REQUIRED", "약관에 먼저 동의해 주세요.", {"consent": "terms_privacy"}
            ) from exc
        key = (user_id, link.entry_id)
        self.desk.running[key] = run_id
        work = self.execute(LinkJob(run_id, user_id, link))
        try:
            await self.runner.start(work)
        except Exception:
            work.close()
            self._release(key, run_id)
            await self._close(run_id)
            raise
        return run_id

    async def execute(self, job: LinkJob) -> None:
        try:
            async with agent_run(
                self.log_connection, trigger=TRIGGER, user_id=job.user_id, run_id=job.run_id
            ) as run:
                await self._run(run, job)
        except ApiError as exc:  # 학생에게 이유를 보인 실패(없는 글·서울 공지·학교 사이트 오류 등)
            logger.info(
                "공지 링크를 가져오지 못했어요: run %s, %s (%s)",
                job.run_id,
                exc.code,
                root_cause(exc),
            )
            await self._close(job.run_id)
        except Exception:
            logger.exception("공지 링크 실행 실패: run %s", job.run_id)
            await self._close(job.run_id)
        finally:
            self._release((job.user_id, job.link.entry_id), job.run_id)

    async def _run(self, run: AgentRun, job: LinkJob) -> None:
        # 모델 설정이 없는 서버는 라우터가 실행을 만들기 전에 막는다(has_model)
        async with self.desk.reading(job.link.entry_id):
            # 같은 공지를 다른 실행이 읽고 있었으면 끝날 때까지 기다렸다. 그새 들어왔으면 읽지 않는다
            found = await self.existing(job.link.entry_id)
            if found is not None:
                await self._found(run, job.link, found)
                return
            fetcher = LinkFetcher(self.desk.gate, transport=self.transport)
            try:
                page, page_url = await self._page(run, fetcher, job.link)
                async with self.desk.heavy():
                    notice = await self._files(run, fetcher, page, page_url)
                    await self._store(run, page, notice)
            finally:
                await fetcher.aclose()

    async def _found(self, run: AgentRun, link: NoticeLink, found: Existing) -> None:
        """읽기 전에 들어온 공지 — 학교 서버에 묻지 않고 그 공고를 결과로 남긴다."""
        async with run.tool(PAGE_TOOL, {"entry_id": link.entry_id, "url": link.url}) as call:
            if found.hidden:
                raise ApiError(422, "SEOUL_NOTICE", SEOUL)
            call.output = {
                "entry_id": link.entry_id,
                **_result(found.opportunity_id, "existing", found.title),
            }

    async def _page(
        self, run: AgentRun, fetcher: LinkFetcher, link: NoticeLink
    ) -> tuple[NoticePage, str]:
        async with run.tool(PAGE_TOOL, {"entry_id": link.entry_id, "url": link.url}) as call:
            try:
                page, page_url = await read_page(fetcher, link)
            except LinkError as exc:
                raise ApiError(exc.status, exc.code, exc.message) from exc
            call.output = _page_output(page)
            if page.scope == "seoul":
                raise ApiError(422, "SEOUL_NOTICE", SEOUL)
        return page, page_url

    async def _files(
        self, run: AgentRun, fetcher: LinkFetcher, page: NoticePage, page_url: str
    ) -> LinkedNotice:
        inputs = {"attachments": len(page.attachments), "images": len(page.image_sources)}
        async with run.tool(FILES_TOOL, inputs) as call:
            try:
                notice = await read_files(fetcher, page, page_url=page_url)
            except LinkError as exc:  # 학교 서버가 잠시 답하지 않았다. 공고를 넣지 않는다
                raise ApiError(exc.status, exc.code, exc.message) from exc
            call.output = _files_output(notice)
        return notice

    async def _store(self, run: AgentRun, page: NoticePage, notice: LinkedNotice) -> None:
        async with run.tool(IMPORT_TOOL, {"entry_id": page.entry_id}) as call:
            result = await self._import(run, notice)
            # 서울은 위에서 막았고 캠퍼스 표시 없음·못 받은 첨부는 OPTIONS로 받는다. 여기 오면 고칠 곳이 있다
            if result.opportunity_id is None:
                raise RuntimeError(f"공지를 넣지 못했어요: {result.status} {result.message}")
            call.output = {
                **_result(result.opportunity_id, result.status, page.title),
                "extraction_run_id": result.run_id,
            }

    async def _import(self, run: AgentRun, notice: LinkedNotice) -> ImportResult:
        assert self.llm is not None
        async with self.transaction() as conn:
            departments = await load_departments(conn)
        async with self.desk.source(), self.transaction() as conn:
            source_id = await ensure_source(conn)
        agent = ExtractionAgent(
            self.llm,
            model=self.settings.extraction_model,
            vision_model=self.settings.vision_model,
            departments=departments,
            limits=Limits(
                max_reads=self.settings.extraction_max_reads,
                max_tokens=self.settings.extraction_max_tokens,
            ),
        )
        try:
            result = await import_content(
                self.transaction,
                self.log_connection,
                source_id,
                notice,
                agent,
                self.options,
                parent=run,
            )
        except (TimeoutError, httpx.TimeoutException) as exc:
            # 기다린 시간(MODEL_SECONDS)을 넘었거나 모델 서버가 답하지 않았다(google-genai는 httpx 오류를 낸다)
            raise ApiError(502, "LLM_TIMEOUT", SLOW) from exc
        if result.unjudged and result.opportunity_id is None:  # 요건을 정리하지 못해 넣지 않았다
            raise ApiError(502, "LLM_ERROR", UNJUDGED)
        return result

    def _release(self, key: tuple[str, str], run_id: str) -> None:
        if self.desk.running.get(key) == run_id:
            del self.desk.running[key]

    async def _close(self, run_id: str, message: str = STOPPED) -> None:
        """아직 running인 실행을 실패로 닫는다(이미 닫혔으면 그대로 둔다)."""
        try:
            await abandon_run(self.log_connection, run_id, ApiError(500, "INTERNAL_ERROR", message))
        except Exception:
            logger.exception("공지 링크 실행을 닫지 못했어요: run %s", run_id)


async def _existing(conn: AsyncConnection, entry_id: str) -> Existing | None:
    row = await (
        await conn.execute(
            "select coalesce(o.merged_into_id, o.id)::text as id, o.status::text as status,"
            " o.title from opportunities o join sources s on s.id = o.source_id"
            " where s.type = %s and s.base_url = %s and o.external_id = %s"
            " order by o.created_at limit 1",
            (SOURCE_TYPE, BOARD_URL, entry_id),
        )
    ).fetchone()
    if row is None:
        return None
    return Existing(row["id"], row["status"] == "hidden", row["title"])


def _result(opportunity_id: str, status: str, title: str) -> dict[str, Any]:
    """결과 칸(GET /runs/{id}의 notice_link). 실행의 마지막 성공 단계에 둔다(repositories/runs.py)."""
    return {"opportunity_id": opportunity_id, "status": status, "title": title}


def _page_output(page: NoticePage) -> dict[str, Any]:
    return {
        "entry_id": page.entry_id,
        "title": page.title,
        "campus": page.campus,
        "category": page.category,
        "attachments": [link.name for link in page.attachments],
    }


def _files_output(notice: LinkedNotice) -> dict[str, Any]:
    return {
        "files": [
            {
                "seq": file.seq,
                "name": file.name,
                "body_image": file.body_image,
                "bytes": len(file.data) if file.data is not None else None,
                "problem": file.problem,
            }
            for file in notice.files
        ],
        "skipped_images": list(notice.skipped_images),
    }


def get_link_desk(request: Request) -> LinkDesk:
    state = request.app.state
    if getattr(state, "link_desk", None) is None:
        state.link_desk = LinkDesk()
    return state.link_desk


def get_school_transport() -> httpx.AsyncBaseTransport | None:
    """학교 서버로 가는 길. 시험은 가짜 서버(httpx.MockTransport)로 바꾼다."""
    return None


def get_link_options() -> ImportOptions:
    """요건 추출 옵션. 시험은 시나리오 표시를 붙여(자기 실행만 지운다) 바꾼다."""
    return OPTIONS


def get_notice_link_service(
    request: Request,
    llm: LlmDep,
    runner: RunnerDep,
    desk: Annotated[LinkDesk, Depends(get_link_desk)],
    transport: Annotated[httpx.AsyncBaseTransport | None, Depends(get_school_transport)],
    options: Annotated[ImportOptions, Depends(get_link_options)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NoticeLinkService:
    state = request.app.state
    pool, log_pool = getattr(state, "pool", None), getattr(state, "log_pool", None)
    if pool is None or log_pool is None:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    return NoticeLinkService(
        transaction=pool.connection,
        log_connection=log_pool.connection,
        llm=llm,
        settings=settings,
        runner=runner,
        desk=desk,
        transport=transport,
        options=options,
    )


NoticeLinkServiceDep = Annotated[NoticeLinkService, Depends(get_notice_link_service)]
