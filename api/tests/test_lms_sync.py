"""LMS 동기화(F-51): `POST /lms/sync`·`GET /lms/assignments`·30분 배치.

LearningX 호출은 respx로 가로채고 저장소는 가짜로 바꿔 끼운다(DB·네트워크 없이 돈다).
SQL은 test_lms_db.py가 실제 스키마로 본다.
"""

import json
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import count
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.agent_log import using
from app.background import InlineRunner
from app.calendar import GoogleCalendarClient
from app.clock import current_time
from app.config import Settings, get_settings
from app.crypto import encrypt
from app.db import get_log_connect
from app.eligibility import KST
from app.extraction.agent import ExtractionAgent
from app.lms.announce import AnnouncementService
from app.lms.announcements import CanvasAnnouncement
from app.lms.assignments import CanvasAssignment
from app.lms.client import LearningXClient
from app.lms.sync import LmsSyncService, Repos, SyncJob, get_lms_sync_service
from app.main import create_app
from app.repositories.announcements import PendingAnnouncement, SavedAnnouncement
from app.repositories.calendar import AssignmentDeadline, GoogleTokens
from app.repositories.lms import (
    AssignmentChanges,
    Connection,
    CourseRow,
    ModuleChanges,
    SavedAssignment,
    SavedItem,
    get_lms_repo,
    update_scope,
)
from app.repositories.notifications import AssignmentNotice, MaterialNotice, ScheduleNotice
from app.repositories.opportunities import Cursor
from app.repositories.runs import get_run_repo
from app.schemas.calendar import CalendarEventView
from app.schemas.lms import (
    AssignmentCourse,
    AssignmentItem,
    CourseAnnouncement,
    CourseAssignment,
    CourseDetail,
    CourseHeader,
    CourseMaterial,
    CourseModuleItem,
    CourseSyllabusItem,
    LmsSyncResult,
    ModuleItemUpdate,
    SyncCounts,
)
from tests.conftest import USER_ID, make_token
from tests.fakes import FakeLogConnection
from tests.llm_fakes import ScriptedLlm
from tests.llm_fakes import call as model_call
from tests.lms_samples import (
    COURSES,
    DB_ANNOUNCEMENTS,
    DB_ASSIGNMENTS,
    DB_MODULES,
    ML_ANNOUNCEMENTS,
    ML_ASSIGNMENTS,
    ML_MODULES,
    MODULE_WITHOUT_ITEMS,
    RESEARCH_TITLE,
    RESEARCH_TOPIC_ID,
)
from tests.prepare_fakes import FakeRunRepository, run_row

SYNC = "/api/v1/lms/sync"
ASSIGNMENTS = "/api/v1/lms/assignments"
BASE = "https://lms.test"
GOOGLE = "https://calendar.test"  # 가짜 Google 캘린더(respx가 가로챈다)
TOKEN = "18742~pAtB1g3TestTokenValue0000000000"
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)  # 2026-10-16 12:00 KST
INTERNAL_KEY = "test-internal-key"
CLASSIFY_MODEL = "gemini-3.5-flash-lite"
EXTRACTION_MODEL = "gemini-3.8-flash"
COURSE_UUID = "33333333-3333-4333-8333-333333333333"
EVENT_ROW = "88888888-8888-4888-8888-888888888888"  # 캘린더 일정 행 id(Google 번호의 바탕)
FEED_ITEM = "22222222-2222-4222-8222-222222222222"  # 커서는 uuid만 받는다(decode_cursor)
JOB = "/api/v1/internal/jobs/lms-sync"
DB_COURSE = CourseRow(id="course-db", canvas_course_id=214023, short_name="데이터베이스")
ML_COURSE = CourseRow(id="course-ml", canvas_course_id=216515, short_name="기계학습")


@dataclass
class FakeLms:
    """과제·과목 저장을 기억하는 가짜 저장소. 실제 SQL은 test_lms_db.py가 본다."""

    connection_row: Connection | None = None
    courses: list[CourseRow] = field(default_factory=lambda: [DB_COURSE, ML_COURSE])
    changes: dict[str, AssignmentChanges] = field(default_factory=dict)  # course_id → 돌려줄 변화
    saved: list[tuple[str, list[CanvasAssignment]]] = field(default_factory=list)
    planned: list[AssignmentChanges] = field(default_factory=list)
    synced_at: datetime | None = None
    error: str | None = None
    claims: list[str] = field(default_factory=list)
    items: list[tuple[int, list[Any]]] = field(default_factory=list)
    feed_calls: list[tuple[datetime, tuple[str, ...], str | None, Any]] = field(
        default_factory=list
    )
    opened: list[tuple[str, datetime, str]] = field(default_factory=list)
    module_changes: dict[int, ModuleChanges] = field(default_factory=dict)
    titles: dict[str, str] = field(default_factory=dict)

    async def assignment_titles(self, user_id: str, ids: list[str]) -> dict[str, str]:
        assert user_id == USER_ID or user_id in self.users
        return {key: value for key, value in self.titles.items() if key in set(ids)}

    rows: dict[str, Connection] = field(default_factory=dict)
    users: list[str] = field(default_factory=list)
    before: datetime | None = None

    def _row(self, user_id: str) -> Connection | None:
        """사용자마다 따로 둔다. 배치에서 앞사람의 claim이 뒷사람을 막지 않게."""
        if user_id == USER_ID:
            return self.connection_row
        return self.rows.get(user_id, self.connection_row)

    def _put(self, user_id: str, row: Connection) -> None:
        if user_id == USER_ID:
            self.connection_row = row
        else:
            self.rows[user_id] = row

    async def connection(self, user_id: str) -> Connection | None:
        assert user_id == USER_ID or user_id in self.users
        return self._row(user_id)

    async def claim_sync(self, user_id: str, *, now: datetime, before: datetime) -> bool:
        """실제 SQL과 같은 뜻: 연결이 있고 before 뒤에 받지 않았으면 시각을 밀고 True."""
        row = self._row(user_id)
        if row is None or row.status == "disconnected":
            return False
        if row.last_synced_at is not None and row.last_synced_at > before:
            return False
        self.claims.append(user_id)
        self._put(user_id, Connection(**{**row.__dict__, "last_synced_at": now}))
        return True

    async def save_courses(
        self, user_id: str, courses: list[dict[str, Any]], *, now: datetime
    ) -> int:
        assert user_id == USER_ID or user_id in self.users
        return len(courses)

    async def active_courses(self, user_id: str) -> list[CourseRow]:
        return list(self.courses)

    async def save_assignments(
        self, user_id: str, course_id: str, items: list[CanvasAssignment], *, now: datetime
    ) -> AssignmentChanges:
        assert user_id == USER_ID or user_id in self.users
        self.saved.append((course_id, items))
        return self.changes.get(course_id, AssignmentChanges())

    async def save_module_items(
        self, user_id: str, canvas_course_id: int, items: list[Any], *, now: datetime
    ) -> ModuleChanges:
        assert user_id == USER_ID or user_id in self.users
        self.items.append((canvas_course_id, items))
        return self.module_changes.get(canvas_course_id, ModuleChanges())

    async def sync_planner(self, user_id: str, changes: AssignmentChanges, *, now: datetime) -> int:
        self.planned.append(changes)
        return len(changes.created)

    async def touch_synced(self, user_id: str, *, now: datetime) -> None:
        self.synced_at = now

    async def mark_error(self, user_id: str, message: str) -> None:
        self.error = message

    async def connected_users(self, *, before: datetime, limit: int) -> list[str]:
        self.before = before
        return list(self.users)

    async def course_detail(
        self, user_id: str, course_id: str, *, now: datetime, lms_base: str
    ) -> CourseDetail | None:
        assert user_id == USER_ID
        self.opened.append((course_id, now, lms_base))
        if course_id != COURSE_UUID:
            return None
        return CourseDetail(
            course=CourseHeader(
                id=course_id,
                short_name="데이터베이스",
                has_syllabus=False,
                portal_syllabus_url=None,
                html_url=f"{lms_base}/courses/214023",
            ),
            assignments=[
                CourseAssignment(
                    id="a-1",
                    title="실습 2주차 결과 제출",
                    due_at=datetime(2026, 10, 20, 23, 59, 59, tzinfo=KST),
                    submission_state="unsubmitted",
                    html_url=f"{BASE}/courses/214023/assignments/2811242",
                )
            ],
            module_items=[
                CourseModuleItem(
                    id=FEED_ITEM,
                    module_name="3주차",
                    title="3주차 강의",
                    item_type="ExternalTool",
                    html_url=f"{BASE}/courses/214023/modules/items/8569302",
                    is_new=True,
                    uploaded_file_id=None,
                )
            ],
            announcements=[
                CourseAnnouncement(
                    id="n-1",
                    title="강의실 변경",
                    summary="301호에서 해요",
                    category="schedule_change",
                    posted_at=NOW.astimezone(KST),
                    opportunity_id=None,
                )
            ],
            syllabus_items=[
                CourseSyllabusItem(
                    id="s-1",
                    item_type="midterm",
                    title="중간고사",
                    starts_at=NOW.astimezone(KST),
                    is_confirmed=True,
                )
            ],
            materials=[CourseMaterial(file_id="f-1", original_name="3주차.pdf", status="pending")],
        )

    async def updates(
        self,
        user_id: str,
        *,
        since: datetime,
        now: datetime,
        kinds: list[str],
        course_id: str | None = None,
        cursor: Any = None,
        limit: int = 50,
    ) -> tuple[list[Any], Any]:
        assert user_id == USER_ID
        self.feed_calls.append((since, tuple(kinds), course_id, cursor))
        item = ModuleItemUpdate(
            id=FEED_ITEM,
            course=AssignmentCourse(id=DB_COURSE.id, short_name=DB_COURSE.short_name),
            module_name="3주차",
            title="3주차 강의",
            item_type="ExternalTool",
            html_url=f"{BASE}/courses/214023/modules/items/8569302",
            first_seen_at=NOW.astimezone(KST),
            uploaded_file_id=None,
        )
        if cursor is not None:  # 둘째 쪽은 한 줄만 주고 끝낸다
            return [item], None
        return [item], Cursor(scope=update_scope(kinds, course_id, since), value=NOW, id=FEED_ITEM)

    async def assignments(
        self, user_id: str, *, state: str = "open", course_id: str | None = None
    ) -> list[AssignmentItem]:
        assert user_id == USER_ID
        self.asked = (state, course_id)  # type: ignore[attr-defined]
        return [
            AssignmentItem(
                id="assignment-1",
                course=AssignmentCourse(id=DB_COURSE.id, short_name=DB_COURSE.short_name),
                title="실습 2주차 결과 제출",
                due_at=datetime(2026, 10, 20, 23, 59, 59, tzinfo=KST),
                submission_state="unsubmitted",
                html_url=f"{BASE}/courses/214023/assignments/2811242",
                planner_task_id="task-1",
                calendar_registered=False,
            )
        ]


