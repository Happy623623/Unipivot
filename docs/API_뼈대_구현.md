# API 뼈대 구현 — FastAPI 첫 흐름(로그인·동의·프로필·학과·사용 기록)

> 📝 기준: API 명세 v0.4 1·4·13장 · ERD v0.9 · PRD v0.9 7장 · 2026-10-07
>
> 함께 보는 파일: `킥오프_1주차.md`(이 파일을 쓰는 순서) · `온보딩_구현.md`(이 API를 부르는 화면) · `판정엔진_구현.md`(S1-3, 이 뼈대 위에 얹는다)

10/6판을 v0.9에 맞춰 다시 만든 판이다. 첫 흐름에 필요한 API 8개와 FastAPI 뼈대가 들어 있다. 뼈대에는 Supabase 로그인 토큰 검증, 명세 13장 에러 형식, 키를 바꿀 수 있는 토큰 암호화, 로그의 토큰 가리기, 에이전트 실행 로깅(`agent_runs`·`tool_calls`·`llm_calls`)과 단가표 비용 계산이 있다. 이후 엔드포인트도 같은 방식으로 붙인다. 샌드박스에서 `ruff`와 테스트 25개(단위 22개, Postgres 16 통합 3개)를 통과시켰다. 통합 테스트는 레포의 마이그레이션 3개와 스키마 점검을 CI와 같은 순서로 적용한 DB에서 돌렸고, `uvicorn`으로 띄워 경로와 로그도 확인했다.

## 10/6판에서 바뀐 것

| 무엇 | 바뀐 내용 | 근거 |
| --- | --- | --- |
| 소득·수급 선택 동의 | `POST /me/consents`에 `agree_income_info`, `PATCH /me/consents` 신설(철회하면 소득 3항목도 지움). 동의 전에 소득 값을 저장하면 403 | API 4장, ERD `profiles_income_consent_chk` |
| 403 `CONSENT_REQUIRED` | `details.consent`로 빠진 동의를 알려 준다(`terms_privacy` · `income_info`) | API 4장 |
| 프로필 | `is_international` 추가, 학과는 학과 목록의 이름만, 시도는 정식 이름 17개만, 채운 수는 16개 기준 | API 4장, ERD `departments` |
| 새 API | `GET /meta/departments`, `POST /events` | API 4장, PRD 8장 지표 |
| `POST /auth/google/tokens` | 로그인 때가 아니라 캘린더를 처음 연결할 때 부른다. 동작은 그대로이고 설명·오류 문구만 바꿨다 | API 4장 증분 승인 |
| 토큰 암호화 | `TOKEN_ENCRYPTION_KEY`에 키를 쉼표로 여러 개 두고 교체할 수 있다(MultiFernet) | PRD 7장 |
| 로그 | Authorization 헤더와 토큰 모양 문자열을 가린다 | API 1장 비밀값 |
| 실행 로깅 | 비용을 단가표로 계산하고, `tool_calls`에서 프로필 항목 이름의 값도 지운다 | PRD 7장, API 1장 |
| 테스트·CI | 통합 테스트를 v0.9 스키마에 맞췄고(학과 행, 소득 동의 흐름), CI에 스키마 점검 단계를 넣었다 | ERD v0.9 "레포에 넣는 법" |

킥오프 Day 2 요청문 뒤에 덧붙였던 두 가지(CI 스키마 점검 단계, `test_profile_repository_roundtrip` 수정)는 이 판에 이미 들어 있다. 요청문은 아래 그대로 쓰면 된다.

## 레포에 넣는 법

```text
docs/API_뼈대_구현.md에 있는 파일을 적힌 경로(api/, supabase/ci/, .github/workflows/)에 그대로 만들어줘.
내용은 바꾸지 마. 그다음 api에서 uv sync, uv run ruff check ., uv run ruff format --check ., uv run pytest를 돌려서 결과를 알려줘.
```

- [ ] `22 passed, 3 skipped`(DB 테스트는 `DATABASE_URL` 환경변수가 없으면 건너뜀). 경고가 1개 나오면 Starlette가 테스트 클라이언트에 httpx2를 권하는 안내라 무시해도 된다
- [ ] `uv run uvicorn app.main:app --reload` → `http://localhost:8000/docs`에 API 9개(`/health` 포함)가 보인다
- [ ] PR을 열면 CI api 작업이 마이그레이션 적용 → 스키마 점검 → 테스트 25개까지 통과한다
- [ ] 판정 엔진(S1-3)은 이 PR을 합친 뒤 `docs/판정엔진_구현.md`대로 넣는다. 함께 돌리면 `107 passed, 3 skipped`

CI의 web 작업이 `web/`을 빌드하므로 프론트 이식 PR을 먼저 합친다. `supabase/ci/schema_checks.sql`은 ERD v0.9 때 레포에 넣었다. 없으면 `docs/ERD_v0.9.md`의 "CI 스키마 점검"에서 가져온다.

## 들어 있는 API

| 엔드포인트 | 하는 일 | 화면 |
| --- | --- | --- |
| `POST /api/v1/auth/google/tokens` | 캘린더 연결 콜백이 넘긴 Google 토큰을 암호화해 저장하고 프로필 행을 만든다. refresh token이 없으면 422 `GOOGLE_REFRESH_TOKEN_MISSING` | `/auth/callback?connect=calendar` |
| `GET /api/v1/me` | 이름, 캘린더·LMS 연결, 프로필 채운 수(16개 기준), 필수·소득 동의 여부, 안 읽은 알림 수. 첫 호출 때 프로필 행을 만든다 | `AppFrame`, 온보딩 |
| `POST /api/v1/me/consents` | 약관·개인정보(필수)와 소득·수급(선택) 동의 저장. 필수 둘 중 하나라도 false면 422 | 온보딩 동의 |
| `PATCH /api/v1/me/consents` | 소득·수급 선택 동의와 철회. 필수 동의 전이면 403 | 온보딩 소득 단계, 설정 |
| `GET /api/v1/me/profile` | 판정용 프로필 17개 항목 | 온보딩, 설정 |
| `PATCH /api/v1/me/profile` | 보낸 항목만 저장(null이면 지움). 필수 동의 전 403, 소득 동의 전 소득 값 403, 범위·만점·학과·시도 422 | 온보딩, 설정 |
| `GET /api/v1/meta/departments` | 사용 중인 학과 목록(정렬 순서, 이름 순) | 온보딩, 설정 |
| `POST /api/v1/events` | 화면에서만 알 수 있는 사용 이벤트 3가지를 기록하고 204. 앱 열기는 KST 하루 1건 | `AppFrame`(`app_open`), 정보 입력창, LMS 연결 가이드 |

`PATCH /me/profile`의 `rejudged`는 지금 `eligibility_results`의 현재 개수만 돌려준다. 판정 엔진(S1-3)을 넣은 뒤 재판정(S1-5)에서 `TODO(Dev1)` 자리에 계산을 붙인다. 소득 동의를 철회한 뒤의 재판정도 같은 자리에 있다.

## 구조

```text
api/
├── pyproject.toml · .python-version(3.12) · .env.example · .gitignore
├── app/
│   ├── main.py            앱, CORS, 로그 가리기, 라우터 등록, DB 풀 열고 닫기
│   ├── config.py          .env 설정
│   ├── errors.py          {"error": {code, message, details}} 형식
│   ├── auth.py            Supabase JWT 검증 → CurrentUserDep
│   ├── db.py              요청용 풀 + 로그용(autocommit) 풀
│   ├── crypto.py          토큰 암호화(MultiFernet, 키 교체)
│   ├── logging_redact.py  로그에서 토큰 가리기
│   ├── pricing.py         모델 단가표, 비용 계산
│   ├── agent_log.py       agent_run → tool → record_llm
│   ├── schemas/{me,meta}.py
│   ├── repositories/{profiles,meta}.py
│   └── routers/{health,auth,me,meta,events}.py
└── tests/                 단위(가짜 저장소) + DB 통합(DATABASE_URL 있을 때)
supabase/ci/auth_stub.sql       CI의 Postgres에 Supabase auth 스키마·역할 흉내
supabase/ci/schema_checks.sql   RLS·FK 인덱스 점검 (ERD v0.9 때 넣음)
.github/workflows/ci.yml        web 빌드 + api 린트·테스트(마이그레이션·스키마 점검 뒤)
```

