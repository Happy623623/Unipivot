"""포스터 업로드 API(F-13, POST /files). 저장소와 SQL은 가짜로 바꿔 끼운다.

실제 SQL은 test_files_db.py, Storage 호출은 test_files_storage.py가 본다.
"""

import hashlib
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.clock import current_time
from app.config import Settings, get_settings
from app.main import create_app
from app.repositories.files import StoredFile, get_file_repos
from app.uploads import DAILY_UPLOAD_LIMIT, MAX_BYTES, SYLLABUS_MAX_PAGES
from app.uploads.storage import StorageError, get_storage
from tests import samples
from tests.conftest import USER_ID, make_token

FILES = "/api/v1/files"
JPEG_SHA = hashlib.sha256(samples.JPEG).hexdigest()
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)  # 2026-10-15 12:00 KST


class FakeFileRepository:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.used_today = 0
        self.steal: dict[str, Any] | None = None  # add 직전에 끼어드는 다른 요청
        self.gone = False  # 올리는 사이에 탈퇴해 프로필이 없어졌다(기록을 넣으면 외래 키에 걸린다)
        self.commit_lost = False  # 커밋 응답을 못 받았다(커밋이 됐는지 모른다)
        self.borrows = 0  # 연결을 몇 번 빌렸는지
        self.open = 0  # 지금 빌려 쓰고 있는지

    async def existing(self, user_id: str, *, kind: str, sha256: str) -> StoredFile | None:
        for row in self.rows:
            if (row["user_id"], row["kind"], row["sha"]) == (user_id, kind, sha256):
                return StoredFile(row["id"], row["kind"], row["pages"])
        return None

    async def uploads_since(self, user_id: str, since: datetime) -> int:
        return self.used_today

    async def add(self, user_id: str, *, file_id: str, kind: str, **row: Any) -> str | None:
        if self.gone:
            raise psycopg.errors.ForeignKeyViolation("files_user_id_fkey")
        if self.steal is not None:
            self.rows.append({"user_id": user_id, "kind": kind} | self.steal)
            self.steal = None
            return None  # 부분 유니크에 걸렸다
        self.rows.append(
            {
                "user_id": user_id,
                "id": file_id,
                "kind": kind,
                "sha": row["sha256"],
                "pages": row["page_count"],
                **row,
            }
        )
        return file_id


class FakeStorage:
    def __init__(self, repo: FakeFileRepository) -> None:
        self.repo = repo
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.removed: list[str] = []
        self.broken = False
        self.open_while_uploading: list[int] = []
        self.removed_while_open: list[int] = []  # 지울 때 연결을 쥐고 있었는지

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        self.open_while_uploading.append(self.repo.open)
        if self.broken:  # 실제 거절 문구처럼 Supabase의 이유가 붙어 있다(로그용)
            raise StorageError(
                "파일 저장소가 요청을 거절했어요(400, AccessDenied: new row violates row-level"
                " security policy)."
            )
        self.objects[path] = (data, content_type)

    async def remove(self, path: str) -> None:
        self.removed.append(path)
        self.removed_while_open.append(self.repo.open)
        self.objects.pop(path, None)


@pytest.fixture
def files_repo() -> FakeFileRepository:
    return FakeFileRepository()


@pytest.fixture
def storage(files_repo: FakeFileRepository) -> FakeStorage:
    return FakeStorage(files_repo)


def borrowing(repo: FakeFileRepository) -> Any:
    """저장소를 빌렸다 돌려주는 공급자. 실제 공급자처럼 블록 밖에서는 쥐고 있지 않다."""

    @asynccontextmanager
    async def connect() -> AsyncIterator[FakeFileRepository]:
        repo.borrows += 1
        repo.open += 1
        before = len(repo.rows)
        try:
            yield repo
            if repo.commit_lost and len(repo.rows) > before:  # 기록을 넣은 연결의 커밋만
                raise psycopg.OperationalError(
                    "consuming input failed: server closed the connection"
                )
        finally:
            repo.open -= 1

    return connect


@pytest.fixture
def client(
    settings: Settings, files_repo: FakeFileRepository, storage: FakeStorage
) -> Iterator[TestClient]:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_file_repos] = lambda: borrowing(files_repo)
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[current_time] = lambda: NOW
    with TestClient(app) as test_client:
        yield test_client


def upload(
    client: TestClient,
    data: bytes = samples.JPEG,
    *,
    name: str = "poster.jpg",
    kind: str | None = "poster",
) -> Any:
    return client.post(
        FILES,
        files={"file": (name, data, "application/octet-stream")},
        data={} if kind is None else {"kind": kind},
        headers={"Authorization": f"Bearer {make_token()}"},
    )


