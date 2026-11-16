"""청년정책 수집 작업의 DB 없이 볼 수 있는 부분 (API 명세 12장 `fetch-policies`, 스케줄러).

키가 없을 때의 거절, 스케줄러 목록에 들어가는 조건, 시각(예약보다 앞)을 본다. 실제로 넣는 것은
tests/test_youth_job_db.py가 본다.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, time
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import jobs, scheduler
from app.config import Settings, get_settings
from app.llm.deps import get_llm
from app.main import create_app
from app.scheduler import FETCH_AT, SCHEDULE_AT, app_jobs, first_run
from app.youth.refine import YouthRefiner
from tests.llm_fakes import ScriptedLlm

KEY = "youth-job-internal-test-key"


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": "",
        "supabase_url": "",
        "supabase_jwt_secret": "youth-job-secret-youth-job-secret",
        "token_encryption_key": Fernet.generate_key().decode(),
        "internal_api_key": KEY,
    }
    return Settings(**{**base, **over})


@pytest.fixture
def internal() -> Iterator[TestClient]:
    """서비스 키는 있고 온통청년 키는 없는 앱. DB 주소는 풀을 만들려고만 둔다(연결하지 않는다)."""
    settings = _settings(database_url="postgresql://postgres:postgres@localhost:5432/not_used_here")
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client


def test_without_a_youth_key_the_job_is_refused_before_calling_anything(
    internal: TestClient,
) -> None:
    response = internal.post(
        "/api/v1/internal/jobs/fetch-policies", headers={"X-Internal-Key": KEY}
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "YOUTH_API_ERROR"
    assert "YOUTH_API_KEY" in response.json()["error"]["message"]


def test_the_job_needs_the_service_key(internal: TestClient) -> None:
    response = internal.post("/api/v1/internal/jobs/fetch-policies")
    assert response.status_code == 403


def test_the_scheduler_adds_the_job_only_with_a_youth_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"):
        without = {job.name for job in app_jobs(create_app(_settings()))}
    assert "fetch-policies" not in without
    assert any("YOUTH_API_KEY" in record.message for record in caplog.records)

    jobs = {job.name: job for job in app_jobs(create_app(_settings(youth_api_key="x-key")))}
    assert set(jobs) == {
        "send-notifications",
        "lms-sync",
        "schedule-notifications",
        "fetch-policies",
    }
    assert jobs["fetch-policies"].daily_at == FETCH_AT
    # 처음 차례는 다음 04:00이다 — --reload 때마다 온통청년을 600번 부르면 안 된다
    now = datetime(2026, 11, 18, 3, 0, tzinfo=UTC)  # KST 정오
    assert first_run(jobs["fetch-policies"], now) > now


def test_fetching_runs_before_the_daily_scheduling() -> None:
    """새벽에 받아 두면 08:30 예약에 그날 새 정책이 들어간다."""
    assert FETCH_AT < SCHEDULE_AT
    assert FETCH_AT == time(4, 0)


# ── 서술형 자격 요건화(F-11b)를 켰을 때 ──────────────────────────────────────


@pytest.mark.parametrize("enabled", [False, True])
def test_the_route_and_the_scheduler_hand_the_refiner_only_when_switched_on(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    """엔드포인트와 스케줄러 줄이 같은 수집 함수에 요건화기를 넘긴다 — 스위치를 켰을 때만(F-11b)."""
    seen: list[Any] = []

    async def fake_fetch(**options: Any) -> Any:
        seen.append(options.get("refiner"))
        return {
            "run_id": "r",
            "fetched": 0,
            "total": 0,
            "complete": True,
            "stopped": None,
            "new": 0,
            "updated": 0,
            "unchanged": 0,
            "expired": 0,
            "hidden": 0,
            "skipped": 0,
            "gone_kept": 0,
        }

    monkeypatch.setattr(jobs, "fetch_policies_fresh", fake_fetch)
    monkeypatch.setattr(scheduler, "fetch_policies_fresh", fake_fetch)
    llm = ScriptedLlm()
    settings = _settings(
        youth_api_key="x-key",
        youth_text_enabled=enabled,
        database_url="postgresql://postgres:postgres@localhost:5432/not_used_here",
    )
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_llm] = lambda: llm
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/internal/jobs/fetch-policies", headers={"X-Internal-Key": KEY}
        )
    assert response.status_code == 200, response.text
    app.state.llm = llm  # 스케줄러는 app.state의 모델 클라이언트를 쓴다(llm_for)
    job = {one.name: one for one in app_jobs(app)}["fetch-policies"]
    asyncio.run(job.run())
    assert len(seen) == 2
    for refiner in seen:
        if enabled:
            assert isinstance(refiner, YouthRefiner) and refiner.llm is llm
        else:
            assert refiner is None