판정 엔진은 `app/eligibility/`로 이 구조에 더해진다(`판정엔진_구현.md`).

## 설계에서 정한 것

- **토큰 검증.** `SUPABASE_JWT_SECRET`이 있으면 HS256으로, 비어 있으면 `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` 공개키로 검증한다. 프로젝트가 어느 방식인지는 Supabase 대시보드의 JWT 설정에서 확인한다.
- **로그는 따로 커밋한다.** 요청 트랜잭션이 롤백돼도 실패한 실행이 `agent_runs`에 남아야 성공률을 잴 수 있다. 그래서 로그 전용 autocommit 풀을 두고, `agent_run`은 autocommit 연결이 아니면 거부한다.
- **비밀값은 세 번 막는다.** 저장 전에 암호화한다. 로그 레코드에서는 Authorization 헤더와 토큰 모양 문자열(JWT, Google·LearningX 토큰, Fernet 암호문, API 키)을 가린다. `tool_calls`에 넣는 값은 키 이름(token·secret·password·api_key, 프로필 항목 이름)으로 한 번 더 지운다.
- **로그 가리기는 인자만 바꾼다.** 서식 문자열은 그대로 두고 문자열 인자만 가려서, 인자를 직접 꺼내 쓰는 uvicorn 접근 로그도 깨지지 않는다. 서식 문자열에 authorization·token·secret 같은 말이 있으면 문자열 인자를 통째로 가린다. 예외 내용도 가린다.
- **키 교체.** `TOKEN_ENCRYPTION_KEY="새키,옛키"`로 두면 새 키로 암호화하고 두 키로 복호화한다. 저장된 토큰을 `crypto.rotate()`로 다시 암호화한 뒤 옛 키를 뺀다.
- **비용은 단가표로 계산한다.** `record_llm`에 `cost_usd`를 주지 않으면 `pricing.PRICES`에서 그날(KST) 적용되는 단가로 계산한다. 단가가 바뀌어도 개선 전후를 같은 기준으로 비교하기 위해서다. 표는 비어 있으므로 첫 LLM 호출을 붙이기 전에 쓰는 모델의 단가를 공식 가격표에서 채운다. 표에 없는 모델은 KeyError로 바로 드러난다.
- **동의는 두 겹이다.** 필수 동의 전에는 프로필 저장이 403(`terms_privacy`)이다. 소득 동의 전에는 소득 3항목에 값을 넣는 저장만 403(`income_info`)이고, 지우는 것(null)은 된다. DB 제약 `profiles_income_consent_chk`가 같은 규칙을 한 번 더 막는다. 철회하면 동의 시각과 소득 3항목을 UPDATE 한 번으로 지운다.
- **학과.** 학과 목록(`departments`의 사용 중인 행)에 있는 이름만 받는다. 화면은 프로필 전체를 보내므로, 목록에서 빠진(폐지·통합) 학과라도 저장된 값 그대로면 받는다.
- **사용 이벤트.** 프론트가 보내는 3가지(`app_open`, `profile_prompt_shown`, `lms_guide_opened`)만 받는다. 앱 열기는 KST 하루 1건이다(부분 유니크 + `on conflict do nothing`). 없는 공고 id는 비워서 저장하고, 프로필 행이 없으면 기록하지 않는다.
- **DB 연결.** Supabase 세션 풀러 주소를 권장한다. 트랜잭션 풀러(6543)에서도 깨지지 않게 prepared statement를 껐다.

## 코드

#### `api/pyproject.toml`

```toml
[project]
name = "unipivot-api"
version = "0.2.0"
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

```text
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
# 키를 바꿀 때는 "새키,옛키"처럼 쉼표로 이어 둔다. 새 키로 암호화하고 두 키 모두로 복호화한다
TOKEN_ENCRYPTION_KEY=
CORS_ORIGINS=["http://localhost:3000"]
```

#### `api/.gitignore`

```text
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
.env
```

#### `api/app/__init__.py`

```python
"""UNIPIVOT 학내 정보 에이전트 API."""
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
"""Google·LMS 토큰 암호화 (PRD 7장 토큰 보안).

TOKEN_ENCRYPTION_KEY에는 키를 쉼표로 여러 개 둘 수 있다. 첫 번째 키로 암호화하고 모든 키로 복호화한다.
키를 바꿀 때는 "새키,옛키"로 두고, 저장된 토큰을 rotate()로 다시 암호화한 뒤 옛 키를 뺀다.
"""

from cryptography.fernet import Fernet, MultiFernet


def _fernet(keys: str) -> MultiFernet:
    parts = [key.strip() for key in keys.split(",") if key.strip()]
    if not parts:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY가 비어 있어요. api/.env.example을 보고 키를 만드세요."
        )
    return MultiFernet([Fernet(key) for key in parts])


def encrypt(value: str, keys: str) -> str:
    return _fernet(keys).encrypt(value.encode()).decode()


def decrypt(value: str, keys: str) -> str:
    return _fernet(keys).decrypt(value.encode()).decode()


def rotate(value: str, keys: str) -> str:
    """옛 키로 암호화된 값을 첫 번째(새) 키로 다시 암호화한다."""
    return _fernet(keys).rotate(value.encode()).decode()
```

#### `api/app/logging_redact.py`

```python
"""로그에서 토큰을 가린다 (PRD 7장 토큰 보안). 앱을 만들 때 install_log_redaction()을 한 번 부른다.

가리는 것: Authorization 헤더, Bearer 토큰, token=… 값, JWT, Google access·refresh token,
LearningX(Canvas) 개인 액세스 토큰, Fernet 암호문, Anthropic·Google API 키.
"""

import logging
import re
from collections.abc import Mapping
from typing import Any

_REDACTED = "[REDACTED]"
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?(?:bearer\s+)?)[^\s'\",}]+"),
        r"\1" + _REDACTED,
    ),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1" + _REDACTED),
    (
        re.compile(r"(?i)((?:access_|refresh_|provider_)?token['\"]?\s*[:=]\s*['\"]?)[^\s'\",}&]+"),
        r"\1" + _REDACTED,
    ),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), _REDACTED),
    (re.compile(r"ya29\.[A-Za-z0-9._-]+"), _REDACTED),
    (re.compile(r"1//[A-Za-z0-9._-]{10,}"), _REDACTED),
    (re.compile(r"\b\d{2,6}~[A-Za-z0-9]{20,}"), _REDACTED),
    (re.compile(r"gAAAAA[A-Za-z0-9_=-]{20,}"), _REDACTED),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), _REDACTED),
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), _REDACTED),
)
# 이런 말이 든 서식 문자열이면 인자(문자열)를 통째로 가린다: logger.info("Authorization: %s", value)
_SENSITIVE_FORMAT = re.compile(r"(?i)authorization|bearer|token|secret|password|api[_-]?key")


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


_installed = False


