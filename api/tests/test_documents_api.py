"""문서함 API(F-44, GET /files · GET /files/{id}/url). 저장소와 SQL은 가짜로 바꿔 끼운다.

실제 SQL은 test_documents_db.py, 서명 주소 만들기는 test_files_storage.py가 본다.
"""

import base64
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.clock import current_time
from app.config import Settings, get_settings
from app.eligibility.dates import KST
from app.main import create_app
from app.repositories.files import DOCUMENTS_SCOPE, DocumentFile, get_file_repos
from app.repositories.opportunities import Cursor, encode_cursor
from app.schemas.files import MyFile, MyFileCourse, MyFileList
from app.uploads.storage import StorageError, StorageMissing, get_storage
from tests.conftest import USER_ID, make_token

FILES = "/api/v1/files"
PROJECT_URL = "https://abcdefghijklmnopqrst.supabase.co"
SECRET = "sb_secret_" + "Tq7" * 10 + "x"  # 새 키 모양. 시험용 값이다
PUBLISHABLE = "sb_publishable_" + "Pk4" * 10 + "y"
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)  # 2026-10-15 12:00 KST
FILE_ID = "5b0f0f8e-3c1d-4d7a-9a8e-1f2e3d4c5b6a"
COURSE_ID = "0c6f1d2e-8a4b-4c3d-9e5f-6a7b8c9d0e1f"
PATH = f"{USER_ID}/lecture_material/{FILE_ID}.pdf"
AT = datetime(2026, 10, 14, 5, 30, tzinfo=UTC)
MISSING_OBJECT = "파일 저장소가 요청을 거절했어요(400, NoSuchKey: Object not found)."
# 너무 깊게 겹친 JSON. 2만 겹이면 json이 RecursionError를 낸다(주소 길이 64KB 안에 든다)
DEEP = base64.urlsafe_b64encode(b"[" * 20_000 + b"]" * 20_000).decode()
PAGE = MyFileList(
    items=[
        MyFile(
            file_id=FILE_ID,
            file_name="중간고사 대비 예제.pdf",
            kind="lecture_material",
            origin="lms_attachment",
            course=MyFileCourse(id=COURSE_ID, short_name="기계학습", is_active=True),
            size_bytes=86169,
            created_at=AT.astimezone(KST),  # 저장소가 KST로 바꿔 준다
        )
    ],
    next_cursor=None,
)


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


class FakeDocuments:
    def __init__(self) -> None:
        self.files: dict[str, DocumentFile] = {}  # 내 강의자료·계획서
        self.page = PAGE
        self.listed: list[tuple[str, int, Cursor | None]] = []
        self.open = 0  # 지금 연결을 빌려 쓰고 있는지

    async def documents(self, user_id: str, *, limit: int, after: Cursor | None) -> MyFileList:
        self.listed.append((user_id, limit, after))
        return self.page

    async def document(self, user_id: str, file_id: str) -> DocumentFile | None:
        return self.files.get(file_id) if user_id == USER_ID else None


class FakeStorage:
    def __init__(self, repo: FakeDocuments) -> None:
        self.repo = repo
        self.signed: list[tuple[str, str]] = []
        self.error: StorageError | None = None
        self.open_while_signing: list[int] = []

    async def signed_url(self, path: str, *, download_name: str) -> str:
        self.open_while_signing.append(self.repo.open)
        if self.error is not None:
            raise self.error
        self.signed.append((path, download_name))
        return f"https://storage.test/storage/v1/object/sign/uploads/{path}?token=t1&download=x"


def borrowing(repo: FakeDocuments) -> Callable[[], AbstractAsyncContextManager[FakeDocuments]]:
    """저장소를 빌렸다 돌려주는 공급자. 실제 공급자처럼 블록 밖에서는 쥐고 있지 않다."""

    @asynccontextmanager
    async def connect() -> AsyncIterator[FakeDocuments]:
        repo.open += 1
        try:
            yield repo
        finally:
            repo.open -= 1

    return connect


