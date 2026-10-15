"""마감일 캘린더 등록 API(F-32). Google 호출은 respx로 가로챈다. SQL은 test_calendar_db.py가 본다."""

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
from app.main import create_app
from app.repositories.calendar import (
    GoogleTokens,
    OpportunityDeadline,
    get_calendar_repo,
)
from app.schemas.calendar import CalendarEventView
from tests.conftest import USER_ID, make_token

EVENTS = "/api/v1/calendar/events"
API_BASE = "https://calendar.test/v3"
TOKEN_URL = "https://oauth.test/token"
INSERT = f"{API_BASE}/calendars/primary/events"
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
        self.events: dict[str, CalendarEventView] = {}
        self.saved: list[tuple[str, int]] = []
        self.added: list[dict[str, Any]] = []
        self.attached: list[tuple[str, str]] = []
        self.removed: list[str] = []

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

    async def event_for(
        self, user_id: str, opportunity_id: str, provider: str
    ) -> CalendarEventView | None:
        return self.events.get(f"{opportunity_id}:{provider}")

    async def one(self, user_id: str, event_id: str) -> CalendarEventView | None:
        if user_id != USER_ID:
            return None
        return next((e for e in self.events.values() if e.id == event_id), None)

    async def reserve(self, user_id: str, **values: Any) -> CalendarEventView:
        key = f"{values['opportunity_id']}:{values['provider']}"
        if key in self.events:  # 그새 다른 요청이 잡았다
            return self.events[key]
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
        return event

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
    assert calendar.events[f"{OPPORTUNITY_ID}:google"].external_event_id is None


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
    주는데 그것은 앞 요청이 이미 넣었다는 뜻이라 성공으로 본다.
    """
    with respx.mock(assert_all_called=True) as router:
        router.post(INSERT).mock(side_effect=httpx.ReadTimeout("늦었다"))
        lost = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert lost.status_code == 502 and calendar.attached == []
    with respx.mock(assert_all_called=True) as router:
        route = router.post(INSERT).mock(
            return_value=httpx.Response(409, json={"error": "duplicate"})
        )
        again = client.post(EVENTS, json={"opportunity_id": OPPORTUNITY_ID}, headers=auth)
    assert again.status_code == 201
    assert again.json()["external_event_id"] == GCAL_ID
    assert __import__("json").loads(route.calls[0].request.content)["id"] == GCAL_ID
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
