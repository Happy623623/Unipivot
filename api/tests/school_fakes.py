"""학교 사이트(www.hanyang.ac.kr)를 흉내 낸다. 학생이 붙인 공지 링크(B안)를 읽는 시험이 쓴다.

httpx.MockTransport라 네트워크를 쓰지 않는다. 받은 요청을 모두 적어 두어 "학교 서버에 몇 번 물었는지"를 본다.
"""

from collections.abc import Callable

import httpx

from app.crawl.link import VIEW_URL
from tests.hanyang_pages import file_url

SITE = "https://www.hanyang.ac.kr"
Answer = Callable[
    [httpx.Request], httpx.Response
]  # 요청마다 새 응답을 만든다(응답은 한 번만 읽힌다)


def permalink(entry_id: int) -> str:
    return f"{SITE}/notice/url/4a4/{entry_id:x}"


def view_link(entry_id: int) -> str:
    """목록에서 글을 누르면 열리는 주소(주소창에 보이는 것)."""
    return VIEW_URL.format(entry_id=entry_id)


def download(name: str, uuid: str) -> str:
    """페이지의 첨부 링크가 가리키는 주소(HTML의 &amp;를 푼 것)."""
    return file_url(name, uuid).replace("&amp;", "&")


class FakeSchool:
    def __init__(self) -> None:
        self.routes: dict[str, Answer] = {}
        self.requests: list[httpx.Request] = []

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def notice(self, entry_id: int, html: str) -> None:
        """공지 페이지. 고유 주소와 보기 주소 모두 같은 페이지를 준다."""
        for url in (permalink(entry_id), view_link(entry_id)):
            self.answer(url, 200, html.encode(), "text/html;charset=UTF-8")

    def file(self, url: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.answer(url, 200, data, content_type)

    def answer(self, url: str, status: int, data: bytes = b"", content_type: str = "") -> None:
        headers = {"content-type": content_type} if content_type else {}
        self.routes[url] = lambda _request: httpx.Response(status, content=data, headers=headers)

    def asked(self, prefix: str = SITE) -> list[str]:
        return [
            str(request.url) for request in self.requests if str(request.url).startswith(prefix)
        ]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.routes.get(str(request.url))
        if answer is None:
            return httpx.Response(404, text="없는 주소")
        return answer(request)
