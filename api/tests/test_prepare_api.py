"""준비하기 API(F-30·F-31): POST /opportunities/{id}/prepare와 GET /runs/{id}.
서비스·저장소는 가짜다. 실제 실행(서류 안내·역산 일정·실패 정리)과 SQL은 test_prepare_db.py가 본다."""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.clock import current_time
from app.eligibility import KST
from app.prepare.service import Started, get_prepare_service
from app.repositories.prepare import PlanState
from app.repositories.runs import get_run_repo
from app.schemas.opportunities import DocumentItem, ProcessStep
from app.schemas.prepare import PrepareResult, PrepTask
from tests.conftest import USER_ID
from tests.prepare_fakes import FakePrepareService, FakeRunRepository, new_id, run_row
from tests.test_detail_api import DETAIL, OPPORTUNITY_ID

PREPARE = f"/api/v1/opportunities/{OPPORTUNITY_ID}/prepare"
NOW = datetime(2026, 10, 13, 3, 30, tzinfo=UTC)  # 10/13 12:30 KST
ELIGIBLE = DETAIL.model_copy(
    update={"eligibility": DETAIL.eligibility.model_copy(update={"status": "eligible"})}
)


@pytest.fixture
def service(client: TestClient) -> FakePrepareService:
    fake = FakePrepareService()
    fake.details[OPPORTUNITY_ID] = ELIGIBLE
    client.app.dependency_overrides[get_prepare_service] = lambda: fake  # type: ignore[attr-defined]
    client.app.dependency_overrides[current_time] = lambda: NOW  # type: ignore[attr-defined]
    return fake


@pytest.fixture
def runs(client: TestClient) -> FakeRunRepository:
    fake = FakeRunRepository()
    client.app.dependency_overrides[get_run_repo] = lambda: fake  # type: ignore[attr-defined]
    return fake


def test_prepare_and_runs_require_login(client: TestClient) -> None:
    assert client.post(PREPARE, json={}).status_code == 401
    assert client.get(f"/api/v1/runs/{new_id()}").status_code == 401


def test_prepare_starts_a_run(
    client: TestClient, auth: dict[str, str], service: FakePrepareService
) -> None:
    res = client.post(PREPARE, headers=auth, json={})
    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "running" and body["run_id"]
    # 지금 프로필로 다시 판정하고, 마감일(KST 날짜)과 오늘(KST)로 계획을 만든다
    assert service.judge_calls == [(USER_ID, OPPORTUNITY_ID, "테스트 학생")]
    assert service.begins == [(USER_ID, OPPORTUNITY_ID, date(2026, 10, 15), date(2026, 10, 13))]


def test_prepared_or_running_plan_is_returned(
    client: TestClient, auth: dict[str, str], service: FakePrepareService
) -> None:
    run_id = new_id()
    service.plans[(USER_ID, OPPORTUNITY_ID)] = PlanState(new_id(), run_id, "succeeded", False)
    res = client.post(PREPARE, headers=auth, json={})
    assert (res.status_code, res.json()) == (200, {"run_id": run_id, "status": "succeeded"})
    service.plans[(USER_ID, OPPORTUNITY_ID)] = PlanState(new_id(), run_id, "running", False)
    res = client.post(PREPARE, headers=auth, json={})
    assert (res.status_code, res.json()) == (200, {"run_id": run_id, "status": "running"})
    assert service.begins == [] and service.resets == []


@pytest.mark.parametrize(("status", "stale"), [("running", True), ("failed", False)])
def test_stuck_or_failed_plan_is_made_again(
    client: TestClient,
    auth: dict[str, str],
    service: FakePrepareService,
    status: str,
    stale: bool,
) -> None:
    old = PlanState(new_id(), new_id(), status, stale)
    service.plans[(USER_ID, OPPORTUNITY_ID)] = old
    res = client.post(PREPARE, headers=auth, json={})
    assert res.status_code == 202 and res.json()["run_id"] != old.run_id
    assert service.resets == [old.id] and len(service.begins) == 1


def test_another_request_won_the_race(
    client: TestClient, auth: dict[str, str], service: FakePrepareService
) -> None:
    service.conflict = Started("00000000-0000-4000-8000-00000000abcd", "running", created=False)
    res = client.post(PREPARE, headers=auth, json={})
    assert (res.status_code, res.json()["run_id"]) == (200, "00000000-0000-4000-8000-00000000abcd")


