"""Supabase access token 검증 (API 명세 1장 인증). 실패 이유는 로그에 남기고 토큰은 남기지 않는다.

- 토큰 문제(만료·위조·다른 프로젝트의 토큰): 401 UNAUTHORIZED. 웹이 로그인 화면으로 보낸다
- 서버 문제(SUPABASE_URL이 비었거나 틀림, 공개키를 받지 못함): 503 AUTH_UNAVAILABLE. 401을 주면 웹이
  로그인 화면으로 보내서, 다시 로그인해도 같은 곳을 맴돈다
"""

import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Annotated, Any
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, Header

from app.config import Settings, get_settings
from app.errors import ApiError

logger = logging.getLogger(__name__)

# 서버와 이 컴퓨터의 시계가 조금 달라도 방금 받은 토큰을 "아직 유효하지 않음(iat)"이나 만료로 거절하지 않는다
CLOCK_LEEWAY = timedelta(seconds=60)
JWKS_TIMEOUT_SECONDS = 10  # 공개키를 받는 동안 그 요청이 기다리므로 오래 끌지 않는다
AUTH_UNAVAILABLE = "로그인을 확인하지 못했어요. 잠시 후 다시 시도해 주세요."
_KID_NOT_FOUND = "Unable to find a signing key"  # PyJWKClient: 받은 공개키 목록에 토큰의 kid가 없음


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None
    name: str | None


@lru_cache
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    # cache_keys: 한 번 찾은 키는 기억해서, 공개키 주소가 잠깐 안 돼도 아는 키의 토큰은 계속 검증한다
    return jwt.PyJWKClient(jwks_url, cache_keys=True, timeout=JWKS_TIMEOUT_SECONDS)


# 프로젝트 주소 뒤에 붙으면 안 되는 Supabase API 경로(대시보드에서 복사할 때 따라온다)
_API_PATH = re.compile(r"(?i)/(rest|auth|storage|functions|realtime|graphql)/v1(/|$)")


def auth_settings_problem(settings: Settings) -> str | None:
    """로그인 확인 설정에서 고칠 점. 없으면 None이다. 앱을 시작할 때와 공개키를 받기 전에 본다.

    주소는 http(s)://로 시작하고 계정 정보(@)가 없을 때만 그대로 보여 준다. 잘못 넣은 DB 주소의 비밀번호나
    키가 로그에 남지 않게 한다."""
    if settings.supabase_jwt_secret:
        return None  # 레거시 HS256 비밀키로 검증해서 주소를 쓰지 않는다
    url = settings.supabase_url.strip()
    if not url:
        return "SUPABASE_URL이 비어 있어요(api/.env). 로그인이 필요한 요청이 모두 503이 돼요"
    if "@" in url:
        return (
            "SUPABASE_URL에 계정 정보(@)가 들어 있어요(값은 보여 주지 않음). DB 주소 대신"
            " Supabase 프로젝트 주소(https://….supabase.co)를 넣으세요"
        )
    try:
        parts = urlsplit(url)
    except ValueError:  # "http://[" 같은 값. 여기서 터지면 서버가 뜨지 않는다
        return "SUPABASE_URL이 주소 모양이 아니에요(값은 보여 주지 않음). Supabase 프로젝트 주소를 넣으세요"
    if parts.scheme.lower() not in ("https", "http") or not parts.netloc:
        return "SUPABASE_URL이 https://로 시작하지 않아요(값은 보여 주지 않음). Supabase 프로젝트 주소를 넣으세요"
    if "<" in url or ">" in url:
        return f"SUPABASE_URL에 예시 값이 남아 있어요: {url}. Supabase 프로젝트 주소로 바꾸세요"
    # 공개키 주소는 {SUPABASE_URL}/auth/v1/…라서 대시보드의 API 주소(…/rest/v1)를 그대로 넣으면 엉뚱한 곳이 404로
    # 답하고 로그인이 모두 503이 된다. 원인이 안 보여서 여기서 알린다. 경로는 Supabase API 경로일 때만 막는다 —
    # 앞단에 경로를 붙인 자체 호스팅(https://example.com/supabase)은 그대로 된다(검토). ?·#는 늘 막는다
    if _API_PATH.search(parts.path) or "?" in url or "#" in url:
        return (
            "SUPABASE_URL에 경로가 붙어 있어요(…/rest/v1 같은 것. 값은 보여 주지 않음). 프로젝트 주소"
            "(https://<ref>.supabase.co)만 넣으세요"
        )
    return None