def make_client(settings: Settings, repo: FakeDocuments, storage: FakeStorage) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_file_repos] = lambda: borrowing(repo)
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[current_time] = lambda: NOW
    return TestClient(app)


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """저장소 설정이 맞는 서버. 설정에 고칠 점이 있으면 "없는 파일"을 믿지 않는다(아래 시험)."""
    return settings.model_copy(update={"supabase_url": PROJECT_URL, "supabase_secret_key": SECRET})


@pytest.fixture
def repo() -> FakeDocuments:
    return FakeDocuments()


@pytest.fixture
def storage(repo: FakeDocuments) -> FakeStorage:
    return FakeStorage(repo)


@pytest.fixture
def client(settings: Settings, repo: FakeDocuments, storage: FakeStorage) -> Iterator[TestClient]:
    with make_client(settings, repo, storage) as test_client:
        yield test_client


def test_my_documents_come_back_as_the_repository_lists_them(
    client: TestClient, repo: FakeDocuments
) -> None:
    response = client.get(FILES, headers=auth())
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "file_id": FILE_ID,
                "file_name": "중간고사 대비 예제.pdf",
                "kind": "lecture_material",
                "origin": "lms_attachment",
                "course": {"id": COURSE_ID, "short_name": "기계학습", "is_active": True},
                "size_bytes": 86169,
                "created_at": "2026-10-14T14:30:00+09:00",
            }
        ],
        "next_cursor": None,
    }
    assert repo.listed == [(USER_ID, 20, None)]  # 한 쪽은 20개가 기본이다


def test_the_next_page_follows_the_cursor(client: TestClient, repo: FakeDocuments) -> None:
    last = Cursor(scope=DOCUMENTS_SCOPE, value=AT, id=FILE_ID)
    response = client.get(FILES, params={"limit": 5, "cursor": encode_cursor(last)}, headers=auth())
    assert response.status_code == 200
    assert repo.listed == [(USER_ID, 5, last)]


@pytest.mark.parametrize(
    "cursor",
    [
        "망가진-커서",
        encode_cursor(Cursor(scope="unread=False", value=AT, id=FILE_ID)),  # 알림함 커서
        encode_cursor(Cursor(scope=DOCUMENTS_SCOPE, value=None, id=FILE_ID)),
        DEEP,  # 읽다가 너무 깊어 터진다
    ],
    ids=["broken", "other-list", "no-time", "too-deep"],
)
def test_a_cursor_from_elsewhere_asks_to_start_over(
    client: TestClient, repo: FakeDocuments, cursor: str
) -> None:
    response = client.get(FILES, params={"cursor": cursor}, headers=auth())
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_FAILED"
    assert error["details"]["fields"]["cursor"] == "문서함을 처음부터 다시 불러와 주세요."
    assert not repo.listed


@pytest.mark.parametrize(("limit", "status"), [(0, 422), (1, 200), (50, 200), (51, 422)])
def test_a_page_holds_one_to_fifty(
    client: TestClient, repo: FakeDocuments, limit: int, status: int
) -> None:
    response = client.get(FILES, params={"limit": limit}, headers=auth())
    assert response.status_code == status
    if status == 422:
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"
        assert not repo.listed