@dataclass
class FakeNotes:
    added: list[AssignmentNotice] = field(default_factory=list)
    materials: list[MaterialNotice] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    muted: bool = False

    async def add_material_notices(
        self, canvas_course_id: int, notices: Sequence[MaterialNotice], *, now: datetime
    ) -> int:
        assert canvas_course_id
        self.materials += list(notices)
        return len(notices)

    async def add_assignment_notices(
        self, user_id: str, notices: Sequence[AssignmentNotice], *, now: datetime
    ) -> int:
        assert user_id
        if self.muted:
            return 0
        self.added += list(notices)
        return len(notices)

    async def drop_assignment_notices(self, user_id: str, assignment_ids: Sequence[str]) -> int:
        self.dropped += list(assignment_ids)
        return len(self.dropped)

    async def add_schedule_notices(
        self, canvas_course_id: int, notice: ScheduleNotice, *, now: datetime
    ) -> int:
        assert canvas_course_id
        self.schedules.append(notice)
        return 1

    schedules: list[ScheduleNotice] = field(default_factory=list)


@pytest.fixture
def lms(settings: Settings) -> FakeLms:
    return FakeLms(
        connection_row=Connection(
            status="active",
            token_last4=TOKEN[-4:],
            access_token=encrypt(TOKEN, settings.token_encryption_key),
            canvas_user_id=77001,
            last_synced_at=None,
            last_error=None,
        )
    )


@dataclass
class FakeCalendar:
    """캘린더 저장소 흉내. 기본은 "자동 등록 켬 + 구글 연결 있음"이다."""

    key: str = ""  # 토큰 암호화 키(settings와 같아야 복호화된다)
    auto: bool = True
    connected: bool = True
    expires_in: timedelta = timedelta(hours=1)  # 0이면 갱신 경로를 탄다
    pending: list[AssignmentDeadline] = field(default_factory=list)
    reserved: list[dict[str, Any]] = field(default_factory=list)
    attached: list[tuple[str, str]] = field(default_factory=list)
    moved: list[tuple[str, datetime]] = field(default_factory=list)
    events: dict[str, CalendarEventView] = field(default_factory=dict)

    async def auto_lms(self, user_id: str) -> bool:
        return self.auto

    async def unfinished_assignment_events(
        self, user_id: str, provider: str = "google"
    ) -> list[AssignmentDeadline]:
        return list(self.pending)

    async def tokens(self, user_id: str) -> GoogleTokens | None:
        if not self.connected:
            return None
        return GoogleTokens(
            encrypt("access-1", self.key), encrypt("refresh-1", self.key), NOW + self.expires_in
        )

    async def save_access_token(self, user_id: str, encrypted: str, expires_in: int) -> None:
        pass

    async def events_for_assignments(
        self, user_id: str, assignment_ids: Any, provider: str = "google"
    ) -> dict[str, CalendarEventView]:
        return {key: value for key, value in self.events.items() if key in set(assignment_ids)}

    async def reserve(self, user_id: str, **values: Any) -> CalendarEventView:
        """실제 저장소를 그대로 흉내 낸다(`on conflict ... where external_event_id is null`).

        이미 잡아 둔 자리가 있으면 그 행을 쓴다. 아직 Google에 안 넣은 자리는 제목·시각을 새로
        맞추고, 이미 넣은 일정은 그대로 둔다.
        """
        self.reserved.append(values)
        target = values.get("lms_assignment_id") or values.get("opportunity_id")
        found = self.events.get(str(target))
        if found is not None:
            if found.external_event_id is not None:
                return found
            fresh = found.model_copy(
                update={"title": values["title"], "starts_at": values["starts_at"]}
            )
            self.events[str(target)] = fresh
            return fresh
        return CalendarEventView(
            id=EVENT_ROW,
            provider="google",
            external_event_id=None,
            title=values["title"],
            starts_at=values["starts_at"],
            all_day=False,
        )

    async def attach(self, user_id: str, event_id: str, external_event_id: str) -> None:
        self.attached.append((event_id, external_event_id))

    async def move(self, user_id: str, event_id: str, *, starts_at: datetime) -> None:
        self.moved.append((event_id, starts_at))


@pytest.fixture
def calendar(settings: Settings) -> FakeCalendar:
    return FakeCalendar(key=settings.token_encryption_key)


@dataclass
class FakeAnnouncements:
    """공지 저장소 가짜. 저장한 것과 분류 결과를 메모리에 남긴다(SQL은 test_lms_db.py가 본다)."""

    saved: list[tuple[int, list[CanvasAnnouncement]]] = field(default_factory=list)
    new_ids: dict[int, list[str]] = field(default_factory=dict)  # 과목 → 처음 본 공지 id
    pending_rows: list[PendingAnnouncement] = field(default_factory=list)
    classified: list[tuple[str, str, str | None]] = field(default_factory=list)
    created: list[tuple[str, str]] = field(default_factory=list)  # (공지 id, 공고 종류)
    linked: set[str] = field(default_factory=set)  # 이미 공고가 붙은 공지
    asked: list[tuple[list[int], datetime, int]] = field(default_factory=list)

    async def save(
        self, canvas_course_id: int, items: list[CanvasAnnouncement], *, now: datetime
    ) -> list[SavedAnnouncement]:
        self.saved.append((canvas_course_id, items))
        ids = self.new_ids.get(canvas_course_id)
        chosen = items if ids is None else [one for one in items if str(one.canvas_topic_id) in ids]
        return [
            SavedAnnouncement(
                id=f"n-{one.canvas_topic_id}", canvas_topic_id=one.canvas_topic_id, title=one.title
            )
            for one in chosen
        ]

    async def pending(
        self, *, courses: list[int], recent_from: datetime, limit: int
    ) -> list[PendingAnnouncement]:
        self.asked.append((courses, recent_from, limit))
        return [one for one in self.pending_rows if one.canvas_course_id in set(courses)][:limit]

    async def save_classification(
        self, announcement_id: str, *, category: str, summary: str | None, run_id: str | None
    ) -> None:
        self.classified.append((announcement_id, category, summary))

    async def create_opportunity(
        self,
        announcement: PendingAnnouncement,
        *,
        category: str,
        original_url: str | None,
        extraction: Any,
        run_id: str | None,
    ) -> str | None:
        self.extractions.append(extraction)
        if announcement.id in self.linked:
            return None  # 다른 수강생의 동기화가 먼저 만들었다
        self.linked.add(announcement.id)
        self.created.append((announcement.id, category))
        self.urls.append(original_url)
        return f"opportunity-{announcement.canvas_topic_id}"

    urls: list[str | None] = field(default_factory=list)
    extractions: list[Any] = field(default_factory=list)
    schedule_tasks: list[tuple[str, int, str, Any]] = field(default_factory=list)

    async def add_schedule_task(
        self, announcement_id: str, canvas_course_id: int, *, title: str, on: Any
    ) -> int:
        self.schedule_tasks.append((announcement_id, canvas_course_id, title, on))
        return 1


@pytest.fixture
def announcements_repo() -> FakeAnnouncements:
    return FakeAnnouncements()


@pytest.fixture
def llm() -> ScriptedLlm:
    """기본은 답을 하나도 안 담은 모델. 분류를 보는 테스트만 답을 넣는다."""
    return ScriptedLlm()


@pytest.fixture
def notes() -> FakeNotes:
    return FakeNotes()


@pytest.fixture
def log() -> FakeLogConnection:
    return FakeLogConnection()


