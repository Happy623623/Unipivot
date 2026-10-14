"""청년정책 수집 CLI: 키가 없을 때, 미리 보기(--dry-run), 온통청년 오류·막힘, DB 문제, DB에 넣기(DB 테스트).
온통청년은 가짜 클라이언트나 respx로 바꿔 끼운다. api/.env의 실제 키·DB 주소를 쓰지 않게 환경 변수로 덮어쓴다."""

import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
import psycopg
import pytest
import respx

from app.eligibility import KST
from app.youth import cli, importer
from app.youth.cli import main
from app.youth.client import BASE_URL, POLICY_PATH, YouthPolicyClient
from tests.youth_samples import FakeClient, policy, skip_if_other_youth_policies

pytestmark = pytest.mark.anyio
DATABASE_URL = os.environ.get("DATABASE_URL", "")
KEY = "youthcenter-cli-test-key"
PREFIX = f"C{uuid.uuid4().hex[:8]}-"
END = datetime.now(KST).date() + timedelta(days=40)  # CLI는 오늘(KST)로 마감을 본다


def items() -> list[dict[str, Any]]:
    """가져올 정책 셋(전국·안산·미취업), 가져오지 않을 정책 둘(마감, 부산)."""
    return [
        policy(plcyNo=PREFIX + "A", plcyNm="전국 상시 정책"),
        policy(
            plcyNo=PREFIX + "B",
            plcyNm="안산 청년 정책",
            zipCd="41271,41273",
            sprtTrgtMinAge="19",
            sprtTrgtMaxAge="34",
            aplyPrdSeCd="0057001",
            aplyYmd=f"20260101 ~ {END:%Y%m%d}",
        ),
        policy(plcyNo=PREFIX + "J", plcyNm="미취업 청년 정책", jobCd="0013003"),
        policy(plcyNo=PREFIX + "C", plcyNm="마감된 정책", aplyPrdSeCd="0057003"),
        policy(plcyNo=PREFIX + "D", plcyNm="부산 정책", zipCd="26110"),
    ]


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTH_API_KEY", KEY)
    monkeypatch.setenv("DATABASE_URL", "")


def factory(client: FakeClient, keys: list[str] | None = None) -> Any:
    def make(api_key: str) -> FakeClient:
        if keys is not None:
            keys.append(api_key)
        return client

    return make


async def test_needs_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("YOUTH_API_KEY", " ")
    keys: list[str] = []
    assert await main(["fetch", "--dry-run"], make_client=factory(FakeClient([]), keys)) == 1
    assert "YOUTH_API_KEY가 없어요. api/.env에" in capsys.readouterr().out
    assert keys == []


async def test_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    fake, keys = FakeClient(items()), []
    assert await main(["fetch", "--dry-run"], make_client=factory(fake, keys)) == 0
    out = capsys.readouterr().out
    assert keys == [KEY] and fake.closed and KEY not in out
    assert out.splitlines() == [
        "온통청년 정책 5건 받음(전체 5건, 호출 1회, 0초)",
        "가져올 정책 3건 · 가져오지 않음 마감 1 · 수도권 밖 1",
        "조건 없는 정책 1건 · 기타 조건(원문 확인)이 있는 정책 1건 · 항목별 조건 수"
        " 나이 1 · 거주지역 1 · 기타 조건 1",
        "DB에는 넣지 않았어요(--dry-run). 예시:",
        f"  안산 청년 정책 · 조달청 · 마감 {END:%Y-%m-%d}",
        "    1. 나이 만 19–34세",
        "    2. 거주지역 경기도 안산시",
        "  미취업 청년 정책 · 조달청 · 마감 없음",
        "    1. 기타 조건 취업 상태: 미취업자",
    ]


async def test_youth_api_problems(capsys: pytest.CaptureFixture[str]) -> None:
    blocked = FakeClient([], error="온통청년이 요청을 막았어요(HTTP 403·e001 invalid api key.). …")
    assert await main(["fetch", "--dry-run"], make_client=factory(blocked)) == 1
    assert "온통청년이 요청을 막았어요" in capsys.readouterr().out and blocked.closed
    stopped = FakeClient(items()[:1], skipped=tuple(range(100, 200)), stopped="2~3쪽을 받지 못함")
    assert await main(["fetch", "--dry-run"], make_client=factory(stopped)) == 1
    out = capsys.readouterr().out.splitlines()
    assert (
        "읽지 못해 건너뛴 정책 100건(순번 [100, 101, 102, 103, 104, 105, 106, 107, 108, 109])"
        in out
    )
    assert "끝까지 받지 못했어요: 2~3쪽을 받지 못함. 몇 분 뒤 다시 돌려 주세요" in out