def decode_supabase_token(token: str, settings: Settings) -> dict[str, Any]:
    """Supabase access token을 검증한다.

    레거시 프로젝트는 HS256 비밀키(SUPABASE_JWT_SECRET)로,
    새 프로젝트는 {SUPABASE_URL}/auth/v1/.well-known/jwks.json 공개키로 검증한다.
    """
    try:
        if settings.supabase_jwt_secret:
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                leeway=CLOCK_LEEWAY,
            )
        return jwt.decode(
            token,
            _signing_key(token, settings),
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            leeway=CLOCK_LEEWAY,
        )
    except jwt.PyJWTError as exc:
        # 오류 문구에 토큰 머리(kid 등)가 들어갈 수 있어 한 줄로 줄이고 길이를 자른다(가림 처리도 받는다)
        logger.warning(
            "로그인 확인 실패(401): %s: %s%s",
            type(exc).__name__,
            _one_line(str(exc)),
            _hint(exc, settings, token),
        )
        raise ApiError(401, "UNAUTHORIZED", "로그인이 만료됐어요. 다시 로그인해 주세요.") from exc


def _signing_key(token: str, settings: Settings) -> jwt.PyJWK:
    """토큰의 kid에 맞는 공개키.

    토큰 머리가 틀렸거나 받은 목록에 kid가 없으면 토큰 문제(401, PyJWTError 그대로)다.
    공개키를 받거나 읽다가 난 문제는 모두 서버 문제(503)다.
    PyJWK를 그대로 넘겨서, 토큰의 alg가 키의 알고리즘과 다르면 decode가 401로 거절한다(500이 아님).
    """
    if problem := auth_settings_problem(settings):
        raise _unavailable(problem)
    kid = jwt.get_unverified_header(token).get("kid")
    jwks_url = f"{settings.supabase_url.strip().rstrip('/')}/auth/v1/.well-known/jwks.json"
    try:
        return _jwks_client(jwks_url).get_signing_key(kid)
    except jwt.PyJWKClientError as exc:
        if str(exc).startswith(_KID_NOT_FOUND):
            raise  # 다른 프로젝트의 토큰이거나 바뀐 키(401)
        raise _unavailable(_fetch_failure(jwks_url, exc)) from exc
    except Exception as exc:  # 빈 목록, JSON이 아니거나 모양이 틀린 응답, 읽다 끊김
        raise _unavailable(_fetch_failure(jwks_url, exc)) from exc


def _fetch_failure(jwks_url: str, exc: Exception) -> str:
    reason = f"공개키를 받지 못했어요({jwks_url}). {type(exc).__name__}: {_one_line(str(exc))}"
    if "did not contain any" in str(exc):  # 키 목록이 비었음
        return (
            reason + ". 공개키가 없는 레거시 프로젝트면 api/.env의 SUPABASE_JWT_SECRET을 채우세요"
        )
    return reason + ". api/.env의 SUPABASE_URL과 네트워크를 확인하세요"


def _unavailable(reason: str) -> ApiError:
    logger.error("로그인 확인 실패(503): %s", reason)
    return ApiError(503, "AUTH_UNAVAILABLE", AUTH_UNAVAILABLE)


def _one_line(text: str) -> str:
    """로그 한 줄: 줄바꿈을 없애고, 제어 문자는 \\x1b처럼 적고, 200자로 자른다.

    요청에서 온 값(토큰 머리의 kid 등)이 가짜 로그 줄을 만들거나 터미널을 조작하지 못하게 한다."""
    flat = " ".join(text.split())
    escaped = "".join(c if c.isprintable() else c.encode("unicode_escape").decode() for c in flat)
    return escaped[:200]


def _hint(exc: jwt.PyJWTError, settings: Settings, token: str) -> str:
    """로그에 붙이는 고칠 곳. 흔한 설정 실수만 짚는다."""
    if isinstance(exc, jwt.ImmatureSignatureError):
        return ". 이 컴퓨터 시계가 1분 넘게 늦을 수 있어요. 시간 동기화를 켜세요"
    if settings.supabase_jwt_secret and isinstance(exc, jwt.InvalidAlgorithmError):
        return (
            ". 새 Supabase 프로젝트의 토큰(ES256)이에요. api/.env의 SUPABASE_JWT_SECRET을 비우세요"
        )
    if settings.supabase_jwt_secret and isinstance(exc, jwt.InvalidSignatureError):
        return ". SUPABASE_JWT_SECRET이 이 프로젝트의 값인지 확인하세요"
    if isinstance(exc, jwt.PyJWKClientError):
        if _algorithm(token) == "HS256":
            return ". 레거시(HS256) 토큰이에요. 이 프로젝트면 api/.env에 SUPABASE_JWT_SECRET을 채우세요"
        return ". 웹(.env.local)과 API(.env)가 같은 Supabase 프로젝트 주소를 쓰는지 확인하세요"
    return ""


def _algorithm(token: str) -> str | None:
    try:
        return jwt.get_unverified_header(token).get("alg")
    except jwt.PyJWTError:
        return None


def get_current_user(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """동기 함수라서 FastAPI가 스레드에서 돌린다. 공개키를 받는 동안 다른 요청을 막지 않는다."""
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