@pytest.fixture
def client(
    settings: Settings,
    lms: FakeLms,
    notes: FakeNotes,
    calendar: FakeCalendar,
    announcements_repo: FakeAnnouncements,
    llm: ScriptedLlm,
    log: FakeLogConnection,
) -> Iterator[TestClient]:
    # 배치(`/internal/jobs/lms-sync`)를 부르려면 서비스 키가 있어야 한다
    settings = Settings(**{**settings.model_dump(), "internal_api_key": INTERNAL_KEY})
    app = create_app(settings)

    @asynccontextmanager
    async def transaction() -> AsyncIterator[Any]:
        yield None  # 가짜 저장소는 연결을 쓰지 않는다

    async def departments(conn: Any) -> list[Any]:
        return []  # 학과 목록은 요건 추출의 "목록에 없는 학과" 검사에만 쓴다

    announcer = AnnouncementService(
        transaction=transaction,
        llm=llm,
        classify_model=CLASSIFY_MODEL,
        agent_for=lambda names: ExtractionAgent(llm, model=EXTRACTION_MODEL, departments=names),
        lms_base=BASE,
        repo_for=lambda conn: announcements_repo,  # type: ignore[arg-type,return-value]
        notes_for=lambda conn: notes,  # type: ignore[arg-type,return-value]
        departments_for=departments,
    )
    service = LmsSyncService(
        transaction=transaction,
        log_connection=using(log),  # type: ignore[arg-type]
        client=LearningXClient(api_base=BASE),
        calendar_client=GoogleCalendarClient(
            api_base=GOOGLE,
            token_url=f"{GOOGLE}/token",
            client_id="client-1",
            client_secret="secret-1",
        ),
        encryption_key=settings.token_encryption_key,
        runner=InlineRunner(),  # 응답 전에 동기화를 끝까지 돌린다
        announcer=announcer,
        repos=lambda conn: Repos(  # type: ignore[arg-type]
            lms=lms, notes=notes, calendar=calendar, announcements=announcements_repo
        ),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_lms_sync_service] = lambda: service
    app.dependency_overrides[get_lms_repo] = lambda: lms
    app.dependency_overrides[get_log_connect] = lambda: using(log)  # type: ignore[arg-type]
    app.dependency_overrides[current_time] = lambda: NOW
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {make_token()}"
        yield test_client


@pytest.fixture(autouse=True)
def canvas() -> Iterator[respx.MockRouter]:
    """기본 응답: 과목 3개, 데이터베이스 2건·기계학습 1건."""
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/api/v1/courses").mock(return_value=httpx.Response(200, json=COURSES))
        router.get(f"{BASE}/api/v1/courses/214023/assignments").mock(
            return_value=httpx.Response(200, json=DB_ASSIGNMENTS)
        )
        router.get(f"{BASE}/api/v1/courses/216515/assignments").mock(
            return_value=httpx.Response(200, json=ML_ASSIGNMENTS)
        )
        router.get(f"{BASE}/api/v1/courses/214023/modules").mock(
            return_value=httpx.Response(200, json=DB_MODULES)
        )
        router.get(f"{BASE}/api/v1/courses/216515/modules").mock(
            return_value=httpx.Response(200, json=ML_MODULES)
        )
        router.get(f"{BASE}/api/v1/courses/214023/discussion_topics").mock(
            return_value=httpx.Response(200, json=DB_ANNOUNCEMENTS)
        )
        router.get(f"{BASE}/api/v1/courses/216515/discussion_topics").mock(
            return_value=httpx.Response(200, json=ML_ANNOUNCEMENTS)
        )
        yield router


def test_it_starts_a_sync_and_gives_back_the_run(client: TestClient, lms: FakeLms) -> None:
    response = client.post(SYNC)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "running"
    assert body["run_id"]
    assert lms.synced_at == NOW  # 끝나면 마지막 동기화 시각을 찍는다


def test_it_saves_only_published_assignments(client: TestClient, lms: FakeLms) -> None:
    client.post(SYNC)
    saved = {course: [one.title for one in items] for course, items in lms.saved}
    assert saved == {
        "course-db": ["실습 2주차 결과 제출", "실습 3주차 결과 제출"],  # 준비 중 과제는 빠진다
        "course-ml": ["3주차 퀴즈"],
    }


def test_the_run_records_every_outside_call_as_a_tool(
    client: TestClient, log: FakeLogConnection
) -> None:
    """외부 호출은 모두 실행 안의 도구로 남는다. 토큰은 입력에 넣지 않는다."""
    client.post(SYNC)
    assert log.tools() == [
        "fetch_lms_courses",
        "fetch_lms_assignments",
        "fetch_lms_modules",
        "fetch_lms_announcements",
        "save_lms_sync",
    ]
    assert TOKEN not in str(log.statements)  # 입력·출력에 토큰이 남지 않는다


def test_the_result_is_in_the_save_step(
    client: TestClient, lms: FakeLms, log: FakeLogConnection
) -> None:
    """`GET /runs/{id}`는 save_lms_sync의 출력으로 결과를 만든다(repositories/runs.py)."""
    lms.changes["course-db"] = AssignmentChanges(
        created=[SavedAssignment("a1", "실습 2주차 결과 제출", NOW + timedelta(days=4))],
        due_changed=[SavedAssignment("a2", "실습 3주차 결과 제출", NOW + timedelta(days=2))],
        submitted=["a3"],
    )
    client.post(SYNC)
    output = log.outputs()["save_lms_sync"]
    assert output["courses"] == 2
    assert (output["new"], output["due_changed"], output["submitted"]) == (1, 1, 1)


def test_a_new_assignment_becomes_a_task_and_a_notice(
    client: TestClient, lms: FakeLms, notes: FakeNotes
) -> None:
    lms.changes["course-ml"] = AssignmentChanges(
        created=[SavedAssignment("a9", "3주차 퀴즈", datetime(2026, 10, 11, 14, 59, tzinfo=UTC))]
    )
    client.post(SYNC)
    assert [one.created for one in lms.planned] == [lms.changes["course-ml"].created]
    assert len(notes.added) == 1
    notice = notes.added[0]
    assert notice.assignment_id == "a9"
    assert notice.title == "기계학습 새 과제가 올라왔어요"
    assert notice.body == "3주차 퀴즈 · 마감 10/11 23:59"  # KST로 보여 준다


def test_an_assignment_already_submitted_gets_no_notice(
    client: TestClient, lms: FakeLms, notes: FakeNotes
) -> None:
    """연결 첫 동기화에는 지난 학기 과제까지 들어온다. 이미 낸 과제로 알림을 보내면 안 된다."""
    lms.changes["course-db"] = AssignmentChanges(
        created=[
            SavedAssignment("a1", "지난 과제", NOW - timedelta(days=9), submitted=True),
            SavedAssignment("a2", "이번 과제", NOW + timedelta(days=2)),
        ]
    )
    client.post(SYNC)
    assert [one.assignment_id for one in notes.added] == ["a2"]


def test_an_assignment_without_a_deadline_still_gets_a_notice(
    client: TestClient, lms: FakeLms, notes: FakeNotes
) -> None:
    lms.changes["course-db"] = AssignmentChanges(
        created=[SavedAssignment("a8", "기말 보고서", None)]
    )
    client.post(SYNC)
    assert notes.added[0].body == "기말 보고서"


def test_submitting_stops_the_pending_notice(
    client: TestClient, lms: FakeLms, notes: FakeNotes
) -> None:
    """제출하면 아직 보내지 않은 알림을 지운다(명세 10장)."""
    lms.changes["course-db"] = AssignmentChanges(submitted=["a3", "a4"])
    client.post(SYNC)
    assert notes.dropped == ["a3", "a4"]


def test_it_skips_a_sync_that_just_happened(client: TestClient, lms: FakeLms) -> None:
    """5분 안에 또 부르면 LearningX를 부르지 않는다(명세 8장)."""
    assert lms.connection_row is not None
    lms.connection_row = Connection(
        **{**lms.connection_row.__dict__, "last_synced_at": NOW - timedelta(minutes=2)}
    )
    response = client.post(SYNC)
    assert response.status_code == 200
    assert response.json() == {"skipped": True, "last_synced_at": "2026-10-16T11:58:00+09:00"}
    assert lms.saved == []  # 아무것도 받지 않았다


def test_a_second_call_does_not_start_a_second_sync(client: TestClient, lms: FakeLms) -> None:
    """대시보드를 두 탭에서 열어도 한 번만 받는다. claim이 한 문장으로 자리를 잡는다."""
    assert client.post(SYNC).status_code == 202
    first = len(lms.saved)
    again = client.post(SYNC)
    assert again.status_code == 200
    assert again.json()["skipped"] is True
    assert len(lms.saved) == first  # 두 번째는 LearningX를 부르지 않았다
    assert lms.claims == [USER_ID]


def test_it_syncs_again_after_five_minutes(client: TestClient, lms: FakeLms) -> None:
    assert lms.connection_row is not None
    lms.connection_row = Connection(
        **{**lms.connection_row.__dict__, "last_synced_at": NOW - timedelta(minutes=6)}
    )
    assert client.post(SYNC).status_code == 202
    assert lms.saved != []


def test_it_asks_to_connect_first(client: TestClient, lms: FakeLms) -> None:
    lms.connection_row = None
    response = client.post(SYNC)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LMS_NOT_CONNECTED"


