"""LMS 동기화 (F-51, API 명세 8장). 과목 목록 → 과목마다 과제·제출 → 저장 → 플래너·알림.

두 곳에서 부른다. `POST /lms/sync`는 대시보드를 열 때(202 + `run_id`, 결과는 `GET /runs/{id}`)이고,
`POST /internal/jobs/lms-sync`는 30분마다 도는 배치다. 둘 다 같은 `_sync`를 쓴다.

지키는 것:
- 외부 호출은 모두 실행(`lms_sync`) 안의 도구로 기록한다. 토큰은 입력에 넣지 않는다
- LearningX를 부르는 동안 요청용 DB 연결을 쥐지 않는다(준비하기와 같다). 받아 둔 뒤 한 트랜잭션에 쓴다
- 과목의 과제 목록을 끝까지 받지 못하면 **그 과목은 저장하지 않는다**. 부분 목록으로 저장하면 못 받은
  과제가 "사라진 과제"가 된다(저장소의 `removed_at`)
- 토큰이 막히면(401) 거기서 멈추고 연결을 `error`로 바꾼다. 화면이 다시 연결을 안내한다
- 마지막 동기화가 5분 안이면 건너뛴다(명세 9장). 대시보드를 여러 번 열어도 LearningX를 또 부르지 않는다

과목 공지(F-53)는 받아 저장하고 **분류는 `app/lms/announce.py`가** 같은 실행 안에서 한다. 분류가
터져도 동기화는 성공이다 — 그 공지는 분류 전으로 남아 다음 동기화에서 다시 집힌다.

주차 항목(F-52)은 과목 공통이라 저장도 알림도 과목 단위다. 그 과목의 항목을 **이번에 처음** 받으면
한 학기 분량이 모두 "새 항목"이라 알림을 보내지 않고 저장만 한다.

공지 첨부(F-54)는 마지막에 학생 문서함에 받는다(`app/lms/files.py`). 파일 저장소 설정이 없으면 하지
않고, 실패해도 동기화는 성공이다.
"""

import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from typing import Annotated, Any

from fastapi import Depends, Request
from psycopg import AsyncConnection

from app.agent_log import AgentRun, LogConnect, abandon_run, agent_run, start_run
from app.background import RunnerDep, TaskRunner
from app.calendar import EVENT_MINUTES, GoogleCalendarClient, assignment_title, event_id_for
from app.calendar.service import CalendarService
from app.config import Settings, get_settings
from app.crypto import decrypt
from app.eligibility import KST, Department
from app.errors import ApiError
from app.extraction.agent import ExtractionAgent
from app.extraction.models import Limits
from app.llm import LlmClient
from app.llm.deps import LlmDep
from app.lms.announce import AnnouncementOutcome, AnnouncementService
from app.lms.announcements import CanvasAnnouncement, announcements
from app.lms.assignments import CanvasAssignment, assignments
from app.lms.client import LearningXClient, LearningXError
from app.lms.files import AttachmentSaver
from app.lms.modules import CanvasModuleItem, module_items, needs_items
from app.lms.service import API_ERROR, NOT_CONNECTED, TOKEN_EXPIRED, student_courses
from app.repositories.announcements import AnnouncementRepository
from app.repositories.calendar import AssignmentDeadline, CalendarRepository
from app.repositories.files import FileRepository
from app.repositories.lms import (
    AssignmentChanges,
    CourseRow,
    LmsRepository,
    ModuleChanges,
    SavedAssignment,
    SavedItem,
)
from app.repositories.notifications import (
    AssignmentNotice,
    MaterialNotice,
    NotificationRepository,
)
from app.schemas.lms import SAVE_TOOL, SyncCounts, SyncResponse, SyncSkipped, SyncStarted
from app.uploads.storage import SupabaseStorage, get_storage

logger = logging.getLogger(__name__)
Connect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]

SKIP_AFTER = timedelta(minutes=5)  # 이 안에 동기화했으면 건너뛴다(명세 9장)
BATCH_USERS = 50  # 배치 한 번에 보는 사용자 수 상한. 넘으면 다음 차례에 간다
STOPPED = "동기화를 시작하지 못했어요. 잠시 후 다시 시도해 주세요."
TOKEN_UNREADABLE = "저장한 토큰을 읽을 수 없어요. 다시 연결해 주세요."
NEW_TITLE = "{course} 새 과제가 올라왔어요"
MATERIAL_TITLE = "{course} {module} 자료가 올라왔어요"


