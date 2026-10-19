"""청년정책 수집 작업의 DB 없이 볼 수 있는 부분 (API 명세 12장 `fetch-policies`, 스케줄러).

키가 없을 때의 거절, 스케줄러 목록에 들어가는 조건, 시각(예약보다 앞)을 본다. 실제로 넣는 것은
tests/test_youth_job_db.py가 본다.
"""

from collections.abc import Iterator
from datetime import time
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.scheduler import FETCH_AT, SCHEDULE_AT, app_jobs

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
    assert "청년정책 수집" not in without
    assert any("YOUTH_API_KEY" in record.message for record in caplog.records)

    jobs = {job.name: job for job in app_jobs(create_app(_settings(youth_api_key="x-key")))}
    assert set(jobs) == {"알림 발송", "LMS 동기화", "공고 알림 예약", "청년정책 수집"}
    assert jobs["청년정책 수집"].daily_at == FETCH_AT
    assert not jobs["청년정책 수집"].at_start  # --reload 때마다 온통청년을 600번 부르면 안 된다


def test_fetching_runs_before_the_daily_scheduling() -> None:
    """새벽에 받아 두면 08:30 예약에 그날 새 정책이 들어간다."""
    assert FETCH_AT < SCHEDULE_AT
    assert FETCH_AT == time(4, 0)
