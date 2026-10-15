"""Supabase Storage 클라이언트(F-13). HTTP는 respx로 가로챈다."""

import httpx
import pytest
import respx

from app.config import Settings
from app.uploads.storage import StorageError, SupabaseStorage, get_storage

pytestmark = pytest.mark.anyio

BASE = "https://storage.test/storage/v1"
KEY = "service-role-key-for-tests-only"
OBJECT = f"{BASE}/object/uploads/user-1/poster/file-1.jpg"


def storage(**over: str) -> SupabaseStorage:
    fields = {"base_url": BASE, "bucket": "uploads", "service_key": KEY} | over
    return SupabaseStorage(**fields)  # type: ignore[arg-type]


@respx.mock
async def test_upload_puts_the_bytes_in_the_user_folder() -> None:
    route = respx.post(OBJECT).mock(return_value=httpx.Response(200, json={"Key": "uploads/…"}))
    await storage().upload("user-1/poster/file-1.jpg", b"\xff\xd8\xffbytes", "image/jpeg")
    request = route.calls.last.request
    assert request.content == b"\xff\xd8\xffbytes"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["content-type"] == "image/jpeg"


@respx.mock
async def test_a_refusal_becomes_a_storage_error_without_the_key_in_it() -> None:
    respx.post(OBJECT).mock(return_value=httpx.Response(403, text=f"bad key {KEY}"))
    with pytest.raises(StorageError) as caught:
        await storage().upload("user-1/poster/file-1.jpg", b"x", "image/jpeg")
    assert "403" in str(caught.value)
    assert KEY not in str(caught.value)


@respx.mock
async def test_not_reaching_the_storage_is_a_storage_error() -> None:
    respx.post(OBJECT).mock(side_effect=httpx.ConnectError("끊김"))
    with pytest.raises(StorageError):
        await storage().upload("user-1/poster/file-1.jpg", b"x", "image/jpeg")


@respx.mock
async def test_remove_passes_over_a_file_that_is_already_gone() -> None:
    respx.delete(OBJECT).mock(return_value=httpx.Response(404))
    await storage().remove("user-1/poster/file-1.jpg")


@respx.mock
async def test_remove_raises_on_anything_else() -> None:
    respx.delete(OBJECT).mock(return_value=httpx.Response(500))
    with pytest.raises(StorageError):
        await storage().remove("user-1/poster/file-1.jpg")


@respx.mock
async def test_empty_settings_fail_before_any_request() -> None:
    route = respx.post(OBJECT).mock(return_value=httpx.Response(200))
    for empty in ({"service_key": ""}, {"bucket": ""}, {"base_url": ""}):
        assert not storage(**empty).ready
        with pytest.raises(StorageError):
            await storage(**empty).upload("user-1/poster/file-1.jpg", b"x", "image/jpeg")
    assert not route.called


def test_the_base_url_comes_from_supabase_url_unless_a_test_one_is_set() -> None:
    settings = Settings(supabase_url="https://ref.supabase.co", supabase_service_role_key=KEY)
    assert get_storage(settings).base_url == "https://ref.supabase.co/storage/v1"
    assert get_storage(settings).bucket == "uploads"
    settings = settings.model_copy(update={"supabase_storage_base": BASE + "/"})
    assert get_storage(settings).base_url == BASE
    assert get_storage(Settings(supabase_url="")).base_url == ""