def test_a_dead_token_marks_the_connection(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """401이면 연결을 error로 바꿔 화면이 다시 연결을 안내한다. 실행은 실패로 남는다."""
    canvas.get(f"{BASE}/api/v1/courses").mock(return_value=httpx.Response(401, json={}))
    response = client.post(SYNC)
    assert response.status_code == 202  # 동기화는 뒤에서 돌아서 시작 응답은 202다
    assert lms.error == "토큰이 만료되었거나 삭제되었어요."
    assert lms.synced_at is None


def test_a_broken_stored_token_asks_to_connect_again(client: TestClient, lms: FakeLms) -> None:
    """키를 바꿨거나 값이 깨졌다. 500으로 끝내지 않고 다시 연결하게 한다."""
    assert lms.connection_row is not None
    lms.connection_row = Connection(
        **{**lms.connection_row.__dict__, "access_token": "암호문이 아니다"}
    )
    response = client.post(SYNC)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LMS_TOKEN_INVALID"


def test_learningx_being_down_does_not_mark_the_token(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """503은 토큰 문제가 아니다. 연결 상태를 바꾸지 않고 다음 동기화에서 다시 시도한다."""
    canvas.get(f"{BASE}/api/v1/courses").mock(return_value=httpx.Response(503, json={}))
    client.post(SYNC)
    assert lms.error is None
    assert lms.synced_at is None


def test_one_broken_course_does_not_stop_the_others(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter, log: FakeLogConnection
) -> None:
    """한 과목이 403이면 그 과목만 두고 넘어간다. 부분 목록으로 저장하면 과제가 사라진 것이 된다."""
    canvas.get(f"{BASE}/api/v1/courses/214023/assignments").mock(
        return_value=httpx.Response(403, json={})
    )
    client.post(SYNC)
    assert [course for course, _ in lms.saved] == ["course-ml"]
    assert log.outputs()["save_lms_sync"]["failed_courses"] == 1
    assert lms.synced_at == NOW  # 나머지는 받았으니 동기화는 성공이다


def test_a_dead_token_in_the_middle_stops_the_sync(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    canvas.get(f"{BASE}/api/v1/courses/214023/assignments").mock(
        return_value=httpx.Response(401, json={})
    )
    client.post(SYNC)
    assert lms.saved == []  # 쓰기 트랜잭션에 들어가지 않았다
    assert lms.error == "토큰이 만료되었거나 삭제되었어요."


def test_a_course_with_no_assignments_is_fine(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """녹화 6과목 중 2과목이 과제 0건이었다. 빈 목록은 오류가 아니다(명세 9장)."""
    canvas.get(f"{BASE}/api/v1/courses/216515/assignments").mock(
        return_value=httpx.Response(200, json=[])
    )
    assert client.post(SYNC).status_code == 202
    saved = dict(lms.saved)
    assert saved["course-ml"] == []
    assert lms.synced_at == NOW


def test_it_sends_the_token_only_in_the_header(
    client: TestClient, canvas: respx.MockRouter
) -> None:
    client.post(SYNC)
    for call in canvas.calls:
        assert call.request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in str(call.request.url)


def test_the_sync_needs_a_login(settings: Settings, lms: FakeLms) -> None:
    app = create_app(settings)
    app.dependency_overrides[get_lms_repo] = lambda: lms
    with TestClient(app) as anonymous:
        assert anonymous.post(SYNC).status_code == 401
        assert anonymous.get(ASSIGNMENTS).status_code == 401


def test_the_run_shows_the_sync_result(client: TestClient) -> None:
    """`GET /runs/{id}`가 동기화 결과를 보여 준다(명세 8장·11장). 단계 이름도 한글로 나온다."""
    runs = FakeRunRepository()
    client.app.dependency_overrides[get_run_repo] = lambda: runs  # type: ignore[attr-defined]
    run = run_row(
        id="00000000-0000-4000-8000-0000000000b1",
        user_id=USER_ID,
        trigger_type="lms_sync",
        status="succeeded",
    )
    runs.runs[run.id] = run
    runs.lms_results[run.id] = LmsSyncResult(
        courses=2, assignments=SyncCounts(new=1, due_changed=0, submitted=2)
    )

    body = client.get(f"/api/v1/runs/{run.id}").json()
    assert body["result"] == {
        "kind": "lms_sync",
        "courses": 2,
        "assignments": {"new": 1, "due_changed": 0, "submitted": 2},
        "new_module_items": 0,
        "new_announcements": 0,
        "calendar_events": 0,
        "calendar_moved": 0,
    }


def test_it_saves_the_module_items_of_every_course(client: TestClient, lms: FakeLms) -> None:
    client.post(SYNC)
    saved = {course: [one.title for one in items] for course, items in lms.items}
    assert saved == {
        214023: ["3주차 강의", "3주차 강의", "3주차 퀴즈"],  # 제목이 같은 둘도 따로 저장된다
        216515: ["3주차 과제 안내"],
    }


def test_a_new_module_item_becomes_a_notice(
    client: TestClient, lms: FakeLms, notes: FakeNotes
) -> None:
    """명세 10장 예시와 같은 꼴: "기계학습 8주차 자료가 올라왔어요" + 항목 제목."""
    lms.module_changes[216515] = ModuleChanges(
        created=[SavedItem("item-1", "8주차", "08 - Ensemble Methods")]
    )
    client.post(SYNC)
    assert len(notes.materials) == 1
    notice = notes.materials[0]
    assert notice.item_id == "item-1"
    assert notice.title == "기계학습 8주차 자료가 올라왔어요"
    assert notice.body == "08 - Ensemble Methods"


def test_the_first_load_of_a_course_is_silent(
    client: TestClient, lms: FakeLms, notes: FakeNotes
) -> None:
    """연결하고 처음 받으면 한 학기 분량(녹화 87건)이 모두 새 항목이다. 알림을 보내지 않는다."""
    lms.module_changes[214023] = ModuleChanges(
        created=[SavedItem("item-1", "1주차", "01 - 소개"), SavedItem("item-2", "2주차", "02")],
        first_load=True,
    )
    client.post(SYNC)
    assert notes.materials == []
    assert [course for course, _ in lms.items] == [214023, 216515]  # 저장은 했다


def test_the_result_counts_new_module_items(
    client: TestClient, lms: FakeLms, log: FakeLogConnection
) -> None:
    lms.module_changes[214023] = ModuleChanges(
        created=[SavedItem("item-1", "1주차", "01"), SavedItem("item-2", "1주차", "02")],
        first_load=True,  # 첫 수집이어도 수는 센다(알림만 안 보낸다)
    )
    client.post(SYNC)
    assert log.outputs()["save_lms_sync"]["new_module_items"] == 2


def test_a_course_whose_modules_fail_does_not_fail_the_sync(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """과제는 받았는데 주차 항목만 못 받았다고 동기화를 실패로 적지 않는다."""
    canvas.get(f"{BASE}/api/v1/courses/214023/modules").mock(
        return_value=httpx.Response(500, json={})
    )
    client.post(SYNC)
    assert [course for course, _ in lms.items] == [216515]
    assert [course for course, _ in lms.saved] == ["course-db", "course-ml"]  # 과제는 둘 다
    assert lms.synced_at == NOW


def test_a_dead_token_while_reading_modules_stops_the_sync(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    canvas.get(f"{BASE}/api/v1/courses/214023/modules").mock(
        return_value=httpx.Response(401, json={})
    )
    client.post(SYNC)
    assert lms.error == "토큰이 만료되었거나 삭제되었어요."
    assert lms.synced_at is None  # 저장까지 가지 않았다


def test_items_that_did_not_come_inline_are_fetched(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """`include[]=items`로 항목이 오지 않은 모듈은 허용된 보충 경로로 따로 받는다(명세 9장)."""
    canvas.get(f"{BASE}/api/v1/courses/214023/modules").mock(
        return_value=httpx.Response(200, json=[MODULE_WITHOUT_ITEMS])
    )
    separate = canvas.get(f"{BASE}/api/v1/courses/214023/modules/2871999/items").mock(
        return_value=httpx.Response(
            200, json=[{"id": 999, "title": "5주차 강의", "type": "ExternalTool"}]
        )
    )
    client.post(SYNC)
    assert separate.called
    saved = dict(lms.items)
    assert [one.title for one in saved[214023]] == ["5주차 강의"]


def test_a_sync_where_every_course_fails_is_not_a_success(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """한 과목도 받지 못하면 성공으로 적지 않는다. 적으면 오류 표시가 지워지고 학생은 받았다고 믿는다."""
    for course in (214023, 216515):
        canvas.get(f"{BASE}/api/v1/courses/{course}/assignments").mock(
            return_value=httpx.Response(403, json={})
        )
    client.post(SYNC)
    assert lms.saved == []
    assert lms.synced_at is None  # touch_synced를 부르지 않았다
    assert lms.error is None  # 토큰 문제가 아니라 학교 쪽 문제다


def test_a_failed_sync_closes_its_run(
    client: TestClient, lms: FakeLms, log: FakeLogConnection, canvas: respx.MockRouter
) -> None:
    """실행이 running으로 남으면 GET /runs/{id}가 끝나지 않고 성공률 지표의 분모만 늘어난다."""
    canvas.get(f"{BASE}/api/v1/courses").mock(return_value=httpx.Response(503, json={}))
    client.post(SYNC)
    closed = [
        query for query, _ in log.statements if "update agent_runs" in query and "'failed'" in query
    ]
    assert closed, "실패한 실행을 닫지 않았다"


def test_a_token_we_cannot_decrypt_does_not_blame_the_student(
    client: TestClient, lms: FakeLms
) -> None:
    """암호화 키 문제다. 연결을 error로 바꾸면 멀쩡한 토큰을 다시 받게 만든다(app/crypto.py 키 교체)."""
    assert lms.connection_row is not None
    lms.connection_row = Connection(
        **{**lms.connection_row.__dict__, "access_token": "암호문이 아니다"}
    )
    lms.users = ["user-a"]
    body = client.post(JOB, headers={"X-Internal-Key": INTERNAL_KEY}).json()
    assert (body["synced"], body["failed"]) == (0, 1)
    assert lms.error is None


def test_the_batch_counts_the_ones_someone_else_took(client: TestClient, lms: FakeLms) -> None:
    """대시보드가 방금 동기화를 시작한 사람은 배치에서 건너뛴다(claim이 막는다)."""
    lms.users = ["user-a"]
    assert lms.connection_row is not None
    lms.connection_row = Connection(
        **{**lms.connection_row.__dict__, "last_synced_at": NOW - timedelta(minutes=1)}
    )
    body = client.post(JOB, headers={"X-Internal-Key": INTERNAL_KEY}).json()
    assert (body["users"], body["synced"], body["failed"], body["skipped"]) == (1, 0, 0, 1)


def test_the_job_does_not_print_the_token() -> None:
    """실수로 로그에 찍어도 토큰이 나오지 않게 repr에서 뺀다(Connection.access_token과 같다)."""
    job = SyncJob(run_id="run-1", user_id=USER_ID, now=NOW, token=TOKEN)
    assert TOKEN not in repr(job)
    assert job.token == TOKEN


def test_a_failed_sync_tells_the_student_about_the_sync() -> None:
    """실패 문구가 준비하기 것("준비 일정을 만들지 못했어요")으로 나가면 안 된다."""
    run = run_row(trigger_type="lms_sync", status="failed", error_message="RuntimeError()")
    error = run.error()
    assert error is not None
    assert error.code == "INTERNAL_ERROR"
    assert "LMS" in error.message and "준비" not in error.message


# ── 과제 목록 ───────────────────────────────────────────────────────────────


def test_it_lists_open_assignments_by_default(client: TestClient, lms: FakeLms) -> None:
    response = client.get(ASSIGNMENTS)
    assert response.status_code == 200
    assert lms.asked == ("open", None)  # type: ignore[attr-defined]
    item = response.json()["items"][0]
    assert item["course"] == {"id": "course-db", "short_name": "데이터베이스"}
    assert item["due_at"] == "2026-10-20T23:59:59+09:00"  # KST로 내려준다
    assert item["planner_task_id"] == "task-1"
    assert item["calendar_registered"] is False


def test_it_passes_the_filters_through(client: TestClient, lms: FakeLms) -> None:
    client.get(
        ASSIGNMENTS,
        params={"state": "all", "lms_course_id": "11111111-1111-4111-8111-111111111111"},
    )
    assert lms.asked == ("all", "11111111-1111-4111-8111-111111111111")  # type: ignore[attr-defined]


def test_it_refuses_an_unknown_state(client: TestClient) -> None:
    response = client.get(ASSIGNMENTS, params={"state": "done"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_it_refuses_a_course_id_that_is_not_a_uuid(client: TestClient) -> None:
    response = client.get(ASSIGNMENTS, params={"lms_course_id": "214023"})
    assert response.status_code == 422


# ── 30분 배치 ───────────────────────────────────────────────────────────────


def test_the_batch_syncs_every_connected_user(client: TestClient, lms: FakeLms) -> None:
    lms.users = ["user-a", "user-b"]
    response = client.post(JOB, headers={"X-Internal-Key": INTERNAL_KEY})
    assert response.status_code == 200
    body = response.json()
    assert (body["users"], body["synced"], body["failed"]) == (2, 2, 0)
    assert lms.before == NOW - timedelta(minutes=5)  # 방금 받은 사람은 건너뛴다


def test_the_batch_goes_on_after_one_user_fails(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """앞사람이 실패해도 뒷사람은 받는다. 첫 호출만 401로 막아 둘을 가른다."""
    lms.users = ["user-a", "user-b"]
    calls = {"n": 0}

    def answer(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(401, json={})
        return httpx.Response(200, json=COURSES)

    canvas.get(f"{BASE}/api/v1/courses").mock(side_effect=answer)
    body = client.post(JOB, headers={"X-Internal-Key": INTERNAL_KEY}).json()
    assert (body["users"], body["synced"], body["failed"]) == (2, 1, 1)
    assert lms.error == "토큰이 만료되었거나 삭제되었어요."  # 실패한 사람만 표시된다
    assert lms.saved  # 뒷사람 과제는 저장됐다


def test_the_batch_needs_the_service_key(client: TestClient) -> None:
    assert client.post(JOB).status_code == 403
    assert client.post(JOB, headers={"X-Internal-Key": "not-the-key"}).status_code == 403


# ── 새 자료·과제 피드 (F-52) ────────────────────────────────────────────────

UPDATES = "/api/v1/lms/updates"


def test_the_feed_defaults_to_the_last_two_weeks(client: TestClient, lms: FakeLms) -> None:
    response = client.get(UPDATES)
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0] == {
        "type": "module_item",
        "id": FEED_ITEM,
        "course": {"id": "course-db", "short_name": "데이터베이스"},
        "module_name": "3주차",
        "title": "3주차 강의",
        "item_type": "ExternalTool",
        "html_url": f"{BASE}/courses/214023/modules/items/8569302",
        "first_seen_at": "2026-10-16T12:00:00+09:00",
        "uploaded_file_id": None,
    }
    since, kinds, course, cursor = lms.feed_calls[0]
    assert since == NOW - timedelta(days=14)
    assert kinds == ("module_item", "assignment") and course is None and cursor is None


def test_the_feed_passes_the_filters_through(client: TestClient, lms: FakeLms) -> None:
    client.get(
        UPDATES,
        params={
            "since": "2026-10-01T00:00:00+09:00",
            "type": "module_item",
            "lms_course_id": "11111111-1111-4111-8111-111111111111",
        },
    )
    since, kinds, course, _ = lms.feed_calls[0]
    assert since == datetime(2026, 9, 30, 15, 0, tzinfo=UTC)  # KST → UTC
    assert kinds == ("module_item",)
    assert course == "11111111-1111-4111-8111-111111111111"


def test_the_feed_reads_the_next_page_without_since(client: TestClient, lms: FakeLms) -> None:
    """`since`를 안 주면 기본값이 요청마다 달라진다. 그래도 다음 쪽을 부를 수 있어야 한다.

    실제 시계는 요청마다 다르다(`datetime.now`). 테스트의 고정 시계로는 이 문제가 안 보여서,
    이 테스트만 요청마다 1마이크로초씩 가는 시계를 쓴다.
    """
    ticking = count()
    client.app.dependency_overrides[current_time] = (  # type: ignore[attr-defined]
        lambda: NOW + timedelta(microseconds=next(ticking))
    )
    first = client.get(UPDATES).json()
    assert first["next_cursor"]

    second = client.get(UPDATES, params={"cursor": first["next_cursor"]})
    assert second.status_code == 200
    assert second.json()["next_cursor"] is None
    # 둘째 쪽은 커서에 적힌 since를 그대로 쓴다(지금 - 14일을 다시 계산하지 않는다)
    assert lms.feed_calls[1][0] == lms.feed_calls[0][0]
    assert lms.feed_calls[1][3] is not None  # 커서를 그대로 저장소에 넘겼다


def test_the_feed_refuses_a_cursor_from_another_list(client: TestClient) -> None:
    first = client.get(UPDATES).json()
    response = client.get(UPDATES, params={"cursor": first["next_cursor"], "type": "module_item"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_FAILED"
    assert "cursor" in error["details"]["fields"]


def test_the_feed_refuses_a_broken_cursor(client: TestClient) -> None:
    assert client.get(UPDATES, params={"cursor": "커서가 아니다"}).status_code == 422


def test_the_feed_refuses_an_unknown_kind(client: TestClient) -> None:
    for value in ("", "nope", "module_item,nope", "MODULE_ITEM"):
        response = client.get(UPDATES, params={"type": value})
        assert response.status_code == 422, value
        assert "type" in response.json()["error"]["details"]["fields"]


def test_the_feed_accepts_announcements_but_has_none_yet(client: TestClient, lms: FakeLms) -> None:
    """공지는 F-53이 채운다. 그때까지는 조건만 받아 두고 빈 목록이다."""
    assert client.get(UPDATES, params={"type": "announcement"}).status_code == 200
    assert lms.feed_calls[0][1] == ("announcement",)


def test_the_feed_needs_a_login(settings: Settings, lms: FakeLms) -> None:
    app = create_app(settings)
    app.dependency_overrides[get_lms_repo] = lambda: lms
    with TestClient(app) as anonymous:
        assert anonymous.get(UPDATES).status_code == 401


# ── 과목 상세 (F-14·F-51·F-52) ──────────────────────────────────────────────


def test_it_opens_a_course(client: TestClient, lms: FakeLms, settings: Settings) -> None:
    response = client.get(f"/api/v1/lms/courses/{COURSE_UUID}")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "course",
        "assignments",
        "module_items",
        "announcements",
        "syllabus_items",
        "materials",
    }
    # 칸 이름이 명세 9장 예시와 같아야 한다(web 타입도 이걸 보고 쓴다)
    assert set(body["course"]) == {
        "id",
        "short_name",
        "has_syllabus",
        "syllabus_id",  # 확인 전 일정을 다시 열 때 쓴다(F-14)
        "portal_syllabus_url",
        "html_url",
    }
    assert body["course"]["short_name"] == "데이터베이스"
    assert set(body["assignments"][0]) == {
        "id",
        "title",
        "due_at",
        "submission_state",
        "html_url",
    }
    assert set(body["module_items"][0]) == {
        "id",
        "module_name",
        "title",
        "item_type",
        "html_url",
        "is_new",
        "uploaded_file_id",
    }
    assert set(body["announcements"][0]) == {
        "id",
        "title",
        "summary",
        "category",
        "posted_at",
        "opportunity_id",
    }
    assert set(body["syllabus_items"][0]) == {
        "id",
        "item_type",
        "title",
        "starts_at",
        "is_confirmed",
    }
    assert set(body["materials"][0]) == {"file_id", "original_name", "status"}
    assert body["assignments"][0]["due_at"] == "2026-10-20T23:59:59+09:00"  # KST로 간다
    course_id, when, base = lms.opened[0]
    assert (course_id, when) == (COURSE_UUID, NOW)
    assert base == settings.lms_api_base  # "LMS에서 열기" 링크를 만들 주소


def test_a_course_that_is_not_mine_is_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/lms/courses/44444444-4444-4444-8444-444444444444")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_a_course_id_that_is_not_a_uuid_is_refused(client: TestClient) -> None:
    response = client.get("/api/v1/lms/courses/214023")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


# ── 과제 마감 캘린더 자동 등록 (F-51·F-32) ──────────────────────────────────

INSERT_EVENT = f"{GOOGLE}/calendars/primary/events"
PATCH_EVENT = f"{GOOGLE}/calendars/primary/events/{EVENT_ROW.replace('-', '')}"


def _new_assignment(title: str = "실습 2주차 결과 제출") -> AssignmentChanges:
    return AssignmentChanges(created=[SavedAssignment("a-1", title, NOW + timedelta(days=4))])


def test_a_new_assignment_goes_into_the_calendar(
    client: TestClient,
    lms: FakeLms,
    calendar: FakeCalendar,
    canvas: respx.MockRouter,
    log: FakeLogConnection,
) -> None:
    lms.changes["course-db"] = _new_assignment()
    lms.titles = {"a-1": "[과제] 데이터베이스 · 실습 2주차 결과 제출"}
    route = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "gcal-1"}))

    client.post(SYNC)
    assert route.called
    sent = json.loads(route.calls[0].request.content)
    assert sent["summary"] == "[과제] 데이터베이스 · 실습 2주차 결과 제출"
    assert sent["id"] == EVENT_ROW.replace("-", "")  # 우리 행 id가 Google 번호다
    # Google 일정 번호는 우리 행 id에서 만든 값이다(응답의 id를 믿지 않는다)
    assert calendar.attached == [(EVENT_ROW, EVENT_ROW.replace("-", ""))]
    output = log.outputs()["save_lms_sync"]
    assert (output["calendar_events"], output["calendar_moved"]) == (1, 0)


def test_the_setting_turns_the_calendar_off(
    client: TestClient, lms: FakeLms, calendar: FakeCalendar, canvas: respx.MockRouter
) -> None:
    """`calendar_auto_lms`를 끄면 Google을 부르지 않는다(명세 4장)."""
    calendar.auto = False
    lms.changes["course-db"] = _new_assignment()
    lms.titles = {"a-1": "[과제] 데이터베이스 · 실습"}
    route = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "x"}))

    client.post(SYNC)
    assert not route.called
    assert calendar.reserved == []
    assert lms.synced_at == NOW  # 동기화 자체는 성공이다


def test_without_a_google_connection_the_calendar_is_skipped(
    client: TestClient,
    lms: FakeLms,
    calendar: FakeCalendar,
    canvas: respx.MockRouter,
    log: FakeLogConnection,
) -> None:
    calendar.connected = False
    lms.changes["course-db"] = _new_assignment()
    lms.titles = {"a-1": "[과제] 데이터베이스 · 실습"}
    route = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "x"}))

    client.post(SYNC)
    assert not route.called
    assert lms.synced_at == NOW
    assert "save_lms_sync" in log.tools()  # 동기화가 끝까지 갔다(캘린더만 건너뛴 것이다)


def test_an_already_submitted_new_assignment_gets_no_event(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    lms.changes["course-db"] = AssignmentChanges(
        created=[SavedAssignment("a-1", "지난 과제", NOW + timedelta(days=4), submitted=True)]
    )
    lms.titles = {"a-1": "[과제] 데이터베이스 · 지난 과제"}
    route = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "x"}))

    client.post(SYNC)
    assert not route.called


def test_an_assignment_without_a_deadline_gets_no_event(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    lms.changes["course-db"] = AssignmentChanges(
        created=[SavedAssignment("a-1", "마감 없는 과제", None)]
    )
    lms.titles = {"a-1": "[과제] 데이터베이스 · 마감 없는 과제"}
    route = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "x"}))

    client.post(SYNC)
    assert not route.called


