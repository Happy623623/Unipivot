"""계획서 추출 실행 (F-14, API 명세 8장 `POST /syllabi/extract`).

202와 run_id를 먼저 주고 뒤에서 돈다(포스터 추출과 같은 방식). 일은 요청과 따로 돌며 자기 연결을 연다.

차례: 저장소에서 PDF 받기 → 글자 뽑기 → 모델 한 번 → 받은 일정 검사 → 계획서·일정 저장.
모델을 기다리는 동안 DB 연결(요청 풀)을 쥐지 않는다.

실패 이유는 ApiError로 남겨 학생에게 그대로 보인다. 글자를 못 읽은 것(SYLLABUS_READ_FAILED)은
다른 PDF로 다시 올리면 되는 일이고, LLM_TIMEOUT·STORAGE_API_ERROR는 잠시 뒤 다시 누르면 되는 일이다.
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
from app.llm import LlmClient
from app.llm.deps import LlmDep
from app.repositories.syllabi import SavedSyllabus, SyllabusFile, SyllabusRepository
from app.schemas.syllabi import READ_TOOL, SAVE_TOOL
from app.syllabi.extract import Extracted, SyllabusError, extract, semester_range
from app.uploads import pdf_text
from app.uploads.storage import StorageDep, StorageError, SupabaseStorage

logger = logging.getLogger(__name__)
Connect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
TRIGGER = "syllabus_upload"
RETRY_HINT = "포털 계획서를 브라우저에서 PDF로 저장해 올려 주세요."
NO_TEXT = "계획서에서 글자를 찾지 못했어요."
SLOW = "계획서를 읽는 데 너무 오래 걸렸어요. 잠시 후 다시 눌러 주세요."
STORAGE_FAILED = "올린 계획서를 불러오지 못했어요. 잠시 후 다시 눌러 주세요."
MODEL_FAILED = "계획서를 읽지 못했어요. 잠시 후 다시 눌러 주세요."
STOPPED = "계획서를 읽다 멈췄어요. 다시 눌러 주세요."
KEPT_OLD = (
    "이 PDF에서는 일정을 찾지 못했어요. 먼저 올린 계획서를 그대로 두었으니, 다른 PDF로 올려 주세요."
)


@dataclass(frozen=True)
class SyllabusJob:
    run_id: str
    user_id: str
    file: SyllabusFile
    course_id: str | None
    course_short_name: str | None  # 과목을 붙였으면 그 이름(모델이 못 읽었을 때 쓴다)
    semester_start: date | None  # 과목명에서 센 학기 시작일(연도 없는 날짜의 기준)
    today: date  # KST
    now: datetime


class SyllabusService:
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

    def repo(self, conn: AsyncConnection) -> SyllabusRepository:
        return SyllabusRepository(conn)

    async def begin(self, job_without_run: "SyllabusJob") -> str:
        """실행 행을 만들고 일을 띄운다. run_id를 준다."""
        run_id = await start_run(
            self.log_connection, trigger=TRIGGER, user_id=job_without_run.user_id
        )
        job = SyllabusJob(**{**job_without_run.__dict__, "run_id": run_id})
        work = self.execute(job)
        try:
            await self.runner.start(work)
        except Exception:
            work.close()
            await self._close(run_id)
            raise
        return run_id

    async def execute(self, job: SyllabusJob) -> None:
        try:
            async with agent_run(
                self.log_connection, trigger=TRIGGER, user_id=job.user_id, run_id=job.run_id
            ) as run:
                text = await self._text(run, job)
                async with run.tool(SAVE_TOOL, {"file_id": job.file.id}) as call:
                    extracted = await self._read(run, call, job, text)
                    saved = await self._save(job, extracted)
                    # `GET /runs/{id}`가 이 출력으로 결과를 만든다(repositories/runs.py)
                    call.output = {
                        "syllabus_id": saved.id,
                        "course_name": saved.course_name,
                        "items": [one.model_dump(mode="json") for one in saved.items],
                    }
        except Exception:
            logger.exception("계획서 추출 실행 실패: run %s", job.run_id)
            await self._close(job.run_id)

    async def _text(self, run: AgentRun, job: SyllabusJob) -> str:
        """저장소에서 PDF를 받아 글자를 뽑는다(모델에 넘길 것)."""
        async with run.tool(READ_TOOL, {"file_id": job.file.id}) as call:
            try:
                data = await self.storage.download(job.file.storage_path)
            except StorageError as exc:
                logger.warning("계획서를 저장소에서 받지 못했어요: %s", exc)
                raise ApiError(502, "STORAGE_API_ERROR", STORAGE_FAILED) from exc
            text = pdf_text(data)
            if not text.strip():
                raise ApiError(422, "SYLLABUS_READ_FAILED", f"{NO_TEXT} {RETRY_HINT}")
            call.output = {"chars": len(text)}  # 글자는 남기지 않는다(계획서 본문이다)
            return text

    async def _read(self, run: AgentRun, call: ToolCall, job: SyllabusJob, text: str) -> Extracted:
        """모델에 한 번 넘긴다. 기다리는 동안 DB 연결을 쥐지 않는다."""
        if self.llm is None:
            raise ApiError(502, "LLM_ERROR", MODEL_FAILED)
        start, end = semester_range(job.semester_start, job.today)
        try:
            extracted = await extract(
                self.llm,
                model=self.model,
                text=text,
                semester_start=start,
                semester_end=end,
                uploaded_on=job.today,
            )
        except SyllabusError as exc:
            raise ApiError(422, "SYLLABUS_READ_FAILED", f"{exc} {RETRY_HINT}") from exc
        except TimeoutError as exc:
            raise ApiError(502, "LLM_TIMEOUT", SLOW) from exc
        except Exception as exc:
            logger.warning("계획서 모델 호출 실패: %r", exc)
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

    async def _save(self, job: SyllabusJob, extracted: Extracted) -> SavedSyllabus:
        async with self.transaction() as conn:
            repo = self.repo(conn)
            if not extracted.items and job.course_id is not None:
                # 일정을 하나도 못 찾았다. 이미 확인해 둔 일정이 있으면 **덮어쓰지 않는다** —
                # 그 일정으로 만든 할 일·캘린더 기록까지 함께 지워진다(cascade)
                if await repo.existing_items(job.user_id, job.course_id) > 0:
                    raise ApiError(422, "SYLLABUS_READ_FAILED", KEPT_OLD)
            return await repo.save(
                job.user_id,
                file_id=job.file.id,
                course_id=job.course_id,
                # 모델이 교과목명을 못 읽으면 LMS 과목 이름을 쓴다(둘 다 없으면 비운다)
                course_name=extracted.course_name or job.course_short_name,
                semester=extracted.semester,
                items=extracted.items,
                now=job.now,
            )

    async def _close(self, run_id: str, message: str = STOPPED) -> None:
        """아직 running인 실행을 실패로 닫는다(이미 닫혔으면 그대로 둔다)."""
        try:
            await abandon_run(self.log_connection, run_id, ApiError(500, "INTERNAL_ERROR", message))
        except Exception:
            logger.exception("계획서 실행을 닫지 못했어요: run %s", run_id)


def get_syllabus_service(
    request: Request,
    llm: LlmDep,
    runner: RunnerDep,
    storage: StorageDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SyllabusService:
    state = request.app.state
    pool, log_pool = getattr(state, "pool", None), getattr(state, "log_pool", None)
    if pool is None or log_pool is None:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    return SyllabusService(
        transaction=pool.connection,
        log_connection=log_pool.connection,
        storage=storage,
        llm=llm,
        # 계획서는 글자만 읽는다. 공지 요건 추출과 같은 모델을 쓴다(단가표 키도 같다)
        model=settings.extraction_model,
        runner=runner,
    )


SyllabusServiceDep = Annotated[SyllabusService, Depends(get_syllabus_service)]