async def test_blocked_by_youthcenter(capsys: pytest.CaptureFixture[str]) -> None:
    """실제 클라이언트로: 첫 쪽에서 막히면 이유와 할 일 한 줄, 2쪽에서 막히면 받은 100건으로 미리 보기. 둘 다 끝 코드 1."""
    listed = [policy(plcyNo=f"{PREFIX}{n:03d}", plcyNm=f"정책 {n}") for n in range(150)]
    blocked = httpx.Response(403, json={"errorCode": "e001", "errorMsg": "invalid api key."})

    def make(api_key: str) -> YouthPolicyClient:
        return YouthPolicyClient(api_key, retry_delay=0, page_delay=0)

    def answer(block_from: int) -> Any:
        def handle(request: httpx.Request) -> httpx.Response:
            num, size = int(request.url.params["pageNum"]), int(request.url.params["pageSize"])
            if num >= block_from:
                return blocked
            page = {"totCount": len(listed), "pageNum": num, "pageSize": size}
            found = listed[(num - 1) * size : num * size]
            body = {"resultCode": 200, "result": {"pagging": page, "youthPolicyList": found}}
            return httpx.Response(200, json=body)

        return handle

    with respx.mock() as router:
        router.get(BASE_URL + POLICY_PATH).mock(side_effect=answer(1))
        assert await main(["fetch", "--dry-run"], make_client=make) == 1
    out = capsys.readouterr().out
    assert out.splitlines() == [
        "온통청년이 요청을 막았어요(HTTP 403·e001 invalid api key.). 키가 틀렸거나, 방금 여러 번 불러"
        " 잠깐 막혔을 수 있어요. 몇 분 뒤 다시 돌려 보고, 그래도 같으면 api/.env의 YOUTH_API_KEY를"
        " 확인하세요"
    ]
    with respx.mock() as router:
        router.get(BASE_URL + POLICY_PATH).mock(side_effect=answer(2))
        assert await main(["fetch", "--dry-run"], make_client=make) == 1
    out = capsys.readouterr().out
    assert out.splitlines()[:3] == [
        "온통청년 정책 100건 받음(전체 150건, 호출 2회, 0초)",
        "끝까지 받지 못했어요: 2쪽에서 온통청년이 요청을 막음(HTTP 403·e001 invalid api key.)."
        " 몇 분 뒤 다시 돌려 주세요",
        "가져올 정책 100건 · 가져오지 않음 없음",
    ]
    assert KEY not in out


