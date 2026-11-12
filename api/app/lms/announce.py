"""과목 공지 분류와 기회성 공지 → 공고 (F-53 1부, PRD F-53).

동기화(`lms_sync`) 안에서 돈다. 공지를 받아 저장한 다음 이 순서다.

1. 분류할 공지를 집는다(`AnnouncementRepository.claim` — 최근 공지와, 공고를 못 만든 기회성 공지). 집은 공지는
   2시간 동안 다른 동기화가 집지 못하고(임대), 실패하면 더 늦춰 다시 집는다(5번까지)
2. 공지마다 모델을 **한 번** 불러 네 갈래와 한 줄 요약을 받는다(`app/lms/classify.py`). 분류도 동기화 실행의
   **자식 실행**이다(엔진 `classify.announcement`, O2) — 공지의 `classified_run_id`가 그 자식이고, 동기화에는
   `classify_announcement` 한 줄이 남는다
3. 기회성이면 공지 글을 공고 원문으로 삼아 **요건 추출 에이전트**를 돌리고, 공고 행과 요건·서류를
   한 트랜잭션에 쓴다. 공고는 그 과목 수강생만 본다(`visible_canvas_course_id`). 요건 추출은 동기화 실행의
   **자식 실행**이고(실행 트리 O1) 공고의 `extraction_run_id`가 그 자식이다 — 동기화에는 `extract_announcement`
   한 줄만 남는다
4. 공고가 생기면 판정·알림은 **이미 있는 길**이 처리한다 — 피드·상세가 판정하고(S1-5), 적격이면
   예약 작업이 "새 공고" 알림을 만든다(F-33). 여기서 따로 부르지 않는다
5. 일정 변경이고 **바뀌는 날을 읽었으면** 그 과목 수강생 모두의 플래너에 할 일을 넣고 일정 변경
   알림을 만든다(F-53 2부). 갈래를 적는 것과 **한 트랜잭션**이다 — 할 일·알림 쓰기가 터지면 갈래도
   적히지 않아 공지가 다시 집힌다. 날짜를 못 읽었거나 이미 지난 날이면 갈래만 적고 넘어간다

지키는 것:
- **동기화는 실패하지 않는다.** 분류가 터져도 과제·주차 자료는 이미 저장했고, 그 공지는 분류 전으로
  남아 늦춘 시각(30분 × 2^(시도 − 1)) 뒤의 동기화에서 다시 집힌다. 모델 오류·시간 초과는 로그만 남기고 넘어간다
- 갈래는 먼저 적은 쪽만 남는다. 늦은 쪽은 자기 모델 답으로 다음 일(할 일·공고)을 하지 않는다
- 모델을 기다리는 동안 DB 연결을 쥐지 않는다(준비하기·포스터와 같다)
- 한 동기화에서 공지 `MAX_PER_SYNC`개까지만 본다. 연결 직후에는 한 학기 분량이 한꺼번에 들어온다
- 공지 글은 자료일 뿐 지시가 아니다(프롬프트에 못 박았다). 공지로 만든 공고는 `needs_review`를
  요건 추출 결과대로 둔다 — 지어낸 요건이 조용히 판정에 들어가지 않게 한다
"""

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from psycopg import AsyncConnection

from app.agent_log import AgentRun
from app.eligibility import KST, Department
from app.engines.review import ReviewCode
from app.extraction.agent import ExtractionAgent
from app.extraction.models import NoticeInput
from app.extraction.store import load_departments
from app.llm import LlmClient
from app.lms.classify import Classified, classify
from app.repositories.announcements import (
    MAX_ATTEMPTS,
    AnnouncementRepository,
    PendingAnnouncement,
)
from app.repositories.notifications import NotificationRepository, ScheduleNotice
from app.schemas.lms import EXTRACT_TOOL
from app.schemas.opportunities import Category

logger = logging.getLogger(__name__)
Connect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
AgentFor = Callable[[Sequence[Department]], ExtractionAgent]
RepoFor = Callable[[AsyncConnection], AnnouncementRepository]
NotesFor = Callable[[AsyncConnection], NotificationRepository]
DepartmentsFor = Callable[[AsyncConnection], Awaitable[Sequence[Department]]]

MAX_PER_SYNC = 5  # 한 동기화에서 분류할 공지 수 상한(비용)
RECENT_DAYS = 30  # 이보다 오래된 공지는 분류하지 않는다(지금 할 일이 없다)
CLASSIFY_TOOL = "classify_announcement"  # 실행 기록의 도구 이름(처리 과정 F-42)
# 엔진 등록부 id(O2). 분류·요건 추출의 자식 실행에 이 이름·버전을 남긴다
CLASSIFY_ENGINE = "classify.announcement"
EXTRACT_ENGINE = "extract.requirements"
SCHEDULE_TITLE = "{course} 수업 일정이 바뀌었어요"  # 일정 변경 알림 제목(F-53 2부)
TOPIC_PATH = "{base}/courses/{course}/discussion_topics/{topic}"
DEFAULT_KIND: Category = "etc"  # 분류를 다시 하지 않는 재시도에서 쓰는 공고 종류


