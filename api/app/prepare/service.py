"""준비하기 실행(PRD 6장 "준비하기 버튼": get_document_guide → build_prep_plan).

POST /opportunities/{id}/prepare(라우터)가 판정·확인을 마치면 begin이 실행 행과 계획 행을 만들고 일을 띄운다.
일(execute)은 요청과 따로 돌며 자기 연결을 연다.

일은 읽기 → 모델 → 쓰기 셋으로 나눈다. 모델 호출은 트랜잭션 밖이라 묻는 동안 DB 연결(요청 풀)과 공고 행
잠금을 쥐지 않는다. 쓰기(서류 안내 + 할 일)는 공고를 잠근 한 트랜잭션이고, 잠근 뒤 서류를 다시 읽어 그새
다른 학생이 넣거나 채운 값을 그대로 쓴다. 실패하면 아무것도 남지 않고 계획 행을 지워 다시 누를 수 있다.
실행 기록(agent_runs·tool_calls·llm_calls)은 실패해도 남고, running으로 남지 않게 닫는다.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass, field
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
from app.prepare.documents import Guide, lookup
from app.prepare.guide import GuideDraft, GuideError, ask_guides
from app.prepare.plan import PlanDocument, build_tasks
from app.repositories.opportunities import OpportunityRepository
from app.repositories.prepare import DocumentRow, OpportunityText, PlanState, PrepareRepository
from app.schemas.opportunities import OpportunityDetail
from app.youth.convert import raw_section

logger = logging.getLogger(__name__)
Connect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
GUIDE_FAILED = "필요 서류를 확인하지 못했어요. 잠시 후 다시 눌러 주세요."
STOPPED = "준비 일정을 만들다 멈췄어요. 다시 눌러 주세요."


@dataclass(frozen=True)
class PrepareJob:
    run_id: str
    plan_id: str
    user_id: str
    opportunity_id: str
    deadline: date  # 마감일(KST 날짜). 상시 공고는 학생이 고른 목표일
    today: date  # 요청한 날(KST). 이보다 앞선 할 일은 이날로 둔다


@dataclass(frozen=True)
class Asked:
    """모델에 물어 온 것. 쓰기 트랜잭션을 열기 전에 다 받아 둔다."""

    listed: list[GuideDraft] | None = None  # 청년정책 '제출 서류' 글에서 만든 서류 목록
    guides: dict[str, GuideDraft] = field(default_factory=dict)  # 사전에 없던 서류의 이름 → 안내


@dataclass(frozen=True)
class Started:
    run_id: str | None
    status: str  # running | succeeded
    created: bool  # 이번 요청이 시작했다(202). 아니면 그새 다른 요청이 시작한 계획(200)


class PrepareService:
    def __init__(
        self,
        *,
        transaction: Connect,
        log_connection: Connect,
        llm: LlmClient | None,
        model: str,
        runner: TaskRunner,
    ) -> None:
        self.transaction = transaction  # 블록이 끝나면 커밋하는 연결(요청 트랜잭션과 따로)
        self.log_connection = log_connection  # autocommit 연결(agent_run)
        self.llm = llm
        self.model = model
        self.runner = runner

    async def judge(
        self, user_id: str, opportunity_id: str, *, now: datetime, display_name: str | None
    ) -> OpportunityDetail | None:
        """상세와 같이 지금 프로필로 다시 판정한다(프로필 잠금 포함). 보이지 않는 공고면 None.

        요청 트랜잭션을 쓰지 않고 바로 커밋한다. 뒤에서 도는 일과 잠금을 나눠 갖지 않게 한다.
        """
        async with self.transaction() as conn:
            return await OpportunityRepository(conn).detail(
                user_id, opportunity_id, now=now, display_name=display_name
            )

    async def plan(self, user_id: str, opportunity_id: str) -> PlanState | None:
        async with self.transaction() as conn:
            return await PrepareRepository(conn).plan(user_id, opportunity_id)

    async def reset(self, plan: PlanState) -> None:
        """멈췄거나 실패한 계획을 지운다. 실행 중으로 남은 실행은 실패로 닫는다."""
        async with self.transaction() as conn:
            await PrepareRepository(conn).drop_plan(plan.id)
        if plan.run_id:
            await self._close(plan.run_id)

    async def begin(
        self, user_id: str, opportunity_id: str, *, deadline: date, today: date
    ) -> Started:
        """실행 행과 계획 행을 만들고 일을 띄운다. 그새 다른 요청이 계획을 만들었으면 그 계획을 준다."""
        async with self.log_connection() as log_conn:
            run_id = await start_run(log_conn, trigger="prepare", user_id=user_id)
        try:
            async with self.transaction() as conn:
                plan_id = await PrepareRepository(conn).create_plan(user_id, opportunity_id, run_id)
        except Exception:  # 계획 행을 만들지 못했다. 실행이 running으로 남지 않게 닫는다
            await self._close(run_id)
            raise
        if plan_id is None:
            await self._close(run_id, "같은 공고를 이미 준비하고 있어요.")
            existing = await self.plan(user_id, opportunity_id)
            if existing is None:  # 그 계획도 그새 실패해 지워졌다. 다시 누르면 된다
                raise ApiError(500, "INTERNAL_ERROR", STOPPED)
            status = "succeeded" if existing.done else "running"
            return Started(existing.run_id, status, created=False)
        job = PrepareJob(run_id, plan_id, user_id, opportunity_id, deadline, today)
        work = self.execute(job)
        try:
            await self.runner.start(work)
        except Exception:  # 일을 띄우지 못했다. 계획을 지워 다시 누를 수 있게 한다
            work.close()
            await self._give_up(job)
            raise
        return Started(run_id, "running", created=True)

    async def execute(self, job: PrepareJob) -> None:
        """서류 안내 → 역산 일정. 실패하면 계획을 지운다(실행은 실패로 남는다)."""
        try:
            async with self.log_connection() as log_conn:
                async with agent_run(
                    log_conn, trigger="prepare", user_id=job.user_id, run_id=job.run_id
                ) as run:
                    await self._prepare(run, job)
        except Exception:
            logger.exception("준비하기 실행 실패: run %s", job.run_id)
            await self._give_up(job)

    async def _give_up(self, job: PrepareJob) -> None:
        """계획을 지우고 실행을 닫는다. 로그 연결을 얻지 못해 agent_run 밖에서 끝난 경우까지 닫는다."""
        try:
            async with self.transaction() as conn:
                await PrepareRepository(conn).drop_plan(job.plan_id)
        except Exception:
            logger.exception("실패한 준비 계획을 지우지 못했어요: plan %s", job.plan_id)
        await self._close(job.run_id)

    async def _close(self, run_id: str, message: str = STOPPED) -> None:
        """아직 running인 실행을 실패로 닫는다(이미 닫혔으면 그대로 둔다).

        닫지 못해도 다음 누름이 멈춘 실행으로 보고 지운다(repositories/prepare.py의 STALE_AFTER).
        """
        try:
            async with self.log_connection() as log_conn:
                await abandon_run(log_conn, run_id, ApiError(500, "INTERNAL_ERROR", message))
        except Exception:
            logger.exception("준비하기 실행을 닫지 못했어요: run %s", run_id)

    async def _prepare(self, run: AgentRun, job: PrepareJob) -> None:
        """읽기 → 모델 → 쓰기. 쓰기 트랜잭션은 모델 호출이 끝난 뒤에 열어 두 단계가 함께 커밋된다."""
        async with AsyncExitStack() as stack:
            async with run.tool(
                "get_document_guide", {"opportunity_id": job.opportunity_id}
            ) as call:
                asked = await self._ask_guides(run, call, job)  # 트랜잭션 밖(모델)
                conn = await stack.enter_async_context(self.transaction())
                repo = PrepareRepository(conn)
                if not await repo.lock_plan(job.plan_id):
                    # 묻는 사이에 다음 누름이 멈춘 실행으로 보고 계획을 지웠다. 그 요청에 넘긴다
                    raise ApiError(500, "INTERNAL_ERROR", STOPPED)
                documents, counts = await self._save_guides(repo, job, asked)
                call.output = {"documents": len(documents), **counts}
            plan_input = {
                "opportunity_id": job.opportunity_id,
                "deadline": job.deadline.isoformat(),
                "documents": len(documents),
            }
            async with run.tool("build_prep_plan", plan_input) as call:
                tasks = build_tasks(
                    [PlanDocument(doc.id, doc.name, doc.lead_days) for doc in documents],
                    job.deadline,
                    job.today,
                )
                await repo.add_tasks(job.user_id, job.plan_id, tasks)
                call.output = {"tasks": len(tasks)}

    async def _ask_guides(self, run: AgentRun, call: ToolCall, job: PrepareJob) -> Asked:
        """모델에 물을 것만 묻는다. 공고 행을 잠그지 않고, 묻는 동안 DB 연결도 쥐지 않는다."""
        async with self.transaction() as conn:
            repo = PrepareRepository(conn)
            opportunity = await repo.opportunity(job.opportunity_id)
            if opportunity is None:  # 그새 공고가 지워졌다
                raise ApiError(404, "NOT_FOUND", "공고를 찾을 수 없어요.")
            documents = await repo.documents(job.opportunity_id)
        if not documents and opportunity.source_type == "youth_policy":
            text = raw_section(opportunity.raw_text, "제출 서류")
            if text:  # 청년정책은 서류 행이 없다. 제출 서류 글에서 목록과 안내를 함께 만든다
                drafts = await self._ask(run, call, opportunity, text=text)
                # 묻는 사이에 서류 행이 생겼으면 목록은 버리고 안내만 이름으로 맞춰 쓴다
                return Asked(listed=drafts, guides={draft.name: draft for draft in drafts})
        unknown = [
            document.name
            for document in documents
            if not document.guided and lookup(document.name) is None
        ]
        if not unknown:  # 사전으로 다 되거나 이미 채워진 공고는 모델을 부르지 않는다
            return Asked()
        drafts = await self._ask(run, call, opportunity, names=unknown)
        return Asked(guides={draft.name: draft for draft in drafts})

    async def _save_guides(
        self, repo: PrepareRepository, job: PrepareJob, asked: Asked
    ) -> tuple[list[DocumentRow], dict[str, int]]:
        """공고를 잠그고 서류를 다시 읽어 빈 칸만 채운다. 채운 값은 공고에 남아 다른 학생도 쓴다."""
        if await repo.lock_opportunity(job.opportunity_id) is None:  # 그새 공고가 지워졌다
            raise ApiError(404, "NOT_FOUND", "공고를 찾을 수 없어요.")
        documents = await repo.documents(job.opportunity_id)
        counts = {"dictionary": 0, "model": 0, "unknown": 0, "listed": 0}
        if asked.listed is not None and not documents:  # 그새 다른 학생이 넣었으면 그 서류를 쓴다
            drafts = [_with_dictionary(draft) for draft in asked.listed]
            await repo.add_documents(job.opportunity_id, drafts)
            counts["listed"] = len(drafts)
            documents = await repo.documents(job.opportunity_id)
        guides: list[tuple[str, Guide]] = []
        for document in documents:
            if document.guided:  # 이미 채워져 있다(다른 학생이 준비한 공고)
                continue
            if guide := lookup(document.name):
                guides.append((document.id, guide))
                counts["dictionary"] += 1
            elif draft := asked.guides.get(document.name):
                guides.append((document.id, _guide(draft)))
                counts["model"] += 1
            else:  # 모델도 답하지 않은 서류. 소요 일수는 계획에서 하루로 둔다
                counts["unknown"] += 1
        await repo.save_guides(guides)
        return await repo.documents(job.opportunity_id), counts

    async def _ask(
        self,
        run: AgentRun,
        call: ToolCall,
        opportunity: OpportunityText,
        *,
        names: list[str] | None = None,
        text: str | None = None,
    ) -> list[GuideDraft]:
        if self.llm is None:
            raise ApiError(502, "LLM_ERROR", GUIDE_FAILED)
        try:
            drafts, reply = await ask_guides(
                self.llm,
                model=self.model,
                title=opportunity.title,
                organizer=opportunity.organizer,
                names=names,
                text=text,
            )
        except TimeoutError as exc:
            raise ApiError(502, "LLM_TIMEOUT", GUIDE_FAILED) from exc
        except GuideError as exc:
            raise ApiError(502, "LLM_ERROR", GUIDE_FAILED) from exc
        except Exception as exc:
            logger.warning("서류 안내 모델 호출 실패: %r", exc)
            raise ApiError(502, "LLM_ERROR", GUIDE_FAILED) from exc
        await run.record_llm(
            provider=self.llm.provider,
            model=self.model,
            input_tokens=reply.usage.input_tokens,
            output_tokens=reply.usage.output_tokens,
            latency_ms=reply.latency_ms,
            tool_call=call,
        )
        return drafts


def _guide(draft: GuideDraft) -> Guide:
    return Guide(draft.issuer, draft.how_to, draft.lead_days, draft.effort_minutes)


def _with_dictionary(draft: GuideDraft) -> GuideDraft:
    """사전에 있는 서류는 모델 답 대신 사전 안내를 쓴다(이름과 필수 여부는 모델 답)."""
    if guide := lookup(draft.name):
        return GuideDraft(
            draft.name,
            guide.issuer,
            guide.how_to,
            guide.lead_days,
            guide.effort_minutes,
            draft.is_required,
        )
    return draft


def get_prepare_service(
    request: Request,
    llm: LlmDep,
    runner: RunnerDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PrepareService:
    state = request.app.state
    pool, log_pool = getattr(state, "pool", None), getattr(state, "log_pool", None)
    if pool is None or log_pool is None:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    return PrepareService(
        transaction=pool.connection,
        log_connection=log_pool.connection,
        llm=llm,
        model=settings.guide_model,
        runner=runner,
    )


PrepareServiceDep = Annotated[PrepareService, Depends(get_prepare_service)]
