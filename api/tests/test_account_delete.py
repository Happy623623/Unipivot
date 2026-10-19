"""탈퇴 (API 명세 4장 `DELETE /me`, F-06). 저장소·Google은 가짜·respx다. SQL은 test_account_delete_db.py가 본다.

보는 것: 파일 → Google 권한 → 프로필 순서, 파일을 못 지우면 502로 멈추고 아무것도 안 바꾼다,
파일이 없으면 저장소를 부르지 않는다, 캘린더 연결이 없으면 Google을 부르지 않는다, 두 번 눌러도 204.
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
from app.repositories.files import get_file_repo
from app.repositories.profiles import get_profile_repo
from app.uploads.storage import StorageError, SupabaseStorage, get_storage
from tests.conftest import USER_ID, make_token
from tests.fakes import FakeProfileRepository

ME = "/api/v1/me"
REVOKE_URL = "https://oauth.test/revoke"
NOW = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)
PATHS = [f"{USER_ID}/poster/one.png", f"{USER_ID}/syllabus/two.pdf"]


class FakeFileRepository:
    def __init__(self, paths: list[str]) -> None:
        self.paths = paths

    async def storage_paths(self, user_id: str) -> list[str]:
        return list(self.paths) if user_id == USER_ID else []


class FakeStorage(SupabaseStorage):
    """지운 경로를 적어 두고, 정한 경로에서는 실패한다."""

    def __init__(self, *, fail_on: str | None = None) -> None:
        super().__init__(
            base_url="https://storage.test/storage/v1", bucket="uploads", service_key="k"
        )
        self.removed: list[str] = []
        self.fail_on = fail_on

    async def remove(self, path: str) -> None:
        if path == self.fail_on:  # 실제 거절 문구처럼 Supabase의 이유가 붙어 있다(로그용)
            raise StorageError(
                "파일 저장소가 요청을 거절했어요(400, AccessDenied: Invalid Compact JWS)."
            )
        self.removed.append(path)


class FakeCalendarRepository:
    def __init__(self, key: str, *, connected: bool) -> None:
        self.tokens_row: GoogleTokens | None = (
            GoogleTokens(encrypt("a", key), encrypt("refresh-1", key), NOW + timedelta(minutes=30))
            if connected
            else None
        )

    async def tokens(self, user_id: str) -> GoogleTokens | None:
        return self.tokens_row if user_id == USER_ID else None

    async def delete_tokens(self, user_id: str) -> bool:
        had = self.tokens_row is not None
        self.tokens_row = None
        return had


class World:
    def __init__(
        self, settings: Settings, *, paths: list[str], connected: bool, fail_on: str | None = None
    ):
        self.profiles = FakeProfileRepository()
        self.files = FakeFileRepository(paths)
        self.storage = FakeStorage(fail_on=fail_on)
        self.calendar = FakeCalendarRepository(settings.token_encryption_key, connected=connected)
        tuned = settings.model_copy(update={"google_revoke_url": REVOKE_URL})
        app = create_app(tuned)
        app.dependency_overrides[get_settings] = lambda: tuned
        app.dependency_overrides[get_profile_repo] = lambda: self.profiles
        app.dependency_overrides[get_file_repo] = lambda: self.files
        app.dependency_overrides[get_storage] = lambda: self.storage
        app.dependency_overrides[get_calendar_repo] = lambda: self.calendar
        self.app = app


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


def _signed_in(world: World) -> Iterator[TestClient]:
    with TestClient(world.app) as client:
        client.get(ME, headers={"Authorization": f"Bearer {make_token()}"})  # 프로필을 만든다
        yield client


def test_deleting_the_account_requires_login(settings: Settings) -> None:
    world = World(settings, paths=[], connected=False)
    with TestClient(world.app) as client:
        assert client.delete(ME).status_code == 401


@respx.mock
def test_deletion_removes_files_then_google_then_the_profile(
    settings: Settings, auth: dict[str, str]
) -> None:
    world = World(settings, paths=PATHS, connected=True)
    revoke = respx.post(REVOKE_URL).mock(return_value=httpx.Response(200, json={}))
    for client in _signed_in(world):
        assert USER_ID in world.profiles.profiles
        response = client.delete(ME, headers=auth)
        assert response.status_code == 204 and response.content == b""
    assert world.storage.removed == PATHS
    assert revoke.called and revoke.calls.last.request.content == b"token=refresh-1"
    assert world.calendar.tokens_row is None
    assert USER_ID not in world.profiles.profiles


@respx.mock
def test_a_file_that_cannot_be_removed_stops_everything(
    settings: Settings, auth: dict[str, str]
) -> None:
    """개인 파일을 남긴 채 탈퇴했다고 할 수 없다. 502로 멈추고 아무것도 바꾸지 않는다."""
    world = World(settings, paths=PATHS, connected=True, fail_on=PATHS[1])
    revoke = respx.post(REVOKE_URL).mock(return_value=httpx.Response(200, json={}))
    for client in _signed_in(world):
        response = client.delete(ME, headers=auth)
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "STORAGE_API_ERROR"
        assert "다시 시도" in response.json()["error"]["message"]
        assert "AccessDenied" not in response.text  # 저장소가 준 이유는 로그에만 남는다
    assert world.storage.removed == PATHS[:1]  # 첫 파일은 지워졌다(다시 누르면 404라 지나간다)
    assert not revoke.called
    assert world.calendar.tokens_row is not None
    assert USER_ID in world.profiles.profiles


@respx.mock
def test_without_files_or_calendar_nothing_outside_is_called(
    settings: Settings, auth: dict[str, str]
) -> None:
    """파일 저장소 설정이 없는 로컬에서도 파일이 없으면 탈퇴가 된다."""
    world = World(settings, paths=[], connected=False)
    revoke = respx.post(REVOKE_URL).mock(return_value=httpx.Response(200, json={}))
    for client in _signed_in(world):
        assert client.delete(ME, headers=auth).status_code == 204
        assert client.delete(ME, headers=auth).status_code == 204  # 두 번째도 같다
    assert world.storage.removed == [] and not revoke.called
    assert USER_ID not in world.profiles.profiles
