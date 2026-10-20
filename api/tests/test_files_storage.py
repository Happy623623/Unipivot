"""Supabase Storage 클라이언트(F-13). HTTP는 respx로 가로챈다.

키 모양에 따라 싣는 곳이 다르다(10/19 실제 프로젝트에서 확인). 새 secret key(`sb_secret_…`)는
`apikey`에만 싣고, 예전 service_role 키(JWT)는 `apikey`와 `Authorization` 둘 다에 싣는다. 거절되면
Supabase가 준 이유를 오류 문구에 남기되 키는 넣지 않는다. 머리값에 못 싣는 글자가 섞인 키는 보내지
않는다(보내다 깨지면 그 오류에 키가 실린다). 시작할 때는 키 모양을 보고 고칠 점을 알린다. 지우기는
이미 없는 파일(Supabase는 404가 아니라 400 `NoSuchKey`로 답한다)을 지나가지만, 버킷이 없으면 실패다.
받기 주소(F-44)는 저장소가 준 서명 경로에 `download`(원래 이름)를 붙인 것이다.
"""

import json
import logging

import httpx
import jwt
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Settings
from app.logging_redact import redact
from app.main import create_app
from app.uploads.storage import (
    MISSING,
    REASON_LIMIT,
    SIGNED_SECONDS,
    WHERE,
    StorageError,
    StorageMissing,
    SupabaseStorage,
    get_storage,
    storage_settings_problem,
)

pytestmark = pytest.mark.anyio

BASE = "https://storage.test/storage/v1"
KEY = "service-role-key-for-tests-only"
SECRET = "sb_secret_" + "Tq7" * 10 + "x"  # 새 키 모양(41자). 시험용 값이다
PUBLISHABLE = "sb_publishable_" + "Pk4" * 10 + "y"
LEGACY = jwt.encode({"iss": "supabase", "role": "service_role"}, "x" * 32, algorithm="HS256")
ANON = jwt.encode({"iss": "supabase", "role": "anon"}, "x" * 32, algorithm="HS256")
NOT_AN_OBJECT = jwt.api_jws.encode(
    b"[1, 2]", "x" * 32, algorithm="HS256"
)  # JWT 모양, payload는 배열
# 복사하다 섞이는 글자: 보이지 않는 빈칸, 둥근 따옴표, 가운데 줄바꿈·빈칸
DIRTY = [
    SECRET + "​",
    "“" + SECRET + "”",
    SECRET[:20] + "\n" + SECRET[20:],
    SECRET[:20] + " " + SECRET[20:],
]
PROJECT_URL = "https://abcdefghijklmnopqrst.supabase.co"
OBJECT = f"{BASE}/object/uploads/user-1/poster/file-1.jpg"
PATH = "user-1/poster/file-1.jpg"
# 10/19 실제 프로젝트가 secret key를 Bearer로 받았을 때 준 본문
REFUSED = {
    "statusCode": "403",
    "error": "Unauthorized",
    "message": "Invalid Compact JWS",
    "code": "AccessDenied",
}
# 10/19 실제 프로젝트가 이미 지운 파일을 또 지울 때 준 본문(HTTP 400)
NO_SUCH_KEY = {
    "statusCode": "404",
    "error": "not_found",
    "message": "Object not found",
    "code": "NoSuchKey",
}
NO_SUCH_BUCKET = {
    "statusCode": "404",
    "error": "Bucket not found",
    "message": "Bucket not found",
    "code": "NoSuchBucket",
}
# 주소가 틀려 저장소가 아닌 곳이 답한 404(흉내 낸 본문, 실측 아님). 경로가 붙은 SUPABASE_URL이면
# 게이트웨이나 PostgREST가 답한다. 이것을 "이미 없음"으로 받으면 탈퇴가 파일을 남긴 채 끝난다
NO_ROUTE = {"message": "no Route matched with those values"}
POSTGREST_PATH = {
    "code": "PGRST125",
    "details": None,
    "hint": None,
    "message": "Invalid path specified in request URL",
}


