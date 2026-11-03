"""학생이 붙인 한양대 공지 링크 한 건을 그 자리에서 읽는다(B안, PRD F-10).

학교 www의 robots.txt는 모든 수집기를 막는다(2026-10-08 확인). 그래서 목록을 훑거나 링크를 따라가며 모으지
않는다(A안은 팀이 브라우저로 저장한 페이지를 읽는다, app/crawl/saved.py). B안은 학생이 공지 주소를 붙여
"이 공지를 가져와 달라"고 할 때 **그 공지 한 건과 거기 걸린 첨부·본문 이미지만** 읽는다. 학생이 브라우저로 그
글을 여는 것과 같은 요청이라 자동 수집(robots.txt의 대상)으로 보지 않는다(11/2 결정). 대신 이것을 지킨다.

- 주소: www.hanyang.ac.kr의 공지 글 주소만 받는다 — 고유 주소(/notice/url/…)나 글 번호(entryId)가 든 주소.
  글 번호가 든 주소는 학생이 붙인 주소를 그대로 쓰지 않고 공지사항 보기 주소를 새로 만든다(VIEW_URL). 다른
  값(액션·검색어 등)을 학교 서버에 넘기지 않는다
- 공지 하나: 그 페이지와 페이지에 걸린 첨부·본문 이미지만 받는다. 목록·이전글·다음글은 따라가지 않는다
- 같은 공지는 한 번만: 이미 가져온 글이면 학교 서버에 묻지 않는다(app/crawl/service.py)
- 학교 서버에는 한 번에 하나씩, 앞 요청(따라간 리다이렉트까지)이 끝나고 MIN_INTERVAL초 뒤(LinkGate).
  같은 공지는 한 번에 한 실행만 읽고, 사용자당 하루 한도도 둔다(service)
- 리다이렉트도 학교 주소 안에서만. 페이지 5MB, 파일 하나 20MB(업로드 상한), 모두 합쳐 60MB, 첨부 10개,
  본문 이미지는 남길 것 10개(아이콘 크기는 세지 않는다)·묻는 것 20번까지, 같은 주소는 한 번만 받는다. 넘는 것은
  받지 않고 못 읽은 첨부로 남긴다(원문 확인 필요가 된다)
- 학교 서버가 잠시 답하지 않아(5xx·429·시간 초과·연결 실패) 첨부를 못 받으면 공고를 넣지 않고 실패로 끝낸다 —
  다시 붙이면 다시 읽는다. 지워진 파일(404)·너무 큰 파일처럼 다시 해도 같은 것만 못 읽은 첨부로 남긴다
- 누가 무엇 때문에 묻는지 알 수 있는 User-Agent(LINK_USER_AGENT, 서비스 주소를 적었다)

읽은 결과는 A안과 같은 모양(NoticeContent)이라 가져오기(app/crawl/importer.py)가 그대로 넣는다.
"""

import asyncio
import math
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import parse_qsl, urljoin, urlsplit

import httpx

from app.crawl.fetch import Fetched, FetchError, decode_html
from app.crawl.hanyang import SITE, NoticePage, NotNoticePage, body_text, parse_notice
from app.crawl.saved import (
    MIN_IMAGE_BYTES,
    BodyImage,
    NoticeContent,
    SavedFile,
    add_body_images,
    data_uri,
    url_name,
)
from app.uploads import MAX_BYTES

LINK_USER_AGENT = (
    "UNIPIVOT-link/0.3 (+https://unipivot.vercel.app/privacy;"
    " reads one notice a student asked for; student capstone project)"
)
SCHOOL_HOSTS = frozenset({"www.hanyang.ac.kr", "hanyang.ac.kr"})
MIN_INTERVAL = 1.0  # 학교 서버 요청 사이 초
TIMEOUT = 20  # 연결·읽기 한 번을 기다리는 초
TOTAL_TIMEOUT = 60  # 요청 하나(파일을 다 받기까지)의 전체 초. 넘으면 그 파일은 못 받은 것으로 둔다
MAX_REDIRECTS = 5
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_FILE_BYTES = MAX_BYTES  # 첨부·본문 이미지 하나(업로드 상한과 같다)
MAX_TOTAL_BYTES = 60 * 1024 * 1024  # 한 공지에서 받는 파일을 모두 합쳐
MAX_ATTACHMENTS = 10
MAX_IMAGES = (
    10  # 학교 서버에서 받아 남기는 본문 이미지(아이콘 크기·본문에 넣은 data: 이미지는 세지 않는다)
)
MAX_IMAGE_REQUESTS = 20  # 본문 이미지를 받으려고 학교 서버에 묻는 횟수(같은 주소는 한 번)
MAX_LINK_LENGTH = 2000

