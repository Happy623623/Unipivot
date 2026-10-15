"""Supabase Storage 업로드 (F-13).

버킷은 비공개다(ERD 8장). 클라이언트는 버킷에 직접 닿지 못하고, 서버가 서비스 역할 키로만 올린다.
경로는 `<user_id>/<kind>/<file_id>.<확장자>`다.

- 올리기: POST {base}/object/{bucket}/{path} (본문은 파일 바이트 그대로)
- 지우기: DELETE {base}/object/{bucket}/{path}

서비스 역할 키는 DB 전체를 읽고 쓸 수 있는 값이라 응답·로그·오류 문구에 넣지 않는다. 내려받기는
나중에 API가 만드는 5분짜리 서명 URL로만 한다(포스터 추출에서 쓴다).
"""

from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import Depends

from app.config import Settings, get_settings

TIMEOUT_SECONDS = 60.0  # 20MB까지 올라온다


class StorageError(Exception):
    """저장소에 올리지 못했다. 설정이 비었을 때도 이 오류다(키·주소는 담지 않는다)."""


class SupabaseStorage:
    def __init__(self, *, base_url: str, bucket: str, service_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.bucket = bucket
        self.service_key = service_key

    @property
    def ready(self) -> bool:
        """주소·버킷·키가 모두 있어야 올릴 수 있다."""
        return bool(self.base_url and self.bucket and self.service_key)

    def _url(self, path: str) -> str:
        quoted = quote(path, safe="/")
        return f"{self.base_url}/object/{quote(self.bucket, safe='')}/{quoted}"

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        await self._send("POST", path, content=data, content_type=content_type)

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
    ) -> None:
        if not self.ready:
            raise StorageError("파일 저장소 설정이 비었어요(SUPABASE_SERVICE_ROLE_KEY).")
        headers = {"Authorization": f"Bearer {self.service_key}"}
        if content_type:
            headers["Content-Type"] = content_type
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.request(
                    method, self._url(path), content=content, headers=headers
                )
        except httpx.HTTPError as exc:
            raise StorageError(f"파일 저장소에 닿지 못했어요: {type(exc).__name__}") from exc
        if gone_is_ok and response.status_code in (404, 410):
            return
        if response.status_code >= 400:
            raise StorageError(f"파일 저장소가 요청을 거절했어요({response.status_code}).")


def get_storage(settings: Annotated[Settings, Depends(get_settings)]) -> SupabaseStorage:
    return SupabaseStorage(
        base_url=settings.storage_base_url,
        bucket=settings.supabase_storage_bucket,
        service_key=settings.supabase_service_role_key,
    )


StorageDep = Annotated[SupabaseStorage, Depends(get_storage)]