def storage(**over: str) -> SupabaseStorage:
    fields = {"base_url": BASE, "bucket": "uploads", "service_key": KEY} | over
    return SupabaseStorage(**fields)  # type: ignore[arg-type]


@respx.mock
async def test_upload_puts_the_bytes_in_the_user_folder() -> None:
    route = respx.post(OBJECT).mock(return_value=httpx.Response(200, json={"Key": "uploads/…"}))
    await storage().upload(PATH, b"\xff\xd8\xffbytes", "image/jpeg")
    request = route.calls.last.request
    assert request.content == b"\xff\xd8\xffbytes"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["apikey"] == KEY
    assert request.headers["content-type"] == "image/jpeg"


@pytest.mark.parametrize("action", ["upload", "download", "remove"])
@respx.mock
async def test_a_secret_key_goes_only_in_the_apikey_header(action: str) -> None:
    """Bearer로만 보내면 저장소가 JWT로 읽으려다 `Invalid Compact JWS`로 거절한다(10/19 실제)."""
    route = respx.route(url=OBJECT).mock(return_value=httpx.Response(200, content=b"data"))
    target = storage(service_key=SECRET)
    if action == "upload":
        await target.upload(PATH, b"x", "image/jpeg")
    elif action == "download":
        await target.download(PATH)
    else:
        await target.remove(PATH)
    request = route.calls.last.request
    assert request.headers["apikey"] == SECRET
    assert "authorization" not in request.headers


@respx.mock
async def test_a_legacy_service_role_key_goes_in_both_headers() -> None:
    route = respx.post(OBJECT).mock(return_value=httpx.Response(200))
    await storage(service_key=LEGACY).upload(PATH, b"x", "image/jpeg")
    request = route.calls.last.request
    assert request.headers["apikey"] == LEGACY
    assert request.headers["authorization"] == f"Bearer {LEGACY}"


@respx.mock
async def test_a_refusal_becomes_a_storage_error_without_the_key_in_it() -> None:
    respx.post(OBJECT).mock(return_value=httpx.Response(403, text=f"bad key {KEY}"))
    with pytest.raises(StorageError) as caught:
        await storage().upload(PATH, b"x", "image/jpeg")
    assert str(caught.value) == "파일 저장소가 요청을 거절했어요(403)."  # JSON이 아니면 상태만


@respx.mock
async def test_the_reason_supabase_gives_is_kept_in_the_error() -> None:
    """이유가 로그에 남아야 원인이 보인다(10/19에는 `400`만 남아 키 문제인 줄 몰랐다)."""
    respx.post(OBJECT).mock(return_value=httpx.Response(400, json=REFUSED))
    with pytest.raises(StorageError) as caught:
        await storage(service_key=SECRET).upload(PATH, b"x", "image/jpeg")
    assert str(caught.value) == (
        "파일 저장소가 요청을 거절했어요(400, AccessDenied: Invalid Compact JWS)."
    )


@respx.mock
async def test_the_reason_never_carries_the_key_and_stays_short() -> None:
    body = {"code": "Weird", "message": f"bad key {SECRET}\n" + "가" * 500}
    respx.post(OBJECT).mock(return_value=httpx.Response(400, json=body))
    with pytest.raises(StorageError) as caught:
        await storage(service_key=SECRET).upload(PATH, b"x", "image/jpeg")
    text = str(caught.value)
    assert SECRET not in text
    assert "Weird: bad key [가림] 가" in text
    assert "\n" not in text
    reason = text.removeprefix("파일 저장소가 요청을 거절했어요(400, ").removesuffix(").")
    assert len(reason) == REASON_LIMIT


@respx.mock
async def test_a_reason_with_only_a_message_is_kept_too() -> None:
    """publishable key로 올렸을 때처럼 이유만 있는 본문(10/19 실제)."""
    body = {"statusCode": "403", "message": "new row violates row-level security policy"}
    respx.post(OBJECT).mock(return_value=httpx.Response(400, json=body))
    with pytest.raises(StorageError) as caught:
        await storage(service_key=SECRET).upload(PATH, b"x", "image/jpeg")
    assert str(caught.value) == (
        "파일 저장소가 요청을 거절했어요(400, new row violates row-level security policy)."
    )