def install_log_redaction() -> None:
    """모든 로그 레코드의 메시지·인자·예외 내용에서 토큰을 가린다. 여러 번 불러도 한 번만 건다.

    인자가 있는 레코드는 서식 문자열을 건드리지 않고 인자만 가린다. 인자 개수와 타입이 그대로라서
    uvicorn 접근 로그처럼 인자를 직접 꺼내 쓰는 포매터도 깨지지 않는다.
    """
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()
    formatter = logging.Formatter()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        if record.args:
            mask_all = isinstance(record.msg, str) and bool(_SENSITIVE_FORMAT.search(record.msg))

            def clean(item: Any) -> Any:
                if not isinstance(item, str):
                    return item
                return _REDACTED if mask_all else redact(item)

            if isinstance(record.args, Mapping):
                record.args = {key: clean(item) for key, item in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(clean(item) for item in record.args)
        elif isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(formatter.formatException(record.exc_info))
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
```

#### `api/app/pricing.py`

```python
"""모델 단가표 (PRD 7장 비용). 비용을 이 표로 계산해서, 단가가 바뀌어도 개선 전후를 같은 기준으로 비교한다.

PRICES에는 실제로 쓰는 모델을 각 사의 공식 가격표에서 옮겨 적는다.
값은 100만 토큰당 USD이고, 같은 모델은 적용 시작일 순서로 둔다. 표에 없는 모델을 부르면 KeyError가 난다.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Price:
    effective_from: date
    input_per_mtok: Decimal
    output_per_mtok: Decimal


# (provider, model) → 적용 시작일 순서의 단가
# TODO(Dev1): 쓰기로 정한 모델의 단가를 공식 가격표에서 채운다 (PRD 14장 "LLM 작업별 기본 모델")
PRICES: dict[tuple[str, str], tuple[Price, ...]] = {}


def price_on(
    provider: str,
    model: str,
    on: date,
    prices: Mapping[tuple[str, str], tuple[Price, ...]] = PRICES,
) -> Price:
    history = prices.get((provider, model))
    if not history:
        raise KeyError(
            f"단가표에 없는 모델: {provider}/{model}. app/pricing.py의 PRICES에 넣어 주세요."
        )
    applicable = [price for price in history if price.effective_from <= on]
    if not applicable:
        raise KeyError(f"{provider}/{model}의 {on} 기준 단가가 없어요.")
    return max(applicable, key=lambda price: price.effective_from)


def cost_usd(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    on: date,
    prices: Mapping[tuple[str, str], tuple[Price, ...]] = PRICES,
) -> Decimal:
    """on 날짜에 적용되는 단가로 계산한 비용 (소수점 6자리, llm_calls.cost_usd와 같은 자릿수)."""
    price = price_on(provider, model, on, prices)
    total = price.input_per_mtok * input_tokens + price.output_per_mtok * output_tokens
    return (total / Decimal(1_000_000)).quantize(Decimal("0.000001"))
```

#### `api/app/agent_log.py`

```python
"""에이전트 실행 로깅: agent_runs → tool_calls → llm_calls (ERD 로깅 도메인, PRD 8장 지표의 원천).

async with agent_run(log_conn, trigger="poster_upload", user_id=user.id) as run:
    async with run.tool("extract_from_image", {"file_id": file_id}) as call:
        result = await llm.extract(...)
        await run.record_llm(provider="anthropic", model="...", input_tokens=...,
                             output_tokens=..., latency_ms=..., tool_call=call)
        call.output = {"title": result.title}

cost_usd를 빼면 단가표(app/pricing.py)로 비용을 계산한다.
"""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.pricing import cost_usd as priced_cost
from app.schemas.me import PROFILE_FIELDS

SECRET_HINTS = ("token", "secret", "password", "authorization", "api_key")
# 프로필 값은 LLM에도 로그에도 넣지 않는다(PRD 6장). 실수로 들어와도 여기서 지운다
PROFILE_KEYS = frozenset(PROFILE_FIELDS)
_KST = timezone(timedelta(hours=9))


def _hidden(key: str) -> bool:
    lowered = key.lower()
    return lowered in PROFILE_KEYS or any(hint in lowered for hint in SECRET_HINTS)


def scrub(value: Any) -> Any:
    """비밀값이나 프로필 항목 이름의 키는 값을 지운다. tool_calls에 남지 않게 하는 마지막 안전장치."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _hidden(str(key)) else scrub(item) for key, item in value.items()
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
    cost_usd: Decimal = Decimal(0)
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
        latency_ms: int,
        cost_usd: Decimal | float | None = None,
        tool_call: ToolCall | None = None,
        priced_on: date | None = None,
    ) -> None:
        """LLM 호출 1건. cost_usd를 빼면 priced_on(기본: 오늘 KST)의 단가로 계산한다."""
        if cost_usd is None:
            on = priced_on or datetime.now(_KST).date()
            cost = priced_cost(provider, model, input_tokens, output_tokens, on)
        else:
            cost = Decimal(str(cost_usd))
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
                cost,
                latency_ms,
            ),
        )
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_usd += cost


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

#### `api/app/schemas/__init__.py`

```python
"""요청·응답 모델 (API 명세 v0.4)."""
```

#### `api/app/schemas/me.py`

```python
"""GET /me, /me/profile, /me/consents, /auth/google/tokens 모델 (API 명세 v0.4 4장, web types/api.ts와 같은 이름)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EnrollmentStatus = Literal["enrolled", "on_leave", "deferred_graduation", "graduated"]
WelfareStatus = Literal["none", "near_poverty", "basic_livelihood"]
# 시도는 정식 이름만 받는다 (판정 엔진의 지역 비교 기준)
RegionSido = Literal[
    "서울특별시",
    "부산광역시",
    "대구광역시",
    "인천광역시",
    "광주광역시",
    "대전광역시",
    "울산광역시",
    "세종특별자치시",
    "경기도",
    "강원특별자치도",
    "충청북도",
    "충청남도",
    "전북특별자치도",
    "전라남도",
    "경상북도",
    "경상남도",
    "제주특별자치도",
]


class ProfileFields(BaseModel):
    department: str | None = Field(None, max_length=60)  # 학과 목록(GET /meta/departments)의 이름
    grade: int | None = Field(None, ge=1, le=6)
    enrollment_status: EnrollmentStatus | None = None
    semesters_completed: int | None = Field(None, ge=0, le=16)  # 마친 학기 수
    credits_total: float | None = Field(None, ge=0, le=200)
    credits_last_semester: float | None = Field(None, ge=0, le=30)
    gpa_total: float | None = Field(None, ge=0, le=4.5)
    gpa_last_semester: float | None = Field(None, ge=0, le=4.5)  # 직전학기 장학용 평점(F 포함)
    gpa_scale: float | None = Field(None, ge=4.0, le=4.5)
    birth_date: date | None = None
    military_service_months: int | None = Field(None, ge=0, le=60)
    region_sido: str | None = None  # 주민등록 주소 기준
    region_sigungu: str | None = Field(None, max_length=40)
    income_bracket: int | None = Field(None, ge=0, le=10)  # 학자금 지원구간, 0 = 기초·차상위
    median_income_pct: int | None = Field(None, ge=0, le=500)  # 기준 중위소득 % (가구)
    welfare_status: WelfareStatus | None = None
    is_international: bool | None = None  # 외국인 유학생 여부


class Profile(ProfileFields):
    gpa_scale: float = Field(4.5, ge=4.0, le=4.5)


class ProfilePatch(ProfileFields):
    """보낸 필드만 바꾸고, null을 보내면 지운다."""

    model_config = ConfigDict(extra="forbid")

    region_sido: RegionSido | None = None


PROFILE_FIELDS: tuple[str, ...] = tuple(Profile.model_fields)
COMPLETION_FIELDS: tuple[str, ...] = tuple(f for f in PROFILE_FIELDS if f != "gpa_scale")
# 선택 동의(소득·수급 정보)가 있어야 저장되는 항목. DB 제약 profiles_income_consent_chk와 같다
INCOME_FIELDS: tuple[str, ...] = ("income_bracket", "median_income_pct", "welfare_status")


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
    income_info_consented: bool
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
    agree_income_info: bool = False  # 소득·수급 정보 수집·이용 (선택)


class ConsentResult(BaseModel):
    terms_agreed_at: datetime
    privacy_agreed_at: datetime
    income_info_agreed_at: datetime | None
    consent_version: str


class IncomeConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agree_income_info: bool


class IncomeConsentResult(BaseModel):
    income_info_agreed_at: datetime | None


class GoogleTokensRequest(BaseModel):
    provider_token: str = Field(min_length=1)
    provider_refresh_token: str | None = None


class GoogleTokensResponse(BaseModel):
    calendar_connected: bool
    scope: str
```