def test_a_changed_deadline_moves_the_event(
    client: TestClient,
    lms: FakeLms,
    calendar: FakeCalendar,
    canvas: respx.MockRouter,
    log: FakeLogConnection,
) -> None:
    """마감이 바뀌면 이미 넣은 일정의 시각을 고친다 — 새 일정을 만들지 않는다(S17)."""
    moved_to = NOW + timedelta(days=6)
    lms.changes["course-db"] = AssignmentChanges(
        due_changed=[SavedAssignment("a-1", "실습 2주차 결과 제출", moved_to)]
    )
    lms.titles = {"a-1": "[과제] 데이터베이스 · 실습 2주차 결과 제출"}
    calendar.events["a-1"] = CalendarEventView(
        id=EVENT_ROW,
        provider="google",
        external_event_id="gcal-1",
        title="[과제] 데이터베이스 · 실습 2주차 결과 제출",
        starts_at=NOW,
        all_day=False,
    )
    insert = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "new"}))
    patch = canvas.patch(f"{GOOGLE}/calendars/primary/events/gcal-1").mock(
        return_value=httpx.Response(200, json={"id": "gcal-1"})
    )

    client.post(SYNC)
    assert patch.called and not insert.called
    assert calendar.moved and calendar.moved[0][0] == EVENT_ROW
    output = log.outputs()["save_lms_sync"]
    assert (output["calendar_events"], output["calendar_moved"]) == (0, 1)