_PORTLET = "kr_ac_hanyang_noticeBoard_web_portlet_NoticeBoardPortlet"
# 공지사항(전체) 게시판의 글 보기 주소. 목록에서 글을 누르면 열리는 주소와 같다
VIEW_URL = (
    f"{SITE}/notice_all?p_p_id={_PORTLET}&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
    f"&_{_PORTLET}_action=view_message&_{_PORTLET}_entryId={{entry_id}}"
)
_PERMALINK_PATH = re.compile(r"/notice/url/([0-9a-fA-F]{1,8})/([0-9a-fA-F]{1,12})/?")
_DIGITS = re.compile(r"[0-9]{1,15}")

EMPTY = "공지 주소를 붙여 주세요."
NOT_URL = "주소를 확인해 주세요. https://로 시작하는 공지 주소를 붙여 주세요."
NOT_HANYANG = "한양대 공지사항(www.hanyang.ac.kr)의 글 주소만 가져올 수 있어요."
NOT_ONE_NOTICE = "공지 글 하나의 주소를 붙여 주세요. 목록이 아니라 글을 연 화면의 주소예요."
TOO_LONG = "주소가 너무 길어요. 공지 글 주소만 붙여 주세요."
OTHER_NOTICE = "붙인 주소와 다른 공지가 열렸어요. 주소를 다시 확인해 주세요."
NOT_FOUND = "그 주소에서 공지를 찾지 못했어요. 지워졌거나 주소가 잘렸을 수 있어요."
FETCH_FAILED = "학교 사이트에서 공지를 읽지 못했어요. 잠시 후 다시 붙여 주세요."
FILES_FAILED = "학교 사이트에서 첨부를 받지 못했어요. 잠시 후 다시 붙여 주세요."
OUTSIDE = "학교 사이트 밖 주소로 넘어가서 멈췄어요"


class LinkError(Exception):
    """링크를 읽지 못함. code는 API 오류 코드(명세 13장), message는 학생에게 그대로 보여도 되는 한 줄이다."""

    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class _TooLarge(FetchError):
    pass


class _Gone(FetchError):
    pass


class _Busy(FetchError):
    """학교 서버가 잠시 답하지 않음(5xx·429·시간 초과·연결 실패). 다시 하면 될 수 있다."""


@dataclass(frozen=True)
class NoticeLink:
    entry_id: str  # 게시판 글 번호(10진수). opportunities.external_id
    url: str  # 학교 서버에서 읽을 주소


@dataclass(frozen=True)
class LinkedNotice(NoticeContent):
    """학생이 붙인 링크에서 읽은 공지. 가져오기에는 NoticeContent로 들어간다."""

    url: str  # 실제로 읽은 페이지 주소(리다이렉트 뒤)
    skipped_images: tuple[str, ...] = ()  # 아이콘 크기라 뺀 본문 이미지


def parse_link(text: str) -> NoticeLink:
    """붙인 글 → 읽을 공지. 한양대 공지 글 주소가 아니면 LinkError(VALIDATION_FAILED)다."""
    raw = text.strip()
    if not raw:
        raise LinkError("VALIDATION_FAILED", EMPTY)
    if len(raw) > MAX_LINK_LENGTH:
        raise LinkError("VALIDATION_FAILED", TOO_LONG)
    if "://" not in raw:  # 주소창에서 "www.hanyang.ac.kr/…"만 복사한 경우
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as exc:
        raise LinkError("VALIDATION_FAILED", NOT_URL) from exc
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise LinkError("VALIDATION_FAILED", NOT_URL)
    if parts.hostname.lower() not in SCHOOL_HOSTS or port not in (None, 80, 443) or parts.username:
        raise LinkError("VALIDATION_FAILED", NOT_HANYANG)
    permalink = _PERMALINK_PATH.fullmatch(parts.path)
    if permalink:
        board, entry = (group.lower() for group in permalink.groups())
        entry_id = int(entry, 16)
        if entry_id > 0:
            return NoticeLink(str(entry_id), f"{SITE}/notice/url/{board}/{entry}")
    entry_ids = {
        value
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key == "entryId" or key.endswith("_entryId")
    }
    if len(entry_ids) == 1:
        (value,) = entry_ids
        if _DIGITS.fullmatch(value) and int(value) > 0:
            entry_id = str(int(value))
            return NoticeLink(entry_id, VIEW_URL.format(entry_id=entry_id))
    raise LinkError("VALIDATION_FAILED", NOT_ONE_NOTICE)


