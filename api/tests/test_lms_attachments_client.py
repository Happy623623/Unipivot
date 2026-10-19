"""공지 첨부 받기(F-54): `LearningXClient.attachment`. HTTP는 respx로 가로챈다.

10/19 녹화의 흐름을 그대로 흉내 낸다: 첨부 주소(verifier 포함) → 302 → 파일 저장소 서명 주소 → 200.
토큰만으로 받으려 하면 LearningX가 `/login`으로 302를 준다.
"""

import logging

import httpx
import pytest
import respx

from app.lms.client import (
    MAX_REDIRECTS,
    AttachmentTooLarge,
    AttachmentUnavailable,
    LearningXClient,
)
from app.logging_redact import install_log_redaction
from tests.lms_samples import GUIDE_FILE_ID, attachment

pytestmark = pytest.mark.anyio

BASE = "https://lms.test"
URL = attachment()["url"]  # https://lms.test/files/11637886/download?download_frd=1&verifier=…
STORE = "https://kr.object.storage.test/canvas/11637886/ERICA-projects-guide-v2.json"
SIGNED = f"{STORE}?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIAEXAMPLE%2F20261019&X-Amz-Signature=deadbeef1234"
BODY = b'{"projects": []}'


def client() -> LearningXClient:
    return LearningXClient(api_base=BASE, timeout=2.0)


def file_route(router: respx.MockRouter, body: bytes = BODY, **headers: str) -> respx.Route:
    router.get(URL).mock(httpx.Response(302, headers={"Location": SIGNED}))
    return router.get(STORE).mock(
        httpx.Response(200, content=body, headers={"Content-Type": "application/json", **headers})
    )


async def test_it_follows_the_store_redirect_without_any_token() -> None:
    with respx.mock(assert_all_called=True) as router:
        stored = file_route(router)
        got = await client().attachment(URL, max_bytes=1000)
        # 블록 안에서 본다 — 블록을 나가면 respx가 기록을 비워 아래 반복이 아무것도 보지 않는다
        sent = [call.request for call in router.calls]
    assert got.data == BODY and got.content_type == "application/json"
    assert len(sent) == 2  # 첫 요청(LearningX)과 둘째(저장소)
    for request in sent:
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
    assert stored.calls[0].request.url.params["X-Amz-Signature"] == "deadbeef1234"


async def test_only_our_download_path_is_fetched() -> None:
    """공지 응답의 주소라도 우리 LearningX의 `/files/{id}/download`가 아니면 보내기 전에 거절한다."""
    with respx.mock(assert_all_called=False) as router:
        anything = router.route().mock(httpx.Response(200, content=BODY))
        for url in (
            f"https://evil.test/files/{GUIDE_FILE_ID}/download?verifier=x",  # 남의 호스트
            f"http://lms.test/files/{GUIDE_FILE_ID}/download?verifier=x",  # 평문
            f"{BASE}/api/v1/courses/1/users",  # 허용 경로가 아니다
            f"{BASE}/files/{GUIDE_FILE_ID}",  # 받기 경로가 아니다
            f"{BASE}/files/abc/download?verifier=x",
        ):
            with pytest.raises(AttachmentUnavailable):
                await client().attachment(url, max_bytes=1000)
    assert not anything.called


async def test_a_redirect_to_the_login_page_is_a_failure() -> None:
    """verifier가 맞지 않으면 LearningX는 `/login`으로 보낸다(녹화 ④). 그 화면을 첨부로 저장하지 않는다."""
    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(httpx.Response(302, headers={"Location": "/login"}))
        login = router.get(f"{BASE}/login").mock(httpx.Response(200, html="<html>로그인</html>"))
        with pytest.raises(AttachmentUnavailable, match="로그인"):
            await client().attachment(URL, max_bytes=1000)
    assert not login.called


async def test_a_downgrade_to_plain_http_is_refused() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(
            httpx.Response(302, headers={"Location": "http://kr.object.storage.test/x"})
        )
        plain = router.get("http://kr.object.storage.test/x").mock(httpx.Response(200))
        with pytest.raises(AttachmentUnavailable, match="안전하지"):
            await client().attachment(URL, max_bytes=1000)
    assert not plain.called