class StoredTokenUnreadable(Exception):
    """저장한 토큰을 복호화하지 못했다(암호화 키를 바꿨거나 값이 깨졌다).

    LearningX가 거절한 것이 아니므로 연결을 `error`로 바꾸지 않는다 — 키 문제로 모든 사용자에게
    "토큰이 만료됐어요"를 띄우면 멀쩡한 토큰을 다시 받게 만든다(app/crypto.py의 키 교체).
    """


@dataclass(frozen=True)
class Repos:
    """한 트랜잭션에서 쓰는 저장소 묶음. 테스트는 가짜로 바꿔 끼운다."""

    lms: LmsRepository
    notes: NotificationRepository
    calendar: CalendarRepository
    announcements: AnnouncementRepository

    @classmethod
    def of(cls, conn: AsyncConnection) -> "Repos":
        return cls(
            lms=LmsRepository(conn),
            notes=NotificationRepository(conn),
            calendar=CalendarRepository(conn),
            announcements=AnnouncementRepository(conn),
        )


@dataclass(frozen=True)
class _EventPlan:
    """Google에 넣거나 고칠 일정 하나. 트랜잭션을 닫은 뒤에 쓰려고 미리 모은다."""

    event_id: str
    title: str
    due_at: datetime
    new: bool
    external: str | None = None


@dataclass(frozen=True)
class SyncJob:
    run_id: str
    user_id: str
    now: datetime
    token: str = field(repr=False)  # 복호화한 토큰. 실수로 찍지 않게 repr에서 뺀다


@dataclass(frozen=True)
class SyncOutcome:
    """동기화 한 번의 결과. `GET /runs/{id}`가 보여 주는 수와 같다(명세 9장)."""

    courses: int = 0
    created: int = 0
    due_changed: int = 0
    submitted: int = 0
    new_items: int = 0  # 처음 본 주차 항목(F-52)
    new_announcements: int = 0  # 처음 본 과목 공지(F-53)
    classified: int = 0  # 그중 갈래를 정한 공지 수
    announcement_opportunities: int = 0  # 기회성 공지로 만든 공고 수
    schedule_tasks: int = 0  # 일정 변경 공지로 넣은 플래너 할 일 수(수강생 전체 합)
    events: int = 0  # 캘린더에 넣은 과제 마감(F-51)
    moved_events: int = 0  # 마감이 바뀌어 시각을 고친 일정
    notices: int = 0
    failed_courses: int = 0

    def counts(self) -> SyncCounts:
        return SyncCounts(new=self.created, due_changed=self.due_changed, submitted=self.submitted)


@dataclass
class BatchOutcome:
    """배치 한 번의 결과(명세 12장). 실패한 사용자는 다음 차례에 다시 본다."""

    users: int = 0
    synced: int = 0
    failed: int = 0
    skipped: int = 0  # 그새 다른 쪽이 동기화를 시작했거나 연결이 사라진 사람
    new_assignments: int = 0
    due_changed: int = 0
    submitted: int = 0