async def test_db_problems(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeClient(items())
    assert await main(["fetch"], make_client=factory(fake)) == 1
    assert "DATABASE_URL이 없어요" in capsys.readouterr().out
    # 닫힌 포트. 보안 프로그램이 응답 없이 버리는 PC에서도 2초 안에 끝나게 시간 제한을 준다
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:x@127.0.0.1:1/none?connect_timeout=2")
    assert await main(["fetch"], make_client=factory(fake)) == 1
    assert "DB에 연결하지 못했어요" in capsys.readouterr().out


async def test_db_error_while_saving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """넣다가 DB 오류(예: 학위과정 마이그레이션 전이라 요건 제약에 걸림)가 나면 이유 한 줄과 끝 코드 1."""

    class Closing:
        autocommit = True  # 실행 로그 연결은 autocommit이어야 한다(agent_log.using)

        async def close(self) -> None:
            return None

    async def connect(database_url: str) -> Closing:
        return Closing()

    async def collect(*args: Any, **kwargs: Any) -> None:
        raise psycopg.errors.CheckViolation(
            'new row for relation "requirements" violates check constraint\nDETAIL: 줄 내용'
        )

    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:x@127.0.0.1:1/none")
    monkeypatch.setattr(cli, "_connect", connect)
    monkeypatch.setattr(cli, "collect", collect)
    fake = FakeClient(items())
    assert await main(["fetch"], make_client=factory(fake)) == 1
    out = capsys.readouterr().out
    assert "DB에 넣다가 멈췄어요(CheckViolation: new row for relation" in out
    assert "DETAIL" not in out and fake.closed


async def _cleanup(scenario: str) -> None:
    """이 테스트가 만든 행만 지운다. CLI는 autocommit이라 되돌릴 수 없다."""
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
        await conn.execute("delete from agent_runs where scenario_code = %s", (scenario,))


async def _statuses(scenario: str) -> tuple[list[str], dict[str, str]]:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        runs = await (
            await conn.execute(
                "select status::text from agent_runs where scenario_code = %s order by started_at",
                (scenario,),
            )
        ).fetchall()
        found = await (
            await conn.execute(
                "select external_id, status::text from opportunities where external_id like %s",
                (PREFIX + "%",),
            )
        ).fetchall()
    return [row[0] for row in runs], {row[0].removeprefix(PREFIX): row[1] for row in found}


@pytest.mark.db
@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀")
async def test_fetch_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    scenario = f"youth-cli-test-{uuid.uuid4().hex[:8]}"
    argv = ["fetch", "--scenario", scenario]
    without_b = [entry for entry in items() if not entry["plcyNo"].endswith("-B")]
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        await skip_if_other_youth_policies(conn, PREFIX)
    try:
        assert await main(argv, make_client=factory(FakeClient(items()))) == 0
        out = capsys.readouterr().out
        assert "가져올 정책 3건: 새 공고 3 · 바뀐 공고 0 · 그대로 0" in out
        assert (
            "가져오지 않은 정책 2건: 마감 1 · 수도권 밖 1 → 이미 넣은 공고 중 만료 0 · 숨김 0"
            in out
        )
        assert re.search(r"^실행 기록: agent_runs [0-9a-f-]{36}$", out, re.MULTILINE)
        assert KEY not in out

        # 안산 정책이 목록에서 빠졌지만 목록을 빠짐없이 받지 못했다 → 숨기지 않는다
        assert await main(argv, make_client=factory(FakeClient(without_b, skipped=(9,)))) == 0
        out = capsys.readouterr().out
        assert "목록을 빠짐없이 받지 못해 목록에서 사라진 정책은 숨기지 않았어요" in out
        assert "가져올 정책 2건: 새 공고 0 · 바뀐 공고 0 · 그대로 2" in out
        assert "만료 0 · 숨김 0" in out

        # 한 번에 너무 많이 사라졌다(한도를 0으로) → 숨기지 않고 알린다. --hide-gone이면 숨긴다
        with monkeypatch.context() as patch:
            patch.setattr(importer, "GONE_MIN", 0)
            patch.setattr(importer, "GONE_SHARE", 0.0)
            assert await main(argv, make_client=factory(FakeClient(without_b))) == 0
            out = capsys.readouterr().out
            assert "목록에서 한 번에 1건이 사라져 숨기지 않았어요." in out and "숨김 0" in out
            assert "--hide-gone을 붙여 다시 돌려 주세요" in out
            forced = [*argv, "--hide-gone"]
            assert await main(forced, make_client=factory(FakeClient(without_b))) == 0
            assert "만료 0 · 숨김 1" in capsys.readouterr().out

        # 중간에 멈춤: 받은 정책은 넣고 끝 코드 1로 알린다. 실행 기록은 성공, 받기 결과에 멈춘 이유가 남는다
        stopped = FakeClient(
            without_b[:1], skipped=tuple(range(100, 200)), stopped="2~3쪽을 받지 못함"
        )
        assert await main(argv, make_client=factory(stopped)) == 1
        out = capsys.readouterr().out
        assert (
            "끝까지 받지 못했어요: 2~3쪽을 받지 못함. 받은 정책은 넣었어요."
            " 몇 분 뒤 다시 돌리면 나머지를 넣어요" in out
        )
        assert "가져올 정책 1건: 새 공고 0 · 바뀐 공고 0 · 그대로 1" in out
        runs, statuses = await _statuses(scenario)
        assert runs == ["succeeded"] * 5
        assert statuses == {"A": "active", "B": "hidden", "J": "active"}
    finally:
        await _cleanup(scenario)