async def test_it_gives_up_after_a_few_redirects() -> None:
    hops = [f"https://kr.object.storage.test/hop{index}" for index in range(MAX_REDIRECTS + 1)]
    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(httpx.Response(302, headers={"Location": hops[0]}))
        for here, there in zip(hops, hops[1:], strict=False):
            router.get(here).mock(httpx.Response(302, headers={"Location": there}))
        last = router.get(hops[-1]).mock(httpx.Response(200, content=BODY))
        with pytest.raises(AttachmentUnavailable, match="여러 번"):
            await client().attachment(URL, max_bytes=1000)
    assert not last.called
    # 세 번까지는 따라간다(녹화는 한 번)
    with respx.mock(assert_all_called=True) as router:
        router.get(URL).mock(httpx.Response(302, headers={"Location": hops[0]}))
        for here, there in zip(hops[:2], hops[1:3], strict=True):
            router.get(here).mock(httpx.Response(302, headers={"Location": there}))
        router.get(hops[2]).mock(httpx.Response(200, content=BODY))
        assert (await client().attachment(URL, max_bytes=1000)).data == BODY


async def test_a_web_page_instead_of_the_file_is_a_failure() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(httpx.Response(302, headers={"Location": SIGNED}))
        router.get(STORE).mock(
            httpx.Response(
                200, content=b"<html>", headers={"Content-Type": "text/html; charset=utf-8"}
            )
        )
        with pytest.raises(AttachmentUnavailable, match="웹 페이지"):
            await client().attachment(URL, max_bytes=1000)
        # 첨부 자체가 HTML이면 받는다
        got = await client().attachment(URL, max_bytes=1000, html_ok=True)
    assert got.data == b"<html>"


async def test_errors_from_the_store_are_failures() -> None:
    for status in (403, 404, 500):
        with respx.mock(assert_all_called=False) as router:
            router.get(URL).mock(httpx.Response(302, headers={"Location": SIGNED}))
            router.get(STORE).mock(httpx.Response(status))
            with pytest.raises(AttachmentUnavailable, match=str(status)):
                await client().attachment(URL, max_bytes=1000)
    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(AttachmentUnavailable, match="연결 오류"):
            await client().attachment(URL, max_bytes=1000)
    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(httpx.Response(302))  # 갈 곳이 없다
        with pytest.raises(AttachmentUnavailable, match="갈 곳"):
            await client().attachment(URL, max_bytes=1000)


async def test_a_file_over_the_limit_stops_before_it_is_kept() -> None:
    """목록의 크기와 달리 실제 파일이 상한을 넘으면 받다가 멈춘다(길이 헤더가 있든 없든)."""
    with respx.mock(assert_all_called=False) as router:
        file_route(router, body=b"x" * 11, **{"Content-Length": "11"})
        with pytest.raises(AttachmentTooLarge):
            await client().attachment(URL, max_bytes=10)
    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(httpx.Response(302, headers={"Location": SIGNED}))
        router.get(STORE).mock(
            httpx.Response(200, stream=httpx.ByteStream(b"x" * 11))  # 길이 헤더 없이
        )
        with pytest.raises(AttachmentTooLarge):
            await client().attachment(URL, max_bytes=10)
    with respx.mock(assert_all_called=False) as router:
        file_route(router, body=b"x" * 10)
        assert len((await client().attachment(URL, max_bytes=10)).data) == 10


async def test_the_keys_in_the_addresses_stay_out_of_the_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """httpx는 요청 주소를 INFO로 남긴다. verifier와 저장소 서명은 가려져야 한다."""
    install_log_redaction()
    caplog.set_level(logging.INFO)
    with respx.mock(assert_all_called=True) as router:
        file_route(router)
        await client().attachment(URL, max_bytes=1000)
    with respx.mock(assert_all_called=False) as router:
        router.get(URL).mock(httpx.Response(302, headers={"Location": SIGNED}))
        router.get(STORE).mock(httpx.Response(404))
        with pytest.raises(AttachmentUnavailable) as caught:
            await client().attachment(URL, max_bytes=1000)
    logged = caplog.text
    assert "HTTP Request" in logged  # 로그는 남는다(가려서)
    for secret in (f"v{GUIDE_FILE_ID}abc", "deadbeef1234", "AKIAEXAMPLE"):
        assert secret not in logged
        assert secret not in str(caught.value)
