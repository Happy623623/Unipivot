"""계획서 추출 API(F-14): `POST /syllabi/extract`와 `GET /runs/{id}`.

서비스·저장소는 가짜다. 실제 실행(저장소 → 모델 → 저장)과 SQL은 test_syllabi_db.py가 본다.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.clock import current_time
from app.repositories.runs import get_run_repo
from app.repositories.syllabi import SyllabusCourse, SyllabusFile, get_syllabus_repo
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


class FakeSyllabusRepository:
    def __init__(self) -> None:
        self.files = {(USER_ID, FILE_ID): FILE}
        self.courses = {(USER_ID, COURSE_ID): COURSE}
        self.already: str | None = None

    async def syllabus_file(self, user_id: str, file_id: str) -> SyllabusFile | None:
        return self.files.get((user_id, file_id))

    async def course(self, user_id: str, course_id: str) -> SyllabusCourse | None:
        return self.courses.get((user_id, course_id))

    async def existing(self, user_id: str, course_id: str) -> str | None:
        return self.already


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
    client.app.dependency_overrides[get_syllabus_repo] = lambda: fake  # type: ignore[attr-defined]
    client.app.dependency_overrides[current_time] = lambda: NOW  # type: ignore[attr-defined]
    return fake


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