class LmsSyncService:
    def __init__(
        self,
        *,
        transaction: Connect,
        log_connection: LogConnect,
        client: LearningXClient,
        calendar_client: GoogleCalendarClient,
        encryption_key: str,
        runner: TaskRunner,
        announcer: AnnouncementService | None = None,
        repos: Callable[[AsyncConnection], Repos] = Repos.of,
        storage: SupabaseStorage | None = None,
        files: Callable[[AsyncConnection], FileRepository] = FileRepository,
    ) -> None:
        self.transaction = transaction  # 블록이 끝나면 커밋하는 연결(요청 트랜잭션과 따로)
        self.log_connection = log_connection
        self.client = client
        self.calendar_client = calendar_client
        self.key = encryption_key
        self.runner = runner
        self.announcer = announcer  # 없으면 공지를 저장만 하고 분류하지 않는다(F-53)
        self.repos = repos
        self.storage = storage  # 없으면 공지 첨부를 받지 않는다(F-54)
        self.files = files

    # ── 사용자가 눌렀을 때 ──────────────────────────────────────────────────

    async def start(self, user_id: str, *, now: datetime) -> SyncResponse:
        """실행 행을 만들고 일을 띄운다. 얼마 전에 동기화했으면 건너뛴 응답(200)이다."""
        async with self.transaction() as conn:
            repo = self.repos(conn).lms
            connection = await repo.connection(user_id)
            if connection is None:
                raise ApiError(404, "LMS_NOT_CONNECTED", NOT_CONNECTED)
            # 한 문장으로 "내가 한다"고 못 박는다. 5분 안에 이미 했거나 다른 탭이 가져가면 False다
            claimed = await repo.claim_sync(user_id, now=now, before=now - SKIP_AFTER)
        if not claimed:
            last = connection.last_synced_at
            return SyncSkipped(last_synced_at=last.astimezone(KST) if last else None)
        try:
            token = self._token(connection.access_token)
        except StoredTokenUnreadable as exc:
            logger.warning("저장한 LMS 토큰을 읽지 못했어요: user %s", user_id)
            raise ApiError(422, "LMS_TOKEN_INVALID", TOKEN_UNREADABLE) from exc
        run_id = await start_run(self.log_connection, trigger="lms_sync", user_id=user_id)
        job = SyncJob(run_id=run_id, user_id=user_id, now=now, token=token)
        work = self.execute(job)
        try:
            await self.runner.start(work)
        except Exception:  # 일을 띄우지 못했다. 실행이 running으로 남지 않게 닫는다
            work.close()
            await self._close(run_id)
            raise ApiError(500, "INTERNAL_ERROR", STOPPED) from None
        return SyncStarted(run_id=run_id, status="running")

    async def execute(self, job: SyncJob) -> None:
        """뒤에서 도는 일. 실패해도 실행 기록에 남고 연결 상태를 바꾼다."""
        try:
            async with agent_run(
                self.log_connection, trigger="lms_sync", user_id=job.user_id, run_id=job.run_id
            ) as run:
                await self._sync(run, job)
        except Exception as exc:
            logger.warning("LMS 동기화 실패: user %s, run %s, %r", job.user_id, job.run_id, exc)
            await self._mark_error(job.user_id, exc)
            # 로그 연결을 얻지 못해 agent_run 밖에서 끝난 경우까지 닫는다(준비하기와 같다).
            # 닫지 않으면 GET /runs/{id}가 영원히 running이고 성공률 지표의 분모만 늘어난다
            await self._close(job.run_id)

    # ── 30분 배치 ───────────────────────────────────────────────────────────

    async def sync_all(self, *, now: datetime, limit: int = BATCH_USERS) -> BatchOutcome:
        """연결된 사용자를 차례로 동기화한다. 한 사람이 실패해도 다음 사람을 계속한다."""
        async with self.transaction() as conn:
            users = await self.repos(conn).lms.connected_users(before=now - SKIP_AFTER, limit=limit)
        result = BatchOutcome(users=len(users))
        for user_id in users:
            try:
                outcome = await self._run_for(user_id, now=now)
            except StoredTokenUnreadable:  # 우리 키 문제다. 사용자 연결은 건드리지 않는다
                logger.warning("저장한 LMS 토큰을 읽지 못했어요: user %s", user_id)
                result.failed += 1
                continue
            except Exception as exc:  # 토큰이 막혔거나 LearningX가 답하지 않았다
                logger.warning("LMS 배치 동기화 실패: user %s, %r", user_id, exc)
                result.failed += 1
                await self._mark_error(user_id, exc)
                continue
            if outcome is None:  # 그새 다른 쪽이 동기화를 시작했거나 연결이 사라졌다
                result.skipped += 1
                continue
            result.synced += 1
            result.new_assignments += outcome.created
            result.due_changed += outcome.due_changed
            result.submitted += outcome.submitted
        return result

    async def _run_for(self, user_id: str, *, now: datetime) -> SyncOutcome | None:
        """한 사람을 동기화한다. 그새 다른 쪽이 가져갔거나 연결이 사라졌으면 None이다."""
        async with self.transaction() as conn:
            repo = self.repos(conn).lms
            connection = await repo.connection(user_id)
            if connection is None:  # 그새 해제했다
                return None
            if not await repo.claim_sync(user_id, now=now, before=now - SKIP_AFTER):
                return None
        token = self._token(connection.access_token)
        async with agent_run(self.log_connection, trigger="lms_sync", user_id=user_id) as run:
            return await self._sync(run, SyncJob(run.id, user_id, now, token))

    # ── 동기화 본체 ─────────────────────────────────────────────────────────

    async def _sync(self, run: AgentRun, job: SyncJob) -> SyncOutcome:
        """과목 → 과제 → 저장. 외부 호출을 모두 마친 뒤에 쓰기 트랜잭션을 연다."""
        async with run.tool("fetch_lms_courses") as call:
            courses = student_courses(await self._fetch_courses(job.token))
            call.output = {"courses": len(courses)}
        async with self.transaction() as conn:
            repo = self.repos(conn).lms
            await repo.save_courses(job.user_id, courses, now=job.now)
            rows = await repo.active_courses(job.user_id)
        fetched, failed = await self._fetch_assignments(run, job, rows)
        modules = await self._fetch_modules(run, job, rows)
        notices = await self._fetch_announcements(run, job, rows)
        if rows and failed and not fetched:
            # 과목이 있는데 한 과목도 받지 못했다. 저장할 것도 없고 성공으로 적으면 안 된다
            # (`touch_synced`가 오류 표시를 지워 버린다). 다음 배치에서 다시 시도한다
            raise ApiError(502, "LMS_API_ERROR", API_ERROR)
        outcome, changes = await self._save(job, fetched, modules, notices, failed=failed)
        outcome = await self._calendar(run, job, outcome, changes)
        outcome = await self._classify(run, job, outcome, rows)
        await self._attachments(run, job, notices)
        async with run.tool(SAVE_TOOL) as call:
            # `GET /runs/{id}`가 이 출력으로 결과를 만든다(repositories/runs.py)
            call.output = {
                "courses": outcome.courses,
                "new": outcome.created,
                "due_changed": outcome.due_changed,
                "submitted": outcome.submitted,
                "new_module_items": outcome.new_items,
                "new_announcements": outcome.new_announcements,
                "classified_announcements": outcome.classified,
                "announcement_opportunities": outcome.announcement_opportunities,
                "schedule_tasks": outcome.schedule_tasks,
                "notices": outcome.notices,
                "failed_courses": outcome.failed_courses,
                "calendar_events": outcome.events,
                "calendar_moved": outcome.moved_events,
            }
        return outcome

    async def _fetch_assignments(
        self, run: AgentRun, job: SyncJob, rows: list[CourseRow]
    ) -> tuple[list[tuple[CourseRow, list[CanvasAssignment]]], int]:
        """과목마다 과제를 받는다. 한 과목이 실패하면 그 과목만 빼고 이어 간다(401은 멈춘다)."""
        fetched: list[tuple[CourseRow, list[CanvasAssignment]]] = []
        failed = 0
        async with run.tool("fetch_lms_assignments", {"courses": len(rows)}) as call:
            for course in rows:
                try:
                    raw = await self.client.assignments(job.token, course.canvas_course_id)
                except LearningXError as exc:
                    failed += self._skip(exc, course, what="과제 목록")
                    continue
                fetched.append((course, assignments(raw)))
            call.output = {
                "courses": len(fetched),
                "assignments": sum(len(items) for _, items in fetched),
                "failed_courses": failed,
            }
        return fetched, failed

    async def _fetch_modules(
        self, run: AgentRun, job: SyncJob, rows: list[CourseRow]
    ) -> list[tuple[CourseRow, list[CanvasModuleItem]]]:
        """과목마다 주차 모듈·항목을 받는다(F-52). 실패한 과목은 그냥 두고 넘어간다.

        과제와 달리 실패를 세지 않는다 — 과제는 받았는데 주차 항목만 못 받았다고 동기화 전체를
        실패로 적을 이유가 없다(새 자료 수가 잠깐 비어 있을 뿐이다).
        """
        fetched: list[tuple[CourseRow, list[CanvasModuleItem]]] = []
        async with run.tool("fetch_lms_modules", {"courses": len(rows)}) as call:
            for course in rows:
                try:
                    modules = await self.client.modules(job.token, course.canvas_course_id)
                    extra = await self._missing_items(job, course, modules)
                except LearningXError as exc:
                    self._skip(exc, course, what="주차 모듈")
                    continue
                fetched.append((course, module_items(modules, extra=extra)))
            call.output = {
                "courses": len(fetched),
                "items": sum(len(items) for _, items in fetched),
            }
        return fetched

    async def _fetch_announcements(
        self, run: AgentRun, job: SyncJob, rows: list[CourseRow]
    ) -> list[tuple[CourseRow, list[CanvasAnnouncement]]]:
        """과목마다 공지를 받는다(F-53). 주차 항목과 같이 실패를 세지 않는다.

        공지를 못 받았다고 동기화 전체를 실패로 적을 이유가 없다 — 과제·주차 자료는 이미 받았고,
        그 과목 공지는 다음 동기화에서 다시 받는다.
        """
        fetched: list[tuple[CourseRow, list[CanvasAnnouncement]]] = []
        async with run.tool("fetch_lms_announcements", {"courses": len(rows)}) as call:
            for course in rows:
                try:
                    raw = await self.client.announcements(job.token, course.canvas_course_id)
                except LearningXError as exc:
                    self._skip(exc, course, what="공지 목록")
                    continue
                fetched.append((course, announcements(raw)))
            call.output = {
                "courses": len(fetched),
                "announcements": sum(len(items) for _, items in fetched),
            }
        return fetched

    async def _missing_items(
        self, job: SyncJob, course: CourseRow, modules: list[Any]
    ) -> dict[int, list[Any]]:
        """`include[]=items`로 항목이 오지 않은 모듈만 따로 받는다(녹화에서는 없었다)."""
        extra: dict[int, list[Any]] = {}
        for module in modules:
            number = needs_items(module)
            if number is None:
                continue
            extra[number] = await self.client.module_items(
                job.token, course.canvas_course_id, number
            )
        return extra

    def _skip(self, exc: LearningXError, course: CourseRow, *, what: str) -> int:
        """한 과목을 건너뛴다. 토큰이 막힌 경우(401)는 남은 과목도 못 받으니 멈춘다."""
        if exc.unauthorized:
            raise ApiError(422, "LMS_TOKEN_INVALID", TOKEN_EXPIRED) from exc
        logger.warning(
            "%s을 받지 못해 그 과목은 두고 넘어가요: course %s, status %s",
            what,
            course.canvas_course_id,
            exc.status,
        )
        return 1

    async def _save(
        self,
        job: SyncJob,
        fetched: list[tuple[CourseRow, list[CanvasAssignment]]],
        modules: list[tuple[CourseRow, list[CanvasModuleItem]]],
        notices: list[tuple[CourseRow, list[CanvasAnnouncement]]],
        *,
        failed: int,
    ) -> tuple[SyncOutcome, AssignmentChanges]:
        """받아 둔 과제·주차 항목을 한 트랜잭션에 쓰고, 플래너·알림을 맞춘다.

        바뀐 과제도 함께 돌려준다 — 캘린더 단계(`_calendar`)가 그걸 보고 넣을 것을 고른다.
        """
        changes = AssignmentChanges()
        alerts: list[AssignmentNotice] = []
        items = ModuleChanges()
        made = 0
        fresh_notices = 0
        async with self.transaction() as conn:
            repos = self.repos(conn)
            repo, notes = repos.lms, repos.notes
            for course, assignment_items in fetched:
                one = await repo.save_assignments(
                    job.user_id, course.id, assignment_items, now=job.now
                )
                changes = changes + one
                # 이미 낸 과제는 알리지 않는다(연결 첫 동기화에 지난 과제가 한꺼번에 들어온다)
                alerts += [_notice(course, saved) for saved in one.created if not saved.submitted]
            await repo.sync_planner(job.user_id, changes, now=job.now)
            # 제출한 과제는 알림을 멈춘다(명세 10장). 새 과제 알림은 찾은 때 바로 보낸다
            await notes.drop_assignment_notices(job.user_id, changes.submitted)
            made += await notes.add_assignment_notices(job.user_id, alerts, now=job.now)
            for course, module_list in modules:
                one_course = await repo.save_module_items(
                    job.user_id, course.canvas_course_id, module_list, now=job.now
                )
                items = items + one_course
                # 주차 항목은 과목 공통이라 그 과목 수강생 모두에게 간다(첫 수집이면 보내지 않는다)
                made += await notes.add_material_notices(
                    course.canvas_course_id,
                    [_material(course, saved) for saved in one_course.notifiable],
                    now=job.now,
                )
            for course, announcement_list in notices:
                # 공지도 과목 공통 표다(ERD 3-2). 저장만 하고 알림은 만들지 않는다 — 갈래를 정한
                # 뒤에 알릴 것을 고른다(일정 변경 알림은 F-53 2부다)
                saved_notices = await repos.announcements.save(
                    course.canvas_course_id, announcement_list, now=job.now
                )
                fresh_notices += len(saved_notices)
            await repo.touch_synced(job.user_id, now=job.now)
        return (
            SyncOutcome(
                courses=len(fetched),
                created=len(changes.created),
                due_changed=len(changes.due_changed),
                submitted=len(changes.submitted),
                new_items=len(items.created),
                new_announcements=fresh_notices,
                notices=made,
                failed_courses=failed,
            ),
            changes,
        )

    # ── 공지 분류 (F-53) ────────────────────────────────────────────────────

    async def _classify(
        self, run: AgentRun, job: SyncJob, outcome: SyncOutcome, rows: list[CourseRow]
    ) -> SyncOutcome:
        """받은 공지의 갈래를 정하고 기회성 공지를 공고로 만든다(`app/lms/announce.py`).

        **실패해도 동기화는 성공이다.** 공지는 이미 저장했고, 분류하지 못한 공지는 분류 전으로 남아
        다음 동기화에서 다시 집힌다. 모델이 없으면(설정이 비면) 아무것도 하지 않는다.
        """
        if self.announcer is None:
            return outcome
        try:
            made = await self.announcer.run(
                run,
                now=job.now,
                courses={course.canvas_course_id: course.short_name for course in rows},
            )
        except Exception as exc:  # pending 조회가 터진 경우까지. 다음 동기화에서 다시 본다
            logger.warning("공지 분류를 건너뛰어요: user %s, %r", job.user_id, exc)
            return outcome
        if made == AnnouncementOutcome():
            return outcome
        return SyncOutcome(
            **{
                **outcome.__dict__,
                "classified": made.classified,
                "announcement_opportunities": made.opportunities,
                "schedule_tasks": made.schedule_tasks,
                # 일정 변경 알림은 과제·자료 알림과 같은 칸에 더해 센다(명세 8장의 notices)
                "notices": outcome.notices + made.notices,
            }
        )

    # ── 공지 첨부 (F-54) ────────────────────────────────────────────────────

    async def _attachments(
        self,
        run: AgentRun,
        job: SyncJob,
        notices: list[tuple[CourseRow, list[CanvasAnnouncement]]],
    ) -> None:
        """받은 공지의 첨부를 학생 문서함에 넣는다(`app/lms/files.py`).

        파일 저장소 설정이 없으면 하지 않는다. **실패해도 동기화는 성공이다** — 공지는 이미 저장했고,
        못 받은 첨부는 "저장 전"으로 남아 다음 동기화가 다시 받는다.
        """
        if self.storage is None or not notices:
            return
        saver = AttachmentSaver(
            transaction=self.transaction, client=self.client, storage=self.storage, files=self.files
        )
        try:
            await saver.run(run, job.user_id, notices)
        except Exception as exc:  # 이미 저장한 첨부 조회가 터진 경우까지. 다음 동기화에서 다시 본다
            logger.warning("공지 첨부 저장을 건너뛰어요: user %s, %r", job.user_id, exc)

    # ── 캘린더 (F-51·F-32) ──────────────────────────────────────────────────

    async def _calendar(
        self, run: AgentRun, job: SyncJob, outcome: SyncOutcome, changes: AssignmentChanges
    ) -> SyncOutcome:
        """새 과제 마감을 캘린더에 넣고, 바뀐 마감은 이미 넣은 일정의 시각을 고친다.

        설정(`calendar_auto_lms`, 기본 켬)을 끄면 하지 않고, Google 연결이 없으면 조용히 건너뛴다.
        **실패해도 동기화는 성공이다** — 과제·주차 자료는 이미 저장했고, 다음 동기화가 다시 시도한다.
        """
        fresh = [one for one in changes.created if one.due_at and not one.submitted]
        moved = [one for one in changes.due_changed if one.due_at]
        async with self.transaction() as conn:
            repos = self.repos(conn)
            if not await repos.calendar.auto_lms(job.user_id):
                return outcome  # 설정을 껐다. 도구 호출도 열지 않는다
            # 앞 동기화에서 Google이 막혀 넣다 만 과제를 여기서 줍는다(그러지 않으면 영영 안 들어간다)
            done = {one.id for one in fresh} | {one.id for one in moved}
            retry = [
                one
                for one in await repos.calendar.unfinished_assignment_events(job.user_id)
                if one.id not in done
            ]
        if not fresh and not moved and not retry:
            return outcome
        async with run.tool(
            "register_calendar",
            {"new": len(fresh), "due_changed": len(moved), "retry": len(retry)},
        ) as call:
            plan = await self._calendar_plan(job, fresh, moved, retry)
            if plan is None:  # Google 연결이 없거나 토큰을 받지 못했다
                call.output = {"skipped": True}
                return outcome
            token, targets = plan
            made = await self._write_calendar(job, token, targets)
            call.output = {"created": made.events, "moved": made.moved_events}
            return SyncOutcome(
                **{
                    **outcome.__dict__,
                    "events": made.events,
                    "moved_events": made.moved_events,
                }
            )

    async def _calendar_plan(
        self,
        job: SyncJob,
        fresh: list[SavedAssignment],
        moved: list[SavedAssignment],
        retry: list[AssignmentDeadline],
    ) -> tuple[str, list["_EventPlan"]] | None:
        """연결을 보고 넣을 것을 고른다. 자리도 미리 잡아 둔다(일정 번호를 정하려고).

        Google 호출은 이 트랜잭션을 닫은 뒤에 한다(요청용 연결을 쥐고 외부를 부르지 않는다).
        """
        async with self.transaction() as conn:
            repos = self.repos(conn)
            service = self._calendar_service(repos.calendar)
            try:
                token = await service.access_token(job.user_id, job.now)
            except ApiError as exc:
                # 캘린더를 안 쓰는 학생(연결 없음)이거나 Google 토큰 서버가 막혔다.
                # 어느 쪽이든 동기화는 성공이다 — 과제·주차 자료는 이미 저장했다
                logger.info("캘린더를 건너뛰어요: %s", exc.code)
                return None
            titles = await repos.lms.assignment_titles(
                job.user_id, [one.id for one in fresh + moved]
            )
            existing = await repos.calendar.events_for_assignments(
                job.user_id, [one.id for one in moved]
            )
            plans: list[_EventPlan] = []
            for saved in fresh:
                title = titles.get(saved.id)
                if title is None or saved.due_at is None:
                    continue
                row = await repos.calendar.reserve(
                    job.user_id,
                    provider="google",
                    title=title,
                    starts_at=saved.due_at - timedelta(minutes=EVENT_MINUTES),
                    lms_assignment_id=saved.id,
                )
                if row.external_event_id is None:
                    plans.append(_EventPlan(row.id, title, saved.due_at, new=True))
                elif row.starts_at != saved.due_at - timedelta(minutes=EVENT_MINUTES):
                    # 지웠다 다시 올라온 과제다(행은 그대로 살아 있다). 마감이 달라졌으면 고친다
                    plans.append(
                        _EventPlan(
                            row.id, title, saved.due_at, new=False, external=row.external_event_id
                        )
                    )
            for saved in moved:
                row, title = existing.get(saved.id), titles.get(saved.id)
                if row is None or title is None or saved.due_at is None:
                    continue  # 캘린더에 없던 과제는 마감이 바뀌어도 새로 넣지 않는다
                plans.append(
                    _EventPlan(
                        row.id, title, saved.due_at, new=False, external=row.external_event_id
                    )
                )
            for pending in retry:  # 자리만 잡고 못 넣은 과제. 같은 자리로 다시 넣는다
                if pending.due_at is None:
                    continue
                row = await repos.calendar.reserve(
                    job.user_id,
                    provider="google",
                    title=assignment_title(pending.course, pending.title),
                    starts_at=pending.due_at - timedelta(minutes=EVENT_MINUTES),
                    lms_assignment_id=pending.id,
                )
                if row.external_event_id is None:
                    plans.append(_EventPlan(row.id, row.title, pending.due_at, new=True))
        return token, plans

    async def _write_calendar(
        self, job: SyncJob, token: str, plans: list["_EventPlan"]
    ) -> SyncOutcome:
        """Google을 부르고(트랜잭션 밖) 결과를 기록한다. 한 건이 실패해도 나머지를 계속한다."""
        made = SyncOutcome()
        for plan in plans:
            try:
                if plan.new:
                    external = await self._calendar_service(None).insert(
                        token,
                        event_id=event_id_for(plan.event_id),
                        title=plan.title,
                        ends_at=plan.due_at.astimezone(KST),
                    )
                    await self._attach_event(job, plan, external=external)
                    made = SyncOutcome(**{**made.__dict__, "events": made.events + 1})
                    continue
                if plan.external is None:  # 넣다 말았던 일정이다. 다시 넣는다
                    external = await self._calendar_service(None).insert(
                        token,
                        event_id=event_id_for(plan.event_id),
                        title=plan.title,
                        ends_at=plan.due_at.astimezone(KST),
                    )
                    await self._attach_event(job, plan, external=external)
                    made = SyncOutcome(**{**made.__dict__, "events": made.events + 1})
                    continue
                found = await self._calendar_service(None).move(
                    token,
                    event_id=plan.external,
                    title=plan.title,
                    ends_at=plan.due_at.astimezone(KST),
                )
                if found is None:  # 학생이 캘린더에서 지웠다. 되살리지 않는다
                    continue
                await self._attach_event(job, plan, external=plan.external)
                made = SyncOutcome(**{**made.__dict__, "moved_events": made.moved_events + 1})
            except ApiError as exc:
                logger.warning(
                    "과제 마감을 캘린더에 넣지 못했어요: event %s, %s", plan.event_id, exc.code
                )
        return made

    async def _attach_event(self, job: SyncJob, plan: "_EventPlan", *, external: str) -> None:
        async with self.transaction() as conn:
            repos = self.repos(conn)
            await repos.calendar.attach(job.user_id, plan.event_id, external)
            await repos.calendar.move(
                job.user_id,
                plan.event_id,
                starts_at=plan.due_at - timedelta(minutes=EVENT_MINUTES),
            )

    def _calendar_service(self, repo: CalendarRepository | None) -> CalendarService:
        """캘린더 서비스. Google만 부를 때는 저장소가 필요 없다(토큰은 이미 받아 뒀다)."""
        return CalendarService(repo, self.calendar_client, self.key)  # type: ignore[arg-type]

    # ── 거들기 ──────────────────────────────────────────────────────────────

    def _token(self, encrypted: str) -> str:
        """저장한 토큰을 꺼낸다. 읽지 못하면 StoredTokenUnreadable이다(연결 상태는 건드리지 않는다)."""
        try:
            return decrypt(encrypted, self.key)
        except Exception as exc:
            raise StoredTokenUnreadable from exc

    async def _fetch_courses(self, token: str) -> list[dict[str, Any]]:
        try:
            return await self.client.courses(token)
        except LearningXError as exc:
            if exc.unauthorized:
                raise ApiError(422, "LMS_TOKEN_INVALID", TOKEN_EXPIRED) from exc
            logger.warning("LearningX 과목 목록 실패: status %s", exc.status)
            raise ApiError(502, "LMS_API_ERROR", API_ERROR) from exc

    async def _mark_error(self, user_id: str, exc: BaseException) -> None:
        """토큰이 막힌 경우만 연결을 error로 바꾼다. LearningX가 잠깐 답하지 않은 것은 두고 다시 시도한다."""
        if not (isinstance(exc, ApiError) and exc.code == "LMS_TOKEN_INVALID"):
            return
        try:
            async with self.transaction() as conn:
                await self.repos(conn).lms.mark_error(user_id, exc.message)
        except Exception:
            logger.exception("연결 상태를 바꾸지 못했어요: user %s", user_id)

    async def _close(self, run_id: str) -> None:
        try:
            await abandon_run(self.log_connection, run_id, ApiError(500, "INTERNAL_ERROR", STOPPED))
        except Exception:
            logger.exception("LMS 동기화 실행을 닫지 못했어요: run %s", run_id)


