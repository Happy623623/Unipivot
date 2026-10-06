# API 뼈대 구현 — FastAPI 첫 흐름(로그인·동의·프로필)

> 📝 기준: API 명세 v0.2 + v0.3 변경분 4장 · ERD v0.7 + v0.8 · 2026-10-06
>
> 함께 보는 파일: `킥오프_1주차.md`(이 파일을 쓰는 순서) · `온보딩_구현.md`(이 API를 부르는 화면)

FastAPI 뼈대와 첫 흐름에 필요한 API 5개다. Supabase 로그인 토큰 검증, 명세 13장 에러 형식, 토큰 암호화, 에이전트 실행 로깅(`agent_runs`·`tool_calls`·`llm_calls`)이 들어 있고, 이후 엔드포인트는 이 위에 같은 방식으로 붙인다. 샌드박스에서 `ruff`와 테스트 13개(단위 11개, Postgres 16 통합 2개)를 통과시키고 `uvicorn`으로 띄워 확인했다.

## 들어 있는 API

| 엔드포인트 | 하는 일 | 화면 |
| --- | --- | --- |
| `POST /api/v1/auth/google/tokens` | 로그인 콜백이 넘긴 Google 토큰을 암호화해 저장, 프로필 행 생성. refresh token이 없으면 422 `GOOGLE_REFRESH_TOKEN_MISSING` | `/auth/callback` |
| `GET /api/v1/me` | 이름, 캘린더·LMS 연결, 프로필 채운 수(15개 기준), 동의 여부, 안 읽은 알림 수 | `AppFrame` |
| `POST /api/v1/me/consents` | 약관·개인정보 동의 시각과 버전 저장. 둘 중 하나라도 false면 422 | 온보딩 동의 |
| `GET /api/v1/me/profile` | 판정용 프로필 16개 항목 | 온보딩, 설정 |
| `PATCH /api/v1/me/profile` | 보낸 항목만 저장(null이면 지움), 동의 전이면 403 `CONSENT_REQUIRED`, 평점이 만점보다 크면 422 | 온보딩, 설정 |

`PATCH /me/profile`의 `rejudged`는 지금 `eligibility_results`의 현재 개수만 돌려준다. 판정 엔진(S1-3)이 붙으면 그 자리(`TODO(Dev1)`)에서 다시 계산한다.

## 구조

```text
api/
├── pyproject.toml · .python-version(3.12) · .env.example · .gitignore
├── app/
│   ├── main.py            앱, CORS, 라우터 등록, DB 풀 열고 닫기
│   ├── config.py          .env 설정
│   ├── errors.py          {"error": {code, message, details}} 형식
│   ├── auth.py            Supabase JWT 검증 → CurrentUserDep
│   ├── db.py              요청용 풀 + 로그용(autocommit) 풀
│   ├── crypto.py          토큰 암호화(Fernet)
│   ├── agent_log.py       agent_run → tool → record_llm
│   ├── schemas/me.py
│   ├── repositories/profiles.py
│   └── routers/{health,auth,me}.py
└── tests/                 단위(가짜 저장소) + DB 통합(DATABASE_URL 있을 때)
supabase/ci/auth_stub.sql  CI의 Postgres에 Supabase auth 스키마·역할 흉내
.github/workflows/ci.yml   web 빌드 + api 린트·테스트(마이그레이션 적용 후)
```

## 설계에서 정한 것

- **토큰 검증.** `SUPABASE_JWT_SECRET`이 있으면 HS256으로, 비어 있으면 `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` 공개키로 검증한다. 프로젝트가 어느 방식인지는 Supabase 대시보드의 JWT 설정에서 확인한다.
- **로그는 따로 커밋한다.** 요청 트랜잭션이 롤백돼도 실패한 실행이 `agent_runs`에 남아야 성공률을 잴 수 있다. 그래서 로그 전용 autocommit 풀을 두고, `agent_run`은 autocommit 연결이 아니면 거부한다.
- **비밀값은 두 번 막는다.** 저장 전에 암호화하고, `tool_calls`에 넣는 값은 키 이름(token·secret·password·api_key 등)으로 한 번 더 지운다.
- **DB 연결.** Supabase 세션 풀러 주소를 권장한다. 트랜잭션 풀러(6543)에서도 깨지지 않게 prepared statement를 껐다.
- **명세 13장에 추가할 에러 코드.** `DB_UNAVAILABLE`(503, DB 연결 실패), `INTERNAL_ERROR`(500, 처리하지 못한 예외).

## 코드

#### `api/pyproject.toml`

```toml
[project]
name = "unipivot-api"
version = "0.1.0"
description = "UNIPIVOT 학내 정보 에이전트 API"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic-settings>=2.4",
  "psycopg[binary,pool]>=3.2",
  "pyjwt[crypto]>=2.9",
  "cryptography>=43",
]

[dependency-groups]
dev = ["pytest>=8", "httpx>=0.27", "ruff>=0.6"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
markers = ["db: Postgres가 필요한 통합 테스트 (DATABASE_URL이 없으면 건너뜀)"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
ignore = ["E501"]  # 한국어 문구·주석 길이는 ruff format에 맡긴다
```

#### `api/.python-version`

```bash
3.12
```

#### `api/.env.example`

```bash
# Supabase DB 연결 문자열 (Project Settings > Database). 서버는 세션 풀러 주소를 권장
DATABASE_URL=postgresql://postgres.<project-ref>:<password>@<pooler-host>:5432/postgres
# Supabase 프로젝트 주소. 새 프로젝트는 이 주소의 JWKS 공개키로 토큰을 검증한다
SUPABASE_URL=https://<project-ref>.supabase.co
# 레거시 HS256 JWT 비밀키를 쓰는 프로젝트만 채운다. 비우면 JWKS로 검증
SUPABASE_JWT_SECRET=
# Google·LMS 토큰 암호화 키: uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOKEN_ENCRYPTION_KEY=
CORS_ORIGINS=["http://localhost:3000"]
```