def test_a_poster_photo_is_stored_and_answered_with_its_id(
    client: TestClient, files_repo: FakeFileRepository, storage: FakeStorage
) -> None:
    response = upload(client, name="C:\\사진\\모집 포스터.jpg")
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "poster"
    assert body["page_count"] is None
    assert body["reused"] is False
    assert body["duplicate_of"] is None

    path = f"{USER_ID}/poster/{body['file_id']}.jpg"
    assert storage.objects[path] == (samples.JPEG, "image/jpeg")
    (row,) = files_repo.rows
    assert row["path"] == path
    assert row["mime_type"] == "image/jpeg"
    assert row["size_bytes"] == len(samples.JPEG)
    assert row["original_name"] == "모집 포스터.jpg"  # 경로는 떼고 이름만 남는다


def test_the_same_file_again_gives_back_the_first_id_without_storing_it(
    client: TestClient, storage: FakeStorage
) -> None:
    first = upload(client).json()
    again = upload(client, name="다시 올림.jpg")
    assert again.status_code == 200
    assert again.json() == {
        "file_id": first["file_id"],
        "kind": "poster",
        "page_count": None,
        "duplicate_of": first["file_id"],
        "reused": True,
    }
    assert len(storage.objects) == 1


def test_a_different_photo_is_a_new_file(client: TestClient, storage: FakeStorage) -> None:
    first = upload(client).json()
    second = upload(client, samples.PNG, name="다른 포스터.png")
    assert second.status_code == 201
    assert second.json()["file_id"] != first["file_id"]
    assert len(storage.objects) == 2


def test_a_two_page_pdf_keeps_its_page_count(client: TestClient) -> None:
    response = upload(client, samples.pdf(["1쪽", "2쪽"]), name="공고.pdf")
    assert response.status_code == 201
    assert response.json()["page_count"] == 2


def test_a_three_page_pdf_is_turned_away(client: TestClient, storage: FakeStorage) -> None:
    response = upload(client, samples.pdf(["1", "2", "3"]), name="공고.pdf")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAGE_LIMIT_EXCEEDED"
    assert not storage.objects


def test_an_iphone_photo_is_turned_away_with_what_to_do(client: TestClient) -> None:
    response = upload(client, samples.HEIC, name="IMG_0421.HEIC")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert "JPG" in response.json()["error"]["message"]


def test_a_renamed_file_is_judged_by_its_bytes(client: TestClient) -> None:
    response = upload(client, "<html>속았지</html>".encode(), name="poster.jpg")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_too_large_a_file_is_turned_away_before_it_is_stored(
    client: TestClient, storage: FakeStorage
) -> None:
    response = upload(client, samples.JPEG + b"\x00" * MAX_BYTES, name="큰.jpg")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert not storage.objects


def test_the_daily_limit_says_when_it_opens_again(
    client: TestClient, files_repo: FakeFileRepository, storage: FakeStorage
) -> None:
    files_repo.used_today = DAILY_UPLOAD_LIMIT
    response = upload(client)
    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "DAILY_UPLOAD_LIMIT"
    assert error["details"]["reset_at"] == "2026-10-16T00:00:00+09:00"
    assert not storage.objects


def test_one_below_the_limit_still_goes_through(
    client: TestClient, files_repo: FakeFileRepository
) -> None:
    files_repo.used_today = DAILY_UPLOAD_LIMIT - 1
    assert upload(client).status_code == 201


def test_a_file_already_uploaded_comes_back_even_at_the_limit(
    client: TestClient, files_repo: FakeFileRepository
) -> None:
    first = upload(client).json()
    files_repo.used_today = DAILY_UPLOAD_LIMIT
    again = upload(client)
    assert again.status_code == 200
    assert again.json()["file_id"] == first["file_id"]


def test_a_syllabus_pdf_goes_up(client: TestClient, files_repo: Any, storage: Any) -> None:
    """강의계획서는 글자가 있는 PDF만 받는다(F-14)."""
    response = upload(
        client, samples.pdf(["2026학년도 2학기 강의계획서"]), name="계획서.pdf", kind="syllabus"
    )
    assert response.status_code == 201
    body = response.json()
    assert (body["kind"], body["page_count"]) == ("syllabus", 1)
    path = next(iter(storage.objects))
    assert path.endswith(".pdf") and "/syllabus/" in path  # 종류별 폴더에 들어간다
    assert storage.objects[path][1] == "application/pdf"


def test_a_scanned_syllabus_is_refused(client: TestClient) -> None:
    """사진을 PDF로 감싼 파일은 글자가 없어서 모델에 보낼 것이 없다."""
    response = upload(client, samples.pdf([None]), name="스캔.pdf", kind="syllabus")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert "글자" in response.json()["error"]["message"]


def test_a_photo_is_not_a_syllabus(client: TestClient) -> None:
    response = upload(client, samples.JPEG, name="사진.jpg", kind="syllabus")
    assert response.status_code == 400
    assert "PDF만 올릴 수 있어요" in response.json()["error"]["message"]