@pytest.mark.parametrize(
    "body",
    [
        b'["Invalid Compact JWS"]',  # 객체가 아니다
        b"<html>Bad Gateway</html>",  # JSON이 아니다
        b"[" * 100_000 + b"]" * 100_000,  # 너무 깊게 겹쳐 읽다가 터진다
    ],
    ids=["not-an-object", "html", "too-deep"],
)
@respx.mock
async def test_a_reason_that_cannot_be_read_is_left_out(body: bytes) -> None:
    respx.post(OBJECT).mock(return_value=httpx.Response(500, content=body))
    with pytest.raises(StorageError) as caught:
        await storage().upload(PATH, b"x", "image/jpeg")
    assert str(caught.value) == "파일 저장소가 요청을 거절했어요(500)."


@pytest.mark.parametrize("key", DIRTY, ids=["zwsp", "smart-quotes", "newline", "space"])
@respx.mock
async def test_a_key_a_header_cannot_carry_is_never_sent(key: str) -> None:
    """보내다 깨지면 그 오류(repr)에 키가 통째로 실려 로그·실행 기록에 남는다. 아예 보내지 않는다."""
    route = respx.route(url=OBJECT).mock(return_value=httpx.Response(200))
    target = storage(service_key=key)
    assert not target.ready
    with pytest.raises(StorageError) as caught:
        await target.upload(PATH, b"x", "image/jpeg")
    assert "키 모양이 아니에요" in str(caught.value)
    assert SECRET[:20] not in repr(caught.value)
    assert not route.called


@respx.mock
async def test_a_header_value_that_is_not_ascii_is_a_storage_error() -> None:
    """LMS가 이상한 Content-Type을 줘도 그 첨부 하나만 실패한다(다음 첨부는 계속 받는다)."""
    respx.post(OBJECT).mock(return_value=httpx.Response(200))
    with pytest.raises(StorageError) as caught:
        await storage(service_key=SECRET).upload(PATH, b"x", "application/pdf; name=계획서")
    assert str(caught.value) == "파일 저장소에 보낼 머리값에 쓸 수 없는 글자가 있어요."
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


@respx.mock
async def test_not_reaching_the_storage_is_a_storage_error() -> None:
    respx.post(OBJECT).mock(side_effect=httpx.ConnectError("끊김"))
    with pytest.raises(StorageError):
        await storage().upload(PATH, b"x", "image/jpeg")


@pytest.mark.parametrize(
    ("status", "body"),
    [(404, NO_SUCH_KEY), (400, NO_SUCH_KEY)],
    ids=["404-no-such-key", "supabase-400-no-such-key"],
)
@respx.mock
async def test_remove_passes_over_a_file_that_is_already_gone(
    status: int, body: dict[str, str]
) -> None:
    """탈퇴를 다시 누르면 앞서 지운 파일부터 다시 지운다. Supabase는 그때 400 `NoSuchKey`로 답한다.
    나중에 404로 바뀌어도 같은 `code`면 지나간다."""
    response = httpx.Response(status, json=body)
    respx.delete(OBJECT).mock(return_value=response)
    await storage(service_key=SECRET).remove(PATH)