class LinkGate:
    """학교 서버에 한 번에 하나씩, 앞 요청이 끝나고 interval초가 지나야 다음 요청을 보낸다.

    서버(앱)에 하나다(app.state). 배포 서버는 인스턴스가 하나라 이것으로 학교 서버 쪽 간격이 지켜진다.
    잠금은 처음 쓸 때 만든다(돌고 있는 이벤트 루프에 묶인다).
    """

    def __init__(
        self,
        interval: float = MIN_INTERVAL,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._lock: asyncio.Lock | None = None
        self._last = -math.inf

    @asynccontextmanager
    async def turn(self) -> AsyncIterator[None]:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            wait = self._last + self.interval - self._clock()
            if wait > 0:
                await self._sleep(wait)
            try:
                yield
            finally:
                self._last = self._clock()


class LinkFetcher:
    """학교 서버(SCHOOL_HOSTS)에만 묻는 클라이언트. robots.txt를 보지 않는 대신 주소를 학교로만 묶는다."""

    def __init__(
        self,
        gate: LinkGate,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = TIMEOUT,
        total: float = TOTAL_TIMEOUT,
    ) -> None:
        self._gate = gate
        self._total = total
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=timeout,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            headers={"User-Agent": LINK_USER_AGENT},
            event_hooks={"request": [_only_school]},  # 리다이렉트마다 주소를 다시 본다
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str, *, limit: int) -> Fetched:
        """GET 하나. 404·410은 _Gone, limit바이트를 넘으면 _TooLarge, 잠시 답하지 않으면 _Busy, 그 밖의
        실패(200이 아닌 답·잘못된 주소 등)는 FetchError다."""
        async with self._gate.turn():
            try:
                async with (
                    asyncio.timeout(self._total),
                    self._client.stream("GET", url) as response,
                ):
                    status = response.status_code
                    if status in (404, 410):
                        raise _Gone(f"HTTP {status}")
                    if status == 429 or status >= 500:
                        raise _Busy(f"HTTP {status}")
                    if status != 200:  # 204·Location 없는 3xx 등. 빈 글을 파일로 쓰지 않는다
                        raise FetchError(f"HTTP {status}")
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > limit:
                        raise _TooLarge(_size(limit))
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise _TooLarge(_size(limit))
                        chunks.append(chunk)
                    content_type = response.headers.get("content-type", "")
                    return Fetched(str(response.url), b"".join(chunks), content_type)
            except TimeoutError as exc:
                raise _Busy(f"시간이 너무 오래 걸려요({self._total:g}초 넘음)") from exc
            except httpx.TooManyRedirects as exc:
                raise FetchError("리다이렉트가 너무 많아요") from exc
            except httpx.TransportError as exc:  # 연결 거절·끊김·시간 초과
                raise _Busy(f"연결 실패({type(exc).__name__})") from exc
            except (httpx.HTTPError, httpx.InvalidURL, httpx.StreamError) as exc:
                # 첨부 주소에 보이지 않는 글자가 섞인 것 등. 그 파일만 못 받은 것으로 둔다
                raise FetchError(f"요청 실패({type(exc).__name__})") from exc


async def read_page(fetcher: LinkFetcher, link: NoticeLink) -> tuple[NoticePage, str]:
    """공지 페이지를 읽는다. (읽은 페이지, 실제 주소). 실패는 LinkError(학생에게 보일 이유)다."""
    try:
        fetched = await fetcher.get(link.url, limit=MAX_PAGE_BYTES)
    except _Gone as exc:
        raise LinkError("NOTICE_NOT_FOUND", NOT_FOUND, 404) from exc
    except FetchError as exc:
        raise LinkError("NOTICE_FETCH_FAILED", FETCH_FAILED, 502) from exc
    html = decode_html(fetched.content, fetched.content_type)
    try:
        page = parse_notice(html, page_url=fetched.url)
    except NotNoticePage as exc:
        raise LinkError("NOT_NOTICE_PAGE", str(exc)) from exc
    if page.entry_id != link.entry_id:
        raise LinkError("NOT_NOTICE_PAGE", OTHER_NOTICE)
    return page, fetched.url