def test_a_long_pdf_is_refused_as_a_syllabus(client: TestClient) -> None:
    """계획서는 몇 쪽이다. 수업 교재를 통째로 올리면 모델 입력이 터진다."""
    long_pdf = samples.pdf([f"{no}쪽" for no in range(SYLLABUS_MAX_PAGES + 1)])
    response = upload(client, long_pdf, name="교재.pdf", kind="syllabus")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAGE_LIMIT_EXCEEDED"
    assert f"{SYLLABUS_MAX_PAGES}쪽까지만" in response.json()["error"]["message"]


def test_other_kinds_are_not_open_yet(client: TestClient) -> None:
    response = upload(client, samples.pdf(["자료"]), name="자료.pdf", kind="lecture_material")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_FAILED"
    assert "강의계획서" in error["details"]["fields"]["kind"]


def test_the_db_connection_is_not_held_while_the_file_goes_to_the_storage(
    client: TestClient, files_repo: FakeFileRepository, storage: FakeStorage
) -> None:
    """저장소가 느려도 요청 풀이 묶이지 않게, 읽을 때와 쓸 때만 빌린다."""
    assert upload(client).status_code == 201
    assert storage.open_while_uploading == [0]
    assert files_repo.borrows == 2  # 읽기 한 번, 기록 한 번
    assert files_repo.open == 0


def test_the_kind_has_to_be_sent(client: TestClient) -> None:
    response = upload(client, kind=None)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_a_storage_refusal_leaves_no_record(
    client: TestClient, files_repo: FakeFileRepository, storage: FakeStorage
) -> None:
    storage.broken = True
    response = upload(client)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "STORAGE_API_ERROR"
    # 저장소가 준 이유는 로그에만 남고 응답은 정해 둔 문구다
    assert (
        response.json()["error"]["message"]
        == "파일을 저장하지 못했어요. 잠시 후 다시 시도해 주세요."
    )
    assert "AccessDenied" not in response.text
    assert not files_repo.rows


def test_two_requests_with_the_same_file_leave_one_record_and_one_object(
    client: TestClient, files_repo: FakeFileRepository, storage: FakeStorage
) -> None:
    # 올리는 사이에 같은 파일이 먼저 기록됐다
    files_repo.steal = {
        "id": "11111111-1111-4111-8111-111111111111",
        "sha": JPEG_SHA,
        "pages": None,
    }
    response = upload(client)
    assert response.status_code == 200
    assert response.json()["file_id"] == "11111111-1111-4111-8111-111111111111"
    assert len(files_repo.rows) == 1
    assert storage.removed and not storage.objects  # 방금 올린 것은 지운다


def test_a_file_whose_record_cannot_be_kept_is_removed_from_storage(
    client: TestClient, files_repo: FakeFileRepository, storage: FakeStorage
) -> None:
    """올리는 사이에 탈퇴했다. 탈퇴가 끝날 때까지 기다린 기록 넣기가 외래 키에 걸리면 방금 올린 파일을 지운다 —
    기록 없는 파일은 탈퇴로도 못 찾아 저장소에 남는다(app/account.py)."""
    files_repo.gone = True
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        upload(client)
    assert len(storage.removed) == 1 and not storage.objects
    assert not files_repo.rows
    assert storage.removed_while_open == [0]  # 연결을 돌려준 뒤에 지운다


def test_a_commit_that_may_have_landed_keeps_the_file(
    client: TestClient, files_repo: FakeFileRepository, storage: FakeStorage
) -> None:
    """커밋 중 연결이 끊겼다. 기록이 들어갔을 수도 있으니 파일은 지우지 않는다(지우면 기록이 없는 파일을 가리킨다)."""
    files_repo.commit_lost = True
    with pytest.raises(psycopg.OperationalError):
        upload(client)
    assert not storage.removed and len(storage.objects) == 1


def test_a_lost_commit_after_a_lost_race_still_removes_the_file(
    client: TestClient, files_repo: FakeFileRepository, storage: FakeStorage
) -> None:
    """같은 파일이 먼저 들어와 넣지 않았는데 커밋 응답도 못 받았다. 우리 경로를 가리키는 기록은 없으니 지운다."""
    files_repo.steal = {
        "id": "11111111-1111-4111-8111-111111111111",
        "sha": JPEG_SHA,
        "pages": None,
    }
    files_repo.commit_lost = True
    with pytest.raises(psycopg.OperationalError):
        upload(client)
    assert len(storage.removed) == 1 and not storage.objects


def test_without_a_token_nothing_is_uploaded(client: TestClient, storage: FakeStorage) -> None:
    response = client.post(FILES, files={"file": ("p.jpg", samples.JPEG, "image/jpeg")})
    assert response.status_code == 401
    assert not storage.objects
