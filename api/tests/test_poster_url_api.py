"""포스터 원본 주소 API(W6, GET /opportunities/{id}/poster-url). 저장소와 SQL은 가짜로 바꿔 끼운다.

실제 SQL은 test_poster_url_db.py, 이름 없는 서명 주소는 test_files_storage.py가 본다. 404·502 규칙은
문서함 받기(test_documents_api.py)와 같다.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.clock import current_time
from app.config import Settings, get_settings
from app.main import create_app
from app.repositories.files import PosterOriginalFile, get_file_repos
from app.uploads.storage import StorageError, StorageMissing, get_storage
from tests.conftest import USER_ID, make_token

OPPORTUNITY_ID = "7d0c4f1e-2b3a-4c5d-8e9f-0a1b2c3d4e5f"
URL = f"/api/v1/opportunities/{OPPORTUNITY_ID}/poster-url"
PROJECT_URL = "https://abcdefghijklmnopqrst.supabase.co"
SECRET = "sb_secret_" + "Tq7" * 10 + "x"  # 새 키 모양. 시험용 값이다
PUBLISHABLE = "sb_publishable_" + "Pk4" * 10 + "y"
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)  # 2026-10-15 12:00 KST
PATH = f"{USER_ID}/poster/0f1e2d3c-4b5a-4968-8776-655443322110.png"
MISSING_OBJECT = "파일 저장소가 요청을 거절했어요(400, NoSuchKey: Object not found)."


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


class FakePosters:
    def __init__(self) -> None:
        self.posters: dict[str, PosterOriginalFile] = {}  # 내가 올린 포스터 공고의 원본
        self.asked: list[tuple[str, str]] = []
        self.open = 0  # 지금 연결을 빌려 쓰고 있는지

    async def poster(self, user_id: str, opportunity_id: str) -> PosterOriginalFile | None:
        self.asked.append((user_id, opportunity_id))
        return self.posters.get(opportunity_id) if user_id == USER_ID else None


class FakeStorage:
    def __init__(self, repo: FakePosters) -> None:
        self.repo = repo
        self.signed: list[tuple[str, str | None]] = []
        self.error: StorageError | None = None
        self.open_while_signing: list[int] = []

    async def signed_url(self, path: str, *, download_name: str | None = None) -> str:
        self.open_while_signing.append(self.repo.open)
        if self.error is not None:
            raise self.error
        self.signed.append((path, download_name))
        return f"https://storage.test/storage/v1/object/sign/uploads/{path}?token=t1"


def borrowing(repo: FakePosters) -> Callable[[], AbstractAsyncContextManager[FakePosters]]:
    @asynccontextmanager
    async def connect() -> AsyncIterator[FakePosters]:
        repo.open += 1
        try:
            yield repo
        finally:
            repo.open -= 1

    return connect


def make_client(settings: Settings, repo: FakePosters, storage: FakeStorage) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_file_repos] = lambda: borrowing(repo)
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[current_time] = lambda: NOW
    return TestClient(app)


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """저장소 설정이 맞는 서버."""
    return settings.model_copy(update={"supabase_url": PROJECT_URL, "supabase_secret_key": SECRET})


@pytest.fixture
def repo() -> FakePosters:
    return FakePosters()


@pytest.fixture
def storage(repo: FakePosters) -> FakeStorage:
    return FakeStorage(repo)


@pytest.fixture
def client(settings: Settings, repo: FakePosters, storage: FakeStorage) -> Iterator[TestClient]:
    with make_client(settings, repo, storage) as test_client:
        yield test_client


def test_my_poster_opens_for_five_minutes_without_a_download_name(
    client: TestClient,
    repo: FakePosters,
    storage: FakeStorage,
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo.posters[OPPORTUNITY_ID] = PosterOriginalFile(PATH, "image")
    upper = f"/api/v1/opportunities/{OPPORTUNITY_ID.upper()}/poster-url"
    response = client.get(upper, headers=auth())
    assert response.status_code == 200
    assert response.json() == {
        "url": f"https://storage.test/storage/v1/object/sign/uploads/{PATH}?token=t1",
        "expires_at": "2026-10-15T12:05:00+09:00",
    }
    assert response.headers["cache-control"] == "no-store"  # 열쇠라 브라우저 캐시에 남기지 않는다
    assert repo.asked == [(USER_ID, OPPORTUNITY_ID)]  # id는 소문자로 바꿔 넘긴다
    # 이름을 넘기지 않는다 — 내려받지 않고 브라우저가 그대로 보여 준다
    assert storage.signed == [(PATH, None)]
    assert storage.open_while_signing == [0]  # 저장소를 기다리는 동안 DB 연결을 쥐지 않는다
    assert "token=t1" not in caplog.text  # 주소는 로그에 남기지 않는다


def test_a_poster_that_is_not_mine_is_not_found(client: TestClient, storage: FakeStorage) -> None:
    """남이 올린 포스터·포스터가 아닌 공고·원본이 없는 공고는 모두 저장소가 찾지 못한다. 서명하러 가지 않는다."""
    response = client.get(URL, headers=auth())
    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "포스터를 찾을 수 없어요.",
        "details": {},
    }
    assert storage.open_while_signing == []


def test_a_poster_gone_from_the_storage_asks_to_upload_it_again(
    client: TestClient,
    repo: FakePosters,
    storage: FakeStorage,
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo.posters[OPPORTUNITY_ID] = PosterOriginalFile(PATH, "pdf")
    storage.error = StorageMissing(MISSING_OBJECT)
    response = client.get(URL, headers=auth())
    assert response.status_code == 404
    assert response.json()["error"]["message"] == (
        "올린 포스터 파일이 없어졌어요. 포스터를 다시 올려 주세요."
    )
    assert "NoSuchKey" in caplog.text  # 로그에는 저장소가 준 이유가 남는다
    assert (
        "token=" not in caplog.text and "token=" not in response.text
    )  # 오류 길에서도 주소(열쇠)는 안 남는다


def test_a_missing_answer_is_not_trusted_when_the_storage_key_is_wrong(
    settings: Settings, repo: FakePosters, storage: FakeStorage
) -> None:
    """publishable key에도 저장소는 `NoSuchKey`로 답한다. 그때 404를 주면 설정 문제가 "없는 파일"로 숨는다."""
    wrong = settings.model_copy(update={"supabase_secret_key": PUBLISHABLE})
    repo.posters[OPPORTUNITY_ID] = PosterOriginalFile(PATH, "image")
    storage.error = StorageMissing(MISSING_OBJECT)
    with make_client(wrong, repo, storage) as test_client:
        response = test_client.get(URL, headers=auth())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "STORAGE_API_ERROR"


def test_a_storage_failure_is_a_502_without_its_reason(
    client: TestClient, repo: FakePosters, storage: FakeStorage
) -> None:
    repo.posters[OPPORTUNITY_ID] = PosterOriginalFile(PATH, "image")
    storage.error = StorageError(
        "파일 저장소가 요청을 거절했어요(400, AccessDenied: Invalid Compact JWS)."
    )
    response = client.get(URL, headers=auth())
    assert response.status_code == 502
    error = response.json()["error"]
    assert error == {
        "code": "STORAGE_API_ERROR",
        "message": "포스터를 열지 못했어요. 잠시 후 다시 시도해 주세요.",
        "details": {},
    }
    assert "AccessDenied" not in response.text  # 저장소가 준 이유는 로그에만 남는다
    assert "no-store" not in response.headers.get(
        "cache-control", ""
    )  # 주소가 없는 오류는 캐시 머리를 달지 않는다


def test_an_opportunity_id_must_be_a_uuid(client: TestClient, repo: FakePosters) -> None:
    response = client.get("/api/v1/opportunities/not-a-uuid/poster-url", headers=auth())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert repo.asked == []


def test_without_a_token_nothing_is_signed(
    client: TestClient, repo: FakePosters, storage: FakeStorage
) -> None:
    repo.posters[OPPORTUNITY_ID] = PosterOriginalFile(PATH, "image")
    assert client.get(URL).status_code == 401
    assert repo.asked == []
    assert storage.open_while_signing == []
