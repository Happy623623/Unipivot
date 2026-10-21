"""강의자료 요약 실행 (F-15 축소판, API 명세 8장 `POST /materials`).

차례: 저장소에서 PDF 받기 → 글자 뽑기 → 토큰 상한 보기(넘으면 413, 요청 안에서) → 202와 run_id →
뒤에서 모델 한 번 → 요약 저장. 모델을 기다리는 동안 DB 연결(요청 풀)을 쥐지 않는다.

상한을 넘는 자료는 실행을 만들지 않는다(모델을 부르지 않으니 기록할 실행도 없다). 대신 `materials.over_limit`에
남긴다(유료화 수요 근거). 같은 파일을 다시 요청하면 저장해 둔 요약을 그대로 준다(캐시). 같은 PDF를 다시 올리면
같은 파일이라(`POST /files`의 reused) 그 요약을 쓴다.
"""

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from psycopg import AsyncConnection

from app import uploads
from app.agent_log import abandon_run, agent_run, start_run
from app.background import RunnerDep, TaskRunner
from app.config import Settings, get_settings
from app.errors import ApiError
from app.llm import LlmClient
from app.llm.deps import LlmDep
from app.materials.summarize import TEXT_MAX_CHARS, SummaryError, estimate_tokens, summarize
from app.repositories.materials import MaterialFile, MaterialRepos, material_repos
from app.schemas.materials import READ_TOOL, SUMMARIZE_TOOL
from app.uploads import PDF, pdf_page_count, pdf_text, sniff
from app.uploads.storage import StorageDep, StorageError, StorageMissing, SupabaseStorage

logger = logging.getLogger(__name__)
Connect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
TRIGGER = "material_upload"
STORAGE_FAILED = "올린 강의자료를 불러오지 못했어요. 잠시 후 다시 눌러 주세요."
GONE = "저장한 파일이 없어졌어요. 강의자료를 다시 올려 주세요."
NOT_PDF = "PDF만 요약할 수 있어요. LMS에서 PDF로 받은 자료를 올려 주세요."
NO_TEXT = "PDF에서 글자를 찾지 못했어요. 스캔한 자료는 아직 요약할 수 없어요."
TOO_LONG = "자료가 길어서 한 번에 요약할 수 없어요. 요약할 부분만 PDF로 나눠서 올려 주세요."
SLOW = "요약하는 데 너무 오래 걸렸어요. 잠시 후 다시 눌러 주세요."
MODEL_FAILED = "요약하지 못했어요. 잠시 후 다시 눌러 주세요."
STOPPED = "강의자료를 요약하다 멈췄어요. 다시 눌러 주세요."
TAKEN = "다른 창에서 이미 이 자료를 요약하고 있어요. 그 결과를 기다려 주세요."
LONG_PAGES = "PDF는 {pages}쪽까지만 요약할 수 있어요. 요약할 부분만 PDF로 나눠서 올려 주세요."


@dataclass(frozen=True)
class MaterialJob:
    user_id: str
    file_id: str
    text: str  # 뽑은 글자(실행 기록에는 남기지 않는다 — 강의자료 본문이다)
    pages: int
    text_tokens: int