#### `api/app/schemas/meta.py`

```python
"""GET /meta/departments, POST /events 모델 (API 명세 v0.4 4장)."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Department(BaseModel):
    name: str
    college: str
    field_group: str


class DepartmentList(BaseModel):
    items: list[Department]


# 프론트가 보내는 이벤트. profile_prompt_submitted·lms_connected는 서버가 해당 API 안에서 기록한다
ClientEvent = Literal["app_open", "profile_prompt_shown", "lms_guide_opened"]


class EventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: ClientEvent
    opportunity_id: UUID | None = None
```

#### `api/app/repositories/__init__.py`

```python
"""DB 접근. 라우터는 SQL을 직접 쓰지 않고 저장소 메서드를 부른다."""
```

#### `api/app/repositories/profiles.py`

```python
"""profiles·oauth_tokens·lms_connections·notifications·eligibility_results 조회 (ERD v0.9)."""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection, sql

from app.db import get_conn
from app.schemas.me import (
    COMPLETION_FIELDS,
    PROFILE_FIELDS,
    ConsentResult,
    IncomeConsentResult,
    LmsSummary,
    Me,
    Profile,
    ProfileCompletion,
)

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"

# 선택 동의를 하면 시각을 남기고(이미 있으면 유지), 철회하면 시각과 소득·수급 값을 한 번에 지운다.
# 한 문장으로 바꿔야 DB 제약(profiles_income_consent_chk)을 지키며 철회할 수 있다
_INCOME_CONSENT_SET = (
    "income_info_agreed_at = case when %(agree)s then coalesce(income_info_agreed_at, now()) end,"
    " income_bracket = case when %(agree)s then income_bracket end,"
    " median_income_pct = case when %(agree)s then median_income_pct end,"
    " welfare_status = case when %(agree)s then welfare_status end"
)


@dataclass(frozen=True)
class Consents:
    terms_privacy: bool  # 이용약관·개인정보 (필수)
    income_info: bool  # 소득·수급 정보 (선택)


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
                   p.income_info_agreed_at is not null as income_info_consented,
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
            income_info_consented=row["income_info_consented"],
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

    async def get_consents(self, user_id: str) -> Consents:
        row = await (
            await self.conn.execute(
                "select terms_agreed_at is not null and privacy_agreed_at is not null as terms,"
                " income_info_agreed_at is not null as income from profiles where id = %s",
                (user_id,),
            )
        ).fetchone()
        if row is None:
            return Consents(terms_privacy=False, income_info=False)
        return Consents(terms_privacy=row["terms"], income_info=row["income"])

    async def save_consent(
        self, user_id: str, version: str, agree_income_info: bool
    ) -> ConsentResult:
        row = await (
            await self.conn.execute(
                "update profiles set terms_agreed_at = now(), privacy_agreed_at = now(),"
                f" consent_version = %(version)s, {_INCOME_CONSENT_SET} where id = %(id)s"
                " returning terms_agreed_at, privacy_agreed_at, income_info_agreed_at,"
                " consent_version",
                {"version": version, "agree": agree_income_info, "id": user_id},
            )
        ).fetchone()
        return ConsentResult.model_validate(row)

    async def set_income_consent(self, user_id: str, agree: bool) -> IncomeConsentResult:
        row = await (
            await self.conn.execute(
                f"update profiles set {_INCOME_CONSENT_SET},"
                " profile_updated_at = case when %(agree)s then profile_updated_at else now() end"
                " where id = %(id)s returning income_info_agreed_at",
                {"agree": agree, "id": user_id},
            )
        ).fetchone()
        return IncomeConsentResult.model_validate(row)

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

#### `api/app/repositories/meta.py`

```python
"""departments 목록과 usage_events 기록 (ERD v0.9)."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from psycopg import AsyncConnection

from app.db import get_conn
from app.schemas.meta import Department


class MetaRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def list_departments(self) -> list[Department]:
        rows = await (
            await self.conn.execute(
                "select name, college, field_group from departments"
                " where is_active order by sort_order, name"
            )
        ).fetchall()
        return [Department.model_validate(row) for row in rows]

    async def department_exists(self, name: str) -> bool:
        row = await (
            await self.conn.execute(
                "select exists(select 1 from departments where name = %s and is_active) as ok",
                (name,),
            )
        ).fetchone()
        return bool(row and row["ok"])

    async def record_event(
        self, user_id: str, event: str, opportunity_id: UUID | None = None
    ) -> None:
        """사용 이벤트 1건. 앱 열기는 KST 하루 1건만 남는다(부분 유니크). 없는 공고 id는 비운다."""
        await self.conn.execute(
            "insert into usage_events (user_id, event, opportunity_id)"
            " select %(user_id)s::uuid, %(event)s,"
            " (select id from opportunities where id = %(opportunity_id)s::uuid)"
            " where exists (select 1 from profiles where id = %(user_id)s::uuid)"
            " on conflict do nothing",
            {"user_id": user_id, "event": event, "opportunity_id": opportunity_id},
        )


def get_meta_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> MetaRepository:
    return MetaRepository(conn)


MetaRepoDep = Annotated[MetaRepository, Depends(get_meta_repo)]
```

#### `api/app/routers/__init__.py`

```python
"""엔드포인트. health 말고는 main.py에서 /api/v1 아래에 붙는다."""
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
    """캘린더를 처음 연결할 때(증분 승인) 콜백이 한 번 보낸다 (API 4장, F-01). 로그인 때는 부르지 않는다."""
    if not body.provider_refresh_token:
        raise ApiError(
            422,
            "GOOGLE_REFRESH_TOKEN_MISSING",
            "캘린더 권한을 다시 받아야 해요. Google 화면에서 캘린더 접근을 허용해 주세요.",
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
from app.repositories.meta import MetaRepoDep
from app.repositories.profiles import ProfileRepoDep
from app.schemas.me import (
    INCOME_FIELDS,
    ConsentRequest,
    ConsentResult,
    IncomeConsentRequest,
    IncomeConsentResult,
    Me,
    Profile,
    ProfilePatch,
    ProfileUpdateResponse,
    Rejudged,
    gpa_errors,
)

router = APIRouter(prefix="/me", tags=["내 정보"])


def _consent_required(consent: str, message: str) -> ApiError:
    """403 CONSENT_REQUIRED. details.consent: terms_privacy(필수 동의 전) 또는 income_info(선택 동의 전)."""
    return ApiError(403, "CONSENT_REQUIRED", message, {"consent": consent})


@router.get("", response_model=Me)
async def read_me(user: CurrentUserDep, repo: ProfileRepoDep) -> Me:
    me = await repo.get_me(user.id)
    if me is None:  # 첫 로그인 직후에는 프로필 행이 없어서 여기서 만든다
        await repo.ensure(user.id, user.name)
        me = await repo.get_me(user.id)
    assert me is not None
    return me


@router.get("/profile", response_model=Profile)
async def read_profile(user: CurrentUserDep, repo: ProfileRepoDep) -> Profile:
    return await repo.get_profile(user.id) or Profile()


@router.patch("/profile", response_model=ProfileUpdateResponse)
async def update_profile(
    patch: ProfilePatch, user: CurrentUserDep, repo: ProfileRepoDep, meta: MetaRepoDep
) -> ProfileUpdateResponse:
    consents = await repo.get_consents(user.id)
    if not consents.terms_privacy:
        raise _consent_required("terms_privacy", "약관에 동의한 뒤에 프로필을 저장할 수 있어요.")
    changes = patch.model_dump(exclude_unset=True)
    if not consents.income_info and any(changes.get(name) is not None for name in INCOME_FIELDS):
        raise _consent_required(
            "income_info", "소득·수급 정보는 선택 동의를 한 뒤에 저장할 수 있어요."
        )
    if changes.get("gpa_scale", 4.5) is None:
        changes["gpa_scale"] = 4.5  # 만점은 지울 수 없다
    current = await repo.get_profile(user.id) or Profile()
    try:
        merged = Profile.model_validate({**current.model_dump(), **changes})
    except ValidationError as exc:
        fields = {".".join(map(str, e["loc"])): e["msg"] for e in exc.errors()}
        raise ApiError(
            422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": fields}
        ) from exc
    if errors := gpa_errors(merged):
        raise ApiError(422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": errors})
    # 화면은 프로필 전체를 보내므로, 목록에서 빠진(폐지·통합) 학과라도 원래 값 그대로면 받는다
    department = changes.get("department")
    if (
        department is not None
        and department != current.department
        and not await meta.department_exists(department)
    ):
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "입력값을 확인해 주세요.",
            {"fields": {"department": "학과 목록에서 골라 주세요."}},
        )
    await repo.update_profile(user.id, {key: getattr(merged, key) for key in changes})
    # TODO(Dev1): 판정 엔진(app/eligibility)으로 이 사용자의 판정을 다시 계산하고 changed를 채운다 (S1-5)
    counts = await repo.eligibility_counts(user.id)
    return ProfileUpdateResponse(profile=merged, rejudged=Rejudged(changed=0, **counts))


@router.post("/consents", response_model=ConsentResult)
async def save_consents(
    body: ConsentRequest, user: CurrentUserDep, repo: ProfileRepoDep
) -> ConsentResult:
    """온보딩 동의 단계. 필수 2개와 선택 1개(소득·수급 정보)를 함께 받는다."""
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
    return await repo.save_consent(user.id, body.consent_version, body.agree_income_info)


@router.patch("/consents", response_model=IncomeConsentResult)
async def update_income_consent(
    body: IncomeConsentRequest, user: CurrentUserDep, repo: ProfileRepoDep
) -> IncomeConsentResult:
    """소득·수급 선택 동의와 철회 (F-02 소득 단계, F-06 설정). 철회하면 소득 3항목도 지운다."""
    if not (await repo.get_consents(user.id)).terms_privacy:
        raise _consent_required("terms_privacy", "약관에 먼저 동의해 주세요.")
    result = await repo.set_income_consent(user.id, body.agree_income_info)
    # TODO(Dev1): 철회했으면 판정 엔진으로 이 사용자의 판정을 다시 계산한다 (S1-5)
    return result
```

#### `api/app/routers/meta.py`

```python
from fastapi import APIRouter

from app.auth import CurrentUserDep
from app.repositories.meta import MetaRepoDep
from app.schemas.meta import DepartmentList

router = APIRouter(prefix="/meta", tags=["메타"])


@router.get("/departments", response_model=DepartmentList)
async def list_departments(user: CurrentUserDep, meta: MetaRepoDep) -> DepartmentList:
    """온보딩·설정의 학과 선택 목록. 사용 중인 학과만 정렬 순서대로 준다 (로그인 필요)."""
    return DepartmentList(items=await meta.list_departments())
```

#### `api/app/routers/events.py`

```python
from fastapi import APIRouter, Response

from app.auth import CurrentUserDep
from app.repositories.meta import MetaRepoDep
from app.schemas.meta import EventRequest

router = APIRouter(prefix="/events", tags=["사용 기록"])


@router.post("", status_code=204, response_class=Response)
async def record_event(body: EventRequest, user: CurrentUserDep, meta: MetaRepoDep) -> Response:
    """화면에서만 알 수 있는 사용 이벤트 (제품 지표, PRD 8장). 화면은 응답을 기다리지 않는다."""
    await meta.record_event(user.id, body.event, body.opportunity_id)
    return Response(status_code=204)
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
from app.logging_redact import install_log_redaction
from app.routers import auth, events, health, me, meta


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
    install_log_redaction()  # 로그에서 토큰을 가린다 (요청 처리 전에 건다)
    settings = settings or get_settings()
    app = FastAPI(title="UNIPIVOT API", version="0.2.0", lifespan=lifespan)
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
    for router in (auth.router, me.router, meta.router, events.router):
        app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()
```

### 테스트

#### `api/tests/__init__.py`

```python
"""단위 테스트(가짜 저장소)와 DB 통합 테스트(DATABASE_URL이 있을 때)."""
```

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
from app.repositories.meta import get_meta_repo
from app.repositories.profiles import get_profile_repo
from tests.fakes import FakeMetaRepository, FakeProfileRepository

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
def meta() -> FakeMetaRepository:
    return FakeMetaRepository()


@pytest.fixture
def client(
    settings: Settings, repo: FakeProfileRepository, meta: FakeMetaRepository
) -> Iterator[TestClient]:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_profile_repo] = lambda: repo
    app.dependency_overrides[get_meta_repo] = lambda: meta
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}
```

#### `api/tests/fakes.py`

```python
"""단위 테스트용 가짜 저장소. 실제 저장소와 메서드 이름·반환 타입을 맞춘다."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.repositories.profiles import Consents
from app.schemas.me import (
    COMPLETION_FIELDS,
    INCOME_FIELDS,
    ConsentResult,
    IncomeConsentResult,
    Me,
    Profile,
    ProfileCompletion,
)
from app.schemas.meta import Department


