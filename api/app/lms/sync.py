"""LMS 동기화 (F-51, API 명세 8장). 과목 목록 → 과목마다 과제·제출 → 저장 → 플래너·알림.

두 곳에서 부른다. `POST /lms/sync`는 대시보드를 열 때(202 + `run_id`, 결과는 `GET /runs/{id}`)이고,
`POST /internal/jobs/lms-sync`는 30분마다 도는 배치다. 둘 다 같은 `_sync`를 쓴다.

지키는 것:
- 외부 호출은 모두 실행(`lms_sync`) 안의 도구로 기록한다(api/CLAUDE.md). 토큰은 입력에 넣지 않는다
- LearningX를 부르는 동안 요청용 DB 연결을 쥐지 않는다(준비하기와 같다). 받아 둔 뒤 한 트랜잭션에 쓴다
- 과목의 과제 목록을 끝까지 받지 못하면 **그 과목은 저장하지 않는다**. 부분 목록으로 저장하면 못 받은
  과제가 "사라진 과제"가 된다(저장소의 `removed_at`)
- 토큰이 막히면(401) 거기서 멈추고 연결을 `error`로 바꾼다. 화면이 다시 연결을 안내한다
- 마지막 동기화가 5분 안이면 건너뛴다(명세 9장). 대시보드를 여러 번 열어도 LearningX를 또 부르지 않는다

캘린더 등록은 아직 하지 않는다(사용자 구글 캘린더에 쓰는 일이라 따로 정한다). 과목 공지는 F-53이다.

주차 항목(F-52)은 과목 공통이라 저장도 알림도 과목 단위다. 그 과목의 항목을 **이번에 처음** 받으면
한 학기 분량이 모두 "새 항목"이라 알림을 보내지 않고 저장만 한다.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, Request
from psycopg import AsyncConnection

from app.agent_log import AgentRun, LogConnect, abandon_run, agent_run, start_run
from app.background import RunnerDep, TaskRunner
from app.config import Settings, get_settings
from app.crypto import decrypt
from app.eligibility import KST
from app.errors import ApiError
from app.lms.assignments import CanvasAssignment, assignments
from app.lms.client import LearningXClient, LearningXError
from app.lms.modules import CanvasModuleItem, module_items, needs_items
from app.lms.service import API_ERROR, NOT_CONNECTED, TOKEN_EXPIRED, student_courses
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
    """한 트랜잭션에서 쓰는 저장소 묶음. 테스트는 가짜로 바꿔 끼운다(api/CLAUDE.md)."""

    lms: LmsRepository
    notes: NotificationRepository

    @classmethod
    def of(cls, conn: AsyncConnection) -> "Repos":
        return cls(lms=LmsRepository(conn), notes=NotificationRepository(conn))


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
        encryption_key: str,
        runner: TaskRunner,
        repos: Callable[[AsyncConnection], Repos] = Repos.of,
    ) -> None:
        self.transaction = transaction  # 블록이 끝나면 커밋하는 연결(요청 트랜잭션과 따로)
        self.log_connection = log_connection
        self.client = client
        self.key = encryption_key
        self.runner = runner
        self.repos = repos

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
        if rows and failed and not fetched:
            # 과목이 있는데 한 과목도 받지 못했다. 저장할 것도 없고 성공으로 적으면 안 된다
            # (`touch_synced`가 오류 표시를 지워 버린다). 다음 배치에서 다시 시도한다
            raise ApiError(502, "LMS_API_ERROR", API_ERROR)
        outcome = await self._save(job, fetched, modules, failed=failed)
        async with run.tool(SAVE_TOOL) as call:
            # `GET /runs/{id}`가 이 출력으로 결과를 만든다(repositories/runs.py)
            call.output = {
                "courses": outcome.courses,
                "new": outcome.created,
                "due_changed": outcome.due_changed,
                "submitted": outcome.submitted,
                "new_module_items": outcome.new_items,
                "notices": outcome.notices,
                "failed_courses": outcome.failed_courses,
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
        *,
        failed: int,
    ) -> SyncOutcome:
        """받아 둔 과제·주차 항목을 한 트랜잭션에 쓰고, 플래너·알림을 맞춘다."""
        changes = AssignmentChanges()
        notices: list[AssignmentNotice] = []
        items = ModuleChanges()
        made = 0
        async with self.transaction() as conn:
            repos = self.repos(conn)
            repo, notes = repos.lms, repos.notes
            for course, assignment_items in fetched:
                one = await repo.save_assignments(
                    job.user_id, course.id, assignment_items, now=job.now
                )
                changes = changes + one
                # 이미 낸 과제는 알리지 않는다(연결 첫 동기화에 지난 과제가 한꺼번에 들어온다)
                notices += [_notice(course, saved) for saved in one.created if not saved.submitted]
            await repo.sync_planner(job.user_id, changes, now=job.now)
            # 제출한 과제는 알림을 멈춘다(명세 10장). 새 과제 알림은 찾은 때 바로 보낸다
            await notes.drop_assignment_notices(job.user_id, changes.submitted)
            made += await notes.add_assignment_notices(job.user_id, notices, now=job.now)
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
            await repo.touch_synced(job.user_id, now=job.now)
        return SyncOutcome(
            courses=len(fetched),
            created=len(changes.created),
            due_changed=len(changes.due_changed),
            submitted=len(changes.submitted),
            new_items=len(items.created),
            notices=made,
            failed_courses=failed,
        )

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


def get_lms_sync_service(
    request: Request,
    runner: RunnerDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> LmsSyncService:
    state = request.app.state
    pool, log_pool = getattr(state, "pool", None), getattr(state, "log_pool", None)
    if pool is None or log_pool is None:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    return LmsSyncService(
        transaction=pool.connection,
        log_connection=log_pool.connection,
        client=LearningXClient(api_base=settings.lms_api_base),
        encryption_key=settings.token_encryption_key,
        runner=runner,
    )


LmsSyncServiceDep = Annotated[LmsSyncService, Depends(get_lms_sync_service)]