@dataclass(frozen=True)
class AnnouncementOutcome:
    """분류 한 묶음의 결과. 동기화 결과와 실행 기록에 적는다."""

    classified: int = 0  # 이번에 갈래를 정한 공지 수
    opportunities: int = 0  # 그중 공고로 만든 수
    schedule_tasks: int = 0  # 일정 변경으로 플래너에 넣은 할 일 수(수강생 전체 합)
    notices: int = 0  # 그때 만든 일정 변경 알림 수
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
        notes_for: NotesFor = NotificationRepository,
        departments_for: DepartmentsFor = load_departments,
    ) -> None:
        self.transaction = transaction
        # 저장소·학과 목록은 바꿔 끼울 수 있다(테스트는 가짜를 넣는다)
        self.repo_for = repo_for
        self.notes_for = notes_for
        self.departments_for = departments_for
        self.llm = llm
        self.classify_model = classify_model
        self.agent_for = agent_for
        self.lms_base = lms_base.rstrip("/")
        self.limit = limit
        self.recent_days = recent_days

    async def run(
        self, run: AgentRun, *, now: datetime, courses: Mapping[int, str]
    ) -> AnnouncementOutcome:
        """이 사용자의 과목 공지를 분류한다. 모델이 없거나 집을 것이 없으면 빈 결과다.

        `courses`는 **과목 번호 → 화면 이름**이다(알림 문구에 과목 이름을 쓴다).
        """
        if self.llm is None or not courses:
            return AnnouncementOutcome()
        # 집는 문장만 담아 바로 확정한다 — 그래야 임대가 다른 동기화에 보인다
        async with self.transaction() as conn:
            pending = await self.repo_for(conn).claim(
                courses=list(courses),
                recent_from=now - timedelta(days=self.recent_days),
                now=now,
                limit=self.limit,
            )
        if not pending:
            return AnnouncementOutcome()
        outcome = AnnouncementOutcome()
        for one in pending:
            outcome = _add(outcome, await self._one(run, one, now=now, courses=courses))
        return outcome

    async def _one(
        self,
        run: AgentRun,
        announcement: PendingAnnouncement,
        *,
        now: datetime,
        courses: Mapping[int, str],
    ) -> AnnouncementOutcome:
        """공지 하나. 터지면 그 공지를 늦추고 다음 공지로 간다(동기화는 성공이다)."""
        try:
            return await self._classify_one(run, announcement, now=now, courses=courses)
        except Exception as exc:  # 모델 오류·시간 초과·DB 오류. 늦춘 시각 뒤에 다시 집는다
            logger.warning(
                "공지를 분류하지 못해 다음으로 미뤄요: announcement %s, %r", announcement.id, exc
            )
            await self._retry_later(announcement, now=now)
            return AnnouncementOutcome(failed=1)

    async def _retry_later(self, announcement: PendingAnnouncement, *, now: datetime) -> None:
        """실패한 공지를 늦춘다. 이것마저 실패하면 임대가 끝날 때(2시간 뒤) 다시 집힌다."""
        try:
            async with self.transaction() as conn:
                attempts = await self.repo_for(conn).retry_later(announcement.id, now=now)
        except Exception:
            logger.exception(
                "공지를 다시 볼 시각을 적지 못했어요: announcement %s", announcement.id
            )
            return
        if attempts >= MAX_ATTEMPTS:
            logger.warning(
                "공지를 %d번 처리하지 못해 줄에서 뺐어요: announcement %s",
                attempts,
                announcement.id,
            )

    async def _classify_one(
        self,
        run: AgentRun,
        announcement: PendingAnnouncement,
        *,
        now: datetime,
        courses: Mapping[int, str],
    ) -> AnnouncementOutcome:
        if announcement.classified:
            # 분류는 끝났고 공고만 못 만든 공지다. 모델을 다시 부르지 않는다
            made = await self._opportunity(run, announcement, category_hint=None, now=now)
            return AnnouncementOutcome(classified=0, opportunities=1 if made else 0)
        async with run.tool(CLASSIFY_TOOL, {"announcement_id": announcement.id}) as call:
            assert self.llm is not None
            # 공지 분류는 동기화 실행의 자식 실행이다(엔진 등록부 O2). 모델 호출은 자식에 남고 동기화 실행에는
            # 이 도구 한 줄이 남는다. 갈래는 그 과목 수강생 모두의 할 일·알림·공고가 되어 user_id를 남기지 않는다
            async with run.child(engine=CLASSIFY_ENGINE) as child:
                result = await classify(
                    self.llm,
                    model=self.classify_model,
                    title=announcement.title,
                    body=announcement.message,
                    posted_on=_posted_on(announcement, now),
                )
                await child.record_llm(
                    provider=self.llm.provider,
                    model=self.classify_model,
                    input_tokens=result.reply.usage.input_tokens,
                    output_tokens=result.reply.usage.output_tokens,
                    latency_ms=result.reply.latency_ms,
                )
                if not result.submitted:  # 제출이 없어 general로 둔 공지
                    child.review_codes = (str(ReviewCode.NO_SUBMISSION),)
            call.output = {
                "category": result.category,
                "summary": result.summary,
                "classify_run_id": child.id,
            }
        on = _schedule_day(result, now)
        scheduled: AnnouncementOutcome | None = None
        # 갈래와 일정 변경 할 일·알림을 한 트랜잭션에 쓴다. 할 일·알림 쓰기가 터지면 갈래도 되돌아가
        # 공지가 분류 전으로 남고 다시 집힌다(갈래만 남아 할 일·알림이 영영 빠지는 일이 없다)
        async with self.transaction() as conn:
            written = await self.repo_for(conn).save_classification(
                announcement.id,
                category=result.category,
                summary=result.summary,
                run_id=child.id,  # 갈래를 정한 엔진 실행(어느 엔진 버전·모델이 정했는지 거슬러 간다)
            )
            if written and on is not None:
                scheduled = await self._schedule(
                    conn, announcement, result, on=on, now=now, courses=courses
                )
        if not written:
            # 그새 다른 동기화가 먼저 분류했다(임대가 끝난 뒤 겹친 경우). 다음 일은 그쪽 갈래로 한다
            return AnnouncementOutcome()
        if scheduled is not None:
            return scheduled
        if not result.is_opportunity:  # 일반·자료, 날짜를 못 읽었거나 지난 일정 변경
            return AnnouncementOutcome(classified=1)
        made = await self._opportunity(run, announcement, category_hint=result, now=now)
        return AnnouncementOutcome(classified=1, opportunities=1 if made else 0)

    async def _schedule(
        self,
        conn: AsyncConnection,
        announcement: PendingAnnouncement,
        result: Classified,
        *,
        on: date,
        now: datetime,
        courses: Mapping[int, str],
    ) -> AnnouncementOutcome:
        """일정 변경 공지 → 그 과목 수강생 모두의 플래너 할 일 + 일정 변경 알림(F-53 2부).

        갈래를 적은 트랜잭션(`conn`) 안에서 쓴다 — 확정은 부르는 쪽이 한다.
        """
        course = courses.get(announcement.canvas_course_id, "")
        tasks = await self.repo_for(conn).add_schedule_task(
            announcement.id,
            announcement.canvas_course_id,
            title=result.change_title,
            on=on,
        )
        notices = await self.notes_for(conn).add_schedule_notices(
            announcement.canvas_course_id,
            ScheduleNotice(
                announcement_id=announcement.id,
                title=SCHEDULE_TITLE.format(course=course).strip(),
                body=result.summary or result.change_title,
            ),
            now=now,
        )
        return AnnouncementOutcome(classified=1, schedule_tasks=tasks, notices=notices)

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
        async with run.tool(EXTRACT_TOOL, {"announcement_id": announcement.id}) as call:
            # 요건 추출은 동기화 실행의 자식 실행이다(실행 트리 O1). 공고의 extraction_run_id가 이 자식이라
            # 공고 상세의 처리 과정(F-42)에 동기화의 다른 단계(과목 받기·다른 공지의 분류)가 섞이지 않는다.
            # 공고는 수강생 모두가 보므로 자식에는 user_id를 남기지 않는다(동기화한 학생은 부모에만 있다)
            async with run.child(engine=EXTRACT_ENGINE) as child:
                extraction = await agent.run(notice, child)
                child.review_codes = extraction.review_codes  # 엔진 도장(O2)
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
                    run_id=child.id,
                )
            call.output = {
                "extraction_run_id": child.id,
                "opportunity_id": opportunity_id,  # 다른 수강생의 동기화가 먼저 이었으면 null
                "requirements": len(extraction.requirements),
            }
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
        schedule_tasks=left.schedule_tasks + right.schedule_tasks,
        notices=left.notices + right.notices,
        failed=left.failed + right.failed,
    )


def _schedule_day(result: Classified, now: datetime) -> date | None:
    """플래너에 넣을 일정 변경 날. 일정 변경이 아니거나, 날짜를 못 읽었거나, **이미 지난 날**이면 None이다
    — 지난 휴강은 할 일이 아니다."""
    on = result.change_date
    if not result.is_schedule_change or on is None or on < now.astimezone(KST).date():
        return None
    return on


def _kind(hint: Classified | None) -> Category:
    """공고 종류. 분류를 다시 하지 않는 재시도에서는 모델의 값이 없어 '그 밖'이다."""
    return hint.opportunity_category if hint is not None else DEFAULT_KIND


def _posted_on(announcement: PendingAnnouncement, now: datetime) -> date:
    """연도 없는 날짜("10. 24.까지")를 읽는 기준. 게시일이 없으면 지금(KST)으로 둔다."""
    moment = announcement.posted_at or now
    return moment.astimezone(KST).date()
