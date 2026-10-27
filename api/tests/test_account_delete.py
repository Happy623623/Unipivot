"""탈퇴 (API 명세 4장 `DELETE /me`, F-06). 저장소·Google은 가짜·respx다. SQL은 test_account_delete_db.py가 본다.

보는 것: 파일 → Google 권한 → 프로필 순서, 파일을 못 지우면 502로 멈추고 아무것도 안 바꾼다,
파일이 있는데 저장소 설정에 고칠 점이 있으면 지우기 전에 502로 멈춘다, 저장소가 아닌 곳의 404는 "이미
없음"이 아니다, 파일이 없으면 저장소를 부르지 않는다(설정도 보지 않는다), 캘린더 연결이 없으면 Google을
부르지 않는다, 두 번 눌러도 204. 로그인 계정은 profiles를 지워 확정한 뒤에 지우고, 못 지워도 204다(다시
누르면 다시 지운다). 관리자 API를 부르는 모양(주소·키 자리·없는 사용자)은 respx로 본다.
"""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
import respx
from fastapi.testclient import TestClient

from app.auth_admin import AuthAdminError, SupabaseAuthAdmin, get_auth_admin
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
PROJECT_URL = "https://abcdefghijklmnopqrst.supabase.co"
SECRET = "sb_secret_" + "Tq7" * 10 + "x"  # 새 키 모양. 시험용 값이다
PUBLISHABLE = "sb_publishable_" + "Pk4" * 10 + "y"
ANON = jwt.encode({"iss": "supabase", "role": "anon"}, "x" * 32, algorithm="HS256")


class FakeFileRepository:
    def __init__(self, paths: list[str], profiles: FakeProfileRepository) -> None:
        self.paths = paths
        self.profiles = profiles
        self.listings: list[list[str]] = []  # 목록을 받을 때마다 그때 이미 잠근 사용자
        self.arrives: str | None = None  # 첫 목록 뒤에 들어오는 파일(그사이 업로드·LMS 첨부)

    async def storage_paths(self, user_id: str) -> list[str]:
        self.listings.append(list(self.profiles.deletion_locks))
        if len(self.listings) > 1 and self.arrives:
            self.paths = [*self.paths, self.arrives]
        return list(self.paths) if user_id == USER_ID else []


class FakeStorage(SupabaseStorage):
    """지운 경로를 적어 두고, 정한 경로에서는 실패한다. 폴더 목록은 아직 안 지운 파일(기록 있는 것 + 기록 없는 것)이다."""

    def __init__(
        self,
        *,
        fail_on: str | None = None,
        stored: list[str],
        list_fails: bool = False,
        stale: bool = False,
    ) -> None:
        super().__init__(
            base_url="https://storage.test/storage/v1", bucket="uploads", service_key="k"
        )
        self.removed: list[str] = []
        self.fail_on = fail_on
        self.stored = list(stored)
        self.list_fails = list_fails
        self.stale = stale  # 목록이 늦게 따라와 방금 지운 파일도 아직 보인다
        self.listed: list[str] = []
        self.everything = list(stored)

    async def remove(self, path: str) -> None:
        if path == self.fail_on:  # 실제 거절 문구처럼 Supabase의 이유가 붙어 있다(로그용)
            raise StorageError(
                "파일 저장소가 요청을 거절했어요(400, AccessDenied: Invalid Compact JWS)."
            )
        self.removed.append(path)
        if path in self.stored:
            self.stored.remove(path)

    async def list_paths(self, folder: str) -> list[str]:
        self.listed.append(folder)
        if self.list_fails:
            raise StorageError("파일 저장소가 요청을 거절했어요(500).")
        shown = self.everything if self.stale else self.stored
        return [path for path in shown if path.startswith(f"{folder}/")]


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


