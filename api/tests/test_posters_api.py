"""포스터 추출 API(F-16): POST /posters/extract와 GET /runs/{id}.
서비스·저장소는 가짜다. 실제 실행과 SQL은 test_posters_db.py가 본다."""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.clock import current_time
from app.posters.confirm import Confirmed
from app.posters.service import get_poster_service
from app.repositories.opportunities import Refresh, get_opportunity_repo
from app.repositories.posters import PosterFile, StoredPoster, get_poster_repo
from app.repositories.runs import get_run_repo
from app.schemas.posters import (
    DuplicateCandidate,
    PosterDraft,
    PosterExtractResult,
    PosterRequirementDraft,
)
from tests.conftest import USER_ID
from tests.prepare_fakes import FakeRunRepository, new_id, run_row

EXTRACT = "/api/v1/posters/extract"
CONFIRM = "/api/v1/posters/confirm"
RUN_ID = "00000000-0000-4000-8000-0000000000a9"
OPPORTUNITY_ID = "00000000-0000-4000-8000-0000000000aa"
NOW = datetime(2026, 10, 15, 15, 30, tzinfo=UTC)  # 10/16 00:30 KST
FILE_ID = "00000000-0000-4000-8000-0000000000f1"
POSTER = PosterFile(FILE_ID, f"{USER_ID}/poster/{FILE_ID}.jpg", "image/jpeg")
DRAFT = PosterDraft(
    title="2026 전국 대학생 SW 창업 아이디어톤",
    organizer="과학기술정보통신부",
    category="contest",
    apply_start_at=None,
    deadline_at=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
    easy_summary="창업 아이디어 대회예요.",
    requirements=[
        PosterRequirementDraft(
            clause_no=1,
            field="enrollment_status",
            operator="in",
            value=["enrolled", "on_leave"],
            condition_text="재학생 또는 휴학생",
            evidence_text="국내 대학 재학생 및 휴학생",
            is_ambiguous=False,
        )
    ],
    documents=[],
    extraction_confidence=0.8,
    low_confidence_fields=["deadline_at"],
)


class FakePosterService:
    def __init__(self) -> None:
        self.files: dict[tuple[str, str], PosterFile] = {(USER_ID, FILE_ID): POSTER}
        self.begins: list[tuple[str, str, datetime, date]] = []
        self.run_id = new_id()

    async def file(self, user_id: str, file_id: str) -> PosterFile | None:
        return self.files.get((user_id, file_id))

    async def begin(self, user_id: str, file: PosterFile, *, now: datetime, today: date) -> str:
        self.begins.append((user_id, file.id, now, today))
        return self.run_id


class FakePosterRepository:
    def __init__(self) -> None:
        self.drafts: dict[tuple[str, str], StoredPoster] = {
            (USER_ID, RUN_ID): StoredPoster(file_id=FILE_ID, draft=DRAFT, poster_text="포스터 글자")
        }
        self.duplicate_of: DuplicateCandidate | None = None
        self.asked: list[tuple[str, str, Any, Any]] = []
        self.created: list[Confirmed] = []

    async def stored(self, user_id: str, run_id: str) -> StoredPoster | None:
        return self.drafts.get((user_id, run_id))

    async def duplicate(
        self, user_id: str, *, title: str, deadline_at: Any, now: Any
    ) -> DuplicateCandidate | None:
        self.asked.append((user_id, title, deadline_at, now))
        return self.duplicate_of

    async def create(
        self, user_id: str, *, run_id: str, stored: StoredPoster, confirmed: Confirmed
    ) -> str:
        self.created.append(confirmed)
        return OPPORTUNITY_ID


class FakeJudgments:
    def __init__(self) -> None:
        self.refreshed: list[tuple[str, Any]] = []

    async def refresh_judgments(self, user_id: str, *, now: Any, **_: Any) -> Refresh:
        self.refreshed.append((user_id, now))
        return Refresh(judged=1, changed=0)