class FakeProfileRepository:
    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, dict[str, str]] = {}

    async def ensure(self, user_id: str, display_name: str | None) -> None:
        row = self.profiles.setdefault(
            user_id,
            {
                "display_name": None,
                "consented_at": None,
                "income_agreed_at": None,
                "profile": Profile(),
            },
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
            income_info_consented=row["income_agreed_at"] is not None,
            unread_notifications=0,
        )

    async def get_profile(self, user_id: str) -> Profile | None:
        row = self.profiles.get(user_id)
        return row["profile"] if row else None

    async def update_profile(self, user_id: str, values: dict[str, Any]) -> None:
        row = self.profiles[user_id]
        row["profile"] = row["profile"].model_copy(update=values)

    async def get_consents(self, user_id: str) -> Consents:
        row = self.profiles.get(user_id)
        if row is None:
            return Consents(terms_privacy=False, income_info=False)
        return Consents(
            terms_privacy=row["consented_at"] is not None,
            income_info=row["income_agreed_at"] is not None,
        )

    async def save_consent(
        self, user_id: str, version: str, agree_income_info: bool
    ) -> ConsentResult:
        now = datetime.now(UTC)
        row = self.profiles[user_id]
        row["consented_at"] = now
        self._set_income(row, agree_income_info, now)
        return ConsentResult(
            terms_agreed_at=now,
            privacy_agreed_at=now,
            income_info_agreed_at=row["income_agreed_at"],
            consent_version=version,
        )

    async def set_income_consent(self, user_id: str, agree: bool) -> IncomeConsentResult:
        row = self.profiles[user_id]
        self._set_income(row, agree, datetime.now(UTC))
        return IncomeConsentResult(income_info_agreed_at=row["income_agreed_at"])

    @staticmethod
    def _set_income(row: dict[str, Any], agree: bool, now: datetime) -> None:
        if agree:
            row["income_agreed_at"] = row["income_agreed_at"] or now
        else:  # 철회하면 소득 값도 지운다 (DB 제약과 같은 규칙)
            row["income_agreed_at"] = None
            row["profile"] = row["profile"].model_copy(update=dict.fromkeys(INCOME_FIELDS))

    async def save_google_tokens(self, user_id: str, access_token: str, refresh_token: str) -> None:
        self.tokens[user_id] = {"access_token": access_token, "refresh_token": refresh_token}

    async def eligibility_counts(self, user_id: str) -> dict[str, int]:
        return {"eligible": 0, "undetermined": 0, "ineligible": 0}