def test_hidden_or_unknown_opportunity_is_not_found(
    client: TestClient, auth: dict[str, str], service: FakePrepareService
) -> None:
    other = f"/api/v1/opportunities/{new_id()}/prepare"
    assert client.post(other, headers=auth, json={}).json()["error"]["code"] == "NOT_FOUND"
    service.details[OPPORTUNITY_ID] = ELIGIBLE.model_copy(update={"status": "hidden"})
    res = client.post(PREPARE, headers=auth, json={})
    assert (res.status_code, res.json()["error"]["code"]) == (404, "NOT_FOUND")
    assert service.begins == []


@pytest.mark.parametrize(
    "update",
    [
        {"status": "expired"},
        {"deadline_at": datetime(2026, 10, 13, 12, 0, tzinfo=KST)},  # 오늘 정오 마감, 지금 12:30
    ],
)
def test_passed_deadline_cannot_be_prepared(
    client: TestClient, auth: dict[str, str], service: FakePrepareService, update: dict
) -> None:
    service.details[OPPORTUNITY_ID] = ELIGIBLE.model_copy(update=update)
    res = client.post(PREPARE, headers=auth, json={})
    assert (res.status_code, res.json()["error"]["code"]) == (409, "DEADLINE_PASSED")
    assert res.json()["error"]["message"] == "마감이 지난 공고예요. 준비 일정을 만들 수 없어요."
    assert service.begins == []


def test_a_rejected_press_keeps_the_old_plan(
    client: TestClient, auth: dict[str, str], service: FakePrepareService
) -> None:
    """거절하는 공고(마감 지남 등)에서는 실패한 계획을 지우지 않는다(지우면 숨김 공고를 못 연다)."""
    old = PlanState(new_id(), new_id(), "failed", False)
    service.plans[(USER_ID, OPPORTUNITY_ID)] = old
    service.details[OPPORTUNITY_ID] = ELIGIBLE.model_copy(update={"status": "expired"})
    res = client.post(PREPARE, headers=auth, json={})
    assert (res.status_code, res.json()["error"]["code"]) == (409, "DEADLINE_PASSED")
    assert service.resets == [] and service.begins == []


def test_ineligible_needs_force(
    client: TestClient, auth: dict[str, str], service: FakePrepareService
) -> None:
    service.details[OPPORTUNITY_ID] = ELIGIBLE.model_copy(
        update={"eligibility": DETAIL.eligibility.model_copy(update={"status": "ineligible"})}
    )
    res = client.post(PREPARE, headers=auth, json={})
    assert (res.status_code, res.json()["error"]["code"]) == (409, "NOT_ELIGIBLE")
    assert client.post(PREPARE, headers=auth, json={"force": True}).status_code == 202


def test_open_ended_posting_needs_a_target_date(
    client: TestClient, auth: dict[str, str], service: FakePrepareService
) -> None:
    service.details[OPPORTUNITY_ID] = ELIGIBLE.model_copy(update={"deadline_at": None})
    res = client.post(PREPARE, headers=auth, json={})
    assert res.status_code == 422
    assert res.json()["error"]["details"]["fields"] == {
        "target_date": "상시 공고는 목표일을 골라 주세요."
    }
    res = client.post(PREPARE, headers=auth, json={"target_date": "2026-10-12"})
    assert res.json()["error"]["details"]["fields"] == {
        "target_date": "목표일은 오늘이나 그 뒤로 골라 주세요."
    }
    assert client.post(PREPARE, headers=auth, json={"target_date": "2026-10-13"}).status_code == 202
    assert service.begins[-1][2:] == (date(2026, 10, 13), date(2026, 10, 13))


def test_target_date_is_ignored_when_there_is_a_deadline(
    client: TestClient, auth: dict[str, str], service: FakePrepareService
) -> None:
    assert client.post(PREPARE, headers=auth, json={"target_date": "2026-12-01"}).status_code == 202
    assert service.begins[-1][2] == date(2026, 10, 15)


def test_prepare_rejects_bad_input(
    client: TestClient, auth: dict[str, str], service: FakePrepareService
) -> None:
    res = client.post("/api/v1/opportunities/not-a-uuid/prepare", headers=auth, json={})
    assert res.status_code == 422 and "opportunity_id" in res.json()["error"]["details"]["fields"]
    res = client.post(PREPARE, headers=auth, json={"target_date": "다음 주"})
    assert res.status_code == 422 and "target_date" in res.json()["error"]["details"]["fields"]
    assert service.begins == []


