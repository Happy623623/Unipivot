"""Supabase Storage 업로드 (F-13).

버킷은 비공개다(ERD 8장). 클라이언트는 버킷에 직접 닿지 못하고, 서버가 저장소 키로만 올린다.
경로는 `<user_id>/<kind>/<file_id>.<확장자>`다.

- 올리기: POST {base}/object/{bucket}/{path} (본문은 파일 바이트 그대로)
- 받기: GET {base}/object/{bucket}/{path} (서버가 포스터를 모델에 넘길 때 쓴다)
- 지우기: DELETE {base}/object/{bucket}/{path}

저장소 키(`SUPABASE_SERVICE_ROLE_KEY`)는 두 모양이 있고 싣는 곳이 다르다.
- **secret key `sb_secret_…`**: 2025년 11월 뒤 만든 프로젝트에는 이것만 있다. `apikey` 머리값에만
  싣는다. `Authorization: Bearer`로만 보내면 저장소가 JWT로 읽으려다 `Invalid Compact JWS`로 거절한다.
  10/19 실제 프로젝트에서 Bearer만 400, apikey만 200, 같은 값을 둘 다 실으면 200이었다. Supabase
  안내가 apikey에만 실으라고 해서 그렇게 한다
- **예전 service_role 키(JWT `eyJ…`)**: `apikey`와 `Authorization: Bearer` 둘 다 싣는다

저장소 키는 DB 전체를 읽고 쓸 수 있는 값이라 응답·로그·오류 문구에 넣지 않는다. 머리값에 실을 수
없는 글자가 섞인 키는 없는 것으로 본다 — 보내다 깨지면 그 오류에 키가 그대로 실린다. 내려받기는
나중에 API가 만드는 5분짜리 서명 URL로만 한다(포스터 추출에서 쓴다).
"""

import re
from typing import Annotated
from urllib.parse import quote

import httpx
import jwt
from fastapi import Depends

from app.config import Settings, get_settings

TIMEOUT_SECONDS = 60.0  # 20MB까지 올라온다
NEW_KEY_PREFIX = "sb_"  # Supabase 새 API 키(sb_secret_·sb_publishable_). JWT가 아니다
KEY_SHAPE = re.compile(r"[A-Za-z0-9._-]+")  # 새 키와 JWT가 쓰는 글자. 이 밖의 글자는 머리값을 깬다
SECRET_SHAPE = re.compile(r"sb_secret_[A-Za-z0-9_-]{20,}")  # 실제 키는 접두 뒤가 30자 남짓이다
REASON_LIMIT = 120  # 거절 이유는 이만큼만 남긴다
MISSING = (
    "SUPABASE_SERVICE_ROLE_KEY·SUPABASE_URL이 있어야 포스터를 올리고 공지 첨부를 저장할 수 있어요"
)
WHERE = "Supabase 대시보드 Project Settings > API Keys의 Secret keys 값(sb_secret_…)을 넣으세요"


class StorageError(Exception):
    """저장소에 올리지 못했다. 설정이 비었을 때도 이 오류다(키·주소는 담지 않는다)."""


class SupabaseStorage:
    def __init__(self, *, base_url: str, bucket: str, service_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.bucket = bucket
        self.service_key = service_key

    @property
    def ready(self) -> bool:
        """주소·버킷·키가 모두 있어야 올릴 수 있다. 키 모양이 아니면(빈칸·따옴표 등) 없는 것으로 본다."""
        return bool(self.base_url and self.bucket and KEY_SHAPE.fullmatch(self.service_key))

    def _url(self, path: str) -> str:
        quoted = quote(path, safe="/")
        return f"{self.base_url}/object/{quote(self.bucket, safe='')}/{quoted}"

    def _key_headers(self) -> dict[str, str]:
        """저장소 키를 싣는 머리값. 새 키는 `apikey`에만, 예전 JWT 키는 `Authorization`에도."""
        if self.service_key.startswith(NEW_KEY_PREFIX):
            return {"apikey": self.service_key}
        return {"apikey": self.service_key, "Authorization": f"Bearer {self.service_key}"}

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        await self._send("POST", path, content=data, content_type=content_type)

    async def download(self, path: str) -> bytes:
        """올려 둔 파일을 다시 받는다(포스터를 모델에 넘길 때). 없으면 StorageError다."""
        body = await self._send("GET", path)
        if not body:
            raise StorageError("파일 저장소에 그 파일이 없어요.")
        return body

    async def remove(self, path: str) -> None:
        """올려 둔 파일을 지운다(기록을 남기지 못했을 때 되돌리기용). 없으면 그냥 지나간다."""
        await self._send("DELETE", path, gone_is_ok=True)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        content: bytes | None = None,
        content_type: str | None = None,
        gone_is_ok: bool = False,
    ) -> bytes:
        if not self.ready:
            raise StorageError(
                "파일 저장소 설정이 비었거나 키 모양이 아니에요(SUPABASE_SERVICE_ROLE_KEY)."
            )
        headers = self._key_headers()
        if content_type:
            headers["Content-Type"] = content_type
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.request(
                    method, self._url(path), content=content, headers=headers
                )
        except httpx.HTTPError as exc:
            raise StorageError(f"파일 저장소에 닿지 못했어요: {type(exc).__name__}") from exc
        except UnicodeEncodeError:
            # 머리값(LMS가 준 Content-Type 등)에 ASCII가 아닌 글자가 있었다. 원래 오류는 그 값을
            # 통째로 들고 있어서 잇지 않는다
            raise StorageError("파일 저장소에 보낼 머리값에 쓸 수 없는 글자가 있어요.") from None
        if gone_is_ok and response.status_code in (404, 410):
            return b""
        if response.status_code >= 400:
            reason = _reason(response, self.service_key)
            detail = f"{response.status_code}, {reason}" if reason else str(response.status_code)
            raise StorageError(f"파일 저장소가 요청을 거절했어요({detail}).")
        return response.content