class MaterialService:
    def __init__(
        self,
        *,
        repos: MaterialRepos,
        log_connection: Connect,
        storage: SupabaseStorage,
        llm: LlmClient | None,
        model: str,
        max_tokens: int,
        runner: TaskRunner,
    ) -> None:
        self.repos = repos
        self.log_connection = log_connection
        self.storage = storage
        self.llm = llm
        self.model = model
        self.max_tokens = max_tokens
        self.runner = runner

    async def prepare(self, user_id: str, material: MaterialFile) -> MaterialJob:
        """PDF를 받아 글자를 뽑고 상한을 본다. 넘으면 남기고 413이다(요청 안에서 바로 답한다)."""
        try:
            data = await self.storage.download(material.storage_path)
        except StorageMissing as exc:
            raise ApiError(404, "NOT_FOUND", GONE) from exc
        except StorageError as exc:
            logger.warning("강의자료를 저장소에서 받지 못했어요: %s", exc)
            raise ApiError(502, "STORAGE_API_ERROR", STORAGE_FAILED) from exc
        if sniff(data) is not PDF:  # 공지 첨부로 저장된 자료는 형식을 가리지 않았다
            raise ApiError(400, "UNSUPPORTED_FILE_TYPE", NOT_PDF)
        # PDF 읽기는 CPU를 오래 쓴다(수백 쪽). 다른 요청·실행이 멈추지 않게 따로 돌린다
        pages = material.page_count or await asyncio.to_thread(pdf_page_count, data) or 1
        if pages > uploads.LECTURE_MAX_PAGES:  # 공지 첨부는 올릴 때 쪽수를 보지 않았다
            raise ApiError(
                413, "PAGE_LIMIT_EXCEEDED", LONG_PAGES.format(pages=uploads.LECTURE_MAX_PAGES)
            )
        text = await asyncio.to_thread(pdf_text, data, max_chars=TEXT_MAX_CHARS)
        if not text.strip():
            raise ApiError(400, "UNSUPPORTED_FILE_TYPE", NO_TEXT)
        tokens = estimate_tokens(text)
        if len(text) >= TEXT_MAX_CHARS:  # 글자 상한에서 잘렸다 — 잘린 글로 요약하지 않는다
            tokens = max(tokens, self.max_tokens + 1)
        if tokens > self.max_tokens:
            async with self.repos() as repo:
                await repo.too_long(material.file_id, pages=pages, text_tokens=tokens)
            raise ApiError(
                413,
                "MATERIAL_TOO_LONG",
                TOO_LONG,
                {"total_pages": pages, "text_tokens": tokens, "limit_tokens": self.max_tokens},
            )
        return MaterialJob(
            user_id=user_id, file_id=material.file_id, text=text, pages=pages, text_tokens=tokens
        )

    async def begin(self, job: MaterialJob, *, stopped_run: str | None = None) -> str:
        """실행 행을 만들고 요약을 running으로 둔 뒤 일을 띄운다. 지금 요약하는 실행의 run_id를 준다.

        그새 다른 요청이 먼저 시작했으면 이 실행은 닫고 그 실행의 run_id를 준다. 멈춘 지난 실행(stopped_run)은
        실패로 닫는다(실행 기록에 running으로 남지 않게).
        """
        if self.llm is None:  # 모델이 없는 서버 — 실행을 만들어 봐야 바로 실패한다
            raise ApiError(502, "LLM_ERROR", MODEL_FAILED)
        if stopped_run is not None:
            await self._close(stopped_run)
        run_id = await start_run(self.log_connection, trigger=TRIGGER, user_id=job.user_id)
        try:
            async with self.repos() as repo:
                current = await repo.start(
                    job.file_id, run_id=run_id, pages=job.pages, text_tokens=job.text_tokens
                )
        except Exception:
            await self._close(run_id)
            raise
        if current != run_id:
            await self._close(run_id, TAKEN)
            return current
        work = self.execute(job, run_id)
        try:
            await self.runner.start(work)
        except Exception:
            work.close()
            await self._fail(job.file_id, run_id)
            raise
        return run_id

    async def execute(self, job: MaterialJob, run_id: str) -> None:
        try:
            async with agent_run(
                self.log_connection, trigger=TRIGGER, user_id=job.user_id, run_id=run_id
            ) as run:
                async with run.tool(READ_TOOL, {"file_id": job.file_id}) as call:
                    call.output = {
                        "chars": len(job.text),
                        "pages": job.pages,
                        "text_tokens": job.text_tokens,
                    }
                async with run.tool(SUMMARIZE_TOOL, {"file_id": job.file_id}) as call:
                    if self.llm is None:
                        raise ApiError(502, "LLM_ERROR", MODEL_FAILED)
                    try:
                        summary, reply = await summarize(self.llm, model=self.model, text=job.text)
                    except TimeoutError as exc:
                        raise ApiError(502, "LLM_TIMEOUT", SLOW) from exc
                    except SummaryError as exc:
                        logger.warning("강의자료 요약이 비어 있어요: %s", exc)
                        raise ApiError(502, "LLM_ERROR", MODEL_FAILED) from exc
                    except Exception as exc:
                        logger.warning("강의자료 요약 모델 호출 실패: %r", exc)
                        raise ApiError(502, "LLM_ERROR", MODEL_FAILED) from exc
                    await run.record_llm(
                        provider=self.llm.provider,
                        model=self.model,
                        input_tokens=reply.usage.input_tokens,
                        output_tokens=reply.usage.output_tokens,
                        latency_ms=reply.latency_ms,
                        tool_call=call,
                    )
                    async with self.repos() as repo:
                        saved = await repo.save_summary(job.file_id, run_id=run_id, summary=summary)
                    # 요약 글은 materials에 있다. 기록에는 크기와 저장 여부만 남긴다
                    call.output = {"file_id": job.file_id, "chars": len(summary), "saved": saved}
        except Exception:
            logger.exception("강의자료 요약 실행 실패: run %s", run_id)
            await self._fail(job.file_id, run_id)

    async def _fail(self, file_id: str, run_id: str) -> None:
        try:
            async with self.repos() as repo:
                await repo.fail(file_id, run_id=run_id)
        except Exception:
            logger.exception("강의자료 요약을 실패로 남기지 못했어요: run %s", run_id)
        await self._close(run_id)

    async def _close(self, run_id: str, message: str = STOPPED) -> None:
        """아직 running인 실행을 실패로 닫는다(이미 닫혔으면 그대로 둔다)."""
        try:
            await abandon_run(self.log_connection, run_id, ApiError(500, "INTERNAL_ERROR", message))
        except Exception:
            logger.exception("강의자료 요약 실행을 닫지 못했어요: run %s", run_id)


def get_material_service(
    request: Request,
    llm: LlmDep,
    runner: RunnerDep,
    storage: StorageDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> MaterialService:
    state = request.app.state
    pool, log_pool = getattr(state, "pool", None), getattr(state, "log_pool", None)
    if pool is None or log_pool is None:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    return MaterialService(
        repos=material_repos(pool.connection),
        log_connection=log_pool.connection,
        storage=storage,
        llm=llm,
        model=settings.summary_model,
        max_tokens=settings.material_max_tokens,
        runner=runner,
    )


MaterialServiceDep = Annotated[MaterialService, Depends(get_material_service)]