@pytest.mark.parametrize(
    ("status", "body", "shown"),
    [
        (500, None, "(500)"),
        (400, NO_SUCH_BUCKET, "NoSuchBucket"),  # 버킷 이름이 틀렸다 — 지웠다고 하면 파일이 남는다
        (404, NO_SUCH_BUCKET, "NoSuchBucket"),
        (400, REFUSED, "Invalid Compact JWS"),  # 키 문제
        # code 없는 404·410: 저장소가 아닌 곳의 답일 수 있다 — "지웠다"고 하면 파일이 남는다
        (404, None, "(404)"),
        (410, None, "(410)"),
        (404, NO_ROUTE, "no Route matched"),
        (404, POSTGREST_PATH, "PGRST125"),
        (404, "<html><body>404 Not Found</body></html>", "(404)"),
    ],
    ids=[
        "500",
        "400-no-such-bucket",
        "404-no-such-bucket",
        "400-access-denied",
        "404",
        "410",
        "404-gateway",
        "404-postgrest",
        "404-html",
    ],
)
@respx.mock
async def test_remove_raises_on_anything_else(
    status: int, body: dict[str, str | None] | str | None, shown: str
) -> None:
    if isinstance(body, str):
        response = httpx.Response(status, text=body, headers={"Content-Type": "text/html"})
    else:
        response = httpx.Response(status, json=body) if body else httpx.Response(status)
    respx.delete(OBJECT).mock(return_value=response)
    with pytest.raises(StorageError) as caught:
        await storage(service_key=SECRET).remove(PATH)
    assert shown in str(caught.value)


@respx.mock
async def test_download_of_a_missing_file_is_still_an_error() -> None:
    """ "이미 없음"은 지우기에서만 받아 준다. 받기에서 없는 파일은 오류다(포스터를 모델에 못 넘긴다)."""
    respx.get(OBJECT).mock(return_value=httpx.Response(400, json=NO_SUCH_KEY))
    with pytest.raises(StorageMissing) as caught:
        await storage(service_key=SECRET).download(PATH)
    assert "NoSuchKey: Object not found" in str(caught.value)


# ── 받기 주소 (F-44) ──────────────────────────────────────────────────────────

SIGN = f"{BASE}/object/sign/uploads/{PATH}"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJ1cmwiOiJ1cGxvYWRzL3VzZXItMSJ9.c2lnbmF0dXJlLWZvci10ZXN0cw"
SIGNED = f"/object/sign/uploads/{PATH}?token={TOKEN}"  # 실제 저장소가 주는 모양(경로 + token)


@respx.mock
async def test_a_signed_url_opens_as_a_download_under_the_original_name() -> None:
    """`download`를 붙이면 저장소가 원래 이름으로 내려보낸다(Content-Disposition: attachment)."""
    route = respx.post(SIGN).mock(return_value=httpx.Response(200, json={"signedURL": SIGNED}))
    url = await storage(service_key=SECRET).signed_url(PATH, download_name="3주차 공지.pdf")
    assert url == f"{BASE}{SIGNED}&download=3%EC%A3%BC%EC%B0%A8%20%EA%B3%B5%EC%A7%80.pdf"
    request = route.calls.last.request
    assert json.loads(request.content) == {"expiresIn": SIGNED_SECONDS} == {"expiresIn": 300}
    assert request.headers["content-type"] == "application/json"
    assert request.headers["apikey"] == SECRET
    assert "authorization" not in request.headers


@respx.mock
async def test_every_mark_in_the_name_is_escaped() -> None:
    """`&`·`#`·`+`·`/`를 그대로 두면 이름이 잘리거나 다른 값이 된다."""
    respx.post(SIGN).mock(return_value=httpx.Response(200, json={"signedURL": SIGNED}))
    url = await storage(service_key=SECRET).signed_url(PATH, download_name="A&B #1+2/3?.pdf")
    assert url.endswith("&download=A%26B%20%231%2B2%2F3%3F.pdf")


@respx.mock
async def test_a_signed_url_without_a_name_opens_in_the_browser() -> None:
    """포스터 원본(W6)은 내려받지 않고 그대로 본다. `download`가 없으면 저장소가 attachment를 붙이지 않는다."""
    route = respx.post(SIGN).mock(return_value=httpx.Response(200, json={"signedURL": SIGNED}))
    url = await storage(service_key=SECRET).signed_url(PATH)
    assert url == f"{BASE}{SIGNED}"
    assert "download" not in url
    assert json.loads(route.calls.last.request.content) == {"expiresIn": 300}