class FakeMetaRepository:
    def __init__(self) -> None:
        self.departments = [
            Department(name="인공지능학과", college="소프트웨어융합대학", field_group="공학계열"),
            Department(name="경영학부", college="경상대학", field_group="사회계열"),
        ]
        self.events: list[tuple[str, str, UUID | None]] = []

    async def list_departments(self) -> list[Department]:
        return list(self.departments)

    async def department_exists(self, name: str) -> bool:
        return any(department.name == name for department in self.departments)

    async def record_event(
        self, user_id: str, event: str, opportunity_id: UUID | None = None
    ) -> None:
        self.events.append((user_id, event, opportunity_id))
```

#### `api/tests/test_api.py`

```python
from uuid import UUID

from fastapi.testclient import TestClient

from app.config import Settings
from app.crypto import decrypt
from tests.conftest import USER_ID, make_token
from tests.fakes import FakeMetaRepository, FakeProfileRepository

CONSENT = {"consent_version": "2026-10-07", "agree_terms": True, "agree_privacy": True}


def consent(client: TestClient, auth: dict[str, str], **extra: bool) -> None:
    res = client.post("/api/v1/me/consents", json={**CONSENT, **extra}, headers=auth)
    assert res.status_code == 200


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
    assert (body["consented"], body["income_info_consented"], body["calendar_connected"]) == (
        False,
        False,
        False,
    )
    assert body["profile_completion"] == {"filled": 0, "total": 16}


def test_profile_update_needs_consent(client: TestClient, auth: dict[str, str]) -> None:
    client.get("/api/v1/me", headers=auth)
    res = client.patch("/api/v1/me/profile", json={"grade": 3}, headers=auth)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "CONSENT_REQUIRED"
    assert res.json()["error"]["details"] == {"consent": "terms_privacy"}


def test_consent_requires_both(client: TestClient, auth: dict[str, str]) -> None:
    res = client.post("/api/v1/me/consents", json={**CONSENT, "agree_privacy": False}, headers=auth)
    assert res.status_code == 422
    assert res.json()["error"]["details"]["fields"] == {"agree_privacy": "필수 항목이에요."}


def test_onboarding_flow(client: TestClient, auth: dict[str, str]) -> None:
    res = client.post("/api/v1/me/consents", json=CONSENT, headers=auth)
    assert res.status_code == 200
    assert res.json()["consent_version"] == "2026-10-07"
    assert res.json()["income_info_agreed_at"] is None  # 선택 동의는 하지 않음

    patch = {
        "department": "인공지능학과",
        "grade": 3,
        "gpa_last_semester": 3.9,
        "is_international": False,
    }
    res = client.patch("/api/v1/me/profile", json=patch, headers=auth)
    assert res.status_code == 200
    assert (res.json()["profile"]["grade"], res.json()["profile"]["is_international"]) == (3, False)
    assert res.json()["rejudged"] == {
        "changed": 0,
        "eligible": 0,
        "undetermined": 0,
        "ineligible": 0,
    }

    me = client.get("/api/v1/me", headers=auth).json()
    assert me["consented"] is True
    assert me["profile_completion"]["filled"] == 4

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

    res = client.patch("/api/v1/me/profile", json={"department": "없는학과"}, headers=auth)
    assert res.status_code == 422
    assert res.json()["error"]["details"]["fields"] == {"department": "학과 목록에서 골라 주세요."}

    res = client.patch("/api/v1/me/profile", json={"region_sido": "경기"}, headers=auth)
    assert res.status_code == 422  # 시도는 정식 이름만 (경기도)


def test_department_removed_from_list_is_kept(
    client: TestClient, auth: dict[str, str], meta: FakeMetaRepository
) -> None:
    consent(client, auth)
    res = client.patch("/api/v1/me/profile", json={"department": "경영학부"}, headers=auth)
    assert res.status_code == 200
    meta.departments = [d for d in meta.departments if d.name != "경영학부"]  # 학과가 목록에서 빠짐

    body = {"department": "경영학부", "grade": 2}  # 화면은 프로필 전체를 다시 보낸다
    res = client.patch("/api/v1/me/profile", json=body, headers=auth)
    assert res.status_code == 200
    assert (res.json()["profile"]["department"], res.json()["profile"]["grade"]) == ("경영학부", 2)
    res = client.patch("/api/v1/me/profile", json={"department": "인공지능학과"}, headers=auth)
    assert res.status_code == 200  # 바꿀 때는 목록에 있는 학과로


def test_income_needs_optional_consent(
    client: TestClient, auth: dict[str, str], repo: FakeProfileRepository
) -> None:
    consent(client, auth)
    res = client.patch("/api/v1/me/profile", json={"income_bracket": 6}, headers=auth)
    assert res.status_code == 403
    assert res.json()["error"]["details"] == {"consent": "income_info"}
    res = client.patch("/api/v1/me/profile", json={"income_bracket": None}, headers=auth)
    assert res.status_code == 200  # 지우는 것은 동의 없이도 된다

    res = client.patch("/api/v1/me/consents", json={"agree_income_info": True}, headers=auth)
    assert res.status_code == 200 and res.json()["income_info_agreed_at"] is not None
    res = client.patch(
        "/api/v1/me/profile", json={"income_bracket": 6, "welfare_status": "none"}, headers=auth
    )
    assert res.status_code == 200
    assert client.get("/api/v1/me", headers=auth).json()["income_info_consented"] is True

    res = client.patch("/api/v1/me/consents", json={"agree_income_info": False}, headers=auth)
    assert res.status_code == 200 and res.json()["income_info_agreed_at"] is None
    profile = client.get("/api/v1/me/profile", headers=auth).json()
    assert (profile["income_bracket"], profile["welfare_status"]) == (None, None)  # 철회하면 지운다
    assert client.get("/api/v1/me", headers=auth).json()["income_info_consented"] is False


def test_income_consent_order(client: TestClient, auth: dict[str, str]) -> None:
    client.get("/api/v1/me", headers=auth)
    res = client.patch("/api/v1/me/consents", json={"agree_income_info": True}, headers=auth)
    assert res.status_code == 403  # 필수 동의가 먼저
    assert res.json()["error"]["details"] == {"consent": "terms_privacy"}

    consent(client, auth, agree_income_info=True)  # 온보딩에서 선택 동의까지 한 번에
    assert client.get("/api/v1/me", headers=auth).json()["income_info_consented"] is True
    res = client.patch(
        "/api/v1/me/consents", json={"agree_income_info": True, "extra": 1}, headers=auth
    )
    assert res.status_code == 422


def test_departments(client: TestClient, auth: dict[str, str]) -> None:
    assert client.get("/api/v1/meta/departments").status_code == 401
    res = client.get("/api/v1/meta/departments", headers=auth)
    assert res.status_code == 200
    assert res.json()["items"][0] == {
        "name": "인공지능학과",
        "college": "소프트웨어융합대학",
        "field_group": "공학계열",
    }