def test_a_changed_deadline_without_an_event_adds_nothing(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter, log: FakeLogConnection
) -> None:
    """캘린더에 넣지 않았던 과제는 마감이 바뀌어도 새로 넣지 않는다(학생이 지웠을 수 있다)."""
    lms.changes["course-db"] = AssignmentChanges(
        due_changed=[SavedAssignment("a-1", "실습", NOW + timedelta(days=6))]
    )
    lms.titles = {"a-1": "[과제] 데이터베이스 · 실습"}
    insert = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "x"}))

    client.post(SYNC)
    assert not insert.called
    assert "save_lms_sync" in log.tools()  # 터지지 않고 끝까지 갔다


def test_a_deadline_that_disappeared_moves_nothing(
    client: TestClient,
    lms: FakeLms,
    calendar: FakeCalendar,
    canvas: respx.MockRouter,
    log: FakeLogConnection,
) -> None:
    """마감이 사라진 과제(due_at이 null로 바뀜)는 일정을 고치지 않는다."""
    lms.changes["course-db"] = AssignmentChanges(due_changed=[SavedAssignment("a-1", "실습", None)])
    lms.titles = {"a-1": "[과제] 데이터베이스 · 실습"}
    calendar.events["a-1"] = CalendarEventView(
        id=EVENT_ROW,
        provider="google",
        external_event_id="gcal-1",
        title="[과제] 데이터베이스 · 실습",
        starts_at=NOW,
        all_day=False,
    )
    patch = canvas.patch(f"{GOOGLE}/calendars/primary/events/gcal-1").mock(
        return_value=httpx.Response(200, json={"id": "gcal-1"})
    )

    client.post(SYNC)
    assert not patch.called
    assert calendar.moved == []
    # 할 일이 없으면 캘린더 단계 자체를 열지 않는다(토큰을 꺼내 볼 이유가 없다)
    assert "register_calendar" not in log.tools()


def test_an_assignment_already_in_the_calendar_is_not_added_twice(
    client: TestClient, lms: FakeLms, calendar: FakeCalendar, canvas: respx.MockRouter
) -> None:
    """앞선 동기화가 이미 넣었다(자리에 Google 번호가 붙어 있다). 또 부르지 않는다."""
    lms.changes["course-db"] = _new_assignment()
    lms.titles = {"a-1": "[과제] 데이터베이스 · 실습 2주차 결과 제출"}
    calendar.events["a-1"] = CalendarEventView(
        id=EVENT_ROW,
        provider="google",
        external_event_id="gcal-1",
        title="[과제] 데이터베이스 · 실습 2주차 결과 제출",
        starts_at=NOW,
        all_day=False,
    )
    insert = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "x"}))

    client.post(SYNC)
    assert not insert.called
    assert calendar.attached == []