@pytest.mark.parametrize(
    ("body", "shown"),
    [
        (b"<html>Bad Gateway</html>", "주지 않았어요"),
        (b'{"signedUrl": "/object/sign/uploads/p?token=t"}', "주지 않았어요"),  # 이름이 다르다
        (b'["/object/sign/uploads/p?token=t"]', "주지 않았어요"),
        (b'{"signedURL": 5}', "다른 것을 줬어요"),
        (b'{"signedURL": "https://elsewhere.test/object/sign/p?token=t"}', "다른 것을 줬어요"),
        (b'{"signedURL": "//elsewhere.test/object/sign/p?token=t"}', "다른 것을 줬어요"),
        (b'{"signedURL": "/object/sign/uploads/p"}', "다른 것을 줬어요"),  # token이 없다
        (b'{"signedURL": "/object/sign/uploads/p?token=t#x"}', "다른 것을 줬어요"),
        (b'{"signedURL": "/object/sign/uploads/p?token=t x"}', "다른 것을 줬어요"),
        (b'{"signedURL": "/object/sign/uploads/p?token=t\\n"}', "다른 것을 줬어요"),
        (b'{"signedURL": "/object/sign/uploads\\\\p?token=t"}', "다른 것을 줬어요"),
    ],
    ids=[
        "html",
        "other-key",
        "array",
        "not-text",
        "absolute",
        "scheme-relative",
        "no-token",
        "fragment",
        "space",
        "newline",
        "backslash",
    ],
)
@respx.mock
async def test_a_signed_path_we_cannot_trust_is_not_used(body: bytes, shown: str) -> None:
    """주소는 우리 저장소에만 열리고 `download`가 늘 저장소에 닿아야 한다. 받은 값은 문구에 넣지 않는다."""
    respx.post(SIGN).mock(return_value=httpx.Response(200, content=body))
    with pytest.raises(StorageError) as caught:
        await storage(service_key=SECRET).signed_url(PATH, download_name="a.pdf")
    assert shown in str(caught.value)
    assert "token" not in str(caught.value)


@pytest.mark.parametrize(
    ("status", "body", "missing"),
    [
        (400, NO_SUCH_KEY, True),  # 기록만 남고 파일은 지워졌다(10/19 실제 모양)
        (404, NO_SUCH_KEY, True),
        (400, NO_SUCH_BUCKET, False),
        (400, REFUSED, False),
        (404, None, False),  # 이유가 없으면 파일이 없다고 단정하지 않는다
    ],
    ids=["400-no-such-key", "404-no-such-key", "no-such-bucket", "access-denied", "plain-404"],
)
@respx.mock
async def test_signing_a_file_that_is_not_there_says_so(
    status: int, body: dict[str, str] | None, missing: bool
) -> None:
    response = httpx.Response(status, json=body) if body else httpx.Response(status)
    respx.post(SIGN).mock(return_value=response)
    with pytest.raises(StorageError) as caught:
        await storage(service_key=SECRET).signed_url(PATH, download_name="a.pdf")
    assert isinstance(caught.value, StorageMissing) is missing


@respx.mock
async def test_empty_settings_fail_before_any_request() -> None:
    route = respx.post(OBJECT).mock(return_value=httpx.Response(200))
    for empty in ({"service_key": ""}, {"bucket": ""}, {"base_url": ""}):
        assert not storage(**empty).ready
        with pytest.raises(StorageError):
            await storage(**empty).upload(PATH, b"x", "image/jpeg")
    assert not route.called
    blank = Settings(supabase_url=PROJECT_URL, supabase_service_role_key=" \n")
    assert not get_storage(blank).ready  # 빈칸뿐인 키는 없는 키다(동기화가 첨부를 건너뛴다)


def test_the_base_url_comes_from_supabase_url_unless_a_test_one_is_set() -> None:
    settings = Settings(supabase_url="https://ref.supabase.co", supabase_service_role_key=KEY)
    assert get_storage(settings).base_url == "https://ref.supabase.co/storage/v1"
    assert get_storage(settings).bucket == "uploads"
    settings = settings.model_copy(update={"supabase_storage_base": BASE + "/"})
    assert get_storage(settings).base_url == BASE
    assert get_storage(Settings(supabase_url="")).base_url == ""