@pytest.fixture
def posters(client: TestClient) -> FakePosterRepository:
    fake = FakePosterRepository()
    client.app.dependency_overrides[get_poster_repo] = lambda: fake  # type: ignore[attr-defined]
    return fake


@pytest.fixture
def judgments(client: TestClient) -> FakeJudgments:
    fake = FakeJudgments()
    client.app.dependency_overrides[get_opportunity_repo] = lambda: fake  # type: ignore[attr-defined]
    client.app.dependency_overrides[current_time] = lambda: NOW  # type: ignore[attr-defined]
    return fake


@pytest.fixture
def service(client: TestClient) -> FakePosterService:
    fake = FakePosterService()
    client.app.dependency_overrides[get_poster_service] = lambda: fake  # type: ignore[attr-defined]
    client.app.dependency_overrides[current_time] = lambda: NOW  # type: ignore[attr-defined]
    return fake


@pytest.fixture
def runs(client: TestClient) -> FakeRunRepository:
    fake = FakeRunRepository()
    client.app.dependency_overrides[get_run_repo] = lambda: fake  # type: ignore[attr-defined]
    return fake


def test_extract_requires_login(client: TestClient) -> None:
    assert client.post(EXTRACT, json={"file_id": FILE_ID}).status_code == 401


def test_extract_starts_a_run_and_points_at_it(
    client: TestClient, auth: dict[str, str], service: FakePosterService
) -> None:
    res = client.post(EXTRACT, headers=auth, json={"file_id": FILE_ID})
    assert res.status_code == 202
    assert res.json() == {"run_id": service.run_id, "status": "running"}
    assert res.headers["Location"] == f"/api/v1/runs/{service.run_id}"
    # 오늘은 KST 날짜다(10/15 15:30 UTC는 KST로 10/16이다)
    assert service.begins == [(USER_ID, FILE_ID, NOW, date(2026, 10, 16))]


def test_someone_elses_file_is_not_found(
    client: TestClient, auth: dict[str, str], service: FakePosterService
) -> None:
    service.files.clear()
    res = client.post(EXTRACT, headers=auth, json={"file_id": FILE_ID})
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"
    assert service.begins == []


def test_a_file_id_that_is_not_a_uuid_is_rejected(
    client: TestClient, auth: dict[str, str], service: FakePosterService
) -> None:
    res = client.post(EXTRACT, headers=auth, json={"file_id": "포스터"})
    assert res.status_code == 422
    assert service.begins == []


def test_the_finished_run_gives_the_draft_and_the_duplicate(
    client: TestClient, auth: dict[str, str], runs: FakeRunRepository
) -> None:
    run_id = new_id()
    runs.runs[run_id] = run_row(
        id=run_id, user_id=USER_ID, trigger_type="poster_upload", status="succeeded"
    )
    runs.poster_results[run_id] = PosterExtractResult(
        draft=DRAFT,
        duplicate_candidate=DuplicateCandidate(opportunity_id=new_id(), title=DRAFT.title),
    )
    body = client.get(f"/api/v1/runs/{run_id}", headers=auth).json()
    assert body["status"] == "succeeded"
    assert body["result"]["kind"] == "poster_extract"
    assert body["result"]["draft"]["title"] == DRAFT.title
    assert body["result"]["draft"]["low_confidence_fields"] == ["deadline_at"]
    assert body["result"]["draft"]["requirements"][0]["condition_text"] == "재학생 또는 휴학생"
    assert body["result"]["duplicate_candidate"]["title"] == DRAFT.title
    assert runs.result_calls == [(USER_ID, run_id)]


def test_a_running_poster_run_has_no_result_yet(
    client: TestClient, auth: dict[str, str], runs: FakeRunRepository
) -> None:
    run_id = new_id()
    runs.runs[run_id] = run_row(id=run_id, user_id=USER_ID, trigger_type="poster_upload")
    body = client.get(f"/api/v1/runs/{run_id}", headers=auth).json()
    assert (body["status"], body["result"], body["error"]) == ("running", None, None)
    assert runs.result_calls == []  # 끝나기 전에는 초안을 찾지 않는다