def test_events(client: TestClient, auth: dict[str, str], meta: FakeMetaRepository) -> None:
    res = client.post("/api/v1/events", json={"event": "app_open"}, headers=auth)
    assert (res.status_code, res.content) == (204, b"")
    assert meta.events == [(USER_ID, "app_open", None)]

    res = client.post("/api/v1/events", json={"event": "lms_connected"}, headers=auth)
    assert res.status_code == 422  # 서버가 직접 기록하는 이벤트
    res = client.post(
        "/api/v1/events",
        json={"event": "profile_prompt_shown", "opportunity_id": "not-a-uuid"},
        headers=auth,
    )
    assert res.status_code == 422

    opportunity_id = "00000000-0000-4000-8000-0000000000aa"
    body = {"event": "profile_prompt_shown", "opportunity_id": opportunity_id}
    assert client.post("/api/v1/events", json=body, headers=auth).status_code == 204
    assert meta.events[-1] == (USER_ID, "profile_prompt_shown", UUID(opportunity_id))


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

#### `api/tests/test_security.py`

```python
"""토큰 암호화 키 교체와 로그 마스킹 (PRD 7장 토큰 보안)."""

import logging

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.crypto import decrypt, encrypt, rotate
from app.logging_redact import install_log_redaction, redact

JWT_LIKE = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXZhbHVlLWhlcmU"
LMS_TOKEN = "1234~AbCdEfGhIjKlMnOpQrStUvWx"


def test_key_rotation() -> None:
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    stored = encrypt("1//refresh", old)
    both = f"{new},{old}"
    assert decrypt(stored, both) == "1//refresh"  # 키를 바꾼 뒤에도 옛 값을 읽는다
    rotated = rotate(stored, both)
    assert decrypt(rotated, new) == "1//refresh"  # 다시 암호화하면 새 키만으로 읽는다
    with pytest.raises(InvalidToken):
        decrypt(stored, new)


def test_redact_patterns() -> None:
    secrets = (
        JWT_LIKE,
        "ya29.a0AfH6SMBx",
        "1//0gAbCdEfGhIjKl",
        LMS_TOKEN,
        "gAAAAABlZ0123456789abcdefghij",
        "secret123",
        "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv",
        "AIza" + "B" * 35,
    )
    text = (
        f"Authorization: Bearer {secrets[0]} google={secrets[1]} refresh={secrets[2]}"
        f" lms={secrets[3]} stored={secrets[4]} access_token={secrets[5]} key={secrets[6]}"
        f" gemini={secrets[7]}"
    )
    cleaned = redact(text)
    assert not [secret for secret in secrets if secret in cleaned]
    assert redact("input_tokens=1200, 장학금 3건") == "input_tokens=1200, 장학금 3건"


def test_log_records_are_redacted(caplog: pytest.LogCaptureFixture) -> None:
    install_log_redaction()
    logger = logging.getLogger("unipivot.test")
    with caplog.at_level(logging.INFO, logger="unipivot.test"):
        logger.info("LMS 호출 Authorization: Bearer %s", LMS_TOKEN)
        logger.info(f"세션 토큰 확인 {JWT_LIKE}")
        logger.info(  # uvicorn 접근 로그와 같은 모양
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:5000",
            "GET",
            "/auth/callback?access_token=ya29.zzzzzz",
            "1.1",
            200,
        )
        try:
            raise RuntimeError("refresh failed for 1//0gAbCdEfGhIjKl")
        except RuntimeError:
            logger.exception("Google 토큰 갱신 실패")
    for secret in (LMS_TOKEN, JWT_LIKE, "ya29.zzzzzz", "1//0gAbCdEfGhIjKl"):
        assert secret not in caplog.text
    access = caplog.records[2]
    assert len(access.args) == 5 and access.args[4] == 200  # 인자 개수와 타입은 그대로
```

#### `api/tests/test_agent_log.py`

```python
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app import pricing
from app.agent_log import AgentRun, agent_run, scrub
from app.pricing import Price, cost_usd

TEST_PRICES = {
    ("test", "model-a"): (
        Price(date(2026, 1, 1), Decimal("1.00"), Decimal("5.00")),
        Price(date(2026, 11, 1), Decimal("0.50"), Decimal("2.50")),
    )
}


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


def test_scrub_hides_profile_values() -> None:
    """프로필 값은 tool_calls에 남기지 않는다 (PRD 6장)."""
    value = {
        "notice": "장학 공고",
        "profile": {"gpa_last_semester": 3.9, "birth_date": "2000-01-01", "Income_Bracket": 3},
    }
    assert scrub(value) == {
        "notice": "장학 공고",
        "profile": {
            "gpa_last_semester": "[REDACTED]",
            "birth_date": "[REDACTED]",
            "Income_Bracket": "[REDACTED]",
        },
    }


@pytest.mark.anyio
async def test_agent_run_requires_autocommit_connection() -> None:
    class TransactionConnection:
        autocommit = False

    with pytest.raises(RuntimeError):
        async with agent_run(TransactionConnection(), trigger="eval"):  # type: ignore[arg-type]
            pass


def test_cost_uses_price_effective_on_date() -> None:
    assert cost_usd("test", "model-a", 1200, 300, date(2026, 10, 7), TEST_PRICES) == Decimal(
        "0.002700"
    )
    assert cost_usd("test", "model-a", 1200, 300, date(2026, 11, 1), TEST_PRICES) == Decimal(
        "0.001350"
    )
    with pytest.raises(KeyError):
        cost_usd("test", "unknown", 1, 1, date(2026, 10, 7), TEST_PRICES)
    with pytest.raises(KeyError):
        cost_usd("test", "model-a", 1, 1, date(2025, 12, 31), TEST_PRICES)  # 단가 시작 전


class RecordingConnection:
    autocommit = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def execute(self, query: str, params: Any = None) -> None:
        self.calls.append((query, params))


@pytest.mark.anyio
async def test_record_llm_prices_from_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(pricing.PRICES, ("test", "model-a"), TEST_PRICES[("test", "model-a")])
    conn = RecordingConnection()
    run = AgentRun(conn=conn, id="run-1")  # type: ignore[arg-type]
    await run.record_llm(
        provider="test",
        model="model-a",
        input_tokens=1200,
        output_tokens=300,
        latency_ms=10,
        priced_on=date(2026, 10, 7),
    )
    await run.record_llm(  # 비용을 직접 넘기면 그 값을 쓴다
        provider="test",
        model="model-a",
        input_tokens=1000,
        output_tokens=0,
        latency_ms=10,
        cost_usd=0.001,
    )
    assert conn.calls[0][1][6] == Decimal("0.002700")
    assert (run.input_tokens, run.output_tokens, run.cost_usd) == (2200, 300, Decimal("0.003700"))
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
from app.repositories.meta import MetaRepository
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
        await conn.execute(
            "insert into departments (name, college, field_group)"
            " values ('인공지능학과', '테스트대학', '공학계열') on conflict do nothing"
        )
        repo, meta = ProfileRepository(conn), MetaRepository(conn)
        await repo.ensure(user_id, "테스트 학생")

        me = await repo.get_me(user_id)
        assert me is not None
        assert (me.consented, me.income_info_consented, me.calendar_connected) == (
            False,
            False,
            False,
        )
        assert (me.profile_completion.filled, me.profile_completion.total) == (0, 16)

        result = await repo.save_consent(user_id, "2026-10-07", agree_income_info=False)
        assert (result.consent_version, result.income_info_agreed_at) == ("2026-10-07", None)
        assert await meta.department_exists("인공지능학과")
        assert not await meta.department_exists("없는학과")
        changes = {
            "department": "인공지능학과",
            "gpa_last_semester": 3.9,
            "is_international": False,
        }
        await repo.update_profile(user_id, changes)
        profile = await repo.get_profile(user_id)
        assert profile is not None
        assert (
            profile.department,
            profile.gpa_last_semester,
            profile.gpa_scale,
            profile.is_international,
        ) == ("인공지능학과", 3.9, 4.5, False)

        # 소득·수급 값은 선택 동의가 있어야 저장된다 (DB 제약도 같은 규칙)
        with pytest.raises(psycopg.errors.CheckViolation):
            async with conn.transaction():
                await repo.update_profile(user_id, {"welfare_status": "none"})
        assert (await repo.set_income_consent(user_id, True)).income_info_agreed_at is not None
        await repo.update_profile(user_id, {"welfare_status": "none", "income_bracket": 6})
        assert (await repo.get_consents(user_id)).income_info
        # 철회하면 시각과 소득 값이 한 번에 지워진다
        assert (await repo.set_income_consent(user_id, False)).income_info_agreed_at is None
        profile = await repo.get_profile(user_id)
        assert profile is not None
        assert (profile.welfare_status, profile.income_bracket) == (None, None)

        await repo.save_google_tokens(user_id, "encrypted-access", "encrypted-refresh")
        me = await repo.get_me(user_id)
        assert me is not None
        assert me.consented and me.calendar_connected and not me.income_info_consented
        assert (me.profile_completion.filled, me.unread_notifications) == (3, 0)
        assert await repo.eligibility_counts(user_id) == {
            "eligible": 0,
            "undetermined": 0,
            "ineligible": 0,
        }
    finally:
        await conn.rollback()
        await conn.close()


async def test_meta_repository() -> None:
    conn = await connect()
    try:
        user_id = str(uuid.uuid4())
        await conn.execute("insert into auth.users (id) values (%s)", (user_id,))
        await conn.execute(
            "insert into departments (name, college, field_group, sort_order, is_active) values"
            " ('나중학과', '테스트대학', '공학계열', 2, true),"
            " ('먼저학과', '테스트대학', '인문계열', 1, true),"
            " ('폐지학과', '테스트대학', '공학계열', 0, false)"
        )
        meta = MetaRepository(conn)
        names = [department.name for department in await meta.list_departments()]
        assert names.index("먼저학과") < names.index("나중학과") and "폐지학과" not in names
        assert not await meta.department_exists("폐지학과")

        await meta.record_event(user_id, "app_open")  # 프로필 행이 없으면 남기지 않는다
        await ProfileRepository(conn).ensure(user_id, "테스트 학생")
        for _ in range(2):
            await meta.record_event(user_id, "app_open")  # 같은 날은 1건
        await meta.record_event(user_id, "profile_prompt_shown", uuid.uuid4())  # 없는 공고 id
        rows = await (
            await conn.execute(
                "select event, opportunity_id from usage_events where user_id = %s order by id",
                (user_id,),
            )
        ).fetchall()
        assert [(row["event"], row["opportunity_id"]) for row in rows] == [
            ("app_open", None),
            ("profile_prompt_shown", None),
        ]
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
                "extract_requirements",
                {"notice": "n1", "access_token": "x", "gpa_last_semester": 3.9},
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
        assert by_run[run_ids[0]]["input"]["gpa_last_semester"] == "[REDACTED]"
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
      - name: 마이그레이션 적용 (auth 흉내 → supabase/migrations 이름 순)
        run: |
          psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/ci/auth_stub.sql
          for f in supabase/migrations/*.sql; do
            psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
          done
      - name: 스키마 점검 (RLS·FK 인덱스)
        run: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/ci/schema_checks.sql
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
uv run pytest                             # DATABASE_URL 환경변수가 없으면 DB 테스트 3개는 건너뜀
```