def test_spaces_around_the_key_are_dropped() -> None:
    """따옴표 안에 빈칸이 붙으면 머리값이 깨져 요청이 나가지도 못한다."""
    settings = Settings(supabase_url=PROJECT_URL, supabase_service_role_key=f" {SECRET}\n")
    assert get_storage(settings).service_key == SECRET


@pytest.mark.parametrize(
    ("key", "url", "problem"),
    [
        (SECRET, PROJECT_URL, None),
        (f"  {SECRET}\n", PROJECT_URL, None),  # 앞뒤 빈칸은 떼고 본다
        (LEGACY, PROJECT_URL, None),
        ("", PROJECT_URL, MISSING),
        (" \n", PROJECT_URL, MISSING),
        (SECRET, "", MISSING),
        (PUBLISHABLE, PROJECT_URL, "publishable key가 들어 있어요"),
        ("abcdefghijklmnopqrst", PROJECT_URL, "키 모양이 아니에요"),  # 프로젝트 ID(10/19)
        ("a.b.c", PROJECT_URL, "키 모양이 아니에요"),
        (NOT_AN_OBJECT, PROJECT_URL, "키 모양이 아니에요"),
        (ANON, PROJECT_URL, "service_role 키가 아니에요"),
        ("sb_secret_", PROJECT_URL, "너무 짧아요"),
        (SECRET[:16], PROJECT_URL, "너무 짧아요"),  # 가려진 화면 글자만 옮겨 적었다
        *[(dirty, PROJECT_URL, "키에 없는 글자가 섞여 있어요") for dirty in DIRTY],
        ("abc\udcff", PROJECT_URL, "키에 없는 글자가 섞여 있어요"),  # UTF-8이 아닌 환경 변수
        # 주소 모양. 경로가 붙으면 저장소가 아닌 곳(게이트웨이·PostgREST)이 404로 답한다
        (SECRET, f"{PROJECT_URL}/", None),  # 끝의 /는 괜찮다
        (SECRET, "HTTPS://abcdefghijklmnopqrst.supabase.co", None),  # 대문자 스킴
        (SECRET, "https://abcdefghijklmnopqrst.supabase.co:443", None),  # 포트
        (SECRET, "https://supabase.my-school.ac.kr", None),  # 자체 도메인
        (SECRET, "http://127.0.0.1:54321", None),  # 로컬 Supabase CLI
        (SECRET, "https://[::1]:8000", None),  # IPv6
        (SECRET, f"{PROJECT_URL}/rest/v1", "경로가 붙어 있어요"),
        (SECRET, f"{PROJECT_URL}/storage/v1", "경로가 붙어 있어요"),  # 서버가 붙이는 경로다
        (SECRET, f"{PROJECT_URL}?x=1", "경로가 붙어 있어요"),
        (SECRET, "abcdefghijklmnopqrst.supabase.co", "https://로 시작하지 않아요"),
        (SECRET, "ftp://abcdefghijklmnopqrst.supabase.co", "https://로 시작하지 않아요"),
        (SECRET, "https://", "https://로 시작하지 않아요"),
        (SECRET, "https://<project-ref>.supabase.co", "예시 값이 남아 있어요"),
        (SECRET, "postgresql://postgres:pw-1234@db.ref.supabase.co:5432/postgres", "계정 정보(@)"),
        (SECRET, "https://[::1", "주소 모양이 아니에요"),
    ],
)
def test_storage_settings_problem(key: str, url: str, problem: str | None) -> None:
    found = storage_settings_problem(Settings(supabase_url=url, supabase_service_role_key=key))
    if problem is None:
        assert found is None
        return
    assert found is not None and problem in found
    if key.strip() not in ("", "sb_secret_"):  # 접두만 있는 값은 안내 문구에도 들어 있다
        assert key.strip() not in found  # 키 값은 보여 주지 않는다
    if problem in ("publishable key가 들어 있어요", "키 모양이 아니에요", "너무 짧아요"):
        assert WHERE in found  # 어디서 무엇을 가져올지 알려 준다
    assert (
        "abcdefghijklmnopqrst" not in found and "pw-1234" not in found
    )  # 주소 값도 보여 주지 않는다


