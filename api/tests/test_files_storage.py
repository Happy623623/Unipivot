"""Supabase Storage 클라이언트(F-13). HTTP는 respx로 가로챈다.

키 모양에 따라 싣는 곳이 다르다(10/19 실제 프로젝트에서 확인). 새 secret key(`sb_secret_…`)는
`apikey`에만 싣고, 예전 service_role 키(JWT)는 `apikey`와 `Authorization` 둘 다에 싣는다. 거절되면
Supabase가 준 이유를 오류 문구에 남기되 키는 넣지 않는다. 머리값에 못 싣는 글자가 섞인 키는 보내지
않는다(보내다 깨지면 그 오류에 키가 실린다). 시작할 때는 키 모양을 보고 고칠 점을 알린다.
"""

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
    WHERE,
    StorageError,
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


@respx.mock
async def test_remove_passes_over_a_file_that_is_already_gone() -> None:
    respx.delete(OBJECT).mock(return_value=httpx.Response(404))
    await storage().remove(PATH)


@respx.mock
async def test_remove_raises_on_anything_else() -> None:
    respx.delete(OBJECT).mock(return_value=httpx.Response(500))
    with pytest.raises(StorageError):
        await storage().remove(PATH)


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


def test_an_empty_bucket_is_named_at_startup() -> None:
    settings = Settings(
        supabase_url=PROJECT_URL, supabase_service_role_key=SECRET, supabase_storage_bucket=" "
    )
    assert storage_settings_problem(settings) == (
        "SUPABASE_STORAGE_BUCKET이 비어 있어요. 대시보드 Storage에서 만든 비공개 버킷 이름을 넣으세요"
    )


@pytest.mark.parametrize(
    ("key", "shown"),
    [
        (
            PUBLISHABLE,
            "파일 저장소 설정 확인: SUPABASE_SERVICE_ROLE_KEY에 publishable key가 들어 있어요",
        ),
        ("", f"파일 저장소 설정 확인: {MISSING}"),
        (SECRET, None),
    ],
)
def test_startup_says_what_to_fix_in_the_storage_settings(
    caplog: pytest.LogCaptureFixture, key: str, shown: str | None
) -> None:
    """서버를 켤 때 바로 알린다(.env를 고치면 다시 켠다). 키 값은 로그에 남기지 않는다."""
    settings = Settings(
        database_url="",
        supabase_url=PROJECT_URL,
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


def test_the_hint_survives_log_redaction_but_a_real_secret_does_not() -> None:
    assert redact(WHERE) == WHERE
    assert SECRET not in redact(f"apikey: {SECRET}")