#### `api/.gitignore`

```bash
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
.env
```

#### `api/app/config.py`

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """api/.env에서 읽는 설정. 각 값의 의미는 .env.example 참고."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    token_encryption_key: str = ""
    cors_origins: list[str] = ["http://localhost:3000"]
    api_prefix: str = "/api/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

#### `api/app/errors.py`

```python
"""API 명세 13장 에러 형식: {"error": {"code", "message", "details"}}."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """라우터·서비스에서 던지는 유일한 에러. code는 명세 13장 표에 있는 것만 쓴다."""

    def __init__(
        self, status: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


_HTTP_CODES = {
    401: ("UNAUTHORIZED", "로그인이 필요해요."),
    403: ("FORBIDDEN", "권한이 없어요."),
    404: ("NOT_FOUND", "대상을 찾을 수 없어요."),
    405: ("METHOD_NOT_ALLOWED", "지원하지 않는 요청이에요."),
    429: ("RATE_LIMITED", "요청이 많아요. 잠시 후 다시 시도해 주세요."),
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status, content=error_body(exc.code, exc.message, exc.details)
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = {
            ".".join(str(part) for part in error["loc"][1:]) or "body": error["msg"]
            for error in exc.errors()
        }
        body = error_body("VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": fields})
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_CODES.get(exc.status_code, ("HTTP_ERROR", str(exc.detail)))
        return JSONResponse(status_code=exc.status_code, content=error_body(code, message))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("처리하지 못한 예외", exc_info=exc)
        body = error_body("INTERNAL_ERROR", "잠시 후 다시 시도해 주세요.")
        return JSONResponse(status_code=500, content=body)
```

#### `api/app/auth.py`

```python
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header

from app.config import Settings, get_settings
from app.errors import ApiError


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None
    name: str | None


@lru_cache
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url, cache_keys=True)


def decode_supabase_token(token: str, settings: Settings) -> dict[str, Any]:
    """Supabase access token을 검증한다.

    레거시 프로젝트는 HS256 비밀키(SUPABASE_JWT_SECRET)로,
    새 프로젝트는 {SUPABASE_URL}/auth/v1/.well-known/jwks.json 공개키로 검증한다.
    """
    try:
        if settings.supabase_jwt_secret:
            return jwt.decode(
                token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated"
            )
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        key = _jwks_client(jwks_url).get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["ES256", "RS256"], audience="authenticated")
    except jwt.PyJWTError as exc:
        raise ApiError(401, "UNAUTHORIZED", "로그인이 만료됐어요. 다시 로그인해 주세요.") from exc


async def get_current_user(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "UNAUTHORIZED", "로그인이 필요해요.")
    claims = decode_supabase_token(authorization.split(" ", 1)[1], settings)
    if not claims.get("sub"):
        raise ApiError(401, "UNAUTHORIZED", "로그인 정보가 올바르지 않아요.")
    metadata = claims.get("user_metadata") or {}
    return CurrentUser(
        id=claims["sub"],
        email=claims.get("email"),
        name=metadata.get("full_name") or metadata.get("name"),
    )


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
```

#### `api/app/db.py`

```python
from collections.abc import AsyncIterator

from fastapi import Request
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.errors import ApiError


def create_pools(database_url: str) -> tuple[AsyncConnectionPool, AsyncConnectionPool]:
    """요청용(트랜잭션) 풀과 실행 로그용(autocommit) 풀을 만든다.

    로그를 따로 커밋해야 실패한 에이전트 실행도 agent_runs에 남는다.
    prepare_threshold=None: Supabase 트랜잭션 풀러(6543)에서도 동작하게 prepared statement를 끈다.
    """
    common = {"row_factory": dict_row, "prepare_threshold": None}
    pool = AsyncConnectionPool(database_url, min_size=1, max_size=10, open=False, kwargs=common)
    log_pool = AsyncConnectionPool(
        database_url, min_size=1, max_size=5, open=False, kwargs={**common, "autocommit": True}
    )
    return pool, log_pool


async def _connection(pool: AsyncConnectionPool | None) -> AsyncIterator[AsyncConnection]:
    if pool is None:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    async with pool.connection() as conn:  # 블록이 끝나면 커밋, 예외면 롤백
        yield conn


async def get_conn(request: Request) -> AsyncIterator[AsyncConnection]:
    async for conn in _connection(request.app.state.pool):
        yield conn


async def get_log_conn(request: Request) -> AsyncIterator[AsyncConnection]:
    """agent_run()에 넘기는 autocommit 연결."""
    async for conn in _connection(request.app.state.log_pool):
        yield conn
```

#### `api/app/crypto.py`

```python
"""Google·LMS 토큰 암호화 (PRD 7장 개인정보, API 1장 비밀값 규칙)."""

from cryptography.fernet import Fernet


def _fernet(key: str) -> Fernet:
    if not key:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY가 비어 있어요. api/.env.example을 보고 키를 만드세요."
        )
    return Fernet(key)


def encrypt(value: str, key: str) -> str:
    return _fernet(key).encrypt(value.encode()).decode()


def decrypt(value: str, key: str) -> str:
    return _fernet(key).decrypt(value.encode()).decode()
```

#### `api/app/agent_log.py`

```python
"""에이전트 실행 로깅: agent_runs → tool_calls → llm_calls (ERD 로깅 도메인, PRD 8장 지표의 원천).