class FakeAuthAdmin(SupabaseAuthAdmin):
    """지운 로그인 계정과, 부를 때 프로필이 이미 지워져 확정됐는지 적어 둔다. 정하면 실패한다."""

    def __init__(self, profiles: FakeProfileRepository, *, fails: bool = False) -> None:
        super().__init__(base_url=PROJECT_URL, service_key=SECRET)
        self.profiles = profiles
        self.fails = fails
        self.calls: list[tuple[str, bool]] = []  # (사용자, 그때 프로필이 지워져 확정됐는지)

    async def delete_user(self, user_id: str) -> None:
        settled = user_id not in self.profiles.profiles and self.profiles.commits > 0
        self.calls.append((user_id, settled))
        if self.fails:
            raise AuthAdminError("로그인 서버가 계정 지우기를 거절했어요(500).")


class World:
    def __init__(
        self,
        settings: Settings,
        *,
        paths: list[str],
        connected: bool,
        fail_on: str | None = None,
        key: str = SECRET,
        url: str = PROJECT_URL,
        storage_base: str = "",
        orphans: tuple[str, ...] = (),  # 저장소에만 있고 기록이 없는 파일
        list_fails: bool = False,
        stale: bool = False,
        admin_fails: bool = False,
    ):
        self.profiles = FakeProfileRepository()
        self.admin = FakeAuthAdmin(self.profiles, fails=admin_fails)
        self.files = FakeFileRepository(paths, self.profiles)
        self.storage = FakeStorage(
            fail_on=fail_on, stored=[*paths, *orphans], list_fails=list_fails, stale=stale
        )
        self.calendar = FakeCalendarRepository(settings.token_encryption_key, connected=connected)
        # 저장소 설정(기본은 맞는 secret key). 고칠 점이 있으면 파일을 지우기 전에 멈춘다
        tuned = settings.model_copy(
            update={
                "google_revoke_url": REVOKE_URL,
                "supabase_url": url,
                "supabase_secret_key": key,
                "supabase_storage_base": storage_base,
            }
        )
        app = create_app(tuned)
        app.dependency_overrides[get_settings] = lambda: tuned
        app.dependency_overrides[get_profile_repo] = lambda: self.profiles
        app.dependency_overrides[get_file_repo] = lambda: self.files
        app.dependency_overrides[get_storage] = lambda: self.storage
        app.dependency_overrides[get_calendar_repo] = lambda: self.calendar
        app.dependency_overrides[get_auth_admin] = lambda: self.admin
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
    # 첫 목록은 잠그지 않고, 지우기 직전에 잠근 뒤 다시 받는다(그 뒤 들어오는 기록은 탈퇴가 끝날 때까지 기다린다)
    assert world.files.listings == [[], [USER_ID]]
    assert world.storage.removed == PATHS
    assert revoke.called and revoke.calls.last.request.content == b"token=refresh-1"
    assert world.calendar.tokens_row is None
    assert USER_ID not in world.profiles.profiles
    # 로그인 계정은 마지막에, 프로필을 지워 확정한 뒤에 지운다(확정 전이면 Supabase의 cascade가 잠금을 기다린다)
    assert world.admin.calls == [(USER_ID, True)]