def _reason(response: httpx.Response, key: str) -> str:
    """Supabase가 준 거절 이유(JSON의 `code`·`message`). JSON이 아니면 빈 문자열이다.

    오류 문구를 거쳐 로그에만 남는다(사용자에게는 정해 둔 문구가 간다). 키가 섞여 있으면 가리고,
    줄바꿈을 펴고, 길이를 자른다.
    """
    try:
        body = response.json()
    except (ValueError, RecursionError):  # JSON이 아니거나, 너무 깊게 겹쳐 있다
        return ""
    if not isinstance(body, dict):
        return ""
    parts = [body.get("code"), body.get("message")]
    text = ": ".join(part for part in parts if isinstance(part, str) and part.strip())
    if key:
        text = text.replace(key, "[가림]")
    return " ".join(text.split())[:REASON_LIMIT]


def storage_settings_problem(settings: Settings) -> str | None:
    """파일 저장소 설정에서 고칠 점. 없으면 None이다. 앱을 시작할 때 본다.

    키 값은 보여 주지 않고 모양만 본다. 프로젝트 ID나 publishable key를 넣으면 올릴 때마다 400으로
    거절되는데, 그때는 원인이 잘 안 보인다(10/19에 둘 다 겪었다). 어떤 값이 와도 예외를 내지 않는다 —
    여기서 터지면 서버가 뜨지 않는다.
    """
    key = settings.supabase_service_role_key.strip()
    if not key or not settings.storage_base_url:
        return MISSING
    if not settings.supabase_storage_bucket.strip():
        return "SUPABASE_STORAGE_BUCKET이 비어 있어요. 대시보드 Storage에서 만든 비공개 버킷 이름을 넣으세요"
    if not KEY_SHAPE.fullmatch(key):
        return (
            "SUPABASE_SERVICE_ROLE_KEY에 빈칸·따옴표·보이지 않는 글자처럼 키에 없는 글자가 섞여 있어요"
            "(값은 보여 주지 않음). 복사 버튼으로 다시 복사해 넣으세요"
        )
    if key.startswith("sb_secret_"):
        if SECRET_SHAPE.fullmatch(key):
            return None
        return f"SUPABASE_SERVICE_ROLE_KEY의 secret key가 너무 짧아요(잘려서 복사된 것 같아요). {WHERE}"
    if key.startswith("sb_publishable_"):
        return (
            "SUPABASE_SERVICE_ROLE_KEY에 publishable key가 들어 있어요. 권한이 없어 파일을 못"
            f" 올려요. {WHERE}"
        )
    try:
        claims = jwt.decode(key, options={"verify_signature": False})
    except (jwt.PyJWTError, ValueError, RecursionError):
        return f"SUPABASE_SERVICE_ROLE_KEY가 키 모양이 아니에요(값은 보여 주지 않음). {WHERE}"
    if claims.get("role") != "service_role":
        return f"SUPABASE_SERVICE_ROLE_KEY가 service_role 키가 아니에요(anon 키 같은 것). {WHERE}"
    return None


def get_storage(settings: Annotated[Settings, Depends(get_settings)]) -> SupabaseStorage:
    return SupabaseStorage(
        base_url=settings.storage_base_url,
        bucket=settings.supabase_storage_bucket,
        service_key=settings.supabase_service_role_key.strip(),
    )


StorageDep = Annotated[SupabaseStorage, Depends(get_storage)]
