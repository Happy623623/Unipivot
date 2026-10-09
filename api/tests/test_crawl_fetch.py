"""페이지 가져오기: robots.txt, 크기 상한, 한국어 인코딩. HTTP는 respx로 가로챈다."""

import httpx
import pytest
import respx

from app.crawl import FetchError, WebFetcher, decode_html

pytestmark = pytest.mark.anyio

SITE = "https://www.example.ac.kr"
ROBOTS = "User-agent: *\nDisallow: /admin/\n"


async def test_page_text_respects_robots_and_decodes_euc_kr() -> None:
    html = '<html><head><meta charset="euc-kr"></head><body><p>장학 안내</p></body></html>'
    with respx.mock(assert_all_called=True) as router:
        robots = router.get(f"{SITE}/robots.txt").mock(
            return_value=httpx.Response(200, text=ROBOTS)
        )
        page = router.get(f"{SITE}/notice/1").mock(
            return_value=httpx.Response(200, content=html.encode("cp949"))
        )
        fetcher = WebFetcher()
        assert await fetcher.page_text(f"{SITE}/notice/1") == "장학 안내"
        with pytest.raises(FetchError, match="robots.txt"):
            await fetcher.get(f"{SITE}/admin/secret")
        await fetcher.aclose()
        assert robots.call_count == 1  # robots.txt는 사이트마다 한 번만 읽는다
    assert page.calls[0].request.headers["user-agent"].startswith("UNIPIVOT-bot/")


@pytest.mark.parametrize(
    ("status", "allowed"),
    [(404, True), (403, False), (503, False)],
)
async def test_robots_status_codes(status: int, allowed: bool) -> None:
    with respx.mock() as router:
        router.get(f"{SITE}/robots.txt").mock(return_value=httpx.Response(status))
        fetcher = WebFetcher()
        assert await fetcher.allowed(f"{SITE}/notice/1") is allowed


async def test_unreachable_robots_blocks_the_site() -> None:
    with respx.mock() as router:
        router.get(f"{SITE}/robots.txt").mock(side_effect=httpx.ConnectError("down"))
        assert not await WebFetcher().allowed(f"{SITE}/notice/1")


async def test_size_limit_status_and_scheme() -> None:
    with respx.mock() as router:
        router.get(f"{SITE}/robots.txt").mock(return_value=httpx.Response(404))
        router.get(f"{SITE}/big").mock(return_value=httpx.Response(200, content=b"x" * 2048))
        router.get(f"{SITE}/gone").mock(return_value=httpx.Response(404))
        fetcher = WebFetcher(max_bytes=1024)
        with pytest.raises(FetchError, match="너무 커요"):
            await fetcher.get(f"{SITE}/big")
        with pytest.raises(FetchError, match="HTTP 404"):
            await fetcher.get(f"{SITE}/gone")
        with pytest.raises(FetchError, match="http"):
            await fetcher.get("file:///etc/passwd")


def test_decode_html_order() -> None:
    korean = "장학".encode("cp949")
    assert decode_html(korean, "text/html; charset=EUC-KR") == "장학"
    assert decode_html("장학".encode(), "text/html") == "장학"  # 선언이 없으면 UTF-8 먼저
    assert decode_html(korean, "") == "장학"  # UTF-8이 아니면 CP949
    assert decode_html("장학".encode(), "text/html; charset=nonsense") == "장학"


async def test_internal_addresses_are_refused_even_after_redirects() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{SITE}/robots.txt").mock(return_value=httpx.Response(404))
        router.get(f"{SITE}/go").mock(
            return_value=httpx.Response(302, headers={"Location": "http://169.254.169.254/latest"})
        )
        metadata = router.get("http://169.254.169.254/latest").mock(
            return_value=httpx.Response(200, text="secret")
        )
        fetcher = WebFetcher()
        with pytest.raises(FetchError, match="내부 주소"):
            await fetcher.get(f"{SITE}/go")
        assert metadata.call_count == 0
        for url in ("http://localhost:8000/admin", "http://10.0.0.5/", "http://[::1]/"):
            with pytest.raises(FetchError, match="내부 주소"):
                await fetcher.get(url)
