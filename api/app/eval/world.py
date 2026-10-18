"""시나리오가 쓰는 세계: 고정 시계와 녹화 응답을 끼운 앱 한 대, 사용자·공고 만들기, 끝나면 치우기.

공고·사용자를 만드는 일은 API에 없어서 DB에 직접 쓴다(`app/youth/importer.py`처럼 이 폴더도 SQL을
안고 있다). 세계를 만든 뒤 시나리오가 확인하는 길은 실제 엔드포인트다. 화면으로는 볼 수 없는 것
(캘린더 행 수 등)만 `rows()`로 DB에서 센다.

시계는 주입한다(`app.clock.current_time`을 고정값으로 바꾼다). 마감일·생일은 그 고정 시각에서 센
날짜로 만들기 때문에, 며칠 뒤에 다시 돌려도 판정과 날짜는 같다. 비용은 그렇지 않다 — 단가는 **돌린
날**로 고른다(`app/agent_log.py`의 record_llm). 그래서 결과에 priced_on을 적어 둔다.

치울 때 사용자와 공고는 지우고 **실행 기록(agent_runs)은 남긴다**. 성공률·응답시간·비용과 판정
혼동행렬이 그 행에서 나온다(명세 12장 `GET /internal/metrics`). 사용자를 지우면 agent_runs.user_id는
null이 되고(ERD: on delete set null) 행은 scenario_code와 함께 남는다. 온통청년 `sources` 행은
실제 수집도 쓰는 한 줄이라 그대로 둔다(`ensure_source`가 있으면 다시 만들지 않는다).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from typing import Annotated, Any
from uuid import uuid4

import httpx
import jwt
import psycopg
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from app.agent_log import AgentRun, LogConnect
from app.background import TaskRunner, get_runner
from app.calendar.service import CalendarService, get_calendar_service
from app.clock import current_time
from app.config import Settings, get_settings
from app.db import create_pools, get_conn, get_log_connect
from app.eligibility import KST
from app.eval.fakes import (
    RecordedCalendar,
    RecordedLearningX,
    RecordedLlm,
    RecordedStorage,
    Reply,
)
from app.eval.models import Check, CheckFailed, plain
from app.llm.deps import get_llm
from app.lms.announce import AnnouncementService
from app.lms.service import LmsService, get_lms_service
from app.lms.sync import LmsSyncService, extraction_agent, get_lms_sync_service
from app.main import create_app
from app.repositories.calendar import CalendarRepository
from app.repositories.lms import LmsRepository, get_lms_repo
from app.repositories.profiles import ProfileRepository
from app.schemas.me import INCOME_FIELDS
from app.schemas.metrics import CHECK_TOOL, ELIGIBILITY_CHECK
from app.schemas.opportunities import ELIGIBILITY_STATUSES
from app.uploads.storage import get_storage
from app.youth.convert import PolicyRecord, Skip, convert
from app.youth.importer import ensure_source, save_policy
from app.youth.regions import region_table

logger = logging.getLogger(__name__)

# 명세 12장 `POST /internal/eval/run`의 요청 예와 같은 시각. --now로 바꾼다
DEFAULT_NOW = datetime(2026, 10, 12, 9, 0, tzinfo=KST)
CONSENT_VERSION = "2026-10-07"
RUN_TIMEOUT_SECONDS = 60.0  # 202로 시작한 실행을 기다리는 상한(명세 2장과 같다)
RUN_POLL_SECONDS = 0.05  # 화면(1.5초)보다 자주 묻는다. 시나리오를 빨리 끝내려고
FEED_PAGE = 50  # 피드 한 쪽 상한(명세 5장 limit)
FEED_PAGES = 40  # 피드를 넘겨 볼 쪽 수 상한. 더 많으면 공고가 너무 많은 DB다
# 실제 Supabase DB에서는 돌리지 않는다(사용자·공고를 만들고 지운다)
MANAGED_HOSTS = ("supabase.co", "supabase.com", "supabase.in")


@dataclass
class Clock:
    """시나리오가 보는 현재 시각. 앱의 `current_time`이 이 값을 읽어서, 시나리오가 옮길 수 있다.

    S14처럼 "예약한 뒤 그날이 되면 보낸다"를 보려면 한 시나리오 안에서 시각이 두 번 필요하다.
    옮겨도 주입 시계라서 며칠 뒤에 다시 돌려도 같은 결과가 나온다.
    """

    now: datetime


@dataclass(frozen=True)
class Rule:
    """공고 요건 한 줄. 같은 clause_no끼리 "또는", 다른 번호끼리 "그리고"다(판정엔진_규칙 2장)."""

    clause_no: int
    field: str
    operator: str
    value: Any
    basis: str | None = None
    is_ambiguous: bool = False


def managed_database(database_url: str) -> str | None:
    """실제 Supabase DB 주소면 고칠 말, 아니면 None. 주소·비밀번호는 담지 않는다."""
    if any(host in database_url for host in MANAGED_HOSTS):
        return (
            "DATABASE_URL이 Supabase 주소예요(값은 보여 주지 않음). 시나리오는 사용자·공고를 만들고"
            " 지우니 시험용 DB에서만 돌려요"
        )
    return None


def eval_settings(database_url: str) -> Settings:
    """시나리오용 설정. 로그인 비밀키와 토큰 암호화 키는 이 실행 안에서만 쓸 값을 새로 만든다.

    실제 Supabase 비밀키를 쓰지 않는다. 시나리오가 자기 토큰을 만들어 자기 사용자로 부른다.
    """
    return Settings(
        database_url=database_url,
        supabase_url="",
        supabase_jwt_secret=secrets.token_urlsafe(32),
        token_encryption_key=Fernet.generate_key().decode(),
        internal_api_key=secrets.token_urlsafe(32),
    )


async def connect(database_url: str) -> psycopg.AsyncConnection:
    """세계를 만들고 치우는 연결. autocommit이라 시나리오가 터져도 앞 단계가 남는다."""
    return await psycopg.AsyncConnection.connect(
        database_url, row_factory=dict_row, autocommit=True, prepare_threshold=None
    )


class EvalWorld:
    """시나리오 하나가 사는 동안의 세계. 시나리오는 이것만 받는다."""

    def __init__(
        self,
        *,
        conn: psycopg.AsyncConnection,
        app: FastAPI,
        settings: Settings,
        clock: Clock,
        run: AgentRun,
        scenario_code: str,
        llm: RecordedLlm,
        storage: RecordedStorage,
        calendar: RecordedCalendar,
        lms: RecordedLearningX,
    ) -> None:
        self.conn = conn  # autocommit. 세계를 만들고 치운다
        self.app = app
        self.settings = settings
        self.clock = clock
        self.started = clock.now  # 시나리오를 시작한 시각(옮겨도 그대로)
        self.run = run
        self.scenario_code = scenario_code
        self.llm, self.storage, self.calendar = llm, storage, calendar
        self.lms = lms  # 녹화한 LearningX. 시나리오가 과제·마감·제출을 고친다(S16–S18)
        self.users: list[str] = []
        self.opportunities: list[str] = []
        self.checks: list[Check] = []
        self.api_ms = 0.0  # 엔드포인트가 쓴 시간 합(응답시간 지표)
        self._clients: list[httpx.AsyncClient] = []
        self._departments: list[str] = []  # 이 시나리오가 새로 넣은 학과(치울 때 지운다)
        self.extra_runs: list[str] = []  # 세계를 만들며 생긴 실행(공고에 붙이는 수집 실행)
        self._extraction_run: str | None = None

    @property
    def now(self) -> datetime:
        """시나리오가 보는 지금. travel로 옮긴 값이다."""
        return self.clock.now

    @property
    def today(self) -> date:
        return self.clock.now.astimezone(KST).date()

    def travel(self, **ahead: float) -> datetime:
        """시계를 앞으로 옮긴다(`world.travel(days=3)`). 앱도 옮긴 시각을 본다."""
        self.clock.now += timedelta(**ahead)
        return self.clock.now

    # ── 녹화 응답 ────────────────────────────────────────────────────────────

    def records(self, *replies: Reply) -> None:
        """이 시나리오에서 모델이 차례로 낼 답. 남거나 모자라면 시나리오가 실패한다."""
        self.llm.replies.extend(replies)

    # ── 부르기 ──────────────────────────────────────────────────────────────

    def path(self, suffix: str) -> str:
        return f"{self.settings.api_prefix}{suffix}"

    def client(self, user_id: str) -> httpx.AsyncClient:
        """그 사용자로 로그인한 클라이언트. 응답마다 걸린 시간을 더한다. 끝나면 함께 닫는다."""
        return self._client({"Authorization": f"Bearer {self._token(user_id)}"})

    def internal(self) -> httpx.AsyncClient:
        """서비스 키를 붙인 클라이언트(`/internal/*`). 스케줄러가 부르는 작업을 시나리오가 부른다."""
        return self._client({"X-Internal-Key": self.settings.internal_api_key})

    def _client(self, headers: dict[str, str]) -> httpx.AsyncClient:
        http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://eval",
            headers=headers,
            timeout=RUN_TIMEOUT_SECONDS,
            event_hooks={"response": [self._measure]},
        )
        self._clients.append(http)
        return http

    async def _measure(self, response: httpx.Response) -> None:
        await response.aread()  # elapsed는 응답을 다 읽은 뒤에 정해진다
        self.api_ms += response.elapsed.total_seconds() * 1000

    def _token(self, user_id: str) -> str:
        """로그인 토큰. 유효 기간은 **이 컴퓨터의 지금**으로 잰다 — 주입한 시계는 업무 규칙에만 쓴다.
        고정 시각으로 만들면 과거 날짜를 넣었을 때 토큰이 만료로 거절된다."""
        issued = int(time.time())
        claims = {
            "sub": user_id,
            "aud": "authenticated",
            "role": "authenticated",
            "exp": issued + 3600,
            "iat": issued - 60,
            "email": f"{user_id[:8]}@eval.invalid",
            "user_metadata": {"full_name": "시나리오 학생"},
        }
        return jwt.encode(claims, self.settings.supabase_jwt_secret, algorithm="HS256")

    async def wait_run(
        self, client: httpx.AsyncClient, run_id: str, *, timeout: float = RUN_TIMEOUT_SECONDS
    ) -> dict[str, Any]:
        """202로 시작한 실행이 끝날 때까지 `GET /runs/{id}`를 다시 묻는다(화면이 하는 그대로)."""
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            response = await client.get(self.path(f"/runs/{run_id}"))
            response.raise_for_status()
            body: dict[str, Any] = response.json()
            if body["status"] != "running":
                return body
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError(f"실행이 {timeout}초 안에 끝나지 않았어요: run {run_id}")
            await asyncio.sleep(RUN_POLL_SECONDS)

    async def feed_card(
        self, client: httpx.AsyncClient, opportunity_id: str, **params: Any
    ) -> dict[str, Any] | None:
        """피드에서 그 공고 카드를 찾는다. 없으면 None.

        쪽을 끝까지 넘긴다. 한 쪽은 최대 50건이라(명세 5장) DB에 다른 공고가 많으면 1쪽에 없을 수 있고,
        그때 "피드에 없다"고 보면 멀쩡한 코드가 실패로 보인다.
        """
        cursor: str | None = None
        for _ in range(FEED_PAGES):
            query = {**params, "limit": FEED_PAGE, **({"cursor": cursor} if cursor else {})}
            response = await client.get(self.path("/opportunities"), params=query)
            response.raise_for_status()
            page = response.json()
            for item in page["items"]:
                if item["id"] == opportunity_id:
                    return dict(item)
            cursor = page["next_cursor"]
            if not cursor:
                return None
        raise AssertionError(f"피드가 {FEED_PAGES}쪽을 넘어요. 공고가 너무 많은 DB예요")

    # ── 확인 ────────────────────────────────────────────────────────────────

    async def check(
        self, what: str, *, expected: Any, actual: Any, kind: str | None = None
    ) -> None:
        """기대와 실제를 맞춰 보고 실행 기록에 한 줄 남긴다. 다르면 시나리오를 여기서 멈춘다.

        남는 곳이 tool_calls.input·output이므로 **프로필 값과 토큰은 넘기지 않는다**(ERD의 컬럼 설명).
        `scrub`은 키 이름으로만 지우니 값은 걸러 주지 못한다. 나이·평점처럼 프로필에서
        온 값은 그대로 쓰지 말고 맞는지(bool)나 항목 이름으로 바꿔서 확인한다.

        kind는 집계가 골라 읽을 종류다. 판정 확인은 check를 바로 부르지 말고 judged를 쓴다.
        """
        found = Check(what, plain(expected), plain(actual), kind)
        self.checks.append(found)
        recorded = {"what": found.what, "expected": found.expected}
        async with self.run.tool(CHECK_TOOL, recorded | ({"kind": kind} if kind else {})) as call:
            call.output = {"actual": found.actual, "ok": found.ok}
            if not found.ok:
                raise CheckFailed(found)

    async def judged(self, what: str, *, expected: str, actual: Any) -> None:
        """판정 확인. 판정 혼동행렬(PRD 8장)이 이 줄만 읽는다.

        expected는 정답 상태, actual은 엔진이 낸 상태다. 둘 다 판정 상태 3가지여야 한다 — 화면 라벨
        (display_status, 4가지)을 넣으면 3×3 행렬에 담기지 않는다.
        """
        if expected not in ELIGIBILITY_STATUSES:
            raise AssertionError(
                f"판정 확인의 기대값은 {ELIGIBILITY_STATUSES} 중 하나다: {expected!r}"
            )
        await self.check(what, expected=expected, actual=actual, kind=ELIGIBILITY_CHECK)

    # ── 세계 만들기 ──────────────────────────────────────────────────────────

    async def extraction_run(self) -> str:
        """공고에 붙일 추출 실행. 요건 추출을 한 척하는 수집 실행 한 줄이다.

        시나리오 실행(trigger eval)을 그대로 쓰면 공고 상세의 처리 과정(F-42)에 확인(check) 줄이
        단계로 보인다. 그래서 따로 만든다. 도구 기록이 없으니 처리 과정은 비어 있다.
        """
        if self._extraction_run is None:
            row = await (
                await self.conn.execute(
                    "insert into agent_runs (trigger_type, status, scenario_code, finished_at,"
                    " latency_ms) values ('batch_crawl', 'succeeded', %s, now(), 0)"
                    " returning id::text as id",
                    (self.scenario_code,),
                )
            ).fetchone()
            assert row is not None
            self._extraction_run = row["id"]
            self.extra_runs.append(row["id"])
        return self._extraction_run

    async def department(
        self,
        name: str = "인공지능학과",
        college: str = "소프트웨어융합대학",
        field_group: str = "공학계열",
    ) -> str:
        """학과 하나. 이미 있으면(마이그레이션 seed) 그대로 쓰고, 새로 넣었으면 치울 때 지운다."""
        row = await (
            await self.conn.execute(
                "insert into departments (name, college, field_group) values (%s, %s, %s)"
                " on conflict do nothing returning name",
                (name, college, field_group),
            )
        ).fetchone()
        if row is not None:
            self._departments.append(name)
        return name

    async def user(self, **profile: Any) -> str:
        """사용자 하나. 프로필에 소득·수급 항목이 있으면 선택 동의도 함께 남긴다."""
        user_id = str(uuid4())
        await self.conn.execute("insert into auth.users (id) values (%s)", (user_id,))
        self.users.append(user_id)
        repo = ProfileRepository(self.conn)
        await repo.ensure(user_id, "시나리오 학생")
        income = any(name in profile for name in INCOME_FIELDS)
        await repo.save_consent(user_id, CONSENT_VERSION, agree_income_info=income)
        if profile:
            await repo.update_profile(user_id, profile)
        return user_id

    async def add(
        self,
        title: str,
        *,
        days: float | None,
        requirements: Sequence[Rule] = (),
        documents: Sequence[str] = (),
        **columns: Any,
    ) -> str:
        """공고 하나. days는 고정 시각(now)에서 센 마감일이고, None이면 상시다."""
        values: dict[str, Any] = {
            "source_type": "school_notice",
            "category": "scholarship",
            "title": title,
            "organizer": "학생지원팀",
            "easy_summary": f"{title} 쉬운 설명",
            "deadline_at": None if days is None else self.now + timedelta(days=days),
            "extraction_run_id": await self.extraction_run(),
            **columns,
        }
        insert = sql.SQL(
            "insert into opportunities ({names}) values ({marks}) returning id"
        ).format(
            names=sql.SQL(", ").join(sql.Identifier(name) for name in values),
            marks=sql.SQL(", ").join(sql.Placeholder() * len(values)),
        )
        row = await (await self.conn.execute(insert, tuple(values.values()))).fetchone()
        assert row is not None
        opportunity_id = str(row["id"])
        self.opportunities.append(opportunity_id)
        for index, rule in enumerate(requirements):
            await self.conn.execute(
                # 추출 저장(save_extraction)처럼 넣은 순서를 created_at에 남긴다
                "insert into requirements (opportunity_id, clause_no, field, operator, value,"
                " basis, is_ambiguous, evidence_text, created_at)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s, now() + %s * interval '1 microsecond')",
                (
                    opportunity_id,
                    rule.clause_no,
                    rule.field,
                    rule.operator,
                    Jsonb(rule.value),
                    rule.basis,
                    rule.is_ambiguous,
                    f"{title} 근거",
                    index,
                ),
            )
        for name in documents:
            await self.conn.execute(
                "insert into opportunity_documents (opportunity_id, name) values (%s, %s)",
                (opportunity_id, name),
            )
        return opportunity_id

    async def youth(self, policy: Mapping[str, Any]) -> str:
        """온통청년 정책 하나를 실제 변환 코드로 공고로 만든다(F-11, LLM 없음).

        importer.collect가 아니라 convert + save_policy를 부른다. collect는 목록에서 사라진 정책을
        숨기는 일(retire)까지 하므로, 시나리오가 만들지 않은 공고까지 건드린다. 요건은 같은 코드로
        만들어진다.

        save_policy는 (source_id, external_id)로 덮어쓰기(upsert)다. 그래서 **같은 번호의 공고가
        이미 있으면 손대지 않고 멈춘다** — 실제로 수집해 둔 정책을 고치고 치울 때 지우면 안 된다.
        """
        source_id = await ensure_source(self.conn)
        record = convert(policy, self.today, region_table())
        if isinstance(record, Skip):
            raise AssertionError(f"녹화한 정책이 걸러졌어요: {record.reason}")
        assert isinstance(record, PolicyRecord)
        found = await self.conn.execute(
            "select id from opportunities where source_id = %s and external_id = %s",
            (source_id, record.external_id),
        )
        if await found.fetchone() is not None:
            raise AssertionError(
                f"이미 수집해 둔 정책({record.external_id})이에요. 시나리오 전용 번호를 쓰세요"
            )
        await save_policy(self.conn, source_id, record, await self.extraction_run())
        row = await (
            await self.conn.execute(
                "select id::text as id from opportunities where source_id = %s and external_id = %s",
                (source_id, record.external_id),
            )
        ).fetchone()
        assert row is not None
        self.opportunities.append(row["id"])
        return str(row["id"])

    async def rows(self, query: str, *params: Any) -> list[dict[str, Any]]:
        """확인용 조회. 시나리오가 화면으로 볼 수 없는 것(캘린더 행 수 등)을 셀 때만 쓴다."""
        return await (await self.conn.execute(query, params)).fetchall()

    # ── 치우기 ──────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """클라이언트를 닫는다. 하나가 실패해도 나머지를 닫는다."""
        for http in self._clients:
            try:
                await http.aclose()
            except Exception:
                logger.exception("클라이언트를 닫지 못했어요")
        self._clients.clear()

    async def cleanup(self) -> None:
        """사용자와 공고를 지운다. 실행 기록은 지표의 원천이라 남긴다(모듈 머리말).

        한 줄이 실패해도 나머지를 지우고, 오류를 올리지 않는다. 치우다 터지면 시나리오가 왜 실패했는지
        (CheckFailed)가 그 오류에 덮인다.
        """
        await self.close()
        statements: list[tuple[str, Sequence[Any]]] = []
        if self.opportunities:
            statements.append(
                ("delete from opportunities where id = any(%s::uuid[])", (self.opportunities,))
            )
        if self.users:
            # 시나리오가 API로 만든 포스터 공고. 번호를 모르니 올린 사람으로 찾는다
            statements.append(
                ("delete from opportunities where uploaded_by = any(%s::uuid[])", (self.users,))
            )
            statements.append(("delete from auth.users where id = any(%s::uuid[])", (self.users,)))
        if self._departments:
            statements.append(
                ("delete from departments where name = any(%s)", (self._departments,))
            )
        # 주차 항목·공지는 **과목 공통 표**라 사용자를 지워도 남는다(ERD 3-2). 남겨 두면 다음
        # 실행에서 "처음 본 자료"가 0건이 되어 재현되지 않는다. **녹화가 쓰는 과목 번호**(시나리오
        # 전용 번호대)이고 아무도 듣지 않는 것만 지운다 — 실제 학생의 과목 자료는 건드리지 않는다
        canvas_ids = [row["id"] for row in self.lms.rows]
        # 기회성 공지로 만든 공고(F-53)는 올린 사람이 없어 위의 두 줄로는 지워지지 않는다. 남겨 두면
        # 다음 실행에서 "새 공고" 알림이 공고 수만큼 늘어 S23이 재현되지 않는다
        statements.append(
            (
                "delete from opportunities where source_type = 'lms_announcement'"
                " and visible_canvas_course_id = any(%s::bigint[])",
                (canvas_ids,),
            )
        )
        for table in ("lms_module_items", "lms_announcements"):
            statements.append(
                (
                    f"delete from {table} t where t.canvas_course_id = any(%s::bigint[])"
                    " and not exists (select 1 from lms_courses c"
                    "   where c.canvas_course_id = t.canvas_course_id)",
                    (canvas_ids,),
                )
            )
        for query, params in statements:
            try:
                await self.conn.execute(query, params)
            except Exception:
                logger.exception("치우지 못한 것이 있어요: %s", query[:60])


ScenarioFn = Callable[[EvalWorld], Awaitable[None]]


@dataclass(frozen=True)
class Scenario:
    """시나리오 하나(PRD 8장 표). run은 세계를 받아 기대 결과까지 가는 함수다."""

    code: str
    title: str
    priority: str
    run: ScenarioFn


async def open_app(
    settings: Settings,
    *,
    clock: Clock,
    llm: RecordedLlm,
    storage: RecordedStorage,
    calendar: RecordedCalendar,
    lms: RecordedLearningX,
) -> tuple[FastAPI, AsyncConnectionPool, AsyncConnectionPool]:
    """실제 풀을 달고 시계·모델·파일 저장소·Google 캘린더·LearningX만 녹화한 것으로 바꾼 앱.

    lifespan은 돌지 않는다(ASGITransport는 부르지 않는다). 그래서 풀을 여기서 열고 부른 쪽이 닫는다.
    여는 중에 터지면 먼저 연 풀을 닫고 올린다.
    """
    app = create_app(settings)
    pool, log_pool = create_pools(settings.database_url)
    try:
        await pool.open()
        await log_pool.open()
    except Exception:
        await pool.close()
        await log_pool.close()
        raise
    app.state.pool, app.state.log_pool = pool, log_pool

    async def recorded_calendar(
        conn: Annotated[psycopg.AsyncConnection, Depends(get_conn)],
    ) -> CalendarService:
        """토큰 저장소는 실제 DB를 쓰고 Google만 녹화한 것으로 바꾼다."""
        return CalendarService(CalendarRepository(conn), calendar, settings.token_encryption_key)

    def recorded_lms(
        repo: Annotated[LmsRepository, Depends(get_lms_repo)],
        log_connect: Annotated[LogConnect, Depends(get_log_connect)],
    ) -> LmsService:
        """토큰 저장·과목 저장은 실제 DB를 쓰고 LearningX만 녹화한 것으로 바꾼다."""
        return LmsService(
            repo, lms, encryption_key=settings.token_encryption_key, log_connect=log_connect
        )

    def recorded_sync(runner: Annotated[TaskRunner, Depends(get_runner)]) -> LmsSyncService:
        """동기화도 LearningX와 Google만 녹화한 것으로 바꾼다(저장·로그는 실제 DB).

        공지 분류(F-53)도 끼운다 — 모델만 녹화한 것이고 저장소·학과 목록은 실제 DB다.
        """
        return LmsSyncService(
            transaction=pool.connection,
            log_connection=log_pool.connection,
            client=lms,
            calendar_client=calendar,
            encryption_key=settings.token_encryption_key,
            runner=runner,
            announcer=AnnouncementService(
                transaction=pool.connection,
                llm=llm,
                classify_model=settings.classify_model,
                agent_for=partial(extraction_agent, llm, settings),
                lms_base=settings.lms_api_base,
            ),
        )

    app.dependency_overrides.update(
        {
            get_settings: lambda: settings,
            get_lms_service: recorded_lms,
            get_lms_sync_service: recorded_sync,
            current_time: lambda: clock.now,  # 주입 시계(PRD 8장). travel로 옮긴다
            get_llm: lambda: llm,
            get_storage: lambda: storage,
            get_calendar_service: recorded_calendar,
        }
    )
    return app, pool, log_pool
