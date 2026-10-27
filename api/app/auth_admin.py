"""Supabase 로그인 계정 지우기 (탈퇴, F-06). 관리자 API `DELETE {SUPABASE_URL}/auth/v1/admin/users/{id}`.

키는 파일 저장소와 같은 `SUPABASE_SECRET_KEY`이고 싣는 자리도 같다(app/uploads/storage.py 머리말).
지우면 Supabase가 그 사용자의 로그인 기록(auth.users·identities·sessions)을 지우고, `profiles`가 아직 남아
있었다면 cascade로 함께 지운다.

이미 없는 사용자(404, `user_not_found`)는 지운 것으로 본다 — 탈퇴를 다시 누르면 다시 지우기 때문이다.
`code` 없는 404는 지운 것으로 보지 않는다. 주소가 틀려 로그인 서버가 아닌 곳이 답한 것일 수 있다(저장소의
`NoSuchKey`와 같은 기준). 키·주소는 오류 문구·로그에 넣지 않는다.
"""

from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import Depends

from app.config import Settings, get_settings
from app.uploads.storage import KEY_SHAPE, service_key_headers

TIMEOUT_SECONDS = 15.0
GONE = "user_not_found"  # GoTrue가 없는 사용자에 주는 오류 코드
REASON_LIMIT = 120


class AuthAdminError(Exception):
    """로그인 계정을 지우지 못했다(설정이 비었을 때도). 키·주소는 담지 않는다."""


class SupabaseAuthAdmin:
    def __init__(self, *, base_url: str, service_key: str) -> None:
        self.base_url = base_url.strip().rstrip("/")
        self.service_key = service_key.strip()

    @property
    def ready(self) -> bool:
        """주소와 키가 있어야 부른다. 키 모양이 아니면(빈칸·따옴표 등) 없는 것으로 본다 — 머리값을 깬다."""
        return bool(self.base_url and KEY_SHAPE.fullmatch(self.service_key))

    async def delete_user(self, user_id: str) -> None:
        """그 사용자의 로그인 계정을 지운다. 이미 없으면 그냥 지나간다. 실패하면 AuthAdminError다."""
        if not self.ready:
            raise AuthAdminError("SUPABASE_URL·SUPABASE_SECRET_KEY가 비었거나 키 모양이 아니에요.")
        url = f"{self.base_url}/auth/v1/admin/users/{quote(user_id, safe='')}"
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.delete(url, headers=service_key_headers(self.service_key))
        except httpx.HTTPError as exc:
            raise AuthAdminError(f"로그인 서버에 닿지 못했어요: {type(exc).__name__}") from exc
        if response.status_code == 404 and _error_code(response) == GONE:
            return
        if response.status_code >= 400:
            reason = _reason(response, self.service_key)
            detail = f"{response.status_code}, {reason}" if reason else str(response.status_code)
            raise AuthAdminError(f"로그인 서버가 계정 지우기를 거절했어요({detail}).")


def _body(response: httpx.Response) -> dict[str, object]:
    try:
        body = response.json()
    except (ValueError, RecursionError):
        return {}
    return body if isinstance(body, dict) else {}


def _error_code(response: httpx.Response) -> str | None:
    """GoTrue 오류 코드. 지금은 `error_code`에 오고(`code`는 숫자), 예전 판은 `code`에 글자로 왔다."""
    body = _body(response)
    for key in ("error_code", "code"):
        value = body.get(key)
        if isinstance(value, str):
            return value
    return None


def _reason(response: httpx.Response, key: str) -> str:
    """거절 이유(오류 코드·문구). 로그에만 남는다. 키가 섞여 있으면 가리고, 줄을 펴고, 자른다."""
    body = _body(response)
    parts = [_error_code(response), body.get("msg"), body.get("message")]
    text = ": ".join(part for part in parts if isinstance(part, str) and part.strip())
    if key:
        text = text.replace(key, "[가림]")
    return " ".join(text.split())[:REASON_LIMIT]


def get_auth_admin(settings: Annotated[Settings, Depends(get_settings)]) -> SupabaseAuthAdmin:
    return SupabaseAuthAdmin(
        base_url=settings.supabase_url, service_key=settings.supabase_secret_key
    )


AuthAdminDep = Annotated[SupabaseAuthAdmin, Depends(get_auth_admin)]