async def read_files(fetcher: LinkFetcher, page: NoticePage, *, page_url: str) -> LinkedNotice:
    """페이지의 첨부와 본문 이미지를 받아 A안과 같은 모양으로 만든다. 못 받은 파일은 이유와 함께 남긴다.
    학교 서버가 잠시 답하지 않으면 LinkError(NOTICE_FETCH_FAILED)로 멈춘다 — 다시 붙이면 다시 읽는다."""
    budget = _Budget(MAX_TOTAL_BYTES)
    files: list[SavedFile] = []
    for seq, link in enumerate(page.attachments, 1):
        if seq > MAX_ATTACHMENTS:
            problem = f"첨부가 많아 {MAX_ATTACHMENTS}개까지만 받았어요"
            files.append(SavedFile(seq, link.name, None, link.url, problem=problem))
            continue
        data, problem = await _download(fetcher, link.url, budget, name=link.name)
        files.append(SavedFile(seq, link.name, data, link.url, problem=problem))
    images: list[BodyImage | None] = []
    got: dict[str, tuple[bytes | None, str | None]] = {}  # 같은 주소는 한 번만 묻는다
    kept = 0  # 남길 크기의 이미지(아이콘 크기는 세지 않는다 — 아이콘 뒤의 포스터를 놓치지 않게)
    for src in page.image_sources:
        if not src:
            images.append(None)
        elif src.startswith("data:"):
            data = data_uri(src)
            images.append(("본문 이미지", data, None if data else "이미지 데이터를 읽지 못했어요"))
        else:
            url = urljoin(page_url, src)
            name = url_name(url)
            if url in got:
                images.append((name, *got[url]))
            elif not _is_school(url):
                images.append((name, None, "학교 사이트 밖 이미지라 받지 않았어요"))
            elif kept >= MAX_IMAGES:
                images.append((name, None, f"본문 이미지가 많아 {MAX_IMAGES}개까지만 받았어요"))
            elif len(got) >= MAX_IMAGE_REQUESTS:
                problem = f"본문 이미지가 많아 {MAX_IMAGE_REQUESTS}개까지만 열어 봤어요"
                images.append((name, None, problem))
            else:
                got[url] = await _download(fetcher, url, budget, name=name)
                data = got[url][0]
                if data is not None and len(data) >= MIN_IMAGE_BYTES:
                    kept += 1
                images.append((name, *got[url]))
    labels, skipped = add_body_images(files, images, missing_note="받지 못함")
    return LinkedNotice(
        page=page,
        text=body_text(page, labels),
        files=tuple(files),
        url=page_url,
        skipped_images=tuple(skipped),
    )


@dataclass
class _Budget:
    left: int


async def _download(
    fetcher: LinkFetcher, url: str, budget: _Budget, *, name: str
) -> tuple[bytes | None, str | None]:
    """파일 하나 → (데이터, 못 받은 이유). 학교 서버가 잠시 답하지 않으면 LinkError로 실행을 멈춘다 —
    공고를 넣고 나면 다시 읽지 않으니(같은 공지는 한 번만) 다시 하면 될 실패는 공고로 남기지 않는다."""
    if not _is_school(url):
        return None, "학교 사이트 밖 주소라 받지 않았어요"
    if budget.left <= 0:
        return None, f"한 공지에서 받는 용량({_size(MAX_TOTAL_BYTES)})을 넘어 받지 않았어요"
    limit = min(MAX_FILE_BYTES, budget.left)
    try:
        fetched = await fetcher.get(url, limit=limit)
    except _TooLarge:
        if limit < MAX_FILE_BYTES:
            return None, f"한 공지에서 받는 용량({_size(MAX_TOTAL_BYTES)})을 넘어 받지 않았어요"
        return None, f"파일이 너무 커요({_size(MAX_FILE_BYTES)} 넘음)"
    except _Busy as exc:
        raise LinkError("NOTICE_FETCH_FAILED", FILES_FAILED, 502) from exc
    except FetchError as exc:
        return None, f"받지 못했어요({exc})"
    if "text/html" in fetched.content_type.lower() and not re.search(
        r"\.html?$", name, re.IGNORECASE
    ):
        # 파일 대신 안내 페이지(로그인·오류)가 왔다. 그 글을 첨부로 읽으면 엉뚱한 요건이 나온다
        return None, "파일 대신 웹페이지가 왔어요(지워졌거나 로그인이 필요한 파일일 수 있어요)"
    budget.left -= len(fetched.content)
    return fetched.content, None


async def _only_school(request: httpx.Request) -> None:
    if request.url.host.lower() not in SCHOOL_HOSTS or request.url.port not in (None, 80, 443):
        raise FetchError(OUTSIDE)


def _is_school(url: str) -> bool:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme in ("http", "https")
        and (parts.hostname or "").lower() in SCHOOL_HOSTS
        and port in (None, 80, 443)
    )


def root_cause(exc: BaseException) -> str:
    """맨 밑의 원인 한 줄(로그·명령용). 학생에게 보이는 이유는 짧게 두고, 고칠 때는 이것을 본다(인증서·연결 거절 등)."""
    while exc.__cause__ is not None:
        exc = exc.__cause__
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def _size(limit: int) -> str:
    return f"{limit // 1024 // 1024}MB" if limit >= 1024 * 1024 else f"{limit:,}바이트"