async with agent_run(log_conn, trigger="poster_upload", user_id=user.id) as run:
    async with run.tool("extract_from_image", {"file_id": file_id}) as call:
        result = await llm.extract(...)
        await run.record_llm(provider="anthropic", model="...", input_tokens=...,
                             output_tokens=..., cost_usd=..., latency_ms=..., tool_call=call)
        call.output = {"title": result.title}
"""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

SECRET_HINTS = ("token", "secret", "password", "authorization", "api_key")


def scrub(value: Any) -> Any:
    """키 이름에 비밀값 냄새가 나면 지운다. tool_calls에 토큰이 남지 않게 하는 마지막 안전장치."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(hint in key.lower() for hint in SECRET_HINTS) else scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


@dataclass
class ToolCall:
    id: str
    output: Any = None


@dataclass
class AgentRun:
    conn: AsyncConnection
    id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    _seq: int = 0

    @asynccontextmanager
    async def tool(self, name: str, input: dict[str, Any] | None = None) -> AsyncIterator[ToolCall]:
        self._seq += 1
        started = time.perf_counter()
        cursor = await self.conn.execute(
            "insert into tool_calls (run_id, seq, tool_name, input, status)"
            " values (%s, %s, %s, %s, 'running') returning id",
            (self.id, self._seq, name, Jsonb(scrub(input or {}))),
        )
        call = ToolCall(id=str((await cursor.fetchone())["id"]))
        status = "failed"
        try:
            yield call
            status = "succeeded"
        finally:
            output = Jsonb(scrub(call.output)) if call.output is not None else None
            await self.conn.execute(
                "update tool_calls set output = %s, status = %s, latency_ms = %s where id = %s",
                (output, status, _elapsed_ms(started), call.id),
            )

    async def record_llm(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        latency_ms: int,
        tool_call: ToolCall | None = None,
    ) -> None:
        await self.conn.execute(
            "insert into llm_calls (run_id, tool_call_id, provider, model, input_tokens,"
            " output_tokens, cost_usd, latency_ms) values (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                self.id,
                tool_call.id if tool_call else None,
                provider,
                model,
                input_tokens,
                output_tokens,
                cost_usd,
                latency_ms,
            ),
        )
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_usd += cost_usd


@asynccontextmanager
async def agent_run(
    conn: AsyncConnection,
    *,
    trigger: str,
    user_id: str | None = None,
    scenario_code: str | None = None,
) -> AsyncIterator[AgentRun]:
    """실행 하나를 기록한다. conn은 autocommit이어야 실패한 실행도 남는다(db.get_log_conn)."""
    if not conn.autocommit:
        raise RuntimeError("agent_run에는 autocommit 연결(get_log_conn)을 넘겨야 해요.")
    started = time.perf_counter()
    cursor = await conn.execute(
        "insert into agent_runs (user_id, trigger_type, scenario_code) values (%s, %s, %s)"
        " returning id",
        (user_id, trigger, scenario_code),
    )
    run = AgentRun(conn=conn, id=str((await cursor.fetchone())["id"]))
    try:
        yield run
    except Exception as exc:
        await _finish(run, started, "failed", repr(exc)[:500])
        raise
    await _finish(run, started, "succeeded", None)


async def _finish(run: AgentRun, started: float, status: str, error: str | None) -> None:
    await run.conn.execute(
        "update agent_runs set status = %s, finished_at = now(), latency_ms = %s,"
        " input_tokens = %s, output_tokens = %s, cost_usd = %s, error_message = %s where id = %s",
        (
            status,
            _elapsed_ms(started),
            run.input_tokens,
            run.output_tokens,
            run.cost_usd,
            error,
            run.id,
        ),
    )
