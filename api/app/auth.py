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