def _notice(course: CourseRow, saved: SavedAssignment) -> AssignmentNotice:
    """새 과제 알림 문구. 제목은 과목 이름, 본문은 과제와 마감(KST)이다."""
    body = saved.title
    if saved.due_at is not None:
        # %-m은 윈도에서 안 되는 서식이라 손으로 붙인다(테스트·CLI를 윈도에서도 돌린다)
        when = saved.due_at.astimezone(KST)
        body = f"{saved.title} · 마감 {when.month}/{when.day} {when:%H:%M}"
    return AssignmentNotice(
        assignment_id=saved.id, title=NEW_TITLE.format(course=course.short_name), body=body
    )


def _material(course: CourseRow, saved: SavedItem) -> MaterialNotice:
    """새 주차 항목 알림 문구(명세 10장 예시와 같은 꼴): "기계학습 8주차 자료가 올라왔어요"."""
    return MaterialNotice(
        item_id=saved.id,
        title=MATERIAL_TITLE.format(course=course.short_name, module=saved.module_name),
        body=saved.title,
    )


def extraction_agent(
    llm: LlmClient, settings: Settings, departments: Sequence[Department]
) -> ExtractionAgent:
    """기회성 공지의 요건을 뽑는 에이전트. 학교 공지 가져오기와 같은 모델·상한을 쓴다."""
    return ExtractionAgent(
        llm,
        model=settings.extraction_model,
        vision_model=settings.vision_model,
        departments=departments,
        limits=Limits(
            max_reads=settings.extraction_max_reads, max_tokens=settings.extraction_max_tokens
        ),
    )


