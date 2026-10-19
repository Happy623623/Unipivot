"""캘린더 연결 해제 (API 4장 `DELETE /auth/google/tokens`, F-06). Google 호출은 respx로 가로챈다.

보는 것: Google 쪽 권한을 거두고 저장한 토큰을 지운다, Google이 막혀도 토큰은 지운다, 이미 풀린
토큰(400)은 성공으로 본다, 연결이 없어도 204다. SQL은 test_calendar_disconnect_db.py가 본다.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.crypto import encrypt
from app.main import create_app
from app.repositories.calendar import GoogleTokens, get_calendar_repo
from tests.conftest import USER_ID, make_token

TOKENS = "/api/v1/auth/google/tokens"
REVOKE_URL = "https://oauth.test/revoke"
NOW = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)


class FakeCalendarRepository:
    """토큰 행 하나만 흉내 낸다."""

    def __init__(self, key: str, *, connected: bool = True) -> None:
        self.tokens_row: GoogleTokens | None = (
            GoogleTokens(
                encrypt("access-1", key), encrypt("refresh-1", key), NOW + timedelta(minutes=30)
            )
            if connected
            else None
        )
        self.deleted: list[str] = []

    async def tokens(self, user_id: str) -> GoogleTokens | None:
        return self.tokens_row if user_id == USER_ID else None

    async def delete_tokens(self, user_id: str) -> bool:
        self.deleted.append(user_id)
        had = self.tokens_row is not None
        self.tokens_row = None
        return had


@pytest.fixture
def calendar(settings: Settings) -> FakeCalendarRepository:
    return FakeCalendarRepository(settings.token_encryption_key)


@pytest.fixture
def client(settings: Settings, calendar: FakeCalendarRepository) -> Iterator[TestClient]:
    tuned = settings.model_copy(update={"google_revoke_url": REVOKE_URL})
    app = create_app(tuned)
    app.dependency_overrides[get_settings] = lambda: tuned
    app.dependency_overrides[get_calendar_repo] = lambda: calendar
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


def test_disconnect_requires_login(client: TestClient) -> None:
    assert client.delete(TOKENS).status_code == 401


@respx.mock
def test_disconnect_revokes_at_google_and_forgets_the_tokens(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    revoke = respx.post(REVOKE_URL).mock(return_value=httpx.Response(200, json={}))
    response = client.delete(TOKENS, headers=auth)
    assert response.status_code == 204 and response.content == b""
    assert revoke.called
    assert (
        revoke.calls.last.request.content == b"token=refresh-1"
    )  # refresh token으로 승인 전체를 거둔다
    assert calendar.deleted == [USER_ID] and calendar.tokens_row is None


@respx.mock
def test_tokens_are_forgotten_even_when_google_is_down(
    client: TestClient,
    auth: dict[str, str],
    calendar: FakeCalendarRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Google이 막혀도 우리 쪽은 끊는다. 못 거둔 권한은 학생이 Google 계정에서 직접 거둘 수 있다."""
    respx.post(REVOKE_URL).mock(return_value=httpx.Response(503))
    with caplog.at_level("WARNING", logger="app.calendar.service"):
        assert client.delete(TOKENS, headers=auth).status_code == 204
    assert calendar.tokens_row is None
    assert any(
        "거두지 못했어요" in record.message for record in caplog.records
    )  # 운영자는 알아야 한다


@respx.mock
def test_an_already_revoked_token_is_fine(
    client: TestClient,
    auth: dict[str, str],
    calendar: FakeCalendarRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Google은 이미 풀린 토큰에 400을 준다 — 거두려던 것이 거둬진 상태라 성공이고, 경고도 없다."""
    respx.post(REVOKE_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_token"}))
    with caplog.at_level("WARNING", logger="app.calendar.service"):
        assert client.delete(TOKENS, headers=auth).status_code == 204
    assert calendar.tokens_row is None
    assert not [record for record in caplog.records if record.name == "app.calendar.service"]


@respx.mock
def test_disconnecting_without_a_connection_is_a_no_op(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    calendar.tokens_row = None
    revoke = respx.post(REVOKE_URL).mock(return_value=httpx.Response(200, json={}))
    assert client.delete(TOKENS, headers=auth).status_code == 204
    assert not revoke.called and calendar.deleted == []


@respx.mock
def test_a_token_that_cannot_be_read_is_still_forgotten(
    settings: Settings, auth: dict[str, str]
) -> None:
    """키를 바꿔 복호화가 안 되는 토큰은 거둘 수 없다. 그래도 지운다(다시 연결하면 된다)."""
    repo = FakeCalendarRepository(settings.token_encryption_key)
    repo.tokens_row = GoogleTokens("깨진-값", "깨진-값", NOW + timedelta(minutes=30))
    tuned = settings.model_copy(update={"google_revoke_url": REVOKE_URL})
    app = create_app(tuned)
    app.dependency_overrides[get_settings] = lambda: tuned
    app.dependency_overrides[get_calendar_repo] = lambda: repo
    revoke = respx.post(REVOKE_URL).mock(return_value=httpx.Response(200, json={}))
    with TestClient(app) as client:
        assert client.delete(TOKENS, headers=auth).status_code == 204
    assert not revoke.called and repo.tokens_row is None
