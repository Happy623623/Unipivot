"""청년정책 수집 작업을 실제 DB에 대고 본다 (API 명세 12장 `fetch-policies`, 스케줄러). DATABASE_URL이 있을 때만.

엔드포인트와 스케줄러 줄이 **같은 함수**로 정책을 넣는지, 온통청년 오류가 502로 나오고 실행이 실패로
남는지 본다. 온통청년은 가짜 클라이언트다(네트워크를 쓰지 않는다). 넣은 공고·실행 기록은 끝에 지운다 —
수집은 autocommit이라 되돌릴 수 없다.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app, lifespan
from app.scheduler import app_jobs
from app.youth.client import BASE_URL
from app.youth.deps import youth_client_factory
from tests.db_world import DATABASE_URL
from tests.youth_samples import FakeClient, policy, skip_if_other_youth_policies

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

KEY = "youth-job-db-internal-key"
PREFIX = f"J{uuid.uuid4().hex[:8]}-"
STARTED = datetime.now(UTC)


def _items() -> list[dict[str, Any]]:
    """가져올 정책 둘(전국 상시·미취업), 가져오지 않을 정책 하나(부산)."""
    return [
        policy(plcyNo=PREFIX + "A", plcyNm="전국 상시 정책"),
        policy(plcyNo=PREFIX + "J", plcyNm="미취업 청년 정책", jobCd="0013003"),
        policy(plcyNo=PREFIX + "D", plcyNm="부산 정책", zipCd="26110"),
    ]


def _settings() -> Settings:
    return Settings(
        database_url=DATABASE_URL,
        supabase_url="",
        supabase_jwt_secret="youth-job-db-secret-youth-job-db-secret",
        token_encryption_key=Fernet.generate_key().decode(),
        internal_api_key=KEY,
        youth_api_key="youth-job-db-fake-key",
    )


async def _statuses() -> dict[str, str]:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        rows = await (
            await conn.execute(
                "select external_id, status::text from opportunities where external_id like %s",
                (PREFIX + "%",),
            )
        ).fetchall()
    return {row[0].removeprefix(PREFIX): row[1] for row in rows}


async def _runs() -> dict[str, str]:
    """이 시험이 시작된 뒤의 수집 실행(id → 상태). 다른 시험의 실행도 섞이므로 전후 차로 내 것을 고른다."""
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        rows = await (
            await conn.execute(
                "select id::text, status::text from agent_runs where trigger_type = 'batch_crawl'"
                " and started_at >= %s",
                (STARTED,),
            )
        ).fetchall()
    return {row[0]: row[1] for row in rows}


async def _cleanup(run_ids: set[str]) -> None:
    """이 파일이 만든 행만 지운다(공고는 번호 앞머리로, 실행은 id로 고른다)."""
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        await conn.execute(
            "delete from opportunities o using sources s where s.id = o.source_id"
            " and s.base_url = %s and o.external_id like %s",
            (BASE_URL, PREFIX + "%"),
        )
        await conn.execute(
            "delete from sources s where s.base_url = %s"
            " and not exists (select 1 from opportunities o where o.source_id = s.id)",
            (BASE_URL,),
        )
        if run_ids:
            await conn.execute(
                "delete from agent_runs where id = any(%s::uuid[])", (list(run_ids),)
            )


@pytest.fixture
def internal() -> Iterator[TestClient]:
    settings = _settings()
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client


@pytest.mark.anyio
async def test_the_endpoint_saves_policies_and_a_failed_fetch_is_a_502(
    internal: TestClient,
) -> None:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        await skip_if_other_youth_policies(conn, PREFIX)
    app = internal.app
    headers = {"X-Internal-Key": KEY}
    mine: set[str] = set()
    try:
        app.dependency_overrides[youth_client_factory] = lambda: lambda key: FakeClient(_items())
        response = internal.post("/api/v1/internal/jobs/fetch-policies", headers=headers)
        assert response.status_code == 200, response.text
        found = response.json()
        assert (found["new"], found["updated"], found["unchanged"]) == (2, 0, 0)
        assert (found["fetched"], found["skipped"], found["complete"]) == (3, 1, True)
        assert found["stopped"] is None and found["gone_kept"] == 0
        assert len(found["run_id"]) == 36
        mine.add(found["run_id"])
        assert await _statuses() == {"A": "active", "J": "active"}  # 부산 정책은 넣지 않는다

        # 같은 목록을 다시 받으면 그대로다(DB에 다시 가지 않는다)
        response = internal.post("/api/v1/internal/jobs/fetch-policies", headers=headers)
        assert response.status_code == 200
        assert (response.json()["new"], response.json()["unchanged"]) == (0, 2)
        mine.add(response.json()["run_id"])

        # 온통청년이 막히면 502다. 실행은 실패로 남고, 넣어 둔 공고는 그대로다
        before = await _runs()
        app.dependency_overrides[youth_client_factory] = lambda: (
            lambda key: FakeClient([], error="온통청년이 응답하지 않아요")
        )
        response = internal.post("/api/v1/internal/jobs/fetch-policies", headers=headers)
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "YOUTH_API_ERROR"
        assert "응답하지 않아요" in response.json()["error"]["message"]
        failed = {
            run_id: status for run_id, status in (await _runs()).items() if run_id not in before
        }
        assert list(failed.values()) == ["failed"]
        mine |= set(failed)
        assert await _statuses() == {"A": "active", "J": "active"}
    finally:
        await _cleanup(mine)


@pytest.mark.anyio
async def test_the_scheduler_line_saves_policies_the_same_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """스케줄러 줄은 요청 밖에서 돈다 — 자기 연결을 열고, 끝나면 닫는다."""
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        await skip_if_other_youth_policies(conn, PREFIX)
    from app import scheduler

    clients: list[FakeClient] = []

    def make(key: str) -> FakeClient:
        clients.append(FakeClient(_items()))
        return clients[-1]

    monkeypatch.setattr(scheduler, "YouthPolicyClient", make)
    app = create_app(_settings())
    mine: set[str] = set()
    try:
        async with lifespan(app):
            job = {job.name: job for job in app_jobs(app)}["청년정책 수집"]
            result = await job.run()
        mine.add(result.run_id)
        assert (result.new, result.skipped, result.complete) == (2, 1, True)
        assert clients and clients[0].closed  # 다 쓴 클라이언트를 닫는다
        assert await _statuses() == {"A": "active", "J": "active"}
    finally:
        await _cleanup(mine)