def test_run_visibility(client: TestClient, auth: dict[str, str], runs: FakeRunRepository) -> None:
    batch = run_row(user_id=None, trigger_type="batch_crawl", status="succeeded")
    others = run_row(user_id=new_id())
    runs.runs.update({batch.id: batch, others.id: others})
    res = client.get(f"/api/v1/runs/{batch.id}", headers=auth)
    assert (res.status_code, res.json()["error"]["code"]) == (403, "FORBIDDEN")
    for run_id in (others.id, new_id()):
        res = client.get(f"/api/v1/runs/{run_id}", headers=auth)
        assert (res.status_code, res.json()["error"]["code"]) == (404, "NOT_FOUND")
    assert client.get("/api/v1/runs/not-a-uuid", headers=auth).status_code == 422


def test_running_and_finished_prepare_run(
    client: TestClient, auth: dict[str, str], runs: FakeRunRepository
) -> None:
    started = datetime(2026, 10, 13, 12, 30, tzinfo=KST)
    run = run_row(user_id=USER_ID, started_at=started)
    runs.runs[run.id] = run
    runs.steps_by_run[run.id] = [
        ProcessStep(
            seq=1,
            tool="get_document_guide",
            label="필요 서류 확인",
            status="running",
            latency_ms=None,
            chosen_by="pipeline",
            note=None,
        )
    ]
    body = client.get(f"/api/v1/runs/{run.id}", headers=auth).json()
    assert body["status"] == "running" and body["result"] is None and body["error"] is None
    assert body["started_at"] == "2026-10-13T12:30:00+09:00"
    assert [step["label"] for step in body["steps"]] == ["필요 서류 확인"]
    assert runs.result_calls == []  # 끝나기 전에는 결과를 읽지 않는다

    done = run_row(user_id=USER_ID, status="succeeded", started_at=started, latency_ms=4200)
    runs.runs[done.id] = done
    runs.results[done.id] = PrepareResult(
        prep_plan_id=new_id(),
        documents=[
            DocumentItem(
                id="d1",
                name="재학증명서",
                issuer="한양인 포털",
                how_to="발급",
                lead_days=0,
                effort_minutes=None,
                form_url=None,
                is_required=True,
                task_id="t1",
                is_done=False,
            )
        ],
        tasks=[
            PrepTask(
                id="t1", title="재학증명서 준비", due_date=date(2026, 10, 13), document_id="d1"
            ),
            PrepTask(id="t2", title="신청 제출", due_date=date(2026, 10, 14), document_id=None),
        ],
        calendar_event=None,
        calendar_error=None,
    )
    body = client.get(f"/api/v1/runs/{done.id}", headers=auth).json()
    assert body["result"]["kind"] == "prepare"
    assert [task["title"] for task in body["result"]["tasks"]] == ["재학증명서 준비", "신청 제출"]
    assert body["result"]["documents"][0]["task_id"] == "t1"
    assert runs.result_calls == [(USER_ID, done.id)]


@pytest.mark.parametrize(
    ("message", "code", "text"),
    [
        (
            "LLM_ERROR: 필요 서류를 확인하지 못했어요. 잠시 후 다시 눌러 주세요.",
            "LLM_ERROR",
            "필요 서류를 확인하지 못했어요. 잠시 후 다시 눌러 주세요.",
        ),
        (
            "ValueError('db exploded at row 3')",
            "INTERNAL_ERROR",
            "준비 일정을 만들지 못했어요. 잠시 후 다시 눌러 주세요.",
        ),
        (None, "INTERNAL_ERROR", "준비 일정을 만들지 못했어요. 잠시 후 다시 눌러 주세요."),
    ],
)
def test_failed_run_shows_only_safe_reasons(
    client: TestClient,
    auth: dict[str, str],
    runs: FakeRunRepository,
    message: str | None,
    code: str,
    text: str,
) -> None:
    run = run_row(user_id=USER_ID, status="failed", error_message=message)
    runs.runs[run.id] = run
    body = client.get(f"/api/v1/runs/{run.id}", headers=auth).json()
    assert body["error"] == {"code": code, "message": text} and body["result"] is None