def test_an_event_the_student_deleted_is_not_brought_back(
    client: TestClient, lms: FakeLms, calendar: FakeCalendar, canvas: respx.MockRouter
) -> None:
    lms.changes["course-db"] = AssignmentChanges(
        due_changed=[SavedAssignment("a-1", "실습", NOW + timedelta(days=6))]
    )
    lms.titles = {"a-1": "[과제] 데이터베이스 · 실습"}
    calendar.events["a-1"] = CalendarEventView(
        id=EVENT_ROW,
        provider="google",
        external_event_id="gcal-1",
        title="[과제] 데이터베이스 · 실습",
        starts_at=NOW,
        all_day=False,
    )
    canvas.patch(f"{GOOGLE}/calendars/primary/events/gcal-1").mock(
        return_value=httpx.Response(404, json={})
    )
    insert = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "new"}))

    client.post(SYNC)
    assert not insert.called
    assert calendar.attached == []


def test_a_google_outage_does_not_fail_the_sync(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter, log: FakeLogConnection
) -> None:
    """과제·주차 자료는 이미 저장했다. 캘린더만 다음 동기화로 미룬다."""
    lms.changes["course-db"] = _new_assignment()
    lms.titles = {"a-1": "[과제] 데이터베이스 · 실습"}
    canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(503, json={}))

    assert client.post(SYNC).status_code == 202
    assert lms.synced_at == NOW
    assert log.outputs()["save_lms_sync"]["calendar_events"] == 0


def test_a_token_refresh_failure_does_not_fail_the_sync(
    client: TestClient,
    lms: FakeLms,
    calendar: FakeCalendar,
    canvas: respx.MockRouter,
    log: FakeLogConnection,
) -> None:
    """Google 토큰 갱신이 막혀도(502) 과제·자료는 저장되고 동기화는 성공이다.

    액세스 토큰은 1시간, 배치는 30분이라 갱신 경로는 자주 탄다. 여기서 터지면 다 받아 놓고도
    학생 화면에는 "LMS 자료를 가져오지 못했어요"가 뜬다.
    """
    calendar.expires_in = timedelta(0)  # 만료됐다 → 갱신 경로
    canvas.post(f"{GOOGLE}/token").mock(return_value=httpx.Response(503, json={}))
    insert = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "x"}))
    lms.changes["course-db"] = _new_assignment()
    lms.titles = {"a-1": "[과제] 데이터베이스 · 실습"}

    client.post(SYNC)
    assert not insert.called
    output = log.outputs()["save_lms_sync"]  # 저장 단계가 있다 = 동기화는 끝까지 갔다
    assert (output["new"], output["calendar_events"]) == (1, 0)
    assert log.outputs()["register_calendar"] == {"skipped": True}


def test_the_next_sync_retries_what_google_refused(
    client: TestClient,
    lms: FakeLms,
    calendar: FakeCalendar,
    canvas: respx.MockRouter,
    log: FakeLogConnection,
) -> None:
    """앞 동기화에서 Google이 막혀 자리만 남은 과제를, 변화가 없는 다음 동기화가 다시 넣는다."""
    calendar.pending = [
        AssignmentDeadline("a-1", "실습 2주차 결과 제출", "데이터베이스", NOW + timedelta(days=4))
    ]
    calendar.events["a-1"] = CalendarEventView(
        id=EVENT_ROW,
        provider="google",
        external_event_id=None,  # 자리는 잡았는데 Google에 못 넣었다
        title="[과제] 데이터베이스 · 실습 2주차 결과 제출",
        starts_at=NOW,
        all_day=False,
    )
    route = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "gcal-1"}))

    client.post(SYNC)  # 이번 동기화에는 새 과제도 마감 변경도 없다
    assert route.called
    sent = json.loads(route.calls[0].request.content)
    assert sent["summary"] == "[과제] 데이터베이스 · 실습 2주차 결과 제출"
    assert sent["id"] == EVENT_ROW.replace(
        "-", ""
    )  # 같은 자리 = 같은 번호. 일정이 둘로 늘지 않는다
    assert calendar.attached == [(EVENT_ROW, EVENT_ROW.replace("-", ""))]
    assert log.outputs()["save_lms_sync"]["calendar_events"] == 1


def test_an_assignment_in_this_round_is_not_retried_twice(
    client: TestClient, lms: FakeLms, calendar: FakeCalendar, canvas: respx.MockRouter
) -> None:
    """이번에 새로 들어온 과제가 줍는 목록에도 있으면 한 번만 넣는다."""
    lms.changes["course-db"] = _new_assignment()
    lms.titles = {"a-1": "[과제] 데이터베이스 · 실습 2주차 결과 제출"}
    calendar.pending = [
        AssignmentDeadline("a-1", "실습 2주차 결과 제출", "데이터베이스", NOW + timedelta(days=4))
    ]
    route = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "gcal-1"}))

    client.post(SYNC)
    assert len(route.calls) == 1


def test_an_assignment_that_came_back_with_a_new_deadline_moves(
    client: TestClient,
    lms: FakeLms,
    calendar: FakeCalendar,
    canvas: respx.MockRouter,
    log: FakeLogConnection,
) -> None:
    """내렸다 다시 올린 과제는 "새 과제"로 들어오지만 일정은 이미 있다. 마감이 다르면 고친다."""
    lms.changes["course-db"] = _new_assignment()  # 마감 NOW+4일
    lms.titles = {"a-1": "[과제] 데이터베이스 · 실습 2주차 결과 제출"}
    calendar.events["a-1"] = CalendarEventView(
        id=EVENT_ROW,
        provider="google",
        external_event_id="gcal-1",
        title="[과제] 데이터베이스 · 실습 2주차 결과 제출",
        starts_at=NOW,  # 옛 마감
        all_day=False,
    )
    insert = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "x"}))
    patch = canvas.patch(f"{GOOGLE}/calendars/primary/events/gcal-1").mock(
        return_value=httpx.Response(200, json={"id": "gcal-1"})
    )

    client.post(SYNC)
    assert not insert.called
    assert patch.called
    sent = json.loads(patch.calls[0].request.content)
    assert sent["end"]["dateTime"] == (NOW + timedelta(days=4)).astimezone(KST).isoformat()
    assert log.outputs()["save_lms_sync"]["calendar_moved"] == 1


def test_the_event_ends_at_the_deadline_and_lasts_an_hour(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """자동 등록도 "마감 시각으로 끝나는 1시간, KST"다(명세 7장)."""
    due = NOW + timedelta(days=4)
    lms.changes["course-db"] = _new_assignment()
    lms.titles = {"a-1": "[과제] 데이터베이스 · 실습"}
    route = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "gcal-1"}))

    client.post(SYNC)
    sent = json.loads(route.calls[0].request.content)
    assert sent["end"]["dateTime"] == due.astimezone(KST).isoformat()
    assert sent["start"]["dateTime"] == (due - timedelta(hours=1)).astimezone(KST).isoformat()
    assert sent["start"]["timeZone"] == "Asia/Seoul"


def test_an_event_gone_from_google_410_is_not_brought_back(
    client: TestClient, lms: FakeLms, calendar: FakeCalendar, canvas: respx.MockRouter
) -> None:
    """410(완전히 지움)도 404와 같다 — 학생이 지운 일정은 되살리지 않는다."""
    lms.changes["course-db"] = AssignmentChanges(
        due_changed=[SavedAssignment("a-1", "실습", NOW + timedelta(days=6))]
    )
    lms.titles = {"a-1": "[과제] 데이터베이스 · 실습"}
    calendar.events["a-1"] = CalendarEventView(
        id=EVENT_ROW,
        provider="google",
        external_event_id="gcal-1",
        title="[과제] 데이터베이스 · 실습",
        starts_at=NOW,
        all_day=False,
    )
    canvas.patch(f"{GOOGLE}/calendars/primary/events/gcal-1").mock(
        return_value=httpx.Response(410, json={})
    )
    insert = canvas.post(INSERT_EVENT).mock(return_value=httpx.Response(200, json={"id": "x"}))

    client.post(SYNC)
    assert not insert.called
    assert calendar.moved == []


# ── 과목 공지 (F-53) ────────────────────────────────────────────────────────


def pending(
    topic_id: int = RESEARCH_TOPIC_ID,
    *,
    title: str = RESEARCH_TITLE,
    message: str = "지원 자격: 3학년 이상",
    course: int = 214023,
    category: str | None = None,
) -> PendingAnnouncement:
    return PendingAnnouncement(
        id=f"n-{topic_id}",
        canvas_course_id=course,
        canvas_topic_id=topic_id,
        title=title,
        message=message,
        posted_at=NOW - timedelta(days=2),
        category=category,  # type: ignore[arg-type]
        summary=None,
    )


def classify_reply(category: str, summary: str = "한 줄 요약", **extra: Any) -> Any:
    return model_call("submit_announcement", category=category, summary=summary, **extra)


def submit_requirements(**extra: Any) -> Any:
    """요건 추출 에이전트의 제출. 근거 문장은 공지 본문에 있는 글이어야 통과한다."""
    return model_call(
        "submit_requirements",
        requirements=[
            {
                "clause_no": 1,
                "field": "grade",
                "operator": "gte",
                "value_json": "3",
                "evidence_text": "지원 자격: 3학년 이상",
                "is_ambiguous": False,
            }
        ],
        documents=[],
        confidence=0.9,
        needs_review=False,
        **extra,
    )


