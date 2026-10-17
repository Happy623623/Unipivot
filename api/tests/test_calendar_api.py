"""마감일 캘린더 등록 API(F-32). Google 호출은 respx로 가로챈다. SQL은 test_calendar_db.py가 본다."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.clock import current_time
from app.config import Settings, get_settings
from app.crypto import decrypt, encrypt
from app.eligibility import KST
from app.main import create_app
from app.repositories.calendar import (
    AssignmentDeadline,
    GoogleTokens,
    OpportunityDeadline,
    SyllabusDeadline,
    get_calendar_repo,
)
from app.schemas.calendar import CalendarEventView
from tests.conftest import USER_ID, make_token

EVENTS = "/api/v1/calendar/events"
API_BASE = "https://calendar.test/v3"
TOKEN_URL = "https://oauth.test/token"
INSERT = f"{API_BASE}/calendars/primary/events"
SYLLABUS_ITEM_ID = "00000000-0000-4000-8000-0000000000e5"
ASSIGNMENT_ID = "55555555-5555-4555-8555-555555555555"
OPPORTUNITY_ID = "00000000-0000-4000-8000-0000000000e1"
EVENT_ID = "00000000-0000-4000-8000-0000000000e2"
GCAL_ID = EVENT_ID.replace("-", "")  # Google 일정 번호는 기록 행의 id에서 만든다
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)
DEADLINE = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)  # 2026-10-24 18:00 KST


class FakeCalendarRepository:
    def __init__(self, key: str) -> None:
        self.key = key
        self.tokens_row: GoogleTokens | None = GoogleTokens(
            encrypt("access-1", key), encrypt("refresh-1", key), NOW + timedelta(minutes=30)
        )
        self.opportunity: OpportunityDeadline | None = OpportunityDeadline(
            OPPORTUNITY_ID, "한양브레인 장학금", DEADLINE
        )
        self.assignment: AssignmentDeadline | None = AssignmentDeadline(
            ASSIGNMENT_ID, "실습 2주차 결과 제출", "데이터베이스", DEADLINE
        )
        self.syllabus: SyllabusDeadline | None = SyllabusDeadline(
            SYLLABUS_ITEM_ID, "중간고사", "데이터베이스", "midterm", DEADLINE
        )
        self.events: dict[str, CalendarEventView] = {}
        self.saved: list[tuple[str, int]] = []
        self.added: list[dict[str, Any]] = []
        self.attached: list[tuple[str, str]] = []
        self.removed: list[str] = []
        self.uncommitted: list[str] = []  # 아직 확정하지 않은 자리(rollback이 지운다)

    async def tokens(self, user_id: str) -> GoogleTokens | None:
        return self.tokens_row if user_id == USER_ID else None

    async def save_access_token(self, user_id: str, encrypted: str, expires_in: int) -> None:
        self.saved.append((decrypt(encrypted, self.key), expires_in))

    async def prepared_opportunity(
        self, user_id: str, opportunity_id: str
    ) -> OpportunityDeadline | None:
        if user_id != USER_ID or opportunity_id != OPPORTUNITY_ID:
            return None
        return self.opportunity

    async def assignment_deadline(
        self, user_id: str, assignment_id: str
    ) -> AssignmentDeadline | None:
        if user_id != USER_ID or assignment_id != ASSIGNMENT_ID:
            return None
        return self.assignment

    async def syllabus_deadline(self, user_id: str, item_id: str) -> SyllabusDeadline | None:
        if user_id != USER_ID or item_id != SYLLABUS_ITEM_ID:
            return None
        return self.syllabus

    async def event_for(
        self,
        user_id: str,
        provider: str,
        *,
        opportunity_id: str | None = None,
        lms_assignment_id: str | None = None,
        syllabus_item_id: str | None = None,
    ) -> CalendarEventView | None:
        target = opportunity_id or lms_assignment_id or syllabus_item_id
        return self.events.get(f"{target}:{provider}")

    async def one(self, user_id: str, event_id: str) -> CalendarEventView | None:
        if user_id != USER_ID:
            return None
        return next((e for e in self.events.values() if e.id == event_id), None)

    async def reserve(self, user_id: str, **values: Any) -> CalendarEventView:
        """실제 저장소처럼 `on conflict ... where external_event_id is null`을 흉내 낸다."""
        target = (
            values.get("opportunity_id")
            or values.get("lms_assignment_id")
            or values.get("syllabus_item_id")
        )
        key = f"{target}:{values['provider']}"
        found = self.events.get(key)
        if found is not None:  # 그새 다른 요청이 잡았거나, 넣다 만 자리가 남아 있다
            if found.external_event_id is not None:
                return found
            fresh = found.model_copy(
                update={"title": values["title"], "starts_at": values["starts_at"]}
            )
            self.events[key] = fresh
            return fresh
        self.added.append(values)
        event = CalendarEventView(
            id=EVENT_ID,
            provider=values["provider"],
            external_event_id=None,  # Google에 넣기 전이다
            title=values["title"],
            starts_at=values["starts_at"],
            all_day=False,
        )
        self.events[key] = event
        self.uncommitted.append(key)
        return event

    async def commit_reservation(self) -> None:
        self.uncommitted.clear()

    def rollback(self) -> None:
        """요청이 예외로 끝나면 커넥션이 하는 일(확정하지 않은 자리는 사라진다)."""
        for key in self.uncommitted:
            self.events.pop(key, None)
        self.uncommitted.clear()

    async def attach(self, user_id: str, event_id: str, external_event_id: str) -> None:
        self.attached.append((event_id, external_event_id))
        for key, event in self.events.items():
            if event.id == event_id:
                self.events[key] = event.model_copy(update={"external_event_id": external_event_id})

    async def remove(self, user_id: str, event_id: str) -> None:
        self.removed.append(event_id)
        for key, event in list(self.events.items()):
            if event.id == event_id:
                del self.events[key]


@pytest.fixture
def calendar(settings: Settings) -> FakeCalendarRepository:
    return FakeCalendarRepository(settings.token_encryption_key)


@pytest.fixture
def client(settings: Settings, calendar: FakeCalendarRepository) -> Iterator[TestClient]:
    tuned = settings.model_copy(
        update={
            "google_calendar_api_base": API_BASE,
            "google_token_url": TOKEN_URL,
            "google_oauth_client_id": "client-1",
            "google_oauth_client_secret": "secret-1",
        }
    )
    app = create_app(tuned)
    app.dependency_overrides[get_settings] = lambda: tuned
    app.dependency_overrides[get_calendar_repo] = lambda: calendar
    app.dependency_overrides[current_time] = lambda: NOW
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


def test_calendar_requires_login(client: TestClient) -> None:
    assert client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}).status_code == 401
    assert client.delete(f"{EVENTS}/{EVENT_ID}").status_code == 401


def test_add_event_puts_an_hour_before_the_deadline(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """마감 시각으로 끝나는 1시간짜리를 KST로 넣는다."""
    with respx.mock(assert_all_called=True) as router:
        route = router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": GCAL_ID}))
        res = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "[마감] 한양브레인 장학금"
    assert body["starts_at"] == "2026-10-24T17:00:00+09:00"
    assert (body["external_event_id"], body["all_day"]) == (GCAL_ID, False)
    assert calendar.attached == [(EVENT_ID, GCAL_ID)]
    sent = route.calls[0].request
    assert sent.headers["authorization"] == "Bearer access-1"
    payload = __import__("json").loads(sent.content)
    assert payload["id"] == GCAL_ID  # 일정 번호는 우리가 정한다(다시 넣어도 하나)
    assert payload["summary"] == "[마감] 한양브레인 장학금"
    assert payload["start"] == {"dateTime": "2026-10-24T17:00:00+09:00", "timeZone": "Asia/Seoul"}
    assert payload["end"] == {"dateTime": "2026-10-24T18:00:00+09:00", "timeZone": "Asia/Seoul"}


def test_adding_twice_keeps_one_event(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """다시 눌러도 Google을 또 부르지 않고 200과 그 일정이다(F-32 중복 등록 없음)."""
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": GCAL_ID}))
        first = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    with respx.mock(assert_all_called=False) as router:
        route = router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": "other"}))
        again = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["external_event_id"] == GCAL_ID and not route.called
    assert len(calendar.added) == 1


def test_an_expiring_token_is_refreshed_first(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """곧 만료될 토큰은 먼저 갱신해 저장하고, 새 토큰으로 넣는다."""
    calendar.tokens_row = GoogleTokens(
        encrypt("old", calendar.key),
        encrypt("refresh-1", calendar.key),
        NOW + timedelta(seconds=30),
    )
    with respx.mock(assert_all_called=True) as router:
        token_route = router.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "access-2", "expires_in": 3599})
        )
        insert = router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": GCAL_ID}))
        res = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert res.status_code == 201
    assert insert.calls[0].request.headers["authorization"] == "Bearer access-2"
    assert calendar.saved == [("access-2", 3599)]
    sent = dict(httpx.QueryParams(token_route.calls[0].request.content.decode()))
    assert sent["grant_type"] == "refresh_token" and sent["refresh_token"] == "refresh-1"
    assert sent["client_id"] == "client-1"


def test_no_connection_asks_to_connect(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    calendar.tokens_row = None
    res = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert (res.status_code, res.json()["error"]["code"]) == (409, "CALENDAR_NOT_CONNECTED")
    assert res.json()["error"]["details"] == {"reason": "not_connected"}
    assert res.json()["error"]["message"] == "Google 캘린더를 연결해 주세요."


def test_a_refused_refresh_asks_to_connect_again(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """Google이 갱신을 거절하면(권한 취소 등) 다시 연결하게 한다."""
    calendar.tokens_row = GoogleTokens(
        encrypt("old", calendar.key), encrypt("refresh-1", calendar.key), NOW - timedelta(minutes=1)
    )
    with respx.mock(assert_all_called=True) as router:
        router.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid"}))
        res = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert (res.status_code, res.json()["error"]["code"]) == (409, "CALENDAR_NOT_CONNECTED")
    assert res.json()["error"]["details"] == {"reason": "expired"}


def test_google_errors_become_502(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(return_value=httpx.Response(500, json={"error": "boom"}))
        res = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert (res.status_code, res.json()["error"]["code"]) == (502, "GOOGLE_API_ERROR")
    assert "boom" not in res.json()["error"]["message"]  # 바깥 문구를 그대로 내보내지 않는다
    # 자리는 잡아 두되 번호는 붙지 않는다. 다시 누르면 같은 자리를 써서 캘린더에 하나만 들어간다
    assert calendar.attached == []
    calendar.rollback()  # 예외로 끝난 요청의 커넥션이 하는 일. 확정했으면 자리는 남는다
    assert calendar.events[f"{OPPORTUNITY_ID}:google"].external_event_id is None


def test_a_failed_google_call_keeps_the_place_so_the_retry_adds_one_event(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """Google이 502일 때 자리가 사라지면, 다시 눌렀을 때 **다른 번호**로 들어가 일정이 두 개가 된다.

    요청 커넥션은 예외가 나면 통째로 롤백되므로, 자리 잡기는 Google을 부르기 전에 확정해야 한다.
    """
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(return_value=httpx.Response(500, json={"error": "boom"}))
        client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    calendar.rollback()

    with respx.mock(assert_all_called=True) as router:
        insert = router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": "gcal-1"}))
        again = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert again.status_code == 201
    assert len(calendar.added) == 1  # 자리를 새로 만들지 않았다
    assert json.loads(insert.calls[0].request.content)["id"] == EVENT_ID.replace("-", "")


def test_a_place_left_over_from_a_changed_deadline_is_refreshed(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """넣다 만 자리가 남아 있고 그새 마감이 바뀌었으면, 그 자리의 제목·시각을 새로 맞춰 넣는다."""
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(return_value=httpx.Response(500, json={"error": "boom"}))
        client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    moved = DEADLINE + timedelta(days=1)
    calendar.opportunity = OpportunityDeadline(OPPORTUNITY_ID, "한양브레인 장학금 (연장)", moved)

    with respx.mock(assert_all_called=True) as router:
        insert = router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": "gcal-1"}))
        body = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth).json()
    sent = json.loads(insert.calls[0].request.content)
    assert sent["end"]["dateTime"] == moved.astimezone(KST).isoformat()
    assert body["title"] == "[마감] 한양브레인 장학금 (연장)"
    assert body["starts_at"] == (moved - timedelta(hours=1)).astimezone(KST).isoformat()


def test_an_unprepared_or_undated_opportunity_is_refused(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    calendar.opportunity = None
    res = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert (res.status_code, res.json()["error"]["code"]) == (422, "VALIDATION_FAILED")
    assert res.json()["error"]["details"]["fields"] == {
        "opportunity_id": "준비 일정을 먼저 만들어 주세요."
    }
    calendar.opportunity = OpportunityDeadline(OPPORTUNITY_ID, "상시 공고", None)
    undated = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert undated.status_code == 422
    assert undated.json()["error"]["details"]["fields"]["opportunity_id"].startswith(
        "마감일이 없는"
    )


def test_ics_is_not_ready_yet(client: TestClient, auth: dict[str, str]) -> None:
    res = client.post(
        EVENTS, json={"opportunity_id": OPPORTUNITY_ID, "provider": "ics"}, headers=auth
    )
    assert res.status_code == 422
    assert res.json()["error"]["details"]["fields"]["provider"].startswith("지금은 Google")


def test_unknown_fields_are_refused(client: TestClient, auth: dict[str, str]) -> None:
    res = client.post(
        EVENTS, json={"opportunity_id": OPPORTUNITY_ID, "syllabus_item_id": "x"}, headers=auth
    )
    assert res.status_code == 422


def test_delete_removes_it_from_google_too(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": GCAL_ID}))
        client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    with respx.mock(assert_all_called=True) as router:
        route = router.delete(f"{INSERT}/{GCAL_ID}").mock(return_value=httpx.Response(204))
        res = client.delete(f"{EVENTS}/{EVENT_ID}", headers=auth)
    assert res.status_code == 204 and route.called
    assert calendar.removed == [EVENT_ID] and calendar.events == {}


def test_deleting_an_event_google_already_lost_still_works(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """학생이 Google에서 먼저 지웠으면 404가 온다. 우리 기록도 지운다."""
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": GCAL_ID}))
        client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    with respx.mock(assert_all_called=True) as router:
        router.delete(f"{INSERT}/{GCAL_ID}").mock(return_value=httpx.Response(404))
        res = client.delete(f"{EVENTS}/{EVENT_ID}", headers=auth)
    assert res.status_code == 204 and calendar.removed == [EVENT_ID]


def test_someone_elses_event_is_not_found(client: TestClient, auth: dict[str, str]) -> None:
    res = client.delete(f"{EVENTS}/{EVENT_ID}", headers=auth)
    assert (res.status_code, res.json()["error"]["code"]) == (404, "NOT_FOUND")


def test_without_app_credentials_an_expired_token_asks_to_connect(
    settings: Settings, calendar: FakeCalendarRepository, auth: dict[str, str]
) -> None:
    """client_id·secret을 .env에 넣지 않으면 갱신할 수 없다. 다시 연결하게 한다(Google은 부르지 않는다)."""
    bare = settings.model_copy(
        update={"google_calendar_api_base": API_BASE, "google_token_url": TOKEN_URL}
    )
    app = create_app(bare)
    app.dependency_overrides[get_settings] = lambda: bare
    app.dependency_overrides[get_calendar_repo] = lambda: calendar
    app.dependency_overrides[current_time] = lambda: NOW
    calendar.tokens_row = GoogleTokens(
        encrypt("old", calendar.key), encrypt("refresh-1", calendar.key), NOW - timedelta(minutes=1)
    )
    with TestClient(app) as client, respx.mock(assert_all_called=False) as router:
        route = router.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={}))
        res = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert (res.status_code, res.json()["error"]["details"]) == (409, {"reason": "expired"})
    assert not route.called


def test_retrying_after_a_lost_response_keeps_one_event(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """넣는 응답을 못 받고 다시 눌러도 캘린더에 일정이 하나다.

    번호를 우리가 정해 보내므로 두 번째 요청은 같은 번호로 간다. Google은 409(같은 번호가 있다)를
    주는데 그것은 앞 요청이 이미 넣었다는 뜻이라 성공으로 본다. **그때 Google에 남은 시각은 앞
    요청이 보낸 것**이라, 이어서 한 번 고쳐 이번 마감으로 맞춘다.
    """
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(side_effect=httpx.ReadTimeout("늦었다"))
        lost = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert lost.status_code == 502 and calendar.attached == []
    with respx.mock(assert_all_called=True) as router:
        route = router.post(INSERT).mock(
            return_value=httpx.Response(409, json={"error": "duplicate"})
        )
        fixed = router.patch(f"{API_BASE}/calendars/primary/events/{GCAL_ID}").mock(
            return_value=httpx.Response(200, json={"id": GCAL_ID})
        )
        again = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert again.status_code == 201
    assert again.json()["external_event_id"] == GCAL_ID
    assert json.loads(route.calls[0].request.content)["id"] == GCAL_ID
    # 409 뒤에 시각을 맞춘다. 그 사이 마감이 바뀌었으면 캘린더가 옛 시각을 가리킨다
    sent = json.loads(fixed.calls[0].request.content)
    assert sent["end"]["dateTime"] == DEADLINE.astimezone(KST).isoformat()
    assert len(calendar.added) == 1  # 자리는 하나만 잡았다


def test_a_quota_error_is_not_a_permission_problem(
    client: TestClient, auth: dict[str, str]
) -> None:
    """403은 쿼터·한도에도 온다. 다시 연결하라고 하면 학생이 할 수 있는 일이 없다."""
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(
            return_value=httpx.Response(403, json={"error": "rateLimitExceeded"})
        )
        res = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert (res.status_code, res.json()["error"]["code"]) == (502, "GOOGLE_API_ERROR")


def test_a_revoked_token_asks_to_connect_again(client: TestClient, auth: dict[str, str]) -> None:
    """401은 권한이 없어진 것이다. 다시 연결하게 한다."""
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(return_value=httpx.Response(401, json={"error": "invalid"}))
        res = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert (res.status_code, res.json()["error"]["details"]) == (409, {"reason": "expired"})


def test_a_network_error_is_not_a_permission_problem(
    client: TestClient, auth: dict[str, str]
) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(side_effect=httpx.ConnectError("닿지 못함"))
        res = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert (res.status_code, res.json()["error"]["code"]) == (502, "GOOGLE_API_ERROR")


def test_a_passed_deadline_is_refused(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """마감이 지난 공고는 준비하기처럼 막는다(지난 일정을 캘린더에 넣지 않는다)."""
    calendar.opportunity = OpportunityDeadline(OPPORTUNITY_ID, "지난 장학", NOW - timedelta(days=1))
    res = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert (res.status_code, res.json()["error"]["code"]) == (409, "DEADLINE_PASSED")
    assert calendar.added == []


def test_a_bad_opportunity_id_is_a_validation_error(
    client: TestClient, auth: dict[str, str]
) -> None:
    res = client.post(EVENTS, json={"opportunity_id": "공고아님"}, headers=auth)
    assert (res.status_code, res.json()["error"]["code"]) == (422, "VALIDATION_FAILED")


def test_deleting_works_even_when_the_permission_is_gone(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """권한이 없어졌으면 Google에서는 못 지운다. 우리 기록은 지워 줄을 없앤다."""
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": GCAL_ID}))
        client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    calendar.tokens_row = None  # 설정에서 연결을 끊었다
    res = client.delete(f"{EVENTS}/{EVENT_ID}", headers=auth)
    assert res.status_code == 204
    assert calendar.removed == [EVENT_ID] and calendar.events == {}


def test_a_google_outage_keeps_the_record_for_a_retry(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """Google이 잠깐 멈춘 것은 다시 누르게 한다(기록을 지우면 Google 쪽 일정이 고아가 된다)."""
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": GCAL_ID}))
        client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    with respx.mock(assert_all_called=True) as router:
        router.delete(f"{INSERT}/{GCAL_ID}").mock(return_value=httpx.Response(500))
        res = client.delete(f"{EVENTS}/{EVENT_ID}", headers=auth)
    assert (res.status_code, res.json()["error"]["code"]) == (502, "GOOGLE_API_ERROR")
    assert calendar.removed == []


def test_a_broken_token_asks_to_connect_again(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """암호화 키를 바꿔 복호화하지 못해도 500이 아니라 다시 연결이다."""
    calendar.tokens_row = GoogleTokens("못-푸는-값", "못-푸는-값", NOW + timedelta(minutes=30))
    res = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert (res.status_code, res.json()["error"]["details"]) == (409, {"reason": "expired"})


# ── LMS 과제 마감 (F-51) ────────────────────────────────────────────────────


def test_an_assignment_deadline_goes_in_with_the_course_in_the_title(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """제목에 과목을 앞세운다 — 캘린더에서 어느 수업 과제인지 바로 보인다."""
    with respx.mock(assert_all_called=True) as router:
        route = router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": GCAL_ID}))
        response = client.post(EVENTS, json={"lms_assignment_id": ASSIGNMENT_ID}, headers=auth)
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "[과제] 데이터베이스 · 실습 2주차 결과 제출"
    assert body["external_event_id"] == GCAL_ID
    assert body["all_day"] is False
    sent = json.loads(route.calls[0].request.content)
    assert sent["summary"] == body["title"]
    # 마감 시각으로 끝나는 1시간이다(공고와 같은 규칙)
    assert sent["end"]["dateTime"].startswith(DEADLINE.astimezone(KST).isoformat()[:16])
    assert calendar.added[0]["lms_assignment_id"] == ASSIGNMENT_ID


def test_adding_the_same_assignment_twice_keeps_one_event(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": GCAL_ID}))
        first = client.post(EVENTS, json={"lms_assignment_id": ASSIGNMENT_ID}, headers=auth)
    with respx.mock(assert_all_called=False) as router:
        route = router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": "other"}))
        again = client.post(EVENTS, json={"lms_assignment_id": ASSIGNMENT_ID}, headers=auth)
    assert (first.status_code, again.status_code) == (201, 200)
    assert not route.called
    assert len(calendar.added) == 1


def test_an_assignment_without_a_deadline_is_refused(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    assert calendar.assignment is not None
    calendar.assignment = AssignmentDeadline(ASSIGNMENT_ID, "마감 없는 과제", "데이터베이스", None)
    response = client.post(EVENTS, json={"lms_assignment_id": ASSIGNMENT_ID}, headers=auth)
    assert response.status_code == 422
    assert "lms_assignment_id" in response.json()["error"]["details"]["fields"]


def test_an_assignment_past_its_deadline_is_refused(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    calendar.assignment = AssignmentDeadline(
        ASSIGNMENT_ID, "지난 과제", "데이터베이스", NOW - timedelta(days=1)
    )
    response = client.post(EVENTS, json={"lms_assignment_id": ASSIGNMENT_ID}, headers=auth)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DEADLINE_PASSED"


def test_an_assignment_that_is_not_mine_is_not_found(
    client: TestClient, auth: dict[str, str]
) -> None:
    other = "66666666-6666-4666-8666-666666666666"
    response = client.post(EVENTS, json={"lms_assignment_id": other}, headers=auth)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_exactly_one_target_is_required(client: TestClient, auth: dict[str, str]) -> None:
    both = {"opportunity_id": OPPORTUNITY_ID, "lms_assignment_id": ASSIGNMENT_ID}
    assert client.post(EVENTS, json=both, headers=auth).status_code == 422
    assert client.post(EVENTS, json={}, headers=auth).status_code == 422
    assert client.post(EVENTS, json={"provider": "google"}, headers=auth).status_code == 422
    # 대상 셋 중 둘을 함께 보내도 422다(계획서 일정도 대상이 되었다)
    mixed = {"opportunity_id": OPPORTUNITY_ID, "syllabus_item_id": SYLLABUS_ITEM_ID}
    assert client.post(EVENTS, json=mixed, headers=auth).status_code == 422
    three = {**both, "syllabus_item_id": SYLLABUS_ITEM_ID}
    assert client.post(EVENTS, json=three, headers=auth).status_code == 422


# ── 계획서 일정 (F-14) ──────────────────────────────────────────────────────


def test_a_syllabus_item_goes_in_starting_at_its_own_time(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """시험·발표는 **마감이 아니라 시작 시각**이다. 그 시각에 시작해 1시간 뒤에 끝낸다."""
    with respx.mock(assert_all_called=True) as router:
        route = router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": GCAL_ID}))
        response = client.post(EVENTS, json={"syllabus_item_id": SYLLABUS_ITEM_ID}, headers=auth)
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "[시험] 데이터베이스 · 중간고사"
    assert body["starts_at"].startswith(DEADLINE.astimezone(KST).isoformat()[:16])
    sent = json.loads(route.calls[0].request.content)
    starts = DEADLINE.astimezone(KST)
    assert sent["start"]["dateTime"].startswith(starts.isoformat()[:16])
    assert sent["end"]["dateTime"].startswith((starts + timedelta(hours=1)).isoformat()[:16])
    assert calendar.added[0]["syllabus_item_id"] == SYLLABUS_ITEM_ID


def test_adding_the_same_syllabus_item_twice_keeps_one_event(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": GCAL_ID}))
        first = client.post(EVENTS, json={"syllabus_item_id": SYLLABUS_ITEM_ID}, headers=auth)
    with respx.mock(assert_all_called=False) as router:
        route = router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": "other"}))
        again = client.post(EVENTS, json={"syllabus_item_id": SYLLABUS_ITEM_ID}, headers=auth)
    assert (first.status_code, again.status_code) == (201, 200)
    assert not route.called
    assert len(calendar.added) == 1


def test_a_syllabus_item_without_a_date_is_refused(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    calendar.syllabus = SyllabusDeadline(SYLLABUS_ITEM_ID, "보강", "데이터베이스", "etc", None)
    response = client.post(EVENTS, json={"syllabus_item_id": SYLLABUS_ITEM_ID}, headers=auth)
    assert response.status_code == 422
    assert "syllabus_item_id" in response.json()["error"]["details"]["fields"]


def test_a_syllabus_item_that_already_happened_is_refused(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    calendar.syllabus = SyllabusDeadline(
        SYLLABUS_ITEM_ID, "쪽지시험", "데이터베이스", "etc", NOW - timedelta(days=2)
    )
    response = client.post(EVENTS, json={"syllabus_item_id": SYLLABUS_ITEM_ID}, headers=auth)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "DEADLINE_PASSED")


def test_an_unconfirmed_or_other_students_syllabus_item_is_not_found(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """확인하지 않은 일정과 남의 계획서는 저장소가 돌려주지 않는다(404)."""
    calendar.syllabus = None
    response = client.post(EVENTS, json={"syllabus_item_id": SYLLABUS_ITEM_ID}, headers=auth)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "NOT_FOUND")
    other = "00000000-0000-4000-8000-0000000000ee"
    assert client.post(EVENTS, json={"syllabus_item_id": other}, headers=auth).status_code == 404


def test_a_presentation_and_an_assignment_get_their_own_labels(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    for kind, label in (("presentation", "[발표]"), ("assignment", "[과제]"), ("etc", "[일정]")):
        calendar.events.clear()
        calendar.syllabus = SyllabusDeadline(
            SYLLABUS_ITEM_ID, "팀 프로젝트", "데이터베이스", kind, DEADLINE
        )
        with respx.mock(assert_all_called=True) as router:
            router.post(INSERT).mock(return_value=httpx.Response(200, json={"id": GCAL_ID}))
            response = client.post(
                EVENTS, json={"syllabus_item_id": SYLLABUS_ITEM_ID}, headers=auth
            )
        assert response.json()["title"] == f"{label} 데이터베이스 · 팀 프로젝트"