@respx.mock
def test_a_login_account_that_cannot_be_deleted_still_ends_the_deletion(
    settings: Settings, auth: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """Google 권한 해제처럼 되는 만큼 한다. 데이터는 이미 지워 확정했으니 204이고, 이유는 경고 로그에 남긴다.
    남은 계정으로 다시 누르면(프로필이 없어도) 로그인 계정 지우기를 다시 한다."""
    world = World(settings, paths=PATHS, connected=True, admin_fails=True)
    respx.post(REVOKE_URL).mock(return_value=httpx.Response(200, json={}))
    for client in _signed_in(world):
        assert client.delete(ME, headers=auth).status_code == 204
        assert USER_ID not in world.profiles.profiles
        assert world.storage.removed == PATHS and world.calendar.tokens_row is None
        warned = [r for r in caplog.records if r.name == "app.account"]
        assert len(warned) == 1 and warned[0].levelno == logging.WARNING
        assert "로그인 계정은 지우지 못했어요" in warned[0].getMessage()

        world.admin.fails = False
        assert client.delete(ME, headers=auth).status_code == 204  # 다시 누르면
    assert [user for user, _ in world.admin.calls] == [USER_ID, USER_ID]  # 다시 지운다


ADMIN_URL = f"{PROJECT_URL}/auth/v1/admin/users/{USER_ID}"


@pytest.mark.anyio
@respx.mock
async def test_the_admin_api_is_called_with_the_secret_key_as_apikey_only() -> None:
    """새 키(sb_secret_)는 저장소처럼 `apikey`에만 싣는다. 예전 service_role JWT는 Bearer에도 싣는다."""
    route = respx.delete(ADMIN_URL).mock(return_value=httpx.Response(200, json={}))
    await SupabaseAuthAdmin(base_url=PROJECT_URL + "/", service_key=SECRET).delete_user(USER_ID)
    sent = route.calls.last.request
    assert sent.headers["apikey"] == SECRET and "authorization" not in sent.headers

    legacy = jwt.encode({"iss": "supabase", "role": "service_role"}, "x" * 32, algorithm="HS256")
    await SupabaseAuthAdmin(base_url=PROJECT_URL, service_key=legacy).delete_user(USER_ID)
    assert route.calls.last.request.headers["authorization"] == f"Bearer {legacy}"


@pytest.mark.anyio
@respx.mock
@pytest.mark.parametrize(
    "body", [{"code": 404, "error_code": "user_not_found"}, {"code": "user_not_found"}]
)
async def test_a_login_account_that_is_already_gone_counts_as_deleted(body: dict) -> None:
    """두 번째 탈퇴에서는 계정이 이미 없다. 그 답(지금 판·예전 판 모양)은 지운 것으로 본다."""
    respx.delete(ADMIN_URL).mock(return_value=httpx.Response(404, json=body))
    await SupabaseAuthAdmin(base_url=PROJECT_URL, service_key=SECRET).delete_user(USER_ID)


@pytest.mark.anyio
@respx.mock
@pytest.mark.parametrize(
    ("status", "body"),
    [
        (404, {"message": "no Route matched with those values"}),  # 로그인 서버가 아닌 곳의 404
        (401, {"message": f"Invalid API key {SECRET}"}),
        (500, {"code": 500, "error_code": "unexpected_failure", "msg": "Database error"}),
    ],
    ids=["404-without-code", "401", "500"],
)
async def test_other_answers_are_failures_without_the_key(status: int, body: dict) -> None:
    respx.delete(ADMIN_URL).mock(return_value=httpx.Response(status, json=body))
    with pytest.raises(AuthAdminError) as caught:
        await SupabaseAuthAdmin(base_url=PROJECT_URL, service_key=SECRET).delete_user(USER_ID)
    assert str(status) in str(caught.value)
    assert SECRET not in str(caught.value)  # 이유에 키가 섞여 와도 가린다


@pytest.mark.anyio
@respx.mock
@pytest.mark.parametrize(
    ("url", "key"), [("", SECRET), (PROJECT_URL, ""), (PROJECT_URL, "sb secret")]
)
async def test_without_settings_the_admin_api_is_not_called(url: str, key: str) -> None:
    """설정이 없는 로컬, 키에 머리값을 깨는 글자가 있으면 부르지 않고 실패로 알린다(탈퇴는 경고만 남긴다)."""
    route = respx.delete(url__startswith=PROJECT_URL).mock(return_value=httpx.Response(200))
    with pytest.raises(AuthAdminError):
        await SupabaseAuthAdmin(base_url=url, service_key=key).delete_user(USER_ID)
    assert not route.called


@pytest.mark.anyio
@respx.mock
async def test_an_unreachable_login_server_is_a_failure() -> None:
    respx.delete(ADMIN_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(AuthAdminError, match="닿지 못했어요"):
        await SupabaseAuthAdmin(base_url=PROJECT_URL, service_key=SECRET).delete_user(USER_ID)


@respx.mock
def test_a_file_recorded_while_deleting_is_removed_too(
    settings: Settings, auth: dict[str, str]
) -> None:
    """파일을 지우는 사이에 업로드·LMS 첨부가 새 파일을 남겼다. 잠근 뒤 다시 받은 목록으로 그것도 지운다
    (지운 것은 다시 지우지 않는다)."""
    world = World(settings, paths=PATHS, connected=True)
    late = f"{USER_ID}/poster/late.png"
    world.files.arrives = late
    respx.post(REVOKE_URL).mock(return_value=httpx.Response(200, json={}))
    for client in _signed_in(world):
        assert client.delete(ME, headers=auth).status_code == 204
    assert world.storage.removed == [*PATHS, late]
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
@pytest.mark.parametrize(
    ("key", "shown"),
    [
        (PUBLISHABLE, "publishable key가 들어 있어요"),
        (ANON, "service_role 키가 아니에요"),
        (SECRET[:16], "너무 짧아요"),  # 가려진 화면 글자만 옮겨 적었다
        ("", "SUPABASE_SECRET_KEY·SUPABASE_URL이 있어야"),
    ],
    ids=["publishable", "anon", "short", "empty"],
)
def test_a_wrong_storage_key_stops_before_any_file_is_removed(
    settings: Settings,
    auth: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    key: str,
    shown: str,
) -> None:
    """publishable·anon 키로 지우면 저장소는 파일을 못 보고 "없는 파일"로 답한다. 지우기는 그 답을 "이미
    지웠다"로 받아서, 그대로 가면 파일은 저장소에 남고 기록만 사라진다. 그래서 설정에 고칠 점이 있으면
    (잘린 키·빈 설정도) 파일이 하나뿐이어도 저장소를 부르기 전에 502로 멈추고 이유를 로그에 남긴다."""
    world = World(settings, paths=PATHS[:1], connected=True, key=key)
    revoke = respx.post(REVOKE_URL).mock(return_value=httpx.Response(200, json={}))
    for client in _signed_in(world):
        response = client.delete(ME, headers=auth)
        assert response.status_code == 502
        error = response.json()["error"]
        assert error["code"] == "STORAGE_API_ERROR"
        # 파일을 못 지울 때와 같은 문구다. 무엇을 고칠지는 서버 로그에만 남는다
        assert error["message"] == "파일을 지우지 못해 탈퇴를 멈췄어요. 잠시 후 다시 시도해 주세요."
        assert shown not in response.text
    assert world.storage.removed == []  # 저장소를 부르지 않았다
    assert not revoke.called
    assert world.calendar.tokens_row is not None
    assert USER_ID in world.profiles.profiles
    # 서버를 켤 때도 같은 경고가 뜨므로, 탈퇴가 남긴 줄만 본다. 운영에서 원인을 알 단서라 경고로 남긴다
    stopped = [r for r in caplog.records if r.name == "app.account"]
    assert len(stopped) == 1 and stopped[0].levelno == logging.WARNING
    assert "탈퇴를 멈췄어요" in stopped[0].getMessage() and shown in stopped[0].getMessage()
    if key:
        assert key not in caplog.text  # 키 값은 남기지 않는다


@respx.mock
def test_a_404_that_is_not_from_the_storage_stops_everything(
    settings: Settings, auth: dict[str, str]
) -> None:
    """저장소 주소가 틀리면(여기서는 시험용 저장소 주소 `SUPABASE_STORAGE_BASE`에 다른 경로) 저장소가 아닌
    곳이 `code` 없는 404로 답한다. 그것을 "이미 지웠다"로 받으면 파일이 남은 채 탈퇴가 끝난다. 지우기 실패로
    보고 첫 파일에서 502로 멈춘다. (경로가 붙은 `SUPABASE_URL`은 모양 검사가 먼저 잡는다 — 아래 시험)"""
    world = World(
        settings, paths=PATHS, connected=True, storage_base=f"{PROJECT_URL}/rest/v1/storage/v1"
    )
    del world.app.dependency_overrides[get_storage]  # 실제 저장소 코드로 지운다
    gateway = respx.delete(url__startswith=f"{PROJECT_URL}/rest/v1/storage/v1/object/").mock(
        return_value=httpx.Response(404, json={"message": "no Route matched with those values"})
    )
    revoke = respx.post(REVOKE_URL).mock(return_value=httpx.Response(200, json={}))
    for client in _signed_in(world):
        response = client.delete(ME, headers=auth)
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "STORAGE_API_ERROR"
    assert gateway.call_count == 1  # 첫 파일에서 멈췄다
    assert not revoke.called
    assert world.calendar.tokens_row is not None
    assert USER_ID in world.profiles.profiles


@respx.mock
def test_a_project_url_with_a_path_stops_before_any_file_is_removed(
    settings: Settings, auth: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """경로가 붙은 `SUPABASE_URL`(`…/rest/v1`)은 키처럼 모양으로 잡는다. 저장소를 부르지 않고 502다."""
    world = World(settings, paths=PATHS, connected=True, url=f"{PROJECT_URL}/rest/v1")
    revoke = respx.post(REVOKE_URL).mock(return_value=httpx.Response(200, json={}))
    for client in _signed_in(world):
        response = client.delete(ME, headers=auth)
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "STORAGE_API_ERROR"
        assert "rest/v1" not in response.text
    assert world.storage.removed == [] and not revoke.called
    assert USER_ID in world.profiles.profiles
    stopped = [r.getMessage() for r in caplog.records if r.name == "app.account"]
    assert len(stopped) == 1 and "SUPABASE_URL 값에 경로가 붙어 있어요" in stopped[0]
    assert "abcdefghijklmnopqrst" not in stopped[0]  # 주소 값은 남기지 않는다


@respx.mock
@pytest.mark.parametrize("key", ["", PUBLISHABLE], ids=["no-settings", "publishable"])
def test_without_files_or_calendar_nothing_outside_is_called(
    settings: Settings, auth: dict[str, str], key: str
) -> None:
    """파일이 없으면 저장소를 부르지 않으니 설정도 보지 않는다. 저장소 설정이 없는 로컬에서도 탈퇴된다."""
    world = World(settings, paths=[], connected=False, key=key)
    revoke = respx.post(REVOKE_URL).mock(return_value=httpx.Response(200, json={}))
    for client in _signed_in(world):
        assert client.delete(ME, headers=auth).status_code == 204
        assert client.delete(ME, headers=auth).status_code == 204  # 두 번째도 같다
    assert world.storage.removed == [] and not revoke.called
    assert world.storage.listed == []  # 설정이 없거나 틀리면 폴더도 훑지 않는다
    assert USER_ID not in world.profiles.profiles


ORPHAN = f"{USER_ID}/poster/lost.png"


@respx.mock
def test_files_without_a_record_are_swept_from_my_folder(
    settings: Settings, auth: dict[str, str]
) -> None:
    """기록이 없는 파일(올린 뒤 기록의 커밋이 정말 실패해 남은 것)도 내 폴더를 훑어 지운다. 기록 있는 파일은
    한 번만 지운다."""
    world = World(settings, paths=PATHS, connected=False, orphans=(ORPHAN,), stale=True)
    for client in _signed_in(world):
        assert client.delete(ME, headers=auth).status_code == 204
    assert world.storage.listed == [USER_ID]
    # 목록이 늦게 따라와 방금 지운 파일이 보여도 다시 지우지 않는다
    assert world.storage.removed == [*PATHS, ORPHAN]
    assert world.storage.stored == []


@respx.mock
def test_a_folder_is_swept_even_without_any_record(
    settings: Settings, auth: dict[str, str]
) -> None:
    """기록된 파일이 하나도 없어도 저장소 설정이 맞으면 폴더를 훑는다."""
    world = World(settings, paths=[], connected=False, orphans=(ORPHAN,))
    for client in _signed_in(world):
        assert client.delete(ME, headers=auth).status_code == 204
    assert world.storage.removed == [ORPHAN]


@respx.mock
def test_a_folder_that_cannot_be_listed_stops_everything(
    settings: Settings, auth: dict[str, str]
) -> None:
    """폴더 목록을 못 받으면 파일을 못 지운 것과 같다. 502로 멈추고 Google·프로필은 그대로다."""
    world = World(settings, paths=PATHS, connected=True, list_fails=True)
    revoke = respx.post(REVOKE_URL).mock(return_value=httpx.Response(200, json={}))
    for client in _signed_in(world):
        response = client.delete(ME, headers=auth)
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "STORAGE_API_ERROR"
    assert (
        world.storage.removed == PATHS
    )  # 기록 있는 파일은 먼저 지웠다(다시 누르면 없음으로 지나간다)
    assert not revoke.called and world.calendar.tokens_row is not None
    assert USER_ID in world.profiles.profiles