def test_it_saves_the_announcements_of_every_course(
    client: TestClient, announcements_repo: FakeAnnouncements
) -> None:
    client.post(SYNC)
    saved = {course: [one.title for one in items] for course, items in announcements_repo.saved}
    assert saved == {
        214023: [RESEARCH_TITLE, "휴강 안내", "3주차 강의에 사용한 json 파일"],
        216515: ["중간고사 안내"],
    }
    # 본문은 평문으로 바꿔 저장한다(화면·분류·요건 추출이 같은 글을 본다)
    first = announcements_repo.saved[0][1][0]
    assert "<p>" not in (first.message or "")
    assert "모집 인원: 2명" in (first.message or "")
    assert first.attachment_count == 0


def test_the_result_counts_the_new_announcements(
    client: TestClient, log: FakeLogConnection
) -> None:
    client.post(SYNC)
    assert log.outputs()["save_lms_sync"]["new_announcements"] == 4


def test_it_does_not_call_the_model_when_there_is_nothing_to_classify(
    client: TestClient, llm: ScriptedLlm
) -> None:
    client.post(SYNC)
    assert llm.requests == []


def test_a_schedule_change_announcement_is_only_classified(
    client: TestClient,
    announcements_repo: FakeAnnouncements,
    llm: ScriptedLlm,
    log: FakeLogConnection,
) -> None:
    """갈래만 정하고 공고는 만들지 않는다(플래너 반영은 F-53 2부다)."""
    announcements_repo.pending_rows = [pending(title="휴강 안내", message="10월 20일 휴강합니다")]
    llm.replies = [classify_reply("schedule_change", "10월 20일 수업은 휴강한다")]

    client.post(SYNC)

    assert announcements_repo.classified == [
        (f"n-{RESEARCH_TOPIC_ID}", "schedule_change", "10월 20일 수업은 휴강한다")
    ]
    assert announcements_repo.created == []
    assert "classify_announcement" in log.tools()
    assert log.outputs()["save_lms_sync"]["classified_announcements"] == 1
    assert log.outputs()["save_lms_sync"]["announcement_opportunities"] == 0


def test_an_opportunity_announcement_becomes_an_opportunity(
    client: TestClient,
    announcements_repo: FakeAnnouncements,
    llm: ScriptedLlm,
    log: FakeLogConnection,
) -> None:
    announcements_repo.pending_rows = [pending()]
    llm.replies = [
        classify_reply("opportunity", "연구 참여 학생을 모집한다", opportunity_category="research"),
        submit_requirements(),
    ]

    client.post(SYNC)

    assert announcements_repo.created == [(f"n-{RESEARCH_TOPIC_ID}", "research")]
    # 공고 원문 링크는 저장한 주소가 아니라 LMS 주소 + 번호로 만든다(명세 8장)
    assert announcements_repo.urls == [
        f"{BASE}/courses/214023/discussion_topics/{RESEARCH_TOPIC_ID}"
    ]
    extraction = announcements_repo.extractions[0]
    assert extraction.succeeded and len(extraction.requirements) == 1
    assert log.outputs()["save_lms_sync"]["announcement_opportunities"] == 1


def test_the_classify_call_uses_the_cheap_model_and_the_announcement_text(
    client: TestClient, announcements_repo: FakeAnnouncements, llm: ScriptedLlm
) -> None:
    announcements_repo.pending_rows = [pending()]
    llm.replies = [classify_reply("general")]

    client.post(SYNC)

    first = llm.requests[0]
    assert first.model == CLASSIFY_MODEL
    assert first.force_tool == "submit_announcement"
    message = first.turns[0].text  # type: ignore[union-attr]
    assert RESEARCH_TITLE in message and "지원 자격: 3학년 이상" in message


def test_a_retried_announcement_is_not_classified_again(
    client: TestClient, announcements_repo: FakeAnnouncements, llm: ScriptedLlm
) -> None:
    """분류는 끝났고 공고만 못 만든 공지. 모델은 요건 추출에만 쓴다."""
    announcements_repo.pending_rows = [pending(category="opportunity")]
    llm.replies = [submit_requirements()]

    client.post(SYNC)

    assert announcements_repo.classified == []  # 다시 분류하지 않는다
    assert announcements_repo.created == [(f"n-{RESEARCH_TOPIC_ID}", "etc")]
    assert [one.model for one in llm.requests] == [EXTRACTION_MODEL]


def test_an_already_linked_announcement_makes_no_second_opportunity(
    client: TestClient, announcements_repo: FakeAnnouncements, llm: ScriptedLlm
) -> None:
    announcements_repo.pending_rows = [pending(category="opportunity")]
    announcements_repo.linked.add(f"n-{RESEARCH_TOPIC_ID}")  # 다른 수강생이 먼저 만들었다
    llm.replies = [submit_requirements()]

    client.post(SYNC)

    assert announcements_repo.created == []


def test_the_sync_still_succeeds_when_classifying_fails(
    client: TestClient, announcements_repo: FakeAnnouncements, lms: FakeLms
) -> None:
    """모델이 터져도 과제·주차 자료·공지는 이미 저장했다. 그 공지는 다음 동기화에서 다시 본다."""
    announcements_repo.pending_rows = [pending()]  # 모델에 답을 담아 두지 않았다

    response = client.post(SYNC)

    assert response.status_code == 202
    assert announcements_repo.classified == []
    assert lms.synced_at == NOW  # 동기화는 끝까지 갔다
    assert lms.error is None  # 연결을 오류로 바꾸지 않는다


def test_it_only_classifies_my_courses_and_recent_announcements(
    client: TestClient, announcements_repo: FakeAnnouncements
) -> None:
    client.post(SYNC)
    courses, recent_from, limit = announcements_repo.asked[0]
    assert sorted(courses) == [214023, 216515]
    assert recent_from == NOW - timedelta(days=30)
    assert limit == 5


def test_a_course_whose_announcements_fail_is_skipped(
    client: TestClient, canvas: respx.MockRouter, announcements_repo: FakeAnnouncements
) -> None:
    """공지를 못 받아도 동기화는 성공이다(과제·주차 자료는 이미 받았다)."""
    canvas.get(f"{BASE}/api/v1/courses/214023/discussion_topics").mock(
        return_value=httpx.Response(500)
    )

    response = client.post(SYNC)

    assert response.status_code == 202
    assert [course for course, _ in announcements_repo.saved] == [216515]


# ── 일정 변경 공지 → 플래너 (F-53 2부) ──────────────────────────────────────


def test_a_schedule_change_with_a_date_becomes_a_planner_task(
    client: TestClient,
    announcements_repo: FakeAnnouncements,
    notes: FakeNotes,
    llm: ScriptedLlm,
    log: FakeLogConnection,
) -> None:
    announcements_repo.pending_rows = [pending(title="휴강 안내", message="10월 20일 휴강합니다")]
    llm.replies = [
        classify_reply(
            "schedule_change",
            "10월 20일 수업은 휴강한다",
            change_date="2026-10-20",
            change_kind="cancelled",
        )
    ]

    client.post(SYNC)

    assert announcements_repo.schedule_tasks == [
        (f"n-{RESEARCH_TOPIC_ID}", 214023, "휴강", date(2026, 10, 20))
    ]
    assert [(one.title, one.body) for one in notes.schedules] == [
        ("데이터베이스 수업 일정이 바뀌었어요", "10월 20일 수업은 휴강한다")
    ]
    assert log.outputs()["save_lms_sync"]["schedule_tasks"] == 1


def test_a_schedule_change_without_a_date_is_only_classified(
    client: TestClient,
    announcements_repo: FakeAnnouncements,
    notes: FakeNotes,
    llm: ScriptedLlm,
) -> None:
    """무슨 날인지 모르면 할 일을 만들지 않는다(갈래만 적는다)."""
    announcements_repo.pending_rows = [pending(title="보강 안내")]
    llm.replies = [classify_reply("schedule_change", "보강을 한다", change_kind="time")]

    client.post(SYNC)

    assert announcements_repo.classified and announcements_repo.schedule_tasks == []
    assert notes.schedules == []


def test_a_schedule_change_in_the_past_is_only_classified(
    client: TestClient,
    announcements_repo: FakeAnnouncements,
    notes: FakeNotes,
    llm: ScriptedLlm,
) -> None:
    """지난 휴강은 할 일이 아니다. 지금(NOW)보다 앞선 날짜는 버린다."""
    announcements_repo.pending_rows = [pending(title="휴강 안내")]
    llm.replies = [classify_reply("schedule_change", "어제 휴강했다", change_date="2026-10-15")]

    client.post(SYNC)

    assert announcements_repo.schedule_tasks == []
    assert notes.schedules == []


def test_a_made_up_change_date_is_dropped(
    client: TestClient, announcements_repo: FakeAnnouncements, llm: ScriptedLlm
) -> None:
    """게시일에서 너무 먼 날짜는 모델이 지어낸 것으로 보고 버린다(게시일 + 120일까지)."""
    announcements_repo.pending_rows = [pending(title="휴강 안내")]
    llm.replies = [classify_reply("schedule_change", "휴강한다", change_date="2027-06-01")]

    client.post(SYNC)

    assert announcements_repo.schedule_tasks == []