DB 통합 테스트는 `auth.users`에 테스트 행을 넣으므로 실제 Supabase DB로 돌리지 않는다. CI의 Postgres 컨테이너에서 돈다.

## 확인한 것

| 점검 | 결과 |
| --- | --- |
| `ruff check`, `ruff format --check` | 통과 |
| 단위 테스트 22개 (DB 없이) | 통과: 헬스, 인증 없음·만료·위조 토큰 401, 첫 `/me`(채운 수 16 기준, 동의 false), 필수 동의 전 저장 403(`terms_privacy`), 필수 동의 두 개, 온보딩 흐름(동의 → 학과·유학생 저장 → 채운 수 4 → null로 지우기), 범위·만점·명세 밖 필드·없는 학과·시도 약칭 422, 목록에서 빠진 학과 유지, 소득 선택 동의(동의 전 403 → 동의 → 저장 → 철회하면 지움), 동의 순서, 학과 목록, 사용 이벤트(204, 서버 전용 이벤트·잘못된 id 422), Google 토큰 암호화 저장, 키 교체, 로그 가리기(토큰 모양 8가지, uvicorn 접근 로그 인자 유지, 예외 내용), 적용 시작일별 단가, `tool_calls`에서 비밀값·프로필 값 지움 |
| DB 통합 테스트 3개 (Postgres 16, 마이그레이션 v07·v08·v09 + 스키마 점검) | 통과: 저장소 왕복(학과 FK, 동의 없는 소득 값은 DB 제약 위반, 동의 → 저장 → 철회하면 지움), 학과 목록·사용 이벤트(정렬, 숨긴 학과, 프로필 없으면 기록 안 함, 앱 열기 하루 1건, 없는 공고 id), 실행 로깅 성공·실패(토큰·프로필 값 지움, 토큰 수·비용 합산, 실패 사유) |
| 판정 엔진과 함께 | `판정엔진_구현.md`의 파일을 더해 단위 107개 + DB 3개 통과 |
| `uvicorn` 실행 (마이그레이션을 적용한 DB에 연결) | `/health` 응답, OpenAPI에 API 9개(`/health` 포함), 인증 없는 `/api/v1/me` → 13장 형식 401, 실제 토큰으로 `/me` → 동의 전 저장 403 → 동의 → 소득 동의 → 저장 → 학과 목록 → 앱 열기 두 번(기록 1건). 접근 로그의 `?access_token=` 값은 `[REDACTED]`로 찍힘 |

샌드박스 버전: Python 3.12, FastAPI 0.142, Starlette 1.7, Pydantic 2.13, psycopg 3.3, PyJWT 2.15, cryptography 50. 통합 테스트는 레포와 같은 마이그레이션 파일(`20261006000000_erd_v07.sql` → `…000100_erd_v08.sql` → `…000200_erd_v09.sql`)을 `auth_stub.sql` 뒤에 적용하고 `schema_checks.sql`까지 통과한 DB에서 돌렸다.

## 남은 것

- 단가표 `pricing.PRICES` 채우기: 첫 LLM 호출(S1-4 요건 추출) 전에 PRD 14장 미결 사항의 "LLM 작업별 기본 모델"을 정하고, 그 모델의 공식 단가를 넣는다
- 재판정(S1-5): `PATCH /me/profile`과 소득 동의 철회 뒤의 `TODO(Dev1)` 자리
- `profile_prompt_submitted`: 정보 입력창에서 저장할 때 서버가 기록한다(API 4장). 어느 공고에서 연 입력창인지 서버에 넘기는 방법은 명세에 없어서, 공고 상세(S1-6)를 만들 때 정한다
- `lms_connected`: LMS 연결 API에서 기록한다
- refresh token으로 access token을 다시 받는 코드, 캘린더 API 호출, 끊김 처리(409 `CALENDAR_NOT_CONNECTED`)는 S1-1에서 붙인다. 지금은 저장까지만 있다
- 키를 실제로 바꿀 때 저장된 토큰을 `crypto.rotate()`로 다시 암호화하는 일회성 스크립트를 만든다