@pytest.mark.parametrize(
    ("base", "problem"),
    [
        (BASE, None),
        ("http://127.0.0.1:54321/storage/v1", None),  # 가짜 저장소(시험)
        (
            "http://127.0.0.1:9999",
            None,
        ),  # 경로 없는 가짜 저장소도 된다 — 경로는 서버가 정하지 않는다
        ("127.0.0.1:54321/storage/v1", "https://로 시작하지 않아요"),
        ("https://user:pw@storage.test/storage/v1", "계정 정보(@)"),
        ("https://<storage>/storage/v1", "예시 값이 남아 있어요"),
        ("  ", "경로가 붙어 있어요"),  # 빈칸뿐이면 없는 것이라 SUPABASE_URL을 본다(틀린 값)
    ],
)
def test_a_separate_storage_base_is_checked_by_shape_but_may_have_a_path(
    base: str, problem: str | None
) -> None:
    """시험·개발용 저장소 주소(SUPABASE_STORAGE_BASE)를 넣었으면 그것을 본다. SUPABASE_URL은 안 본다."""
    settings = Settings(
        supabase_url=f"{PROJECT_URL}/rest/v1",  # 틀렸지만 저장소 주소를 따로 넣었으니 상관없다
        supabase_service_role_key=SECRET,
        supabase_storage_base=base,
    )
    found = storage_settings_problem(settings)
    if problem is None:
        assert found is None
    else:
        assert found is not None and problem in found
        assert found.startswith("SUPABASE_URL" if base.strip() == "" else "SUPABASE_STORAGE_BASE")
        assert "user:pw" not in found and "storage.test" not in found


def test_an_empty_bucket_is_named_at_startup() -> None:
    settings = Settings(
        supabase_url=PROJECT_URL, supabase_service_role_key=SECRET, supabase_storage_bucket=" "
    )
    assert storage_settings_problem(settings) == (
        "SUPABASE_STORAGE_BUCKET이 비어 있어요. 대시보드 Storage에서 만든 비공개 버킷 이름을 넣으세요"
    )


@pytest.mark.parametrize(
    ("key", "url", "shown"),
    [
        (
            PUBLISHABLE,
            PROJECT_URL,
            "파일 저장소 설정 확인: SUPABASE_SERVICE_ROLE_KEY에 publishable key가 들어 있어요",
        ),
        ("", PROJECT_URL, f"파일 저장소 설정 확인: {MISSING}"),
        (SECRET, PROJECT_URL, None),
        (
            SECRET,
            f"{PROJECT_URL}/rest/v1",
            "파일 저장소 설정 확인: SUPABASE_URL 값에 경로가 붙어 있어요",
        ),
    ],
)
def test_startup_says_what_to_fix_in_the_storage_settings(
    caplog: pytest.LogCaptureFixture, key: str, url: str, shown: str | None
) -> None:
    """서버를 켤 때 바로 알린다(.env를 고치면 다시 켠다). 키 값·주소 값은 로그에 남기지 않는다."""
    settings = Settings(
        database_url="",
        supabase_url=url,
        supabase_jwt_secret="legacy-secret-legacy-secret-legacy-secret",
        supabase_service_role_key=key,
    )
    with caplog.at_level(logging.WARNING, logger="app"), TestClient(create_app(settings)):
        pass  # 시작(lifespan)만 한다
    if shown is None:
        assert "파일 저장소 설정 확인" not in caplog.text
    else:
        assert shown in caplog.text
    if key:
        assert key not in caplog.text
    assert "abcdefghijklmnopqrst" not in caplog.text


def test_the_hint_survives_log_redaction_but_a_real_secret_does_not() -> None:
    assert redact(WHERE) == WHERE
    assert SECRET not in redact(f"apikey: {SECRET}")