def lms_sync_service_for(
    state: Any, *, settings: Settings, llm: LlmClient | None, runner: TaskRunner
) -> LmsSyncService:
    """동기화 서비스를 만든다. 요청 밖(스케줄러)에서도 쓰려고 `app.state`를 직접 받는다."""
    pool, log_pool = getattr(state, "pool", None), getattr(state, "log_pool", None)
    if pool is None or log_pool is None:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    announcer = (
        AnnouncementService(
            transaction=pool.connection,
            llm=llm,
            classify_model=settings.classify_model,
            agent_for=partial(extraction_agent, llm, settings),
            lms_base=settings.lms_api_base,
        )
        if llm is not None
        else None  # 모델 설정이 없으면 공지를 저장만 한다(F-53)
    )
    storage = get_storage(settings)
    return LmsSyncService(
        transaction=pool.connection,
        log_connection=log_pool.connection,
        client=LearningXClient(api_base=settings.lms_api_base),
        calendar_client=GoogleCalendarClient(
            api_base=settings.google_calendar_api_base,
            token_url=settings.google_token_url,
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
        ),
        encryption_key=settings.token_encryption_key,
        runner=runner,
        announcer=announcer,
        # 저장소 설정(SUPABASE_SERVICE_ROLE_KEY·SUPABASE_URL)이 없으면 공지 첨부를 받지 않는다(F-54)
        storage=storage if storage.ready else None,
    )


def get_lms_sync_service(
    request: Request,
    runner: RunnerDep,
    llm: LlmDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> LmsSyncService:
    return lms_sync_service_for(request.app.state, settings=settings, llm=llm, runner=runner)


LmsSyncServiceDep = Annotated[LmsSyncService, Depends(get_lms_sync_service)]
