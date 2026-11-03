"""학생이 붙인 공지 링크 한 건 읽기(B안, app/crawl/link.py): 주소 검사, 학교 서버로만 묻기·간격·크기, 공지 한 건.

학교 사이트는 가짜(tests/school_fakes.py)다. A안(저장한 폴더)과 같은 공지면 같은 내용(content_hash)이 되는지도 본다.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.crawl import link as link_module
from app.crawl.fetch import FetchError
from app.crawl.link import (
    FILES_FAILED,
    LINK_USER_AGENT,
    MAX_ATTACHMENTS,
    MAX_FILE_BYTES,
    MAX_IMAGE_REQUESTS,
    MAX_IMAGES,
    NOT_HANYANG,
    NOT_ONE_NOTICE,
    NOT_URL,
    OTHER_NOTICE,
    VIEW_URL,
    LinkError,
    LinkFetcher,
    LinkGate,
    parse_link,
    read_files,
    read_page,
)
from app.crawl.saved import load_folder
from app.extraction.store import content_hash
from tests import hanyang_pages, samples
from tests.hanyang_pages import POSTER, file_url, save_notice
from tests.school_fakes import SITE, FakeSchool, download, permalink, view_link

pytestmark = pytest.mark.anyio

ENTRY = 119702
GUIDE = samples.hwpx(samples.hp("가. 직전 학기 평점평균 3.0 이상인 재학생"))
IMAGE = "/documents/20122/0/poster.jpg/0f1e-2d3c?t=1759"


class NoWait:
    """간격을 기다리지 않는 시계(시험이 1초씩 쉬지 않게). 기다린 초를 적어 둔다."""

    def __init__(self) -> None:
        self.now = 100.0
        self.waited: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.waited.append(round(seconds, 3))
        self.now += seconds


def fetcher(school: FakeSchool, pace: NoWait | None = None) -> LinkFetcher:
    pace = pace or NoWait()
    return LinkFetcher(LinkGate(clock=pace.clock, sleep=pace.sleep), transport=school.transport)


def live_page(**options: object) -> str:
    """학교 서버에서 받은 페이지. 본문 이미지가 학교 주소를 가리킨다(저장한 페이지는 _files 폴더를 가리킨다)."""
    options.setdefault("files", ("1. 선발요강.hwpx",))
    body = options.pop("body", "<p>신청 기간: 10. 24.(금) 18:00까지</p>")
    poster = f'<p><img alt="포스터" src="{IMAGE}"></p>'
    return hanyang_pages.detail(body=f"{body}{poster}", **options)  # type: ignore[arg-type]


def school_with_notice(**options: object) -> FakeSchool:
    school = FakeSchool()
    school.notice(ENTRY, live_page(**options))
    school.file(download("1. 선발요강.hwpx", "uuid-1"), GUIDE)
    school.file(f"{SITE}{IMAGE}", POSTER, "image/jpeg")
    return school


# ---------- 주소 ----------


@pytest.mark.parametrize(
    ("text", "entry_id", "url"),
    [
        (permalink(ENTRY), "119702", f"{SITE}/notice/url/4a4/1d396"),
        (
            "https://www.hanyang.ac.kr/notice/url/4A4/1D396/",
            "119702",
            f"{SITE}/notice/url/4a4/1d396",
        ),
        ("  http://hanyang.ac.kr/notice/url/4a4/1d396  ", "119702", f"{SITE}/notice/url/4a4/1d396"),
        ("www.hanyang.ac.kr/notice/url/4a4/1d396", "119702", f"{SITE}/notice/url/4a4/1d396"),
        (view_link(ENTRY), "119702", VIEW_URL.format(entry_id=ENTRY)),
        # 페이지 소스에서 복사한 &amp;, 검색어·쪽 번호가 붙은 주소 — 글 번호만 쓰고 보기 주소를 새로 만든다
        (hanyang_pages.view_url(ENTRY) + "#top", "119702", VIEW_URL.format(entry_id=ENTRY)),
        (
            view_link(ENTRY)
            + "&_kr_ac_hanyang_noticeBoard_web_portlet_NoticeBoardPortlet_sKeyword=장학",
            "119702",
            VIEW_URL.format(entry_id=ENTRY),
        ),
        (
            "https://www.hanyang.ac.kr/web/www/notice_all?entryId=00119702",
            "119702",
            VIEW_URL.format(entry_id=ENTRY),
        ),
    ],
)
def test_notice_links_become_one_school_address(text: str, entry_id: str, url: str) -> None:
    link = parse_link(text)
    assert (link.entry_id, link.url) == (entry_id, url)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "공지 주소를 붙여 주세요."),
        ("javascript:alert(1)", NOT_URL),
        ("ftp://www.hanyang.ac.kr/notice/url/4a4/1d396", NOT_URL),
        ("https://m.hanyang.ac.kr/notice/url/4a4/1d396", NOT_HANYANG),
        ("https://www.hanyang.ac.kr.evil.example/notice/url/4a4/1d396", NOT_HANYANG),
        ("https://evil.example/?next=www.hanyang.ac.kr/notice/url/4a4/1d396", NOT_HANYANG),
        ("https://www.hanyang.ac.kr:8443/notice/url/4a4/1d396", NOT_HANYANG),
        ("https://someone@www.hanyang.ac.kr/notice/url/4a4/1d396", NOT_HANYANG),
        ("https://www.hanyang.ac.kr/notice_all", NOT_ONE_NOTICE),  # 목록
        ("https://www.hanyang.ac.kr/notice/url/4a4/0", NOT_ONE_NOTICE),
        ("https://www.hanyang.ac.kr/notice_all?_x_entryId=1&_y_entryId=2", NOT_ONE_NOTICE),
        ("https://www.hanyang.ac.kr/notice_all?_x_entryId=12a", NOT_ONE_NOTICE),
        ("https://www.hanyang.ac.kr/notice/url/4a4/1d396/../../admin", NOT_ONE_NOTICE),
        (
            "https://www.hanyang.ac.kr/" + "a" * 2000,
            "주소가 너무 길어요. 공지 글 주소만 붙여 주세요.",
        ),
    ],
)
def test_other_addresses_are_refused_with_a_reason(text: str, message: str) -> None:
    with pytest.raises(LinkError) as raised:
        parse_link(text)
    assert (raised.value.code, raised.value.message) == ("VALIDATION_FAILED", message)


# ---------- 학교 서버에 묻는 법 ----------


async def test_requests_go_one_at_a_time_with_a_gap() -> None:
    pace = NoWait()
    gate = LinkGate(1.0, clock=pace.clock, sleep=pace.sleep)
    order: list[str] = []

    async def ask(name: str) -> None:
        async with gate.turn():
            order.append(f"{name} 시작")
            await asyncio.sleep(0)  # 다른 요청이 끼어들 틈을 준다
            pace.now += 0.25  # 요청에 걸린 시간
            order.append(f"{name} 끝")

    await asyncio.gather(ask("가"), ask("나"), ask("다"))
    assert order == ["가 시작", "가 끝", "나 시작", "나 끝", "다 시작", "다 끝"]
    assert pace.waited == [1.0, 1.0]  # 앞 요청이 끝난 뒤 1초


async def test_only_the_school_is_asked_even_through_redirects() -> None:
    school = FakeSchool()
    school.routes[f"{SITE}/a"] = lambda _r: httpx.Response(302, headers={"location": f"{SITE}/b"})
    school.file(f"{SITE}/b", b"ok")
    school.routes[f"{SITE}/out"] = lambda _r: httpx.Response(
        302, headers={"location": "https://evil.example/steal"}
    )
    school.routes[f"{SITE}/inside"] = lambda _r: httpx.Response(
        302, headers={"location": "http://127.0.0.1/admin"}
    )
    client = fetcher(school)
    try:
        fetched = await client.get(f"{SITE}/a", limit=1024)
        assert (fetched.url, fetched.content) == (f"{SITE}/b", b"ok")
        for start in (f"{SITE}/out", f"{SITE}/inside", "https://evil.example/x"):
            with pytest.raises(FetchError, match="학교 사이트 밖"):
                await client.get(start, limit=1024)
    finally:
        await client.aclose()
    assert all(request.url.host == "www.hanyang.ac.kr" for request in school.requests)
    assert {request.headers["user-agent"] for request in school.requests} == {LINK_USER_AGENT}


async def test_sizes_and_failures() -> None:
    school = FakeSchool()
    school.file(f"{SITE}/big", b"x" * 2048)
    school.routes[f"{SITE}/declared"] = lambda _r: httpx.Response(
        200, content=b"x", headers={"content-length": "999999"}
    )
    school.answer(f"{SITE}/broken", 503)

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(4):
            yield b"x" * 512

    # 크기를 밝히지 않고 흘려보내는 응답. 받은 만큼 세다가 한도를 넘으면 멈춘다
    school.routes[f"{SITE}/stream"] = lambda _r: httpx.Response(200, content=chunks())

    async def slow() -> AsyncIterator[bytes]:
        while True:  # 조금씩 끝없이 — 읽기마다의 시간 한도로는 끊기지 않는다
            await asyncio.sleep(0.05)
            yield b"x"

    school.routes[f"{SITE}/slow"] = lambda _r: httpx.Response(200, content=slow())

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    school.routes[f"{SITE}/down"] = down
    school.answer(f"{SITE}/busy", 429)
    school.answer(f"{SITE}/empty", 204)
    school.answer(f"{SITE}/nowhere", 302)  # Location 없는 리다이렉트
    school.answer(f"{SITE}/forbidden", 403)
    client = fetcher(school)
    try:
        for url in (f"{SITE}/big", f"{SITE}/declared", f"{SITE}/stream"):
            with pytest.raises(link_module._TooLarge):
                await client.get(url, limit=1024)
        with pytest.raises(link_module._Gone):
            await client.get(f"{SITE}/missing", limit=1024)
        # 잠시 답하지 않음(다시 하면 될 수 있다)
        with pytest.raises(link_module._Busy, match="HTTP 503"):
            await client.get(f"{SITE}/broken", limit=1024)
        with pytest.raises(link_module._Busy, match="HTTP 429"):
            await client.get(f"{SITE}/busy", limit=1024)
        with pytest.raises(link_module._Busy, match="연결 실패"):
            await client.get(f"{SITE}/down", limit=1024)
        # 200이 아니면 빈 글을 파일로 쓰지 않는다. 다시 해도 같은 실패라 _Busy가 아니다
        for url, reason in (
            (f"{SITE}/empty", "HTTP 204"),
            (f"{SITE}/nowhere", "HTTP 302"),
            (f"{SITE}/forbidden", "HTTP 403"),
            (f"{SITE}/a\x0bb.pdf", "요청 실패(InvalidURL)"),  # 보이지 않는 글자가 섞인 첨부 주소
        ):
            with pytest.raises(
                FetchError, match=reason.replace("(", r"\(").replace(")", r"\)")
            ) as got:
                await client.get(url, limit=1024)
            assert not isinstance(got.value, link_module._Busy), url
    finally:
        await client.aclose()
    pace = NoWait()
    hurried = LinkFetcher(
        LinkGate(clock=pace.clock, sleep=pace.sleep), transport=school.transport, total=0.3
    )
    try:
        with pytest.raises(link_module._Busy, match="시간이 너무 오래 걸려요"):
            await hurried.get(f"{SITE}/slow", limit=1024)
    finally:
        await hurried.aclose()


# ---------- 공지 페이지 ----------


async def test_the_page_is_read_from_either_address() -> None:
    for text in (permalink(ENTRY), view_link(ENTRY)):
        school = school_with_notice()
        client = fetcher(school)
        try:
            page, url = await read_page(client, parse_link(text))
        finally:
            await client.aclose()
        assert (page.entry_id, page.title, page.campus) == (
            "119702",
            "2026학년도 2학기 ○○장학생 선발 안내",
            "ERICA",
        )
        assert url == parse_link(text).url
        assert len(school.requests) == 1  # 페이지만 읽었다(첨부는 아직)


@pytest.mark.parametrize(
    ("setup", "code", "message"),
    [
        (
            "missing",
            "NOTICE_NOT_FOUND",
            "그 주소에서 공지를 찾지 못했어요. 지워졌거나 주소가 잘렸을 수 있어요.",
        ),
        (
            "down",
            "NOTICE_FETCH_FAILED",
            "학교 사이트에서 공지를 읽지 못했어요. 잠시 후 다시 붙여 주세요.",
        ),
        (
            "list",
            "NOT_NOTICE_PAGE",
            "한양대 공지 상세 페이지가 아니에요(목록 페이지거나 다른 사이트일 수 있어요)",
        ),
        ("other", "NOT_NOTICE_PAGE", OTHER_NOTICE),
    ],
)
async def test_page_failures_have_a_reason_for_the_student(
    setup: str, code: str, message: str
) -> None:
    school = FakeSchool()
    if setup == "down":
        school.answer(permalink(ENTRY), 500)
    elif setup == "list":
        school.answer(permalink(ENTRY), 200, hanyang_pages.listing([]).encode(), "text/html")
    elif setup == "other":  # 다른 글이 열렸다(다른 글 번호의 페이지)
        school.answer(permalink(ENTRY), 200, hanyang_pages.detail(entry_id=1).encode(), "text/html")
    client = fetcher(school)
    try:
        with pytest.raises(LinkError) as raised:
            await read_page(client, parse_link(permalink(ENTRY)))
    finally:
        await client.aclose()
    assert (raised.value.code, raised.value.message) == (code, message)


# ---------- 첨부·본문 이미지 ----------


async def test_files_are_read_like_a_saved_folder(tmp_path: Path) -> None:
    """같은 공지를 A안 폴더로 저장한 것과 본문·첨부·해시가 같다(어느 쪽으로 넣어도 다시 추출하지 않는다)."""
    school = school_with_notice()
    pace = NoWait()
    client = fetcher(school, pace)
    try:
        page, url = await read_page(client, parse_link(permalink(ENTRY)))
        notice = await read_files(client, page, page_url=url)
    finally:
        await client.aclose()
    assert pace.waited == [1.0, 1.0]  # 페이지 → 첨부 → 이미지, 요청 사이 1초
    assert [(f.seq, f.name, f.body_image, f.problem) for f in notice.files] == [
        (1, "1. 선발요강.hwpx", False, None),
        (2, "poster.jpg", True, None),
    ]
    assert notice.files[0].source_url == download("1. 선발요강.hwpx", "uuid-1")
    assert notice.files[1].source_url is None  # 본문 이미지는 A안처럼 주소를 두지 않는다
    assert "[이미지: 첨부 2번 poster.jpg]" in notice.text
    assert len(school.requests) == 3  # 페이지·첨부·본문 이미지 하나씩

    saved_page = hanyang_pages.detail(
        body='<p>신청 기간: 10. 24.(금) 18:00까지</p><p><img alt="포스터"'
        f' src="./{hanyang_pages.FILES}/poster.jpg"></p>',
        files=("1. 선발요강.hwpx",),
    )
    folder = save_notice(
        tmp_path / "장학", saved_page, {"1. 선발요강.hwpx": GUIDE}, {"poster.jpg": POSTER}
    )
    saved = load_folder(folder).notice_input()
    linked = notice.notice_input()
    assert linked.body == saved.body
    assert content_hash(linked.body, linked.attachments) == content_hash(
        saved.body, saved.attachments
    )
    assert linked.original_url is None  # 모델이 학교 서버를 다시 부르지 않는다


async def test_files_that_cannot_be_read_stay_as_failed_attachments() -> None:
    school = FakeSchool()
    images = "".join(
        [
            '<img src="https://cdn.example/banner.png">',  # 학교 밖
            '<img src="/documents/icon.png/1">',  # 아이콘 크기
            f'<img src="{IMAGE}">',
            f'<img src="{IMAGE}">',  # 같은 이미지 두 번 → 첨부 하나
            '<img src="data:image/png;base64,' + "A" * 8000 + '">',  # 본문에 넣은 이미지(요청 없음)
            '<img src="">',
        ]
    )
    html = hanyang_pages.detail(
        entry_id=ENTRY,
        body=f"<p>본문</p>{images}",
        files=("1. 공고.pdf", "2. 서식.hwp", "3. 안내.html", "4. 큰 파일.zip"),
    )
    school.notice(ENTRY, html)
    school.file(download("1. 공고.pdf", "uuid-1"), b"%PDF-1.4 notice", "application/pdf")
    school.answer(download("2. 서식.hwp", "uuid-2"), 200, b"<html>login</html>", "text/html")
    school.file(download("3. 안내.html", "uuid-3"), b"<html>ok</html>", "text/html")
    school.routes[download("4. 큰 파일.zip", "uuid-4")] = lambda _r: httpx.Response(
        200, content=b"x", headers={"content-length": str(MAX_FILE_BYTES + 1)}
    )
    school.file(f"{SITE}/documents/icon.png/1", samples.PNG, "image/png")
    school.file(f"{SITE}{IMAGE}", POSTER, "image/jpeg")
    client = fetcher(school)
    try:
        page, url = await read_page(client, parse_link(view_link(ENTRY)))
        notice = await read_files(client, page, page_url=url)
    finally:
        await client.aclose()
    assert [(f.seq, f.name, f.data is not None, f.problem) for f in notice.files] == [
        (1, "1. 공고.pdf", True, None),
        (
            2,
            "2. 서식.hwp",
            False,
            "파일 대신 웹페이지가 왔어요(지워졌거나 로그인이 필요한 파일일 수 있어요)",
        ),
        (3, "3. 안내.html", True, None),  # 이름이 .html인 첨부는 그대로 받는다
        (4, "4. 큰 파일.zip", False, "파일이 너무 커요(20MB 넘음)"),
        (5, "banner.png", False, "학교 사이트 밖 이미지라 받지 않았어요"),
        (6, "poster.jpg", True, None),
        (7, "본문 이미지", True, None),
    ]
    assert notice.skipped_images == ("icon.png(아이콘 크기)",)
    assert "[이미지: 첨부 5번 banner.png(받지 못함)]" in notice.text
    assert notice.text.count("[이미지: 첨부 6번 poster.jpg]") == 2
    assert (
        "가져오지 못해 읽을 수 없는 첨부: 첨부 2번 2. 서식.hwp, 첨부 4번 4. 큰 파일.zip, 첨부 5번 banner.png"
        in (notice.body())
    )
    assert "cdn.example" not in " ".join(school.asked(""))  # 학교 밖 이미지는 묻지도 않았다


async def test_a_school_that_cannot_answer_now_stops_the_read() -> None:
    """학교 서버가 잠시 답하지 않으면 거기서 멈춘다(공고를 넣으면 다시 읽지 않으니 못 읽은 첨부로 두지 않는다).
    지워진 파일(404)·주소가 잘못된 파일은 다시 해도 같아서 못 읽은 첨부로 두고 계속 받는다."""
    files = ("1. 공고.pdf", "2. 서식.hwp", "3. 안내.pdf", "4. 신청서.hwp")
    html = hanyang_pages.detail(entry_id=ENTRY, body="<p>본문</p>", files=files)
    school = FakeSchool()
    school.notice(ENTRY, html)
    school.file(download("1. 공고.pdf", "uuid-1"), b"%PDF-1.4 notice", "application/pdf")
    # 2번은 없다(404)
    school.answer(download("3. 안내.pdf", "uuid-3"), 500)
    school.file(download("4. 신청서.hwp", "uuid-4"), b"hwp", "application/x-hwp")
    client = fetcher(school)
    try:
        page, url = await read_page(client, parse_link(view_link(ENTRY)))
        with pytest.raises(LinkError) as stopped:
            await read_files(client, page, page_url=url)
    finally:
        await client.aclose()
    assert (stopped.value.code, stopped.value.message, stopped.value.status) == (
        "NOTICE_FETCH_FAILED",
        FILES_FAILED,
        502,
    )
    assert school.asked(f"{SITE}/documents") == [
        download(name, f"uuid-{no}") for no, name in enumerate(files[:3], 1)
    ]  # 3번에서 멈추고 4번은 묻지 않았다

    del school.routes[download("3. 안내.pdf", "uuid-3")]  # 이제 3번도 없다(404)
    odd = html.replace(file_url("4. 신청서.hwp", "uuid-4"), file_url("4. 신청서.hwp", "uuid\x0b4"))
    school.notice(ENTRY, odd)
    client = fetcher(school)
    try:
        page, url = await read_page(client, parse_link(view_link(ENTRY)))
        notice = await read_files(client, page, page_url=url)
    finally:
        await client.aclose()
    assert [(f.seq, f.data is not None, f.problem) for f in notice.files] == [
        (1, True, None),
        (2, False, "받지 못했어요(HTTP 404)"),
        (3, False, "받지 못했어요(HTTP 404)"),
        (4, False, "받지 못했어요(요청 실패(InvalidURL))"),
    ]


async def test_body_images_count_kept_ones_and_ask_each_address_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """아이콘이 많아도 그 뒤의 포스터를 받는다(남길 이미지만 센다). 같은 주소는 한 번만 묻는다."""
    icons = "".join(f'<img src="/documents/icon{no}.png/1">' for no in range(MAX_IMAGES + 2))
    poster = f'<img src="{IMAGE}">'
    html = hanyang_pages.detail(entry_id=ENTRY, body=f"{icons}{poster}{poster}", files=())
    school = FakeSchool()
    school.notice(ENTRY, html)
    for no in range(MAX_IMAGES + 2):
        school.file(f"{SITE}/documents/icon{no}.png/1", samples.PNG, "image/png")
    school.file(f"{SITE}{IMAGE}", POSTER, "image/jpeg")
    client = fetcher(school)
    try:
        page, url = await read_page(client, parse_link(view_link(ENTRY)))
        notice = await read_files(client, page, page_url=url)
    finally:
        await client.aclose()
    assert [(f.seq, f.name, f.data is not None) for f in notice.files] == [(1, "poster.jpg", True)]
    assert len(notice.skipped_images) == MAX_IMAGES + 2  # 아이콘 크기라 뺐다
    assert notice.text.count("[이미지: 첨부 1번 poster.jpg]") == 2
    assert school.asked(f"{SITE}{IMAGE}") == [f"{SITE}{IMAGE}"]  # 두 번 나와도 한 번 묻는다

    # 묻는 횟수에도 한도가 있다: 아이콘을 그만큼 열어 본 뒤의 이미지는 받지 않는다(못 읽은 첨부로 남는다)
    monkeypatch.setattr(link_module, "MAX_IMAGE_REQUESTS", 5)
    school.requests.clear()
    client = fetcher(school)
    try:
        notice = await read_files(client, page, page_url=url)
    finally:
        await client.aclose()
    assert len(school.requests) == 5 and len(notice.skipped_images) == 5
    capped = "본문 이미지가 많아 5개까지만 열어 봤어요"
    assert [f.problem for f in notice.files if f.name == "poster.jpg"] == [capped, capped]
    assert MAX_IMAGE_REQUESTS == 20


async def test_many_files_stop_at_the_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    names = tuple(f"{no}. 첨부.pdf" for no in range(1, MAX_ATTACHMENTS + 3))
    images = "".join(f'<img src="/documents/{no}.jpg/x">' for no in range(MAX_IMAGES + 2))
    school = FakeSchool()
    school.notice(ENTRY, hanyang_pages.detail(entry_id=ENTRY, body=images, files=names))
    for no, name in enumerate(names, 1):
        school.file(
            download(name, f"uuid-{no}"), b"%PDF-1.4 " + bytes([no]) * 10, "application/pdf"
        )
    for no in range(MAX_IMAGES + 2):
        school.file(f"{SITE}/documents/{no}.jpg/x", POSTER + bytes([no]), "image/jpeg")
    client = fetcher(school)
    try:
        page, url = await read_page(client, parse_link(permalink(ENTRY)))
        notice = await read_files(client, page, page_url=url)
    finally:
        await client.aclose()
    attachments = [f for f in notice.files if not f.body_image]
    assert [f.problem for f in attachments[MAX_ATTACHMENTS:]] == [
        f"첨부가 많아 {MAX_ATTACHMENTS}개까지만 받았어요"
    ] * 2
    images_read = [f for f in notice.files if f.body_image]
    assert [f.problem for f in images_read[MAX_IMAGES:]] == [
        f"본문 이미지가 많아 {MAX_IMAGES}개까지만 받았어요"
    ] * 2
    assert len(school.requests) == 1 + MAX_ATTACHMENTS + MAX_IMAGES

    # 합친 용량: 한도를 넘는 파일부터는 받지 않는다
    monkeypatch.setattr(link_module, "MAX_TOTAL_BYTES", 25)
    school.requests.clear()
    client = fetcher(school)
    try:
        notice = await read_files(client, page, page_url=url)
    finally:
        await client.aclose()
    problems = [f.problem for f in notice.files[:4]]
    assert problems == [None] + ["한 공지에서 받는 용량(25바이트)을 넘어 받지 않았어요"] * 3
