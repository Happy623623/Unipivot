"""과목 공지 분류와 기회성 공지 → 공고 (F-53 1부, PRD F-53).

동기화(`lms_sync`) 안에서 돈다. 공지를 받아 저장한 다음 이 순서다.

1. 분류할 공지를 집는다(`AnnouncementRepository.pending` — 최근 공지와, 공고를 못 만든 기회성 공지)
2. 공지마다 모델을 **한 번** 불러 네 갈래와 한 줄 요약을 받는다(`app/lms/classify.py`)
3. 기회성이면 공지 글을 공고 원문으로 삼아 **요건 추출 에이전트**를 돌리고, 공고 행과 요건·서류를
   한 트랜잭션에 쓴다. 공고는 그 과목 수강생만 본다(`visible_canvas_course_id`)
4. 공고가 생기면 판정·알림은 **이미 있는 길**이 처리한다 — 피드·상세가 판정하고(S1-5), 적격이면
   예약 작업이 "새 공고" 알림을 만든다(F-33). 여기서 따로 부르지 않는다

지키는 것:
- **동기화는 실패하지 않는다.** 분류가 터져도 과제·주차 자료는 이미 저장했고, 그 공지는 분류 전으로
  남아 다음 동기화에서 다시 집힌다. 모델 오류·시간 초과는 로그만 남기고 넘어간다
- 모델을 기다리는 동안 DB 연결을 쥐지 않는다(준비하기·포스터와 같다)
- 한 동기화에서 공지 `MAX_PER_SYNC`개까지만 본다. 연결 직후에는 한 학기 분량이 한꺼번에 들어온다
- 공지 글은 자료일 뿐 지시가 아니다(프롬프트에 못 박았다). 공지로 만든 공고는 `needs_review`를
  요건 추출 결과대로 둔다 — 지어낸 요건이 조용히 판정에 들어가지 않게 한다
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from psycopg import AsyncConnection

from app.agent_log import AgentRun
from app.eligibility import KST, Department
from app.extraction.agent import ExtractionAgent
from app.extraction.models import NoticeInput
from app.extraction.store import load_departments
from app.llm import LlmClient
from app.lms.classify import Classified, classify
from app.repositories.announcements import AnnouncementRepository, PendingAnnouncement
from app.schemas.opportunities import Category

logger = logging.getLogger(__name__)
Connect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
AgentFor = Callable[[Sequence[Department]], ExtractionAgent]
RepoFor = Callable[[AsyncConnection], AnnouncementRepository]
DepartmentsFor = Callable[[AsyncConnection], Awaitable[Sequence[Department]]]

MAX_PER_SYNC = 5  # 한 동기화에서 분류할 공지 수 상한(비용)
RECENT_DAYS = 30  # 이보다 오래된 공지는 분류하지 않는다(지금 할 일이 없다)
CLASSIFY_TOOL = "classify_announcement"  # 실행 기록의 도구 이름(처리 과정 F-42)
TOPIC_PATH = "{base}/courses/{course}/discussion_topics/{topic}"
DEFAULT_KIND: Category = "etc"  # 분류를 다시 하지 않는 재시도에서 쓰는 공고 종류


@dataclass(frozen=True)
class AnnouncementOutcome:
    """분류 한 묶음의 결과. 동기화 결과와 실행 기록에 적는다."""

    classified: int = 0  # 이번에 갈래를 정한 공지 수
    opportunities: int = 0  # 그중 공고로 만든 수
    failed: int = 0  # 모델·추출이 터져 다음으로 미룬 수


class AnnouncementService:
    """공지 분류. 동기화 서비스가 들고 있고, 모델이 없으면(설정이 비면) 아무것도 하지 않는다."""

    def __init__(
        self,
        *,
        transaction: Connect,
        llm: LlmClient | None,
        classify_model: str,
        agent_for: AgentFor,
        lms_base: str,
        limit: int = MAX_PER_SYNC,
        recent_days: int = RECENT_DAYS,
        repo_for: RepoFor = AnnouncementRepository,
        departments_for: DepartmentsFor = load_departments,
    ) -> None:
        self.transaction = transaction
        # 저장소·학과 목록은 바꿔 끼울 수 있다(테스트는 가짜를 넣는다)
        self.repo_for = repo_for
        self.departments_for = departments_for
        self.llm = llm
        self.classify_model = classify_model
        self.agent_for = agent_for
        self.lms_base = lms_base.rstrip("/")
        self.limit = limit
        self.recent_days = recent_days

    async def run(
        self, run: AgentRun, *, now: datetime, courses: Sequence[int]
    ) -> AnnouncementOutcome:
        """이 사용자의 과목 공지를 분류한다. 모델이 없거나 집을 것이 없으면 빈 결과다."""
        if self.llm is None or not courses:
            return AnnouncementOutcome()
        async with self.transaction() as conn:
            pending = await self.repo_for(conn).pending(
                courses=list(courses),
                recent_from=now - timedelta(days=self.recent_days),
                limit=self.limit,
            )
        if not pending:
            return AnnouncementOutcome()
        outcome = AnnouncementOutcome()
        for one in pending:
            outcome = _add(outcome, await self._one(run, one, now=now))
        return outcome

    async def _one(
        self, run: AgentRun, announcement: PendingAnnouncement, *, now: datetime
    ) -> AnnouncementOutcome:
        """공지 하나. 터지면 로그만 남기고 다음 공지로 간다(동기화는 성공이다)."""
        try:
            return await self._classify_one(run, announcement, now=now)
        except Exception as exc:  # 모델 오류·시간 초과·DB 오류. 다음 동기화에서 다시 집는다
            logger.warning(
                "공지를 분류하지 못해 다음으로 미뤄요: announcement %s, %r", announcement.id, exc
            )
            return AnnouncementOutcome(failed=1)

    async def _classify_one(
        self, run: AgentRun, announcement: PendingAnnouncement, *, now: datetime
    ) -> AnnouncementOutcome:
        if announcement.classified:
            # 분류는 끝났고 공고만 못 만든 공지다. 모델을 다시 부르지 않는다
            made = await self._opportunity(run, announcement, category_hint=None, now=now)
            return AnnouncementOutcome(classified=0, opportunities=1 if made else 0)
        async with run.tool(CLASSIFY_TOOL, {"announcement_id": announcement.id}) as call:
            assert self.llm is not None
            result = await classify(
                self.llm,
                model=self.classify_model,
                title=announcement.title,
                body=announcement.message,
                posted_on=_posted_on(announcement, now),
            )
            await run.record_llm(
                provider=self.llm.provider,
                model=self.classify_model,
                input_tokens=result.reply.usage.input_tokens,
                output_tokens=result.reply.usage.output_tokens,
                latency_ms=result.reply.latency_ms,
                tool_call=call,
            )
            call.output = {"category": result.category, "summary": result.summary}
        async with self.transaction() as conn:
            await self.repo_for(conn).save_classification(
                announcement.id,
                category=result.category,
                summary=result.summary,
                run_id=run.id,
            )
        if not result.is_opportunity:
            return AnnouncementOutcome(classified=1)
        made = await self._opportunity(run, announcement, category_hint=result, now=now)
        return AnnouncementOutcome(classified=1, opportunities=1 if made else 0)

    async def _opportunity(
        self,
        run: AgentRun,
        announcement: PendingAnnouncement,
        *,
        category_hint: Classified | None,
        now: datetime,
    ) -> bool:
        """기회성 공지 → 공고. 요건 추출을 돌린 뒤 한 트랜잭션에 쓴다.

        이미 공고가 이어져 있으면(다른 수강생의 동기화가 먼저 만들었다) 아무것도 하지 않는다.
        """
        body = announcement.message or announcement.title
        async with self.transaction() as conn:
            departments = await self.departments_for(conn)
        agent = self.agent_for(departments)
        notice = NoticeInput(
            title=announcement.title,
            body=body,
            posted_on=_posted_on(announcement, now),
            # 원문 링크를 주지 않는다. LearningX 원문은 토큰이 있어야 열리고, 허용 경로도 아니다
            # (명세 8장) — 에이전트가 fetch_original을 부를 수 있으면 그때마다 실패한다
            original_url=None,
        )
        extraction = await agent.run(notice, run)
        async with self.transaction() as conn:
            opportunity_id = await self.repo_for(conn).create_opportunity(
                announcement,
                category=_kind(category_hint),
                original_url=TOPIC_PATH.format(
                    base=self.lms_base,
                    course=announcement.canvas_course_id,
                    topic=announcement.canvas_topic_id,
                ),
                extraction=extraction,
                run_id=run.id,
            )
        if opportunity_id is None:
            return False
        logger.info(
            "기회성 공지로 공고를 만들었어요: announcement %s, 요건 %s개",
            announcement.id,
            len(extraction.requirements),
        )
        return True


def _add(left: AnnouncementOutcome, right: AnnouncementOutcome) -> AnnouncementOutcome:
    return AnnouncementOutcome(
        classified=left.classified + right.classified,
        opportunities=left.opportunities + right.opportunities,
        failed=left.failed + right.failed,
    )


def _kind(hint: Classified | None) -> Category:
    """공고 종류. 분류를 다시 하지 않는 재시도에서는 모델의 값이 없어 '그 밖'이다."""
    return hint.opportunity_category if hint is not None else DEFAULT_KIND


def _posted_on(announcement: PendingAnnouncement, now: datetime) -> date:
    """연도 없는 날짜("10. 24.까지")를 읽는 기준. 게시일이 없으면 지금(KST)으로 둔다."""
    moment = announcement.posted_at or now
    return moment.astimezone(KST).date()
