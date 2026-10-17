"""계획서 추출 API(F-14): `POST /syllabi/extract`와 `GET /runs/{id}`.

서비스·저장소는 가짜다. 실제 실행(저장소 → 모델 → 저장)과 SQL은 test_syllabi_db.py가 본다.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.calendar.service import get_calendar_service
from app.clock import current_time
from app.eligibility import KST
from app.errors import ApiError
from app.repositories.calendar import get_calendar_repo
from app.repositories.runs import get_run_repo
from app.repositories.syllabi import (
    StoredItem,
    SyllabusCourse,
    SyllabusFile,
    SyllabusHead,
    get_syllabus_repo,
)
from app.schemas.calendar import CalendarEventView
from app.schemas.syllabi import SyllabusExtractResult, SyllabusItemView
from app.syllabi.service import SyllabusJob, get_syllabus_service
from tests.conftest import USER_ID
from tests.prepare_fakes import FakeRunRepository, new_id, run_row

EXTRACT = "/api/v1/syllabi/extract"
NOW = datetime(2026, 10, 17, 1, 0, tzinfo=UTC)  # 10/17 10:00 KST
FILE_ID = "00000000-0000-4000-8000-0000000000f2"
COURSE_ID = "00000000-0000-4000-8000-0000000000c1"
OTHER_FILE = "00000000-0000-4000-8000-0000000000f9"
FILE = SyllabusFile(FILE_ID, f"{USER_ID}/syllabus/{FILE_ID}.pdf")
COURSE = SyllabusCourse(COURSE_ID, "202620HY23525_데이터베이스", "데이터베이스", None)
SYLLABUS_ID = "00000000-0000-4000-8000-0000000000a9"
HEAD = SyllabusHead(SYLLABUS_ID, COURSE_ID, "데이터베이스", "데이터베이스")


class FakeSyllabusRepository:
    def __init__(self) -> None:
        self.files = {(USER_ID, FILE_ID): FILE}
        self.courses = {(USER_ID, COURSE_ID): COURSE}
        self.already: str | None = None
        self.heads = {(USER_ID, SYLLABUS_ID): HEAD}
        self.stored: list[StoredItem] = []
        self.confirmed: list[tuple[str, str, bool]] = []
        self.saved_times: dict[str, Any] = {}
        self.tasks: list[tuple[str, bool]] = []
        self.made_tasks: set[str] = set()  # 이미 만든 할 일(두 번째 확정은 0건이다)

    async def syllabus_file(self, user_id: str, file_id: str) -> SyllabusFile | None:
        return self.files.get((user_id, file_id))

    async def course(self, user_id: str, course_id: str) -> SyllabusCourse | None:
        return self.courses.get((user_id, course_id))

    async def existing(self, user_id: str, course_id: str) -> str | None:
        return self.already

    async def one(self, user_id: str, syllabus_id: str) -> SyllabusHead | None:
        return self.heads.get((user_id, syllabus_id))

    async def items(self, user_id: str, syllabus_id: str) -> list[StoredItem]:
        if (user_id, syllabus_id) not in self.heads:
            return []
        return list(self.stored)

    async def confirm_item(
        self,
        user_id: str,
        item_id: str,
        *,
        syllabus_id: str,
        title: str,
        starts_at: Any,
        selected: bool,
    ) -> None:
        assert (user_id, syllabus_id) in self.heads  # 내 계획서의 일정만 고친다
        self.confirmed.append((item_id, title, selected))
        self.saved_times[item_id] = starts_at

    async def sync_task(
        self, user_id: str, item: StoredItem, *, selected: bool, course_id: str | None
    ) -> bool:
        """실제 저장소처럼 흉내 낸다 — 이미 있는 할 일은 맞추기만 하고 False다."""
        self.tasks.append((item.id, selected))
        if not selected or item.starts_at is None:
            self.made_tasks.discard(item.id)
            return False
        if item.id in self.made_tasks:
            return False
        self.made_tasks.add(item.id)
        return True


class FakeCalendarRepository:
    """자리 잡기와 붙이기만 흉내 낸다. SQL은 test_calendar_db.py가 본다."""

    def __init__(self) -> None:
        self.events: dict[str, CalendarEventView] = {}
        self.reserved: list[dict[str, Any]] = []
        self.attached: list[tuple[str, str]] = []
        self.moved: list[tuple[str, str | None, datetime]] = []
        self.commits = 0

    async def event_for(
        self, user_id: str, provider: str, *, syllabus_item_id: str | None = None, **_: Any
    ) -> CalendarEventView | None:
        return self.events.get(f"{syllabus_item_id}:{provider}")

    async def reserve(self, user_id: str, **values: Any) -> CalendarEventView:
        self.reserved.append(values)
        key = f"{values['syllabus_item_id']}:{values['provider']}"
        found = self.events.get(key)
        if found is not None:
            return found
        event = CalendarEventView(
            id=f"00000000-0000-4000-8000-0000000{len(self.events) + 11:05d}",
            provider=values["provider"],
            external_event_id=None,
            title=values["title"],
            starts_at=values["starts_at"],
            all_day=False,
        )
        self.events[key] = event
        return event

    async def commit_reservation(self) -> None:
        self.commits += 1

    async def move(
        self, user_id: str, event_id: str, *, starts_at: datetime, title: str | None = None
    ) -> None:
        self.moved.append((event_id, title, starts_at))
        for key, event in self.events.items():
            if event.id == event_id:
                update: dict[str, Any] = {"starts_at": starts_at}
                if title is not None:
                    update["title"] = title
                self.events[key] = event.model_copy(update=update)

    def reserved_id(self) -> str:
        """자리를 하나만 잡은 테스트에서 그 행 id."""
        assert len(self.events) == 1
        return next(iter(self.events.values())).id

    async def attach(self, user_id: str, event_id: str, external_event_id: str) -> None:
        self.attached.append((event_id, external_event_id))
        for key, event in self.events.items():
            if event.id == event_id:
                self.events[key] = event.model_copy(update={"external_event_id": external_event_id})


class FakeCalendarService:
    def __init__(self) -> None:
        self.connected = True
        self.inserted: list[tuple[str, str, datetime]] = []
        self.moved: list[tuple[str, str, datetime]] = []
        self.fails = False
        self.revoked = False  # Google이 401로 거절한다(학생이 권한을 거뒀다)
        self.gone = False  # 학생이 캘린더에서 그 일정을 지웠다(404)

    async def access_token(self, user_id: str, now: datetime) -> str:
        if not self.connected:
            raise ApiError(
                409,
                "CALENDAR_NOT_CONNECTED",
                "Google 캘린더를 연결해 주세요.",
                {"reason": "not_connected"},
            )
        return "access-1"

    async def insert(self, token: str, *, event_id: str, title: str, ends_at: datetime) -> str:
        self._check()
        self.inserted.append((event_id, title, ends_at))
        return event_id

    async def move(self, token: str, *, event_id: str, title: str, ends_at: datetime) -> str | None:
        self._check()
        if self.gone:
            return None
        self.moved.append((event_id, title, ends_at))
        return event_id

    def _check(self) -> None:
        if self.revoked:  # 만료 전이라 라우터의 사전 점검은 통과한다
            raise ApiError(
                409,
                "CALENDAR_NOT_CONNECTED",
                "캘린더 권한이 만료됐어요. 다시 연결해 주세요.",
                {"reason": "expired"},
            )
        if self.fails:
            raise ApiError(502, "GOOGLE_API_ERROR", "Google 캘린더가 응답하지 않아요.")


class FakeSyllabusService:
    def __init__(self) -> None:
        self.jobs: list[SyllabusJob] = []
        self.run_id = new_id()

    async def begin(self, job: SyllabusJob) -> str:
        self.jobs.append(job)
        return self.run_id


@pytest.fixture
def syllabi(client: TestClient) -> FakeSyllabusRepository:
    fake = FakeSyllabusRepository()
    fake.stored = [
        _stored(ITEM_ONE, "midterm", "중간고사", MIDTERM),
        _stored(ITEM_TWO, "presentation", "팀 프로젝트 발표", MIDTERM),
        _stored(NO_DATE_ITEM, "etc", "보강", None),
    ]
    client.app.dependency_overrides[get_syllabus_repo] = lambda: fake  # type: ignore[attr-defined]
    client.app.dependency_overrides[current_time] = lambda: NOW  # type: ignore[attr-defined]
    return fake


@pytest.fixture
def gcal(client: TestClient) -> tuple[FakeCalendarRepository, FakeCalendarService]:
    repo, service = FakeCalendarRepository(), FakeCalendarService()
    client.app.dependency_overrides[get_calendar_repo] = lambda: repo  # type: ignore[attr-defined]
    client.app.dependency_overrides[get_calendar_service] = lambda: service  # type: ignore[attr-defined]
    return repo, service


@pytest.fixture
def service(client: TestClient) -> FakeSyllabusService:
    fake = FakeSyllabusService()
    client.app.dependency_overrides[get_syllabus_service] = lambda: fake  # type: ignore[attr-defined]
    return fake


@pytest.fixture
def runs(client: TestClient) -> FakeRunRepository:
    fake = FakeRunRepository()
    client.app.dependency_overrides[get_run_repo] = lambda: fake  # type: ignore[attr-defined]
    return fake


def test_extract_requires_login(client: TestClient) -> None:
    assert client.post(EXTRACT, json={"file_id": FILE_ID}).status_code == 401


def test_it_starts_a_run_and_points_at_it(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    service: FakeSyllabusService,
) -> None:
    response = client.post(
        EXTRACT, json={"file_id": FILE_ID, "lms_course_id": COURSE_ID}, headers=auth
    )
    assert response.status_code == 202
    assert response.json() == {"run_id": service.run_id, "status": "running"}
    job = service.jobs[0]
    assert (job.user_id, job.file.id, job.course_id) == (USER_ID, FILE_ID, COURSE_ID)
    assert job.course_short_name == "데이터베이스"
    assert job.today.isoformat() == "2026-10-17"  # KST 날짜다(UTC로는 전날 01:00)


def test_a_syllabus_without_a_course_is_allowed(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    service: FakeSyllabusService,
) -> None:
    """LMS를 연결하지 않은 학생도 계획서를 올릴 수 있다(과목 연결 없이 저장한다)."""
    assert client.post(EXTRACT, json={"file_id": FILE_ID}, headers=auth).status_code == 202
    job = service.jobs[0]
    assert (job.course_id, job.course_short_name, job.semester_start) == (None, None, None)


def test_someone_elses_file_is_not_found(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    service: FakeSyllabusService,
) -> None:
    response = client.post(EXTRACT, json={"file_id": OTHER_FILE}, headers=auth)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "NOT_FOUND")
    assert service.jobs == []


def test_an_unknown_course_is_not_found(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    service: FakeSyllabusService,
) -> None:
    response = client.post(
        EXTRACT,
        json={"file_id": FILE_ID, "lms_course_id": "00000000-0000-4000-8000-0000000000cc"},
        headers=auth,
    )
    assert (response.status_code, response.json()["error"]["code"]) == (404, "NOT_FOUND")
    assert service.jobs == []


def test_a_course_that_already_has_a_syllabus_is_refused(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    service: FakeSyllabusService,
) -> None:
    syllabi.already = "00000000-0000-4000-8000-0000000000s1".replace("s", "1")
    response = client.post(
        EXTRACT, json={"file_id": FILE_ID, "lms_course_id": COURSE_ID}, headers=auth
    )
    assert (response.status_code, response.json()["error"]["code"]) == (409, "SYLLABUS_EXISTS")
    assert "이미 계획서가 있어요" in response.json()["error"]["message"]
    assert service.jobs == []


def test_replace_takes_over_the_course(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    service: FakeSyllabusService,
) -> None:
    syllabi.already = "00000000-0000-4000-8000-000000000111"
    response = client.post(
        EXTRACT,
        json={"file_id": FILE_ID, "lms_course_id": COURSE_ID, "replace": True},
        headers=auth,
    )
    assert response.status_code == 202
    assert service.jobs[0].course_id == COURSE_ID


def test_unknown_fields_are_refused(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    service: FakeSyllabusService,
) -> None:
    response = client.post(EXTRACT, json={"file_id": FILE_ID, "course": COURSE_ID}, headers=auth)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "VALIDATION_FAILED")


def test_the_run_shows_the_extracted_items(
    client: TestClient, auth: dict[str, str], runs: FakeRunRepository
) -> None:
    """`GET /runs/{id}`가 뽑은 일정을 보여 준다(명세 8장·11장)."""
    run = run_row(
        id="00000000-0000-4000-8000-0000000000b2",
        user_id=USER_ID,
        trigger_type="syllabus_upload",
        status="succeeded",
    )
    runs.runs[run.id] = run
    runs.syllabus_results[run.id] = SyllabusExtractResult(
        syllabus_id="00000000-0000-4000-8000-000000000222",
        course_name="데이터베이스",
        items=[
            SyllabusItemView(
                id="00000000-0000-4000-8000-000000000333",
                item_type="midterm",
                title="중간고사",
                starts_at=datetime(2026, 10, 20, 10, 30, tzinfo=UTC),
            )
        ],
    )

    body: Any = client.get(f"/api/v1/runs/{run.id}", headers=auth).json()
    assert body["result"]["kind"] == "syllabus_extract"
    assert body["result"]["course_name"] == "데이터베이스"
    assert body["result"]["items"][0]["item_type"] == "midterm"
    assert body["result"]["items"][0]["is_confirmed"] is False


def test_a_failed_extraction_tells_the_student_about_the_syllabus(
    client: TestClient, auth: dict[str, str], runs: FakeRunRepository
) -> None:
    """실패 문구가 준비하기 것("준비 일정을 만들지 못했어요")으로 나가면 안 된다.

    코드를 남기지 못한 실패(예: 저장 중 DB 오류)도 계획서 이야기를 해야 한다.
    """
    run = run_row(
        id="00000000-0000-4000-8000-0000000000b3",
        user_id=USER_ID,
        trigger_type="syllabus_upload",
        status="failed",
        error_message="RuntimeError()",
    )
    runs.runs[run.id] = run

    error = client.get(f"/api/v1/runs/{run.id}", headers=auth).json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert "계획서" in error["message"] and "준비 일정" not in error["message"]


CONFIRM = f"/api/v1/syllabi/{SYLLABUS_ID}/confirm"
ITEM_ONE = "00000000-0000-4000-8000-000000000a01"
ITEM_TWO = "00000000-0000-4000-8000-000000000a02"
NO_DATE_ITEM = "00000000-0000-4000-8000-000000000a03"
MIDTERM = datetime(2026, 11, 3, 1, 30, tzinfo=UTC)  # 11/3 10:30 KST


def _stored(item_id: str, kind: str, title: str, starts_at: datetime | None) -> StoredItem:
    return StoredItem(
        id=item_id, item_type=kind, title=title, starts_at=starts_at, is_confirmed=False
    )


def _counts(confirmed: int, tasks: int, events: int, moved: int = 0) -> dict[str, int]:
    return {
        "confirmed": confirmed,
        "planner_tasks_created": tasks,
        "calendar_events_created": events,
        "calendar_events_moved": moved,
    }


def body(*items: dict[str, Any], **over: Any) -> dict[str, Any]:
    return {"items": list(items), **over}


def chosen(item_id: str, title: str = "중간고사", **over: Any) -> dict[str, Any]:
    return {"id": item_id, "title": title, "selected": True, **over}


def test_confirm_requires_login(client: TestClient) -> None:
    assert client.post(CONFIRM, json=body(chosen(ITEM_ONE))).status_code == 401


def test_it_confirms_the_chosen_items_and_makes_tasks(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    response = client.post(
        CONFIRM,
        json=body(
            chosen(ITEM_ONE), {"id": ITEM_TWO, "title": "팀 프로젝트 발표", "selected": False}
        ),
        headers=auth,
    )
    assert response.status_code == 200
    assert response.json() == _counts(1, 1, 0)
    assert syllabi.confirmed == [
        (ITEM_ONE, "중간고사", True),
        (ITEM_TWO, "팀 프로젝트 발표", False),
    ]
    assert syllabi.tasks == [(ITEM_ONE, True), (ITEM_TWO, False)]


def test_a_fixed_title_and_time_are_saved(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    """확인 화면에서 고친 제목·시각을 그대로 저장한다."""
    client.post(
        CONFIRM,
        json=body(
            chosen(ITEM_ONE, title="중간고사(온라인)", starts_at="2026-11-04T13:00:00+09:00")
        ),
        headers=auth,
    )
    assert syllabi.confirmed[0][1] == "중간고사(온라인)"
    assert syllabi.saved_times[ITEM_ONE].isoformat() == "2026-11-04T13:00:00+09:00"


def test_an_item_that_is_not_in_the_syllabus_is_refused(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    response = client.post(
        CONFIRM, json=body(chosen("00000000-0000-4000-8000-00000000aaaa")), headers=auth
    )
    assert (response.status_code, response.json()["error"]["code"]) == (422, "VALIDATION_FAILED")
    assert syllabi.confirmed == []  # 하나라도 모르면 아무것도 바꾸지 않는다


def test_choosing_an_item_without_a_date_is_refused(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    response = client.post(CONFIRM, json=body(chosen(NO_DATE_ITEM, title="보강")), headers=auth)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "VALIDATION_FAILED")
    assert "날짜" in response.json()["error"]["message"]
    assert syllabi.confirmed == []


def test_another_students_syllabus_is_not_found(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    other = "/api/v1/syllabi/00000000-0000-4000-8000-0000000000ff/confirm"
    response = client.post(other, json=body(chosen(ITEM_ONE)), headers=auth)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "NOT_FOUND")


def test_an_empty_list_is_refused(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    response = client.post(CONFIRM, json=body(), headers=auth)
    assert response.status_code == 422


def test_it_also_puts_the_chosen_items_in_the_calendar(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    calendar, service = gcal
    response = client.post(
        CONFIRM,
        json=body(chosen(ITEM_ONE), register_calendar=True),
        headers=auth,
    )
    assert response.status_code == 200
    assert response.json()["calendar_events_created"] == 1
    assert service.inserted[0][1] == "[시험] 데이터베이스 · 중간고사"
    # 시험은 **그 시각에 시작**해 1시간 뒤에 끝난다(공고·과제 마감과 반대다. 계획서 일정은 마감이
    # 아니라 시작 시각이라서, 캘린더 API로 넣을 때(`syllabus_item_id`)와 같은 시각이어야 한다)
    assert calendar.reserved[0]["starts_at"] == MIDTERM.astimezone(KST)
    assert service.inserted[0][2] == MIDTERM.astimezone(KST) + timedelta(hours=1)
    assert calendar.attached == [(calendar.reserved_id(), service.inserted[0][0])]
    assert calendar.commits == 1  # Google을 부르기 전에 자리를 확정한다


def test_no_calendar_connection_changes_nothing(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    """캘린더를 부탁했는데 연결이 없으면 확정도 하지 않는다(연결하고 다시 누르면 된다)."""
    calendar, service = gcal
    service.connected = False
    response = client.post(
        CONFIRM, json=body(chosen(ITEM_ONE), register_calendar=True), headers=auth
    )
    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "CALENDAR_NOT_CONNECTED",
    )
    assert syllabi.confirmed == []
    assert calendar.reserved == []


def test_a_google_failure_still_keeps_the_confirmation(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    calendar, service = gcal
    service.fails = True
    response = client.post(
        CONFIRM, json=body(chosen(ITEM_ONE), register_calendar=True), headers=auth
    )
    assert response.status_code == 200
    assert response.json() == _counts(1, 1, 0)
    assert len(calendar.reserved) == 1  # 자리는 남는다 — 다시 누르면 같은 번호로 들어간다
    assert calendar.attached == []


def test_an_item_already_in_the_calendar_is_not_added_twice(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    calendar, service = gcal
    sent = body(chosen(ITEM_ONE), register_calendar=True)
    assert client.post(CONFIRM, json=sent, headers=auth).json()["calendar_events_created"] == 1
    again = client.post(CONFIRM, json=sent, headers=auth)
    assert again.json() == _counts(1, 0, 0)  # 할 일도 일정도 새로 만들지 않는다
    assert len(service.inserted) == 1


def test_a_past_item_is_confirmed_but_not_put_in_the_calendar(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    """지난 시험은 저장만 한다(지난 일정을 캘린더에 넣어도 쓸 데가 없다)."""
    calendar, service = gcal
    syllabi.stored = [_stored(ITEM_ONE, "midterm", "중간고사", NOW - timedelta(days=3))]
    response = client.post(
        CONFIRM, json=body(chosen(ITEM_ONE), register_calendar=True), headers=auth
    )
    assert response.json() == _counts(1, 1, 0)
    assert calendar.reserved == []


def test_an_unselected_item_never_reaches_the_calendar(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    calendar, service = gcal
    response = client.post(
        CONFIRM,
        json=body({"id": ITEM_ONE, "title": "중간고사", "selected": False}, register_calendar=True),
        headers=auth,
    )
    assert response.json()["calendar_events_created"] == 0
    assert calendar.reserved == []
    assert service.inserted == []


def test_the_same_item_twice_in_one_request_is_refused(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    """같은 일정을 두 번 보내면 센 수가 부풀고 확정과 캘린더가 어긋난다. 받지 않는다."""
    response = client.post(
        CONFIRM,
        json=body(chosen(ITEM_ONE), {"id": ITEM_ONE, "title": "중간고사", "selected": False}),
        headers=auth,
    )
    assert (response.status_code, response.json()["error"]["code"]) == (422, "VALIDATION_FAILED")
    assert syllabi.confirmed == []


def test_a_time_without_an_offset_is_read_as_kst(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    """화면이 오프셋 없이 보내도 KST로 읽는다(그러지 않으면 아홉 시간 밀린다)."""
    client.post(
        CONFIRM,
        json=body(chosen(ITEM_ONE, starts_at="2026-11-04T13:00:00")),
        headers=auth,
    )
    assert syllabi.saved_times[ITEM_ONE].isoformat() == "2026-11-04T13:00:00+09:00"


def test_a_date_only_time_is_read_as_kst_midnight(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    client.post(CONFIRM, json=body(chosen(ITEM_ONE, starts_at="2026-11-04")), headers=auth)
    assert syllabi.saved_times[ITEM_ONE].isoformat() == "2026-11-04T00:00:00+09:00"


def test_a_blank_title_is_refused(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    """공백만 적은 제목을 받으면 플래너에 제목 없는 줄이 생긴다(고칠 길도 없다)."""
    response = client.post(CONFIRM, json=body(chosen(ITEM_ONE, title="   ")), headers=auth)
    assert response.status_code == 422
    assert syllabi.confirmed == []


def test_a_fixed_time_moves_the_calendar_event_too(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    """시각을 고쳐 다시 확정하면 이미 넣어 둔 일정도 그 시각으로 옮긴다."""
    calendar, service = gcal
    first = client.post(CONFIRM, json=body(chosen(ITEM_ONE), register_calendar=True), headers=auth)
    assert first.json() == _counts(1, 1, 1)
    moved = client.post(
        CONFIRM,
        json=body(
            chosen(ITEM_ONE, title="중간고사(온라인)", starts_at="2026-11-04T13:00:00+09:00"),
            register_calendar=True,
        ),
        headers=auth,
    )
    assert moved.json() == _counts(1, 0, 0, moved=1)
    assert len(service.inserted) == 1  # 새로 넣지 않았다
    assert service.moved[0][1] == "[시험] 데이터베이스 · 중간고사(온라인)"
    assert service.moved[0][2].isoformat() == "2026-11-04T14:00:00+09:00"  # 끝 시각
    assert calendar.moved[0][1] == "[시험] 데이터베이스 · 중간고사(온라인)"
    assert calendar.moved[0][2].isoformat() == "2026-11-04T13:00:00+09:00"


def test_the_same_time_again_does_not_touch_google(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    calendar, service = gcal
    sent = body(chosen(ITEM_ONE), register_calendar=True)
    client.post(CONFIRM, json=sent, headers=auth)
    again = client.post(CONFIRM, json=sent, headers=auth)
    assert again.json() == _counts(1, 0, 0)
    assert (service.moved, calendar.moved) == ([], [])


def test_an_event_the_student_deleted_is_not_put_back(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    """학생이 구글 캘린더에서 지운 일정은 시각을 고쳐도 되살리지 않는다."""
    calendar, service = gcal
    client.post(CONFIRM, json=body(chosen(ITEM_ONE), register_calendar=True), headers=auth)
    service.gone = True
    again = client.post(
        CONFIRM,
        json=body(chosen(ITEM_ONE, starts_at="2026-11-04T13:00:00+09:00"), register_calendar=True),
        headers=auth,
    )
    assert again.json() == _counts(1, 0, 0)
    assert calendar.moved == []  # 우리 기록도 건드리지 않는다


def test_a_revoked_permission_asks_to_connect_again(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    """만료 전 토큰이 Google에서 거절당하면(권한 거둠) 409다 — 200에 "0건"으로 묻지 않는다."""
    calendar, service = gcal
    service.revoked = True
    response = client.post(
        CONFIRM, json=body(chosen(ITEM_ONE), register_calendar=True), headers=auth
    )
    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "CALENDAR_NOT_CONNECTED",
    )
    assert response.json()["error"]["details"]["reason"] == "expired"


def test_one_failed_item_does_not_stop_the_others(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    """한 일정만 Google에서 막히면 그 건만 빠진다(센 수도 그만큼 적다)."""
    calendar, service = gcal

    inserts: list[str] = []

    async def flaky(token: str, *, event_id: str, title: str, ends_at: datetime) -> str:
        inserts.append(title)
        if len(inserts) == 1:
            raise ApiError(502, "GOOGLE_API_ERROR", "Google 캘린더가 응답하지 않아요.")
        return event_id

    service.insert = flaky  # type: ignore[method-assign]
    response = client.post(
        CONFIRM,
        json=body(
            chosen(ITEM_ONE),
            chosen(ITEM_TWO, title="팀 프로젝트 발표"),
            register_calendar=True,
        ),
        headers=auth,
    )
    assert response.json() == _counts(2, 2, 1)
    assert len(inserts) == 2  # 두 건 모두 시도했다


def test_a_syllabus_without_a_course_has_no_course_in_the_title(
    client: TestClient,
    auth: dict[str, str],
    syllabi: FakeSyllabusRepository,
    gcal: tuple[FakeCalendarRepository, FakeCalendarService],
) -> None:
    """LMS를 연결하지 않고 올린 계획서는 제목에 과목 자리가 없다."""
    calendar, service = gcal
    syllabi.heads = {(USER_ID, SYLLABUS_ID): SyllabusHead(SYLLABUS_ID, None, None, None)}
    client.post(CONFIRM, json=body(chosen(ITEM_ONE), register_calendar=True), headers=auth)
    assert service.inserted[0][1] == "[시험] 중간고사"
