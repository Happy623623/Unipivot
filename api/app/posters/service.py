"""포스터 추출 실행 (F-16, API 명세 6장 POST /posters/extract).

202와 run_id를 먼저 주고 뒤에서 돈다(준비하기와 같은 방식). 일은 요청과 따로 돌며 자기 연결을 연다.

차례: 저장소에서 포스터 받기 → 학과 목록 읽기 → Vision 한 번 → 중복 공고 찾기 → 실행 기록에 초안 남기기.
초안은 따로 저장하지 않고 tool_calls.output에 둔다. GET /runs/{id}가 그것을 다시 읽어 준다.
모델을 기다리는 동안 DB 연결(요청 풀)을 쥐지 않는다. 로그 연결도 한 줄 쓸 때마다 빌렸다 돌려준다.

실패 이유는 ApiError로 남겨 학생에게 그대로 보인다. 글자를 못 읽은 것(POSTER_READ_FAILED)은 다시
찍어 올리면 되는 일이고, LLM_TIMEOUT·STORAGE_API_ERROR는 잠시 뒤 다시 누르면 되는 일이다.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated

from fastapi import Depends, Request
from psycopg import AsyncConnection

from app.agent_log import AgentRun, ToolCall, abandon_run, agent_run, start_run
from app.background import RunnerDep, TaskRunner
from app.config import Settings, get_settings
from app.errors import ApiError
from app.extraction.store import load_departments
from app.llm import Blob, LlmClient
from app.llm.deps import LlmDep
from app.posters.extract import Extracted, PosterError, extract
from app.posters.prompt import SUBMIT
from app.repositories.posters import PosterFile, PosterRepository
from app.schemas.posters import DuplicateCandidate
from app.uploads.storage import StorageDep, StorageError, SupabaseStorage

logger = logging.getLogger(__name__)
Connect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
TRIGGER = "poster_upload"
RETRY_HINT = "포스터 전체가 보이게 밝은 곳에서 다시 찍어 주세요."
SLOW = "포스터를 읽는 데 너무 오래 걸렸어요. 잠시 후 다시 눌러 주세요."
STORAGE_FAILED = "올린 포스터를 불러오지 못했어요. 잠시 후 다시 눌러 주세요."
MODEL_FAILED = "포스터를 읽지 못했어요. 잠시 후 다시 눌러 주세요."
STOPPED = "포스터를 읽다 멈췄어요. 다시 눌러 주세요."


@dataclass(frozen=True)
class PosterJob:
    run_id: str
    user_id: str
    file: PosterFile
    today: date  # KST. 연도 없는 날짜를 읽는 기준이다
    now: datetime


class PosterService:
    def __init__(
        self,
        *,
        transaction: Connect,
        log_connection: Connect,
        storage: SupabaseStorage,
        llm: LlmClient | None,
        model: str,
        runner: TaskRunner,
    ) -> None:
        self.transaction = transaction
        self.log_connection = log_connection
        self.storage = storage
        self.llm = llm
        self.model = model
        self.runner = runner

    async def file(self, user_id: str, file_id: str) -> PosterFile | None:
        async with self.transaction() as conn:
            return await PosterRepository(conn).poster_file(user_id, file_id)

    async def begin(self, user_id: str, file: PosterFile, *, now: datetime, today: date) -> str:
        """실행 행을 만들고 일을 띄운다. run_id를 준다."""
        run_id = await start_run(self.log_connection, trigger=TRIGGER, user_id=user_id)
        job = PosterJob(run_id, user_id, file, today, now)
        work = self.execute(job)
        try:
            await self.runner.start(work)
        except Exception:
            work.close()
            await self._close(run_id)
            raise
        return run_id

    async def execute(self, job: PosterJob) -> None:
        try:
            async with agent_run(
                self.log_connection, trigger=TRIGGER, user_id=job.user_id, run_id=job.run_id
            ) as run:
                async with run.tool(SUBMIT, {"file_id": job.file.id}) as call:
                    extracted = await self._read(run, call, job)
                    duplicate = await self._duplicate(job, extracted)
                    call.output = {
                        "draft": extracted.draft.model_dump(mode="json"),
                        "duplicate_candidate": duplicate.model_dump() if duplicate else None,
                        # 등록(F-16 2차)에서 공고 원문으로 쓴다
                        "poster_text": extracted.poster_text,
                    }
        except Exception:
            logger.exception("포스터 추출 실행 실패: run %s", job.run_id)
            await self._close(job.run_id)

    async def _read(self, run: AgentRun, call: ToolCall, job: PosterJob) -> Extracted:
        """저장소에서 받아 모델에 한 번 넘긴다. 모델을 기다리는 동안 DB 연결을 쥐지 않는다."""
        if self.llm is None:
            raise ApiError(502, "LLM_ERROR", MODEL_FAILED)
        try:
            data = await self.storage.download(job.file.storage_path)
        except StorageError as exc:
            logger.warning("포스터를 저장소에서 받지 못했어요: %s", exc)
            raise ApiError(502, "STORAGE_API_ERROR", STORAGE_FAILED) from exc
        async with self.transaction() as conn:
            departments = await load_departments(conn)
        blob = Blob(data, job.file.mime_type or "image/jpeg")
        try:
            extracted = await extract(
                self.llm, model=self.model, blob=blob, departments=departments, today=job.today
            )
        except PosterError as exc:
            raise ApiError(422, "POSTER_READ_FAILED", f"{exc} {RETRY_HINT}") from exc
        except TimeoutError as exc:
            raise ApiError(502, "LLM_TIMEOUT", SLOW) from exc
        except Exception as exc:
            logger.warning("포스터 모델 호출 실패: %r", exc)
            raise ApiError(502, "LLM_ERROR", MODEL_FAILED) from exc
        await run.record_llm(
            provider=self.llm.provider,
            model=self.model,
            input_tokens=extracted.reply.usage.input_tokens,
            output_tokens=extracted.reply.usage.output_tokens,
            latency_ms=extracted.reply.latency_ms,
            tool_call=call,
        )
        return extracted

    async def _duplicate(self, job: PosterJob, extracted: Extracted) -> DuplicateCandidate | None:
        async with self.transaction() as conn:
            return await PosterRepository(conn).duplicate(
                job.user_id,
                title=extracted.draft.title,
                deadline_at=extracted.draft.deadline_at,
                now=job.now,
            )

    async def _close(self, run_id: str, message: str = STOPPED) -> None:
        """아직 running인 실행을 실패로 닫는다(이미 닫혔으면 그대로 둔다)."""
        try:
            await abandon_run(self.log_connection, run_id, ApiError(500, "INTERNAL_ERROR", message))
        except Exception:
            logger.exception("포스터 실행을 닫지 못했어요: run %s", run_id)


def get_poster_service(
    request: Request,
    llm: LlmDep,
    runner: RunnerDep,
    storage: StorageDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PosterService:
    state = request.app.state
    pool, log_pool = getattr(state, "pool", None), getattr(state, "log_pool", None)
    if pool is None or log_pool is None:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    return PosterService(
        transaction=pool.connection,
        log_connection=log_pool.connection,
        storage=storage,
        llm=llm,
        model=settings.vision_model,
        runner=runner,
    )


PosterServiceDep = Annotated[PosterService, Depends(get_poster_service)]