```

#### `api/app/schemas/me.py`

```python
"""GET /me, /me/profile, /me/consents, /auth/google/tokens 모델 (API 명세 4장, web types/api.ts와 같은 이름)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EnrollmentStatus = Literal["enrolled", "on_leave", "deferred_graduation", "graduated"]
WelfareStatus = Literal["none", "near_poverty", "basic_livelihood"]


class ProfileFields(BaseModel):
    department: str | None = None
    grade: int | None = Field(None, ge=1, le=6)
    enrollment_status: EnrollmentStatus | None = None
    semesters_completed: int | None = Field(None, ge=0, le=16)
    credits_total: float | None = Field(None, ge=0, le=200)
    credits_last_semester: float | None = Field(None, ge=0, le=30)
    gpa_total: float | None = Field(None, ge=0, le=4.5)
    gpa_last_semester: float | None = Field(None, ge=0, le=4.5)  # 직전학기 장학용 평점(F 포함)
    gpa_scale: float | None = Field(None, ge=4.0, le=4.5)
    birth_date: date | None = None
    military_service_months: int | None = Field(None, ge=0, le=60)
    region_sido: str | None = None
    region_sigungu: str | None = None
    income_bracket: int | None = Field(None, ge=0, le=10)  # 학자금 지원구간, 0 = 기초·차상위
    median_income_pct: int | None = Field(None, ge=0, le=500)  # 기준 중위소득 % (가구)
    welfare_status: WelfareStatus | None = None


class Profile(ProfileFields):
    gpa_scale: float = Field(4.5, ge=4.0, le=4.5)


class ProfilePatch(ProfileFields):
    """보낸 필드만 바꾸고, null을 보내면 지운다."""

    model_config = ConfigDict(extra="forbid")


PROFILE_FIELDS: tuple[str, ...] = tuple(Profile.model_fields)
COMPLETION_FIELDS: tuple[str, ...] = tuple(f for f in PROFILE_FIELDS if f != "gpa_scale")


def gpa_errors(profile: Profile) -> dict[str, str]:
    return {
        name: f"평점 만점({profile.gpa_scale})보다 클 수 없어요."
        for name in ("gpa_total", "gpa_last_semester")
        if (value := getattr(profile, name)) is not None and value > profile.gpa_scale
    }


class LmsSummary(BaseModel):
    status: Literal["active", "error", "disconnected"]
    last_synced_at: datetime | None


class ProfileCompletion(BaseModel):
    filled: int
    total: int


class Me(BaseModel):
    user_id: str
    display_name: str
    hyin_verified: bool
    calendar_connected: bool
    lms: LmsSummary | None
    profile_completion: ProfileCompletion
    consented: bool
    unread_notifications: int


class Rejudged(BaseModel):
    changed: int
    eligible: int
    undetermined: int
    ineligible: int


class ProfileUpdateResponse(BaseModel):
    profile: Profile
    rejudged: Rejudged


class ConsentRequest(BaseModel):
    consent_version: str = Field(min_length=1, max_length=32)
    agree_terms: bool
    agree_privacy: bool


class ConsentResult(BaseModel):
    terms_agreed_at: datetime
    privacy_agreed_at: datetime
    consent_version: str


class GoogleTokensRequest(BaseModel):
    provider_token: str = Field(min_length=1)
    provider_refresh_token: str | None = None


class GoogleTokensResponse(BaseModel):
    calendar_connected: bool
    scope: str
```

#### `api/app/repositories/profiles.py`

```python
"""profiles·oauth_tokens·lms_connections·notifications·eligibility_results 조회 (ERD v0.7+v0.8)."""

from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection, sql

from app.db import get_conn
from app.schemas.me import (
    COMPLETION_FIELDS,
    PROFILE_FIELDS,
    ConsentResult,
    LmsSummary,
    Me,
    Profile,
    ProfileCompletion,
)

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class ProfileRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def ensure(self, user_id: str, display_name: str | None) -> None:
        """로그인 직후 profiles 행을 만든다. 이미 있으면 비어 있는 이름만 채운다."""
        await self.conn.execute(
            "insert into profiles (id, display_name) values (%s, %s) on conflict (id)"
            " do update set display_name = coalesce(profiles.display_name, excluded.display_name)",
            (user_id, display_name),
        )

    async def get_me(self, user_id: str) -> Me | None:
        filled = sql.SQL(" + ").join(
            sql.SQL("(p.{} is not null)::int").format(sql.Identifier(f)) for f in COMPLETION_FIELDS
        )
        query = sql.SQL(
            """
            select p.id, p.display_name, p.hyin_verified_at,
                   p.terms_agreed_at is not null and p.privacy_agreed_at is not null as consented,
                   {filled} as filled,
                   exists(select 1 from oauth_tokens t where t.user_id = p.id
                          and t.provider = 'google' and t.refresh_token is not null)
                       as calendar_connected,
                   l.status as lms_status, l.last_synced_at as lms_last_synced_at,
                   (select count(*) from notifications n where n.user_id = p.id
                    and n.read_at is null and n.scheduled_at <= now()) as unread
            from profiles p left join lms_connections l on l.user_id = p.id
            where p.id = %s
            """
        ).format(filled=filled)
        row = await (await self.conn.execute(query, (user_id,))).fetchone()
        if row is None:
            return None
        lms = None
        if row["lms_status"]:
            lms = LmsSummary(status=row["lms_status"], last_synced_at=row["lms_last_synced_at"])
        return Me(
            user_id=str(row["id"]),
            display_name=row["display_name"] or "학생",
            hyin_verified=row["hyin_verified_at"] is not None,
            calendar_connected=row["calendar_connected"],
            lms=lms,
            profile_completion=ProfileCompletion(
                filled=row["filled"], total=len(COMPLETION_FIELDS)
            ),
            consented=row["consented"],
            unread_notifications=row["unread"],
        )

    async def get_profile(self, user_id: str) -> Profile | None:
        query = sql.SQL("select {} from profiles where id = %s").format(
            sql.SQL(", ").join(map(sql.Identifier, PROFILE_FIELDS))
        )
        row = await (await self.conn.execute(query, (user_id,))).fetchone()
        return Profile.model_validate(row) if row else None

    async def update_profile(self, user_id: str, values: dict[str, Any]) -> None:
        if not values:
            return
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(key), sql.Placeholder(key)) for key in values
        )
        query = sql.SQL("update profiles set {}, profile_updated_at = now() where id = %(id)s")
        await self.conn.execute(query.format(assignments), {**values, "id": user_id})

    async def has_consented(self, user_id: str) -> bool:
        row = await (
            await self.conn.execute(
                "select terms_agreed_at is not null and privacy_agreed_at is not null as ok"
                " from profiles where id = %s",
                (user_id,),
            )
        ).fetchone()
        return bool(row and row["ok"])

    async def save_consent(self, user_id: str, version: str) -> ConsentResult:
        row = await (
            await self.conn.execute(
                "update profiles set terms_agreed_at = now(), privacy_agreed_at = now(),"
                " consent_version = %s where id = %s"
                " returning terms_agreed_at, privacy_agreed_at, consent_version",
                (version, user_id),
            )
        ).fetchone()
        return ConsentResult.model_validate(row)

    async def save_google_tokens(self, user_id: str, access_token: str, refresh_token: str) -> None:
        """토큰은 암호화된 값만 받는다. access token 만료는 Google 기본값(1시간)보다 조금 짧게 잡는다."""
        await self.conn.execute(
            "insert into oauth_tokens (user_id, provider, access_token, refresh_token, scope,"
            " expires_at) values (%s, 'google', %s, %s, %s, now() + interval '55 minutes')"
            " on conflict (user_id, provider) do update set access_token = excluded.access_token,"
            " refresh_token = excluded.refresh_token, scope = excluded.scope,"
            " expires_at = excluded.expires_at",
            (user_id, access_token, refresh_token, CALENDAR_SCOPE),
        )

    async def eligibility_counts(self, user_id: str) -> dict[str, int]:
        rows = await (
            await self.conn.execute(
                "select status, count(*) as n from eligibility_results"
                " where user_id = %s group by status",
                (user_id,),
            )
        ).fetchall()
        counts = {"eligible": 0, "undetermined": 0, "ineligible": 0}
        counts.update({row["status"]: row["n"] for row in rows})
        return counts


def get_profile_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> ProfileRepository:
    return ProfileRepository(conn)


ProfileRepoDep = Annotated[ProfileRepository, Depends(get_profile_repo)]
```

#### `api/app/routers/health.py`

```python
from fastapi import APIRouter

router = APIRouter(tags=["상태"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

#### `api/app/routers/auth.py`

```python
from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth import CurrentUserDep
from app.config import Settings, get_settings
from app.crypto import encrypt
from app.errors import ApiError
from app.repositories.profiles import ProfileRepoDep
from app.schemas.me import GoogleTokensRequest, GoogleTokensResponse

router = APIRouter(prefix="/auth", tags=["인증"])


@router.post("/google/tokens", response_model=GoogleTokensResponse)
async def save_google_tokens(
    body: GoogleTokensRequest,
    user: CurrentUserDep,
    repo: ProfileRepoDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> GoogleTokensResponse:
    """로그인 콜백이 한 번 보낸다(API 4장, F-01). 프로필 행도 여기서 만든다."""
    if not body.provider_refresh_token:
        raise ApiError(
            422,
            "GOOGLE_REFRESH_TOKEN_MISSING",
            "캘린더 권한을 다시 받아야 해요. 로그인 동의 화면에서 캘린더 접근을 허용해 주세요.",
        )
    await repo.ensure(user.id, user.name)
    await repo.save_google_tokens(
        user.id,
        encrypt(body.provider_token, settings.token_encryption_key),
        encrypt(body.provider_refresh_token, settings.token_encryption_key),
    )
    return GoogleTokensResponse(calendar_connected=True, scope="calendar.events")
```

#### `api/app/routers/me.py`

```python
from fastapi import APIRouter
from pydantic import ValidationError

from app.auth import CurrentUserDep
from app.errors import ApiError
from app.repositories.profiles import ProfileRepoDep
from app.schemas.me import (
    ConsentRequest,
    ConsentResult,
    Me,
    Profile,
    ProfilePatch,
    ProfileUpdateResponse,
    Rejudged,
    gpa_errors,
)

router = APIRouter(prefix="/me", tags=["내 정보"])


@router.get("", response_model=Me)
async def read_me(user: CurrentUserDep, repo: ProfileRepoDep) -> Me:
    me = await repo.get_me(user.id)
    if me is None:  # 로그인 콜백보다 먼저 들어온 경우에도 행을 만든다
        await repo.ensure(user.id, user.name)
        me = await repo.get_me(user.id)
    assert me is not None
    return me


@router.get("/profile", response_model=Profile)
async def read_profile(user: CurrentUserDep, repo: ProfileRepoDep) -> Profile:
    return await repo.get_profile(user.id) or Profile()


@router.patch("/profile", response_model=ProfileUpdateResponse)
async def update_profile(
    patch: ProfilePatch, user: CurrentUserDep, repo: ProfileRepoDep
) -> ProfileUpdateResponse:
    if not await repo.has_consented(user.id):
        raise ApiError(403, "CONSENT_REQUIRED", "약관에 동의한 뒤에 프로필을 저장할 수 있어요.")
    current = await repo.get_profile(user.id) or Profile()
    changes = patch.model_dump(exclude_unset=True)
    if changes.get("gpa_scale", 4.5) is None:
        changes["gpa_scale"] = 4.5  # 만점은 지울 수 없다
    try:
        merged = Profile.model_validate({**current.model_dump(), **changes})
    except ValidationError as exc:
        fields = {".".join(map(str, e["loc"])): e["msg"] for e in exc.errors()}
        raise ApiError(
            422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": fields}
        ) from exc
    if errors := gpa_errors(merged):
        raise ApiError(422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": errors})
    await repo.update_profile(user.id, {key: getattr(merged, key) for key in changes})
    # TODO(Dev1): 판정 엔진이 붙으면 여기서 이 사용자의 eligibility_results를 다시 계산하고 changed를 채운다
    counts = await repo.eligibility_counts(user.id)
    return ProfileUpdateResponse(profile=merged, rejudged=Rejudged(changed=0, **counts))


@router.post("/consents", response_model=ConsentResult)
async def save_consents(
    body: ConsentRequest, user: CurrentUserDep, repo: ProfileRepoDep
) -> ConsentResult:
    if not (body.agree_terms and body.agree_privacy):
        missing = {
            key: "필수 항목이에요."
            for key, agreed in (
                ("agree_terms", body.agree_terms),
                ("agree_privacy", body.agree_privacy),
            )
            if not agreed
        }
        raise ApiError(
            422, "VALIDATION_FAILED", "필수 약관에 모두 동의해 주세요.", {"fields": missing}
        )
    await repo.ensure(user.id, user.name)
    return await repo.save_consent(user.id, body.consent_version)
```

#### `api/app/main.py`

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db import create_pools
from app.errors import register_error_handlers
from app.routers import auth, health, me


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    app.state.pool = app.state.log_pool = None
    if settings.database_url:
        app.state.pool, app.state.log_pool = create_pools(settings.database_url)
        await app.state.pool.open()
        await app.state.log_pool.open()
    yield
    for pool in (app.state.pool, app.state.log_pool):
        if pool is not None:
            await pool.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="UNIPIVOT API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(health.router)
    for router in (auth.router, me.router):
        app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()
```

### 테스트

#### `api/tests/conftest.py`

```python
import time
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.repositories.profiles import get_profile_repo
from tests.fakes import FakeProfileRepository

JWT_SECRET = "unit-test-jwt-secret-not-used-anywhere-else"
USER_ID = "00000000-0000-4000-8000-000000000001"


def make_token(
    sub: str = USER_ID, secret: str = JWT_SECRET, expires_in: int = 3600, **claims: Any
) -> str:
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + expires_in,
        "email": "student@example.com",
        "user_metadata": {"full_name": "테스트 학생"},
        **claims,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="",  # 단위 테스트는 DB 없이 돈다
        supabase_jwt_secret=JWT_SECRET,
        token_encryption_key=Fernet.generate_key().decode(),
    )


@pytest.fixture
def repo() -> FakeProfileRepository:
    return FakeProfileRepository()


@pytest.fixture
def client(settings: Settings, repo: FakeProfileRepository) -> Iterator[TestClient]:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_profile_repo] = lambda: repo
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}
```

#### `api/tests/fakes.py`

```python
"""단위 테스트용 가짜 저장소. 실제 ProfileRepository와 메서드 이름·반환 타입을 맞춘다."""

from datetime import UTC, datetime
from typing import Any

from app.schemas.me import COMPLETION_FIELDS, ConsentResult, Me, Profile, ProfileCompletion


class FakeProfileRepository:
    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, dict[str, str]] = {}

    async def ensure(self, user_id: str, display_name: str | None) -> None:
        row = self.profiles.setdefault(
            user_id, {"display_name": None, "consented_at": None, "profile": Profile()}
        )
        row["display_name"] = row["display_name"] or display_name

    async def get_me(self, user_id: str) -> Me | None:
        row = self.profiles.get(user_id)
        if row is None:
            return None
        filled = sum(getattr(row["profile"], f) is not None for f in COMPLETION_FIELDS)
        return Me(
            user_id=user_id,
            display_name=row["display_name"] or "학생",
            hyin_verified=False,
            calendar_connected=user_id in self.tokens,
            lms=None,
            profile_completion=ProfileCompletion(filled=filled, total=len(COMPLETION_FIELDS)),
            consented=row["consented_at"] is not None,
            unread_notifications=0,
        )

    async def get_profile(self, user_id: str) -> Profile | None:
        row = self.profiles.get(user_id)
        return row["profile"] if row else None

    async def update_profile(self, user_id: str, values: dict[str, Any]) -> None:
        row = self.profiles[user_id]
        row["profile"] = row["profile"].model_copy(update=values)

    async def has_consented(self, user_id: str) -> bool:
        row = self.profiles.get(user_id)
        return bool(row and row["consented_at"])

    async def save_consent(self, user_id: str, version: str) -> ConsentResult:
        now = datetime.now(UTC)
        self.profiles[user_id]["consented_at"] = now
        return ConsentResult(terms_agreed_at=now, privacy_agreed_at=now, consent_version=version)

    async def save_google_tokens(self, user_id: str, access_token: str, refresh_token: str) -> None:
        self.tokens[user_id] = {"access_token": access_token, "refresh_token": refresh_token}

    async def eligibility_counts(self, user_id: str) -> dict[str, int]:
        return {"eligible": 0, "undetermined": 0, "ineligible": 0}
```

#### `api/tests/test_api.py`

```python
from fastapi.testclient import TestClient

from app.config import Settings
from app.crypto import decrypt
from tests.conftest import USER_ID, make_token
from tests.fakes import FakeProfileRepository

CONSENT = {"consent_version": "2026-10-05", "agree_terms": True, "agree_privacy": True}


def consent(client: TestClient, auth: dict[str, str]) -> None:
    assert client.post("/api/v1/me/consents", json=CONSENT, headers=auth).status_code == 200


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_me_requires_login(client: TestClient) -> None:
    res = client.get("/api/v1/me")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_expired_or_forged_token_is_rejected(client: TestClient) -> None:
    for token in (
        make_token(expires_in=-10),
        make_token(secret="forged-secret-forged-secret-forged"),
    ):
        res = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_first_me_creates_profile(client: TestClient, auth: dict[str, str]) -> None:
    body = client.get("/api/v1/me", headers=auth).json()
    assert body["user_id"] == USER_ID
    assert body["display_name"] == "테스트 학생"
    assert body["consented"] is False
    assert body["profile_completion"] == {"filled": 0, "total": 15}


def test_profile_update_needs_consent(client: TestClient, auth: dict[str, str]) -> None:
    client.get("/api/v1/me", headers=auth)
    res = client.patch("/api/v1/me/profile", json={"grade": 3}, headers=auth)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "CONSENT_REQUIRED"


def test_consent_requires_both(client: TestClient, auth: dict[str, str]) -> None:
    res = client.post("/api/v1/me/consents", json={**CONSENT, "agree_privacy": False}, headers=auth)
    assert res.status_code == 422
    assert res.json()["error"]["details"]["fields"] == {"agree_privacy": "필수 항목이에요."}


def test_onboarding_flow(client: TestClient, auth: dict[str, str]) -> None:
    res = client.post("/api/v1/me/consents", json=CONSENT, headers=auth)
    assert res.status_code == 200
    assert res.json()["consent_version"] == "2026-10-05"

    patch = {"department": "인공지능학과", "grade": 3, "gpa_last_semester": 3.9}
    res = client.patch("/api/v1/me/profile", json=patch, headers=auth)
    assert res.status_code == 200
    assert res.json()["profile"]["grade"] == 3
    assert res.json()["rejudged"] == {
        "changed": 0,
        "eligible": 0,
        "undetermined": 0,
        "ineligible": 0,
    }

    me = client.get("/api/v1/me", headers=auth).json()
    assert me["consented"] is True
    assert me["profile_completion"]["filled"] == 3

    client.patch("/api/v1/me/profile", json={"grade": None}, headers=auth)  # null이면 지운다
    assert client.get("/api/v1/me/profile", headers=auth).json()["grade"] is None


def test_profile_validation(client: TestClient, auth: dict[str, str]) -> None:
    consent(client, auth)
    res = client.patch("/api/v1/me/profile", json={"grade": 9}, headers=auth)
    assert res.status_code == 422
    assert "grade" in res.json()["error"]["details"]["fields"]

    res = client.patch(
        "/api/v1/me/profile", json={"gpa_scale": 4.3, "gpa_total": 4.4}, headers=auth
    )
    assert res.status_code == 422
    assert res.json()["error"]["details"]["fields"] == {
        "gpa_total": "평점 만점(4.3)보다 클 수 없어요."
    }

    res = client.patch("/api/v1/me/profile", json={"nickname": "x"}, headers=auth)
    assert res.status_code == 422  # 명세에 없는 필드는 받지 않는다


def test_google_tokens(
    client: TestClient, auth: dict[str, str], repo: FakeProfileRepository, settings: Settings
) -> None:
    res = client.post("/api/v1/auth/google/tokens", json={"provider_token": "ya29.a"}, headers=auth)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "GOOGLE_REFRESH_TOKEN_MISSING"

    body = {"provider_token": "ya29.a", "provider_refresh_token": "1//refresh"}
    res = client.post("/api/v1/auth/google/tokens", json=body, headers=auth)
    assert res.status_code == 200
    assert res.json() == {"calendar_connected": True, "scope": "calendar.events"}

    stored = repo.tokens[USER_ID]["refresh_token"]
    assert stored != "1//refresh"  # 암호화해서 저장한다
    assert decrypt(stored, settings.token_encryption_key) == "1//refresh"
    assert client.get("/api/v1/me", headers=auth).json()["calendar_connected"] is True
```

#### `api/tests/test_agent_log.py`

```python
import pytest

from app.agent_log import agent_run, scrub


def test_scrub_hides_secrets() -> None:
    value = {
        "access_token": "a",
        "nested": {"API_KEY": "b", "items": [{"password": "c", "page": 2}]},
        "query": "장학금",
    }
    assert scrub(value) == {
        "access_token": "[REDACTED]",
        "nested": {"API_KEY": "[REDACTED]", "items": [{"password": "[REDACTED]", "page": 2}]},
        "query": "장학금",
    }


@pytest.mark.anyio
async def test_agent_run_requires_autocommit_connection() -> None:
    class TransactionConnection:
        autocommit = False

    with pytest.raises(RuntimeError):
        async with agent_run(TransactionConnection(), trigger="eval"):  # type: ignore[arg-type]
            pass
```

#### `api/tests/test_db_integration.py`

```python
"""DATABASE_URL이 있을 때만 도는 통합 테스트. CI는 Postgres 컨테이너에 마이그레이션을 적용해서 돌린다.

