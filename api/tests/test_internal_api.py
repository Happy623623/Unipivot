"""내부·운영 API(명세 12장): 서비스 키 검증, 기간 해석, 시나리오 실행 겉. DB 없이 돈다."""

import logging
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.clock import current_time
from app.config import Settings, get_settings
from app.eligibility import KST
from app.main import create_app
from app.repositories.metrics import get_metrics_repo, rate
from app.routers.internal import DEFAULT_DAYS
from tests.fakes import FakeMetricsRepository

KEY = "internal-test-key-not-used-anywhere-else"
NOW = datetime(2026, 10, 15, 9, 0, tzinfo=KST)
METRICS = "/api/v1/internal/metrics"
EVAL = "/api/v1/internal/eval/run"


@pytest.fixture
def metrics_repo() -> FakeMetricsRepository:
    return FakeMetricsRepository()


@pytest.fixture
def internal(metrics_repo: FakeMetricsRepository) -> Iterator[TestClient]:
    """서비스 키와 시험용 DB 주소를 넣은 앱. 집계 저장소는 가짜다."""
    settings = Settings(
        database_url="postgresql://postgres:postgres@localhost:5432/not_used_here",
        supabase_url="",
        supabase_jwt_secret="unit-test-secret",
        internal_api_key=KEY,
    )
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_metrics_repo] = lambda: metrics_repo
    app.dependency_overrides[current_time] = lambda: NOW
    with TestClient(app) as client:
        yield client


def body(response: Any) -> dict[str, Any]:
    found: dict[str, Any] = response.json()
    return found


# ── 서비스 키 ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", [METRICS, EVAL])
def test_a_missing_or_wrong_service_key_is_refused(internal: TestClient, path: str) -> None:
    """사용자 토큰으로는 부를 수 없다(명세 12장). 키가 틀렸을 때와 없을 때가 같은 응답이다."""
    for headers in ({}, {"X-Internal-Key": ""}, {"X-Internal-Key": "wrong"}):
        response = internal.post(path, json={}) if path == EVAL else internal.get(path)
        assert response.status_code == 403
        assert body(response)["error"]["code"] == "FORBIDDEN"
        response = (
            internal.post(path, json={}, headers=headers)
            if path == EVAL
            else internal.get(path, headers=headers)
        )
        assert response.status_code == 403


def test_a_server_without_a_key_refuses_everyone(
    metrics_repo: FakeMetricsRepository, caplog: pytest.LogCaptureFixture
) -> None:
    """서버에 키가 없으면 아무도 부를 수 없다. 부른 쪽에는 알려 주지 않고 로그로만 알린다."""
    settings = Settings(supabase_url="", supabase_jwt_secret="s", internal_api_key="")
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_metrics_repo] = lambda: metrics_repo
    with caplog.at_level(logging.WARNING, logger="app.routers.internal"), TestClient(app) as client:
        response = client.get(METRICS, headers={"X-Internal-Key": "anything"})
    assert response.status_code == 403
    assert "INTERNAL_API_KEY" not in response.text  # 설정 이름도 흘리지 않는다
    assert metrics_repo.periods == []
    # 왜 모두 403인지 서버 로그로 알 수 있어야 한다. 그러지 않으면 설정을 빼먹은 줄 모른다
    assert any("INTERNAL_API_KEY" in record.message for record in caplog.records)


def test_the_key_is_never_echoed_back(internal: TestClient) -> None:
    response = internal.get(METRICS, headers={"X-Internal-Key": "wrong-but-long-key"})
    assert "wrong-but-long-key" not in response.text


# ── 기간 ───────────────────────────────────────────────────────────────────


def test_no_period_means_the_last_thirty_days_in_kst(
    internal: TestClient, metrics_repo: FakeMetricsRepository
) -> None:
    response = internal.get(METRICS, headers={"X-Internal-Key": KEY})
    assert response.status_code == 200
    assert metrics_repo.periods == [(date(2026, 9, 16), date(2026, 10, 15))]
    assert date(2026, 10, 15) - date(2026, 9, 16) == timedelta(days=DEFAULT_DAYS - 1)
    assert (body(response)["from"], body(response)["to"]) == ("2026-09-16", "2026-10-15")


def test_a_given_period_is_used_as_is(
    internal: TestClient, metrics_repo: FakeMetricsRepository
) -> None:
    response = internal.get(
        METRICS, headers={"X-Internal-Key": KEY}, params={"from": "2026-10-01", "to": "2026-10-07"}
    )
    assert response.status_code == 200
    assert metrics_repo.periods == [(date(2026, 10, 1), date(2026, 10, 7))]


