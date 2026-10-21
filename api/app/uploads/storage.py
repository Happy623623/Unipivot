"""Supabase Storage 업로드 (F-13).

버킷은 비공개다(ERD 8장). 클라이언트는 버킷에 직접 닿지 못하고, 서버가 저장소 키로만 올린다.
경로는 `<user_id>/<kind>/<file_id>.<확장자>`다.

- 올리기: POST {base}/object/{bucket}/{path} (본문은 파일 바이트 그대로)
- 받기: GET {base}/object/{bucket}/{path} (서버가 포스터를 모델에 넘길 때 쓴다)
- 지우기: DELETE {base}/object/{bucket}/{path} (이미 없는 파일은 400 `NoSuchKey`로 온다 — 지나간다.
  `code` 없는 404는 저장소의 답이 아닐 수 있어 지나가지 않는다)
- 받기 주소: POST {base}/object/sign/{bucket}/{path} → 5분짜리 서명 경로(문서함 받기 F-44, 포스터 원본 W6)

저장소 키(`SUPABASE_SERVICE_ROLE_KEY`)는 두 모양이 있고 싣는 곳이 다르다.
- **secret key `sb_secret_…`**: 2025년 11월 뒤 만든 프로젝트에는 이것만 있다. `apikey` 머리값에만
  싣는다. `Authorization: Bearer`로만 보내면 저장소가 JWT로 읽으려다 `Invalid Compact JWS`로 거절한다.
  10/19 실제 프로젝트에서 Bearer만 400, apikey만 200, 같은 값을 둘 다 실으면 200이었다. Supabase
  안내가 apikey에만 실으라고 해서 그렇게 한다
- **예전 service_role 키(JWT `eyJ…`)**: `apikey`와 `Authorization: Bearer` 둘 다 싣는다

저장소 키는 DB 전체를 읽고 쓸 수 있는 값이라 응답·로그·오류 문구에 넣지 않는다. 머리값에 실을 수
없는 글자가 섞인 키는 없는 것으로 본다 — 보내다 깨지면 그 오류에 키가 그대로 실린다. 브라우저 내려받기는
API가 만드는 5분짜리 서명 URL로만 한다(문서함, F-44). 그 주소도 열쇠라 저장하지도 로그에 남기지도 않는다.
"""

import json
import re
from typing import Annotated, Any
from urllib.parse import quote, urlsplit

import httpx
import jwt
from fastapi import Depends

from app.config import Settings, get_settings

TIMEOUT_SECONDS = 60.0  # 20MB까지 올라온다
NEW_KEY_PREFIX = "sb_"  # Supabase 새 API 키(sb_secret_·sb_publishable_). JWT가 아니다
KEY_SHAPE = re.compile(r"[A-Za-z0-9._-]+")  # 새 키와 JWT가 쓰는 글자. 이 밖의 글자는 머리값을 깬다
SECRET_SHAPE = re.compile(r"sb_secret_[A-Za-z0-9_-]{20,}")  # 실제 키는 접두 뒤가 30자 남짓이다
REASON_LIMIT = 120  # 거절 이유는 이만큼만 남긴다
SIGNED_SECONDS = 300  # 받기 주소 수명(명세 1장: 서명 URL은 5분)
LIST_PAGE = 100  # 목록 한 번에 받는 수(storage-js 기본값과 같다)
LIST_MAX_PAGES = (
    200  # 폴더 훑기 상한(한 번의 훑기에서 부르는 목록 수). 넘으면 멈춘다 — 끝없이 돌지 않게
)
LIST_MAX_DEPTH = 4  # <user_id>/<종류>/<파일>이라 2단이면 되지만 여유를 둔다
SIGNED_PREFIX = "/object/sign/"  # 저장소가 주는 서명 경로의 앞부분
MISSING = (
    "SUPABASE_SERVICE_ROLE_KEY·SUPABASE_URL이 있어야 포스터를 올리고 공지 첨부를 저장할 수 있어요"
)
WHERE = "Supabase 대시보드 Project Settings > API Keys의 Secret keys 값(sb_secret_…)을 넣으세요"


class StorageError(Exception):
    """저장소에 올리지 못했다. 설정이 비었을 때도 이 오류다(키·주소는 담지 않는다)."""


class StorageMissing(StorageError):
    """그 파일이 저장소에 없다(Supabase `NoSuchKey`). 기록만 남고 파일은 지워진 때다."""