def test_a_download_link_lasts_five_minutes_and_keeps_the_name(
    client: TestClient,
    repo: FakeDocuments,
    storage: FakeStorage,
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo.files[FILE_ID] = DocumentFile(PATH, "중간고사 대비 예제.pdf", "lms_attachment")
    response = client.get(f"{FILES}/{FILE_ID}/url", headers=auth())
    assert response.status_code == 200
    assert response.json() == {
        "url": f"https://storage.test/storage/v1/object/sign/uploads/{PATH}?token=t1&download=x",
        "expires_at": "2026-10-15T12:05:00+09:00",
    }
    assert response.headers["cache-control"] == "no-store"  # 열쇠라 브라우저 캐시에 남기지 않는다
    assert storage.signed == [(PATH, "중간고사 대비 예제.pdf")]
    assert storage.open_while_signing == [0]  # 저장소를 기다리는 동안 DB 연결을 쥐지 않는다
    assert "token=t1" not in caplog.text  # 주소는 열쇠라 로그에 남기지 않는다


def test_a_file_without_its_name_downloads_as_file_dot_extension(
    client: TestClient, repo: FakeDocuments, storage: FakeStorage
) -> None:
    repo.files[FILE_ID] = DocumentFile(f"{USER_ID}/syllabus/{FILE_ID}.pdf", None, "upload")
    assert client.get(f"{FILES}/{FILE_ID}/url", headers=auth()).status_code == 200
    assert storage.signed[0][1] == "파일.pdf"


def test_someone_elses_file_or_a_poster_is_not_found(
    client: TestClient, storage: FakeStorage
) -> None:
    """저장소는 둘 다 찾지 못한다(내 강의자료·계획서만 본다). 주소를 만들러 가지도 않는다."""
    response = client.get(f"{FILES}/{FILE_ID}/url", headers=auth())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert storage.open_while_signing == []


@pytest.mark.parametrize(
    ("origin", "message"),
    [
        ("lms_attachment", "저장한 파일이 없어졌어요. LMS 공지에서 받아 주세요."),
        ("upload", "저장한 파일이 없어졌어요. 파일을 다시 올려 주세요."),
    ],
)
def test_a_file_gone_from_the_storage_says_where_to_get_it_again(
    client: TestClient,
    repo: FakeDocuments,
    storage: FakeStorage,
    caplog: pytest.LogCaptureFixture,
    origin: str,
    message: str,
) -> None:
    """기록만 남은 파일이다. 다시 눌러도 같으니 "잠시 후 다시"가 아니라 어디서 다시 받는지 알려 준다."""
    repo.files[FILE_ID] = DocumentFile(PATH, "a.pdf", origin)
    storage.error = StorageMissing(MISSING_OBJECT)
    response = client.get(f"{FILES}/{FILE_ID}/url", headers=auth())
    assert response.status_code == 404
    assert response.json()["error"] == {"code": "NOT_FOUND", "message": message, "details": {}}
    assert "NoSuchKey" in caplog.text  # 로그에는 저장소가 준 이유가 남는다


def test_a_missing_answer_is_not_trusted_when_the_storage_key_is_wrong(
    settings: Settings, repo: FakeDocuments, storage: FakeStorage
) -> None:
    """publishable key에도 저장소는 `NoSuchKey`로 답한다. 그때 404를 주면 설정 문제가 "없는 파일"로 숨는다."""
    wrong = settings.model_copy(update={"supabase_secret_key": PUBLISHABLE})
    repo.files[FILE_ID] = DocumentFile(PATH, "a.pdf", "lms_attachment")
    storage.error = StorageMissing(MISSING_OBJECT)
    with make_client(wrong, repo, storage) as test_client:
        response = test_client.get(f"{FILES}/{FILE_ID}/url", headers=auth())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "STORAGE_API_ERROR"


def test_a_storage_failure_is_a_502_without_its_reason(
    client: TestClient, repo: FakeDocuments, storage: FakeStorage
) -> None:
    repo.files[FILE_ID] = DocumentFile(PATH, "a.pdf", "upload")
    storage.error = StorageError(
        "파일 저장소가 요청을 거절했어요(400, AccessDenied: Invalid Compact JWS)."
    )
    response = client.get(f"{FILES}/{FILE_ID}/url", headers=auth())
    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "STORAGE_API_ERROR"
    assert error["message"] == "파일을 열지 못했어요. 잠시 후 다시 시도해 주세요."
    assert "AccessDenied" not in response.text  # 저장소가 준 이유는 로그에만 남는다


def test_a_file_id_must_be_a_uuid(client: TestClient, storage: FakeStorage) -> None:
    response = client.get(f"{FILES}/not-a-uuid/url", headers=auth())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert storage.open_while_signing == []


def test_without_a_token_nothing_is_listed_or_signed(
    client: TestClient, repo: FakeDocuments, storage: FakeStorage
) -> None:
    repo.files[FILE_ID] = DocumentFile(PATH, "a.pdf", "upload")
    assert client.get(FILES).status_code == 401
    assert client.get(f"{FILES}/{FILE_ID}/url").status_code == 401
    assert not repo.listed
    assert storage.open_while_signing == []