def test_a_failed_poster_run_tells_the_student_what_to_do(
    client: TestClient, auth: dict[str, str], runs: FakeRunRepository
) -> None:
    run_id = new_id()
    runs.runs[run_id] = run_row(
        id=run_id,
        user_id=USER_ID,
        trigger_type="poster_upload",
        status="failed",
        error_message="POSTER_READ_FAILED: 포스터에서 글자를 읽지 못했어요. 다시 찍어 주세요.",
    )
    body = client.get(f"/api/v1/runs/{run_id}", headers=auth).json()
    assert body["error"]["code"] == "POSTER_READ_FAILED"
    assert "다시 찍어" in body["error"]["message"]
    assert body["result"] is None


def confirm(client: TestClient, auth: dict[str, str], draft: Any = None, **over: Any) -> Any:
    body = {"run_id": RUN_ID, "draft": (draft or DRAFT).model_dump(mode="json"), **over}
    return client.post(CONFIRM, headers=auth, json=body)


def test_confirm_requires_login(client: TestClient) -> None:
    assert client.post(CONFIRM, json={"run_id": RUN_ID, "draft": {}}).status_code == 401


def test_confirming_makes_the_opportunity_and_judges_it(
    client: TestClient,
    auth: dict[str, str],
    posters: FakePosterRepository,
    judgments: FakeJudgments,
) -> None:
    edited = DRAFT.model_copy(update={"title": "학생이 고친 제목"})
    res = confirm(client, auth, edited)
    assert res.status_code == 201
    assert res.json() == {"opportunity_id": OPPORTUNITY_ID, "merged": False}
    assert len(posters.created) == 1
    assert posters.created[0].title == "학생이 고친 제목"
    # 중복은 학생이 고친 값과 지금 시각으로 찾는다(초안 값이 아니다)
    assert posters.asked == [(USER_ID, "학생이 고친 제목", DRAFT.deadline_at, NOW)]
    assert judgments.refreshed == [(USER_ID, NOW)]  # 등록 즉시 본인 판정을 계산한다


def test_an_already_registered_opportunity_is_not_made_again(
    client: TestClient,
    auth: dict[str, str],
    posters: FakePosterRepository,
    judgments: FakeJudgments,
) -> None:
    posters.duplicate_of = DuplicateCandidate(opportunity_id=OPPORTUNITY_ID, title=DRAFT.title)
    res = confirm(client, auth)
    assert res.status_code == 200
    assert res.json() == {"opportunity_id": OPPORTUNITY_ID, "merged": True}
    assert posters.created == []


def test_a_run_that_is_not_mine_is_not_found(
    client: TestClient,
    auth: dict[str, str],
    posters: FakePosterRepository,
    judgments: FakeJudgments,
) -> None:
    posters.drafts.clear()
    res = confirm(client, auth)
    assert res.status_code == 404 and res.json()["error"]["code"] == "NOT_FOUND"
    assert posters.created == []


def test_an_unknown_category_is_rejected_by_the_contract(
    client: TestClient,
    auth: dict[str, str],
    posters: FakePosterRepository,
    judgments: FakeJudgments,
) -> None:
    body = DRAFT.model_dump(mode="json") | {"category": "자유공모"}
    res = client.post(CONFIRM, headers=auth, json={"run_id": RUN_ID, "draft": body})
    assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_FAILED"
    assert posters.created == []


def test_a_deadline_before_today_says_which_box_to_fix(
    client: TestClient,
    auth: dict[str, str],
    posters: FakePosterRepository,
    judgments: FakeJudgments,
) -> None:
    past = DRAFT.model_copy(update={"deadline_at": datetime(2026, 10, 14, 9, 0, tzinfo=UTC)})
    res = confirm(client, auth, past)
    assert res.status_code == 422
    assert "deadline_at" in res.json()["error"]["details"]["fields"]
    assert posters.created == []