class SupabaseStorage:
    def __init__(self, *, base_url: str, bucket: str, service_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.bucket = bucket
        self.service_key = service_key

    @property
    def ready(self) -> bool:
        """주소·버킷·키가 모두 있어야 올릴 수 있다. 키 모양이 아니면(빈칸·따옴표 등) 없는 것으로 본다."""
        return bool(self.base_url and self.bucket and KEY_SHAPE.fullmatch(self.service_key))

    def _url(self, path: str, action: str = "object") -> str:
        bucket = f"{self.base_url}/{action}/{quote(self.bucket, safe='')}"
        return f"{bucket}/{quote(path, safe='/')}" if path else bucket  # 목록은 버킷까지만

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
        """올려 둔 파일을 지운다(되돌리기·탈퇴). 이미 없으면(`NoSuchKey`) 그냥 지나간다 — 탈퇴를 다시
        누르면 앞서 지운 파일부터 다시 지우기 때문이다. 권한이 모자란 키(publishable 등)에도 저장소는 같은
        "없는 파일"로 답해서, 탈퇴는 지우기 전에 `storage_settings_problem`을 본다(app/account.py)."""
        await self._send("DELETE", path, gone_is_ok=True)

    async def list_paths(self, folder: str) -> list[str]:
        """`folder` 아래 파일 경로 전부(버킷 안 경로). 탈퇴가 기록이 없는 파일까지 지울 때 쓴다(app/account.py).

        Supabase 목록(`POST /object/list/{bucket}`)은 폴더 하나의 바로 아래만 준다. 폴더는 `id`가 없는 항목이라
        그 안으로 다시 들어간다(`LIST_MAX_DEPTH`단까지). `name`은 폴더 안의 이름이지만, 버킷 안 경로로 오더라도
        맞게 붙인다. 답한 경로가 `folder/`로 시작하지 않거나 `..`·빈 칸이 섞였으면 버린다(다른 사람 폴더를
        지우지 않게).
        """
        root = folder.strip("/")
        found: list[str] = []
        level, calls = [root], 0
        for _ in range(LIST_MAX_DEPTH):
            deeper: list[str] = []
            for current in level:
                offset = 0
                while True:
                    calls += 1
                    if calls > LIST_MAX_PAGES:
                        raise StorageError("파일 저장소 폴더가 너무 커서 다 훑지 못했어요.")
                    entries = await self._list(current, offset)
                    for name, is_folder in entries:
                        path = name if name.startswith(f"{current}/") else f"{current}/{name}"
                        parts = path.split("/")
                        if not path.startswith(f"{root}/") or {"", ".", ".."} & set(parts):
                            continue  # 내 폴더 밖이거나 경로 이동(..)이 섞였다
                        (deeper if is_folder else found).append(path)
                    if len(entries) < LIST_PAGE:
                        break
                    offset += LIST_PAGE
            if not deeper:
                return found
            level = deeper
        raise StorageError("파일 저장소 폴더가 너무 깊어 다 훑지 못했어요.")

    async def _list(self, folder: str, offset: int) -> list[tuple[str, bool]]:
        """폴더 바로 아래 항목 (이름, 폴더인지). storage-js `list`와 같은 본문을 보낸다."""
        body = json.dumps(
            {
                "prefix": folder,
                "limit": LIST_PAGE,
                "offset": offset,
                "sortBy": {"column": "name", "order": "asc"},
            }
        ).encode()
        raw = await self._send(
            "POST", "", content=body, content_type="application/json", action="object/list"
        )
        try:
            entries = json.loads(raw)
        except (ValueError, RecursionError):
            raise StorageError("파일 저장소의 목록 답이 JSON이 아니에요.") from None
        if not isinstance(entries, list):
            raise StorageError("파일 저장소의 목록 답 모양이 달라요.")
        parsed: list[tuple[str, bool]] = []
        for entry in entries:
            name = entry.get("name") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not name.strip("/"):
                raise StorageError("파일 저장소의 목록 답 모양이 달라요.")
            parsed.append((name.strip("/"), entry.get("id") is None))
        return parsed

    async def signed_url(
        self, path: str, *, download_name: str | None = None, seconds: int = SIGNED_SECONDS
    ) -> str:
        """`seconds`초 동안 열리는 주소. `download_name`을 주면 열 때 그 이름으로 내려받는다.

        `download`를 붙이면 저장소가 `Content-Disposition: attachment`로 준다(storage-js의 `download`
        선택과 같다). 공지 첨부는 형식을 가리지 않고 받아서, HTML·SVG가 브라우저에서 그대로 열리면 안
        된다 — 문서함 받기는 늘 이름을 넘긴다. 이름이 없으면 브라우저가 그대로 보여 주는 주소다(포스터
        원본, W6). 포스터는 올릴 때 바이트로 가린 사진·PDF만 받아서 그렇게 열어도 된다. 주소의 호스트는
        언제나 우리 저장소다 — 저장소가 준 것은 서명 경로뿐이다. 없는 파일이면 StorageMissing이다(서명할
        때 저장소가 파일을 찾아본다).
        """
        body = await self._send(
            "POST",
            path,
            content=json.dumps({"expiresIn": seconds}).encode(),
            content_type="application/json",
            action="object/sign",
        )
        signed = _signed_path(body)
        if download_name is None:
            return f"{self.base_url}{signed}"
        return f"{self.base_url}{signed}&download={quote(download_name, safe='')}"

    async def _send(
        self,
        method: str,
        path: str,
        *,
        content: bytes | None = None,
        content_type: str | None = None,
        gone_is_ok: bool = False,
        action: str = "object",
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
                    method, self._url(path, action), content=content, headers=headers
                )
        except httpx.HTTPError as exc:
            raise StorageError(f"파일 저장소에 닿지 못했어요: {type(exc).__name__}") from exc
        except UnicodeEncodeError:
            # 머리값(LMS가 준 Content-Type 등)에 ASCII가 아닌 글자가 있었다. 원래 오류는 그 값을
            # 통째로 들고 있어서 잇지 않는다
            raise StorageError("파일 저장소에 보낼 머리값에 쓸 수 없는 글자가 있어요.") from None
        if gone_is_ok and _gone(response):
            return b""
        if response.status_code >= 400:
            reason = _reason(response, self.service_key)
            detail = f"{response.status_code}, {reason}" if reason else str(response.status_code)
            error = StorageMissing if _missing(response) else StorageError
            raise error(f"파일 저장소가 요청을 거절했어요({detail}).")
        return response.content


def _body(response: httpx.Response) -> dict[str, Any]:
    """오류 본문(JSON 객체). JSON이 아니거나 객체가 아니면 빈 dict다."""
    try:
        body = response.json()
    except (ValueError, RecursionError):  # JSON이 아니거나, 너무 깊게 겹쳐 있다
        return {}
    return body if isinstance(body, dict) else {}


def _gone(response: httpx.Response) -> bool:
    """지우려던 파일이 이미 없다. 본문 `code`가 `NoSuchKey`일 때만이다. Supabase는 404가 아니라 400에
    `code: NoSuchKey`로 답한다(10/19 실제). 나중에 제대로 된 상태 번호(404·410)로 와도 같은 `code`면 받는다.

    `code`가 없는 404·410은 없는 것으로 보지 않는다. 주소가 틀려 저장소가 아닌 곳(API 게이트웨이·
    PostgREST·웹 서버)이 답한 것일 수 있다. 버킷이 없을 때(`NoSuchBucket`)도 같다. 그때 "지웠다"고 하면
    탈퇴한 사람의 파일이 남는다.
    """
    return response.status_code in (400, 404, 410) and _missing(response)


def _missing(response: httpx.Response) -> bool:
    """그 파일이 없다는 거절. 지금 Supabase는 400에 `code: NoSuchKey`로 준다(10/19 실제)."""
    return _body(response).get("code") == "NoSuchKey"


def _signed_path(body: bytes) -> str:
    """저장소가 준 서명 경로(`/object/sign/<버킷>/<경로>?token=…`). 그 모양이 아니면 StorageError다.

    뒤에 `&download=`를 붙이므로 `#`(뒤가 저장소에 가지 않는다)·빈칸·역슬래시가 있으면 쓰지 않는다.
    오류 문구에는 받은 값을 넣지 않는다 — 열쇠(token)가 들어 있다.
    """
    try:
        signed = json.loads(body)["signedURL"]
    except (ValueError, RecursionError, KeyError, TypeError):
        raise StorageError("파일 저장소가 받기 주소를 주지 않았어요.") from None
    if not (
        isinstance(signed, str)
        and signed.startswith(SIGNED_PREFIX)
        and "?token=" in signed
        and not any(ch.isspace() or ch in "\\#" for ch in signed)
    ):
        raise StorageError("파일 저장소가 받기 주소 대신 다른 것을 줬어요.")
    return signed


def _reason(response: httpx.Response, key: str) -> str:
    """Supabase가 준 거절 이유(JSON의 `code`·`message`). JSON이 아니면 빈 문자열이다.

    오류 문구를 거쳐 로그에만 남는다(사용자에게는 정해 둔 문구가 간다). 키가 섞여 있으면 가리고,
    줄바꿈을 펴고, 길이를 자른다.
    """
    body = _body(response)
    parts = [body.get("code"), body.get("message")]
    text = ": ".join(part for part in parts if isinstance(part, str) and part.strip())
    if key:
        text = text.replace(key, "[가림]")
    return " ".join(text.split())[:REASON_LIMIT]


def storage_settings_problem(settings: Settings) -> str | None:
    """파일 저장소 설정에서 고칠 점. 없으면 None이다. 앱을 시작할 때 보고, 저장소의 "없는 파일" 답을
    믿기 전에도 본다(받기 주소의 404, 탈퇴의 지우기).

    키 값은 보여 주지 않고 모양만 본다. 프로젝트 ID나 publishable key를 넣으면 올릴 때마다 400으로
    거절되는데, 그때는 원인이 잘 안 보인다(10/19에 둘 다 겪었다). 주소도 모양만 본다 — 경로가 붙은
    `SUPABASE_URL`(`…/rest/v1`)이면 저장소가 아닌 곳(API 게이트웨이)이 404로 답해서 역시 원인이 안 보인다.
    어떤 값이 와도 예외를 내지 않는다 — 여기서 터지면 서버가 뜨지 않는다.
    """
    key = settings.supabase_service_role_key.strip()
    if not key or not settings.storage_base_url:
        return MISSING
    if problem := _url_problem(settings):
        return problem
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


def _url_problem(settings: Settings) -> str | None:
    """저장소 주소에서 고칠 점. 값은 보여 주지 않는다(DB 주소를 잘못 넣으면 비밀번호가 들어 있다).

    `SUPABASE_STORAGE_BASE`를 따로 넣었으면(시험·개발용 가짜 저장소, 경로가 필요한 자체 호스팅) 그 값을,
    아니면 `SUPABASE_URL`을 본다. `SUPABASE_URL`은 프로젝트 주소(`https://<ref>.supabase.co`)여야 해서 경로가
    붙어 있으면 틀린 것이다 — `/storage/v1`은 서버가 붙인다. 따로 넣은 저장소 주소는 경로가 있을 수 있어
    경로는 보지 않는다.
    """
    base = settings.supabase_storage_base.strip()
    name = "SUPABASE_STORAGE_BASE" if base else "SUPABASE_URL"
    url = base or settings.supabase_url.strip()
    if "@" in url:
        return (
            f"{name} 값에 계정 정보(@)가 들어 있어요(값은 보여 주지 않음). DB 주소 대신 Supabase 프로젝트"
            " 주소(https://….supabase.co)를 넣으세요"
        )
    if "<" in url or ">" in url:
        return f"{name} 값에 예시 값이 남아 있어요(값은 보여 주지 않음). Supabase 프로젝트 주소로 바꾸세요"
    try:
        parts = urlsplit(url)
    except ValueError:
        return f"{name} 값이 주소 모양이 아니에요(값은 보여 주지 않음). Supabase 프로젝트 주소를 넣으세요"
    if parts.scheme.lower() not in ("https", "http") or not parts.netloc:
        return f"{name} 값이 https://로 시작하지 않아요(값은 보여 주지 않음). Supabase 프로젝트 주소를 넣으세요"
    # 빈 ?·#도 막는다(urlsplit은 비어 있으면 query·fragment를 ""로 줘서 못 본다). 뒤에 경로를 붙이면 쿼리가 된다
    if name == "SUPABASE_URL" and (parts.path.strip("/") or "?" in url or "#" in url):
        return (
            "SUPABASE_URL 값에 경로가 붙어 있어요(…/rest/v1 같은 것. 값은 보여 주지 않음). 프로젝트 주소"
            "(https://<ref>.supabase.co)만 넣으세요 — 저장소 경로는 서버가 붙여요. 경로가 꼭 필요한 자체"
            " 호스팅이면 SUPABASE_STORAGE_BASE에 저장소 주소(…/storage/v1)를 따로 넣으세요"
        )
    # 따로 넣은 저장소 주소도 뒤에 경로를 붙이므로 ?·#가 있으면 안 된다
    if "?" in url or "#" in url:
        return (
            f"{name} 값에 ?나 #가 들어 있어요(값은 보여 주지 않음)."
            " 저장소 주소(…/storage/v1)까지만 넣으세요"
        )
    return None


def get_storage(settings: Annotated[Settings, Depends(get_settings)]) -> SupabaseStorage:
    return SupabaseStorage(
        base_url=settings.storage_base_url,
        bucket=settings.supabase_storage_bucket,
        service_key=settings.supabase_service_role_key.strip(),
    )


StorageDep = Annotated[SupabaseStorage, Depends(get_storage)]