실제 Supabase DB를 DATABASE_URL로 주고 돌리지 않는다(auth.users에 테스트 행을 넣는다).
"""

import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from app.agent_log import agent_run
from app.repositories.profiles import ProfileRepository

DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


async def connect(autocommit: bool = False) -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(
        DATABASE_URL, row_factory=dict_row, autocommit=autocommit, prepare_threshold=None
    )


async def test_profile_repository_roundtrip() -> None:
    conn = await connect()
    try:
        user_id = str(uuid.uuid4())
        await conn.execute("insert into auth.users (id) values (%s)", (user_id,))
        repo = ProfileRepository(conn)
        await repo.ensure(user_id, "테스트 학생")

        me = await repo.get_me(user_id)
        assert me is not None
        assert (me.consented, me.calendar_connected, me.profile_completion.filled) == (
            False,
            False,
            0,
        )

        assert (await repo.save_consent(user_id, "2026-10-05")).consent_version == "2026-10-05"
        changes = {"department": "인공지능학과", "gpa_last_semester": 3.9, "welfare_status": "none"}
        await repo.update_profile(user_id, changes)
        profile = await repo.get_profile(user_id)
        assert profile is not None
        assert (profile.department, profile.gpa_last_semester, profile.gpa_scale) == (
            "인공지능학과",
            3.9,
            4.5,
        )

        await repo.save_google_tokens(user_id, "encrypted-access", "encrypted-refresh")
        me = await repo.get_me(user_id)
        assert me is not None
        assert me.consented and me.calendar_connected
        assert (me.profile_completion.filled, me.unread_notifications) == (3, 0)
        assert await repo.eligibility_counts(user_id) == {
            "eligible": 0,
            "undetermined": 0,
            "ineligible": 0,
        }
    finally:
        await conn.rollback()
        await conn.close()


async def test_agent_run_logs_success_and_failure() -> None:
    conn = await connect(autocommit=True)
    run_ids: list[str] = []
    try:
        async with agent_run(conn, trigger="eval", scenario_code="TEST-LOG") as run:
            run_ids.append(run.id)
            async with run.tool(
                "extract_requirements", {"notice": "n1", "access_token": "x"}
            ) as call:
                await run.record_llm(
                    provider="anthropic",
                    model="test-model",
                    input_tokens=1200,
                    output_tokens=300,
                    cost_usd=0.0012,
                    latency_ms=850,
                    tool_call=call,
                )
                call.output = {"requirements": 3}

        with pytest.raises(ValueError):
            async with agent_run(conn, trigger="eval", scenario_code="TEST-LOG") as failed:
                run_ids.append(failed.id)
                async with failed.tool("crawl_board", {"board": "scholarship"}):
                    raise ValueError("게시판 응답 없음")

        runs = {
            str(row["id"]): row
            for row in await (
                await conn.execute(
                    "select * from agent_runs where id = any(%s::uuid[])", (run_ids,)
                )
            ).fetchall()
        }
        ok, bad = runs[run_ids[0]], runs[run_ids[1]]
        assert (ok["status"], ok["input_tokens"], ok["output_tokens"]) == ("succeeded", 1200, 300)
        assert float(ok["cost_usd"]) == pytest.approx(0.0012)
        assert ok["latency_ms"] is not None and ok["finished_at"] is not None
        assert bad["status"] == "failed" and "게시판 응답 없음" in bad["error_message"]

        tools = await (
            await conn.execute(
                "select run_id, status, input, output from tool_calls"
                " where run_id = any(%s::uuid[]) order by seq",
                (run_ids,),
            )
        ).fetchall()
        by_run = {str(row["run_id"]): row for row in tools}
        assert by_run[run_ids[0]]["status"] == "succeeded"
        assert by_run[run_ids[0]]["input"]["access_token"] == "[REDACTED]"
        assert by_run[run_ids[0]]["output"] == {"requirements": 3}
        assert by_run[run_ids[1]]["status"] == "failed"

        llm = await (
            await conn.execute(
                "select count(*) as n from llm_calls where run_id = %s", (run_ids[0],)
            )
        ).fetchone()
        assert llm is not None and llm["n"] == 1
    finally:
        await conn.execute("delete from agent_runs where id = any(%s::uuid[])", (run_ids,))
        await conn.close()
```

### CI

#### `supabase/ci/auth_stub.sql`

```sql
-- CI 전용: Supabase에 원래 있는 auth 스키마와 역할을 흉내 낸다. 실제 Supabase 프로젝트에는 적용하지 않는다.
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key, email text);
create or replace function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;
do $$ begin create role anon; exception when duplicate_object then null; end $$;
do $$ begin create role authenticated; exception when duplicate_object then null; end $$;
do $$ begin create role service_role; exception when duplicate_object then null; end $$;
```

#### `.github/workflows/ci.yml`

```yaml
name: ci

on:
  pull_request:
  push:
    branches: [main]

jobs:
  web:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci
      - run: npm run typecheck
      - run: npm run build
        env:
          NEXT_PUBLIC_USE_MOCKS: "true"

  api:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: postgres
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 5s --health-timeout 5s --health-retries 10
    env:
      DATABASE_URL: postgresql://postgres:postgres@localhost:5432/postgres
    steps:
      - uses: actions/checkout@v4
      - name: 마이그레이션 적용 (auth 흉내 → ERD v0.7 → v0.8 순서)
        run: |
          psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/ci/auth_stub.sql
          for f in supabase/migrations/*.sql; do
            psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
          done
      - uses: astral-sh/setup-uv@v6
      - run: uv sync
        working-directory: api
      - run: uv run ruff check . && uv run ruff format --check .
        working-directory: api
      - run: uv run pytest
        working-directory: api
```

## 실행

```bash
cd api
uv sync                                   # .python-version에 맞춰 Python 3.12와 의존성 설치
cp .env.example .env                      # 값 채우기 (토큰 암호화 키 만드는 명령은 파일 안에 있음)
uv run uvicorn app.main:app --reload      # http://localhost:8000/docs
uv run pytest                             # DATABASE_URL이 없으면 DB 테스트 2개는 건너뜀
```

## 확인한 것

| 점검 | 결과 |
| --- | --- |
| `ruff check`, `ruff format --check` | 통과 |
| 단위 테스트 11개 (DB 없이) | 통과: 헬스, 인증 없음·만료·위조 토큰 401, 첫 `/me`에서 프로필 생성, 동의 전 수정 403, 동의 필수 항목, 온보딩 흐름(동의 → 저장 → 채운 수 3 → null로 지우기), 범위·만점·명세 밖 필드 422, Google 토큰 암호화 저장 |
| DB 통합 테스트 2개 (Postgres 16) | 통과: 저장소 왕복(enum·numeric 변환 포함), 실행 로깅 성공·실패(토큰 지움, 토큰 수·비용 합산, 실패 사유 기록) |
| `uvicorn` 실행 | `/health` 응답, OpenAPI 경로 5개, 인증 없는 `/api/v1/me` → 13장 형식 401 |

샌드박스 버전: FastAPI 0.142, Pydantic 2.13, psycopg 3.3, PyJWT 2.15. 통합 테스트 스키마는 ERD v0.7·v0.8의 해당 테이블 컬럼을 그대로 옮겨 만들었다. 실제 레포 CI는 `supabase/migrations`를 그대로 적용해서 돌리므로, 컬럼이 다르면 거기서 잡힌다.