def test_only_one_end_of_the_period_can_be_given(
    internal: TestClient, metrics_repo: FakeMetricsRepository
) -> None:
    internal.get(METRICS, headers={"X-Internal-Key": KEY}, params={"to": "2026-10-10"})
    internal.get(METRICS, headers={"X-Internal-Key": KEY}, params={"from": "2026-10-10"})
    assert metrics_repo.periods == [
        (date(2026, 9, 11), date(2026, 10, 10)),  # to만 주면 그 앞 30일
        (date(2026, 10, 10), date(2026, 10, 15)),  # from만 주면 오늘까지
    ]


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"from": "어제"}, "from"),
        ({"to": "2026-13-01"}, "to"),
        ({"from": "2026-10-10", "to": "2026-10-01"}, "to"),
    ],
)
def test_a_bad_period_says_which_field(
    internal: TestClient, metrics_repo: FakeMetricsRepository, params: dict[str, str], field: str
) -> None:
    response = internal.get(METRICS, headers={"X-Internal-Key": KEY}, params=params)
    assert response.status_code == 422
    assert field in body(response)["error"]["details"]["fields"]
    assert metrics_repo.periods == []  # 거르기 전에 집계하지 않는다


# ── 응답 모양 ──────────────────────────────────────────────────────────────


def test_the_response_keys_match_the_spec(internal: TestClient) -> None:
    found = body(internal.get(METRICS, headers={"X-Internal-Key": KEY}))
    assert set(found) == {"from", "to", "scenarios", "eligibility", "product"}
    assert set(found["scenarios"]) == {
        "runs",
        "passed",
        "success_rate",
        "latency",
        "cost_usd",
        "llm_calls",
        "by_scenario",
    }
    assert set(found["scenarios"]["latency"]) == {"p50_ms", "p95_ms"}
    assert set(found["eligibility"]) == {
        "run_started_at",
        "checks",
        "correct",
        "accuracy",
        "rows",
        "eligible_to_ineligible",
        "ineligible_to_eligible",
    }
    assert set(found["product"]) == {
        "undetermined",
        "profile_prompt",
        "prepare_conversion",
        "lms_connect",
        "weekly_return",
    }
    assert set(found["product"]["undetermined"]) == {
        "numerator",
        "denominator",
        "rate",
        "top_missing_fields",
    }


def test_a_rate_with_nothing_to_divide_is_null_not_zero() -> None:
    """0.0(아무도 안 했다)과 null(기회가 없었다)을 구분한다."""
    assert rate(0, 0).rate is None
    assert rate(0, 5).rate == 0.0
    assert rate(1, 3).rate == 0.3333
    assert rate(5, 5).rate == 1.0


# ── 시나리오 실행 ──────────────────────────────────────────────────────────


def test_an_unknown_scenario_code_is_refused_before_anything_runs(internal: TestClient) -> None:
    response = internal.post(
        EVAL, headers={"X-Internal-Key": KEY}, json={"scenario_codes": ["S01", "S99"]}
    )
    assert response.status_code == 422
    assert "S99" in body(response)["error"]["details"]["fields"]["scenario_codes"]


def test_only_recorded_fixtures_are_accepted(internal: TestClient) -> None:
    """지금은 녹화한 응답만 쓴다. 실제 호출로 재는 것은 다음 일이다."""
    response = internal.post(EVAL, headers={"X-Internal-Key": KEY}, json={"fixtures": "live"})
    assert response.status_code == 422
    assert body(response)["error"]["code"] == "VALIDATION_FAILED"


def test_scenarios_are_never_run_against_a_real_supabase_database(
    metrics_repo: FakeMetricsRepository,
) -> None:
    """시나리오는 사용자·공고를 만들고 지운다. 주소는 응답에 담지 않는다."""
    settings = Settings(
        database_url="postgresql://postgres:secret@db.abcdefgh.supabase.co:5432/postgres",
        supabase_url="",
        supabase_jwt_secret="s",
        internal_api_key=KEY,
    )
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_metrics_repo] = lambda: metrics_repo
    with TestClient(app) as client:
        response = client.post(
            EVAL, headers={"X-Internal-Key": KEY}, json={"scenario_codes": ["S02"]}
        )
    assert response.status_code == 409
    assert body(response)["error"]["code"] == "EVAL_NOT_ALLOWED"
    assert "abcdefgh" not in response.text and "secret" not in response.text


def test_without_a_database_url_the_run_stops(metrics_repo: FakeMetricsRepository) -> None:
    settings = Settings(
        database_url="", supabase_url="", supabase_jwt_secret="s", internal_api_key=KEY
    )
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_metrics_repo] = lambda: metrics_repo
    with TestClient(app) as client:
        response = client.post(
            EVAL, headers={"X-Internal-Key": KEY}, json={"scenario_codes": ["S02"]}
        )
    assert response.status_code == 503
    assert body(response)["error"]["code"] == "DB_UNAVAILABLE"
