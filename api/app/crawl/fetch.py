"""웹 페이지 가져오기. robots.txt를 지키고, 크기를 제한하고, 한국어 인코딩을 맞춘다.

요건 추출의 fetch_original(원문 다시 읽기)이 쓰고, 게시판 크롤러(S1-4 2부)도 이걸 쓴다.
robots.txt 처리(RFC 9309): 404 같은 4xx면 제한 없음, 5xx·연결 실패면 그 사이트 전체를 막힌 것으로 본다.
401·403은 표준 라이브러리처럼 막힌 것으로 본다. 리다이렉트로 옮겨 간 주소의 robots.txt는 다시 보지 않는다.
내부 주소(localhost, 사설·루프백·링크 로컬 IP)는 리다이렉트로 가는 것까지 막는다. 도메인 이름이
내부 IP를 가리키는 경우(DNS)는 막지 못하므로, 가져올 주소는 크롤러가 정한 학교 주소만 쓴다.
"""

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.attachments import html_text

USER_AGENT = "UNIPIVOT-bot/0.3 (student capstone project)"
MAX_BYTES = 5 * 1024 * 1024
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([A-Za-z0-9_-]+)""", re.IGNORECASE)


class FetchError(Exception):
    """가져오지 못함. 메시지는 사용자·모델에게 그대로 보여도 되는 한 줄이다."""


@dataclass(frozen=True)
class Fetched:
    url: str  # 리다이렉트 뒤 최종 주소
    content: bytes
    content_type: str


class WebFetcher:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        user_agent: str = USER_AGENT,
        max_bytes: int = MAX_BYTES,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=20, follow_redirects=True)
        hooks = self._client.event_hooks
        hooks["request"] = [*hooks.get("request", []), _guard]  # 리다이렉트마다 주소를 다시 본다
        self._client.event_hooks = hooks
        self._user_agent = user_agent
        self._max_bytes = max_bytes
        self._robots: dict[str, RobotFileParser] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str) -> Fetched:
        if not await self.allowed(url):
            raise FetchError("robots.txt가 허용하지 않는 주소예요")
        try:
            async with self._client.stream(
                "GET", url, headers={"User-Agent": self._user_agent}
            ) as response:
                if response.status_code >= 400:
                    raise FetchError(f"HTTP {response.status_code}")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise FetchError(f"너무 커요({self._max_bytes // 1024:,}KB 넘음)")
                    chunks.append(chunk)
                content_type = response.headers.get("content-type", "")
                return Fetched(str(response.url), b"".join(chunks), content_type)
        except httpx.HTTPError as exc:
            raise FetchError(f"연결 실패({type(exc).__name__})") from exc

    async def page_text(self, url: str) -> str:
        """HTML 페이지 → 글자(표는 "셀 | 셀")."""
        fetched = await self.get(url)
        return html_text(decode_html(fetched.content, fetched.content_type))

    async def __call__(self, url: str) -> str:
        return await self.page_text(url)

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise FetchError("http(s) 주소가 아니에요")
        _check_host(parts.hostname or "")
        origin = f"{parts.scheme}://{parts.netloc}"
        robots = self._robots.get(origin)
        if robots is None:
            robots = await self._load_robots(origin)
            self._robots[origin] = robots
        return robots.can_fetch(self._user_agent, url)

    async def _load_robots(self, origin: str) -> RobotFileParser:
        robots = RobotFileParser()
        try:
            response = await self._client.get(
                f"{origin}/robots.txt", headers={"User-Agent": self._user_agent}
            )
        except httpx.HTTPError:
            robots.disallow_all = True
            return robots
        if response.status_code >= 500 or response.status_code in (401, 403):
            robots.disallow_all = True  # 401·403은 표준 라이브러리(read)처럼 막힌 것으로 본다
        elif response.status_code >= 400:
            robots.allow_all = True
        else:
            robots.parse(response.text.splitlines())
        return robots


async def _guard(request: httpx.Request) -> None:
    _check_host(request.url.host)


def _check_host(host: str) -> None:
    host = host.strip("[]").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise FetchError("내부 주소는 가져오지 않아요")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return  # 도메인 이름
    if not address.is_global:
        raise FetchError("내부 주소는 가져오지 않아요")


def decode_html(content: bytes, content_type: str = "") -> str:
    """헤더의 charset → <meta charset> → UTF-8 → CP949(EUC-KR 상위 호환) 순서로 푼다."""
    declared = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
    meta = _META_CHARSET.search(content[:4096])
    for encoding in (
        declared.group(1) if declared else None,
        meta.group(1).decode("ascii") if meta else None,
    ):
        if encoding:
            try:
                return content.decode(_codec(encoding))
            except (LookupError, UnicodeDecodeError):
                pass
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp949", errors="replace")


def _codec(name: str) -> str:
    lowered = name.lower()
    return "cp949" if lowered in ("euc-kr", "euckr", "ks_c_5601-1987", "x-windows-949") else lowered
