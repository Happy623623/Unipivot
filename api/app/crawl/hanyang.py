"""한양대 공지사항(www.hanyang.ac.kr/notice_all) 페이지를 읽는다. Liferay 게시판 HTML에 맞춘 파서다.

학교 서버에는 접속하지 않는다. www·portal의 robots.txt가 모든 수집기를 막고 있어서(2026-10-08 확인)
팀이 브라우저로 저장한 페이지를 읽는다(A안, app/crawl/saved.py). 학교가 수집을 허락하면(C안)
같은 파서로 받아 온 HTML을 읽는다.

상세 페이지에서 읽는 곳:
- 제목: div.noticeBoard-view-message 안의 h4
- 고유 주소: input#…_viewMessageURL. https://www.hanyang.ac.kr/notice/url/4a4/1d396처럼 끝이 글 번호의 16진수다
- 메타: .hyu-meta-item의 <span>이름</span> <span>값</span> (작성자·등록일·캠퍼스 게시·공지분류·공지기간·행사기간·원문 URL)
  작성자 칸의 title 속성에는 담당자 이름이 있어서 읽지 않는다. 화면에 보이는 부서 이름만 쓴다
- 첨부: .hyu-meta-item.file-download 안의 a[href]. 보이는 이름이 내려받는 파일 이름이다
- 본문: div.entry-content
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal
from urllib.parse import unquote_plus, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from app.attachments import html_text

SITE = "https://www.hanyang.ac.kr"
BOARD_URL = f"{SITE}/notice_all"
SOURCE_NAME = "한양대 공지사항"

# 공지분류 → opportunities.category. 카테고리 칩: 장학금·교내 프로그램·청년정책·공모전·대외활동·기타(연구·시험 포함)
CATEGORIES = {
    "장학/등록": "scholarship",
    "학사": "school_program",
    "취업/창업": "school_program",
    "모집/채용": "school_program",
    "행사": "school_program",
    "사회봉사": "activity",
    "산학/연구": "research",
    "학회/세미나": "research",
    "입학": "etc",
    "일반": "etc",
}

CampusScope = Literal["erica", "seoul", "unmarked"]

_DATE = re.compile(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})")
_PERMALINK = re.compile(r"/notice/url/[0-9a-fA-F]+/([0-9a-fA-F]+)/?$")
_ENTRY_ID = re.compile(r"entryId(?:=|\\x3d|%3D)(\d+)", re.IGNORECASE)
# 고유 주소가 없을 때: 좋아요 칸의 글 번호(classPK) → 현재 주소(Liferay.currentURL) → 페이지 주소.
# 본문 아래 이전글·다음글 링크에도 entryId가 있어서 페이지 전체에서 처음 나온 번호를 쓰면 안 된다
_CLASS_PK = re.compile(r"NBEntry',\s*classPK:\s*'(\d+)'")  # 공지 글(NBEntry)의 좋아요 칸
_CURRENT_URL = re.compile(r"Liferay\.currentURL\s*=\s*'[^']*?entryId(?:\\x3d|=)(\d+)")


class NotNoticePage(ValueError):
    """한양대 공지 페이지가 아니거나 구조가 바뀌었다. 메시지는 사용자에게 그대로 보여도 되는 한 줄이다."""


@dataclass(frozen=True)
class AttachmentLink:
    name: str  # 화면에 보이는 파일 이름. 내려받은 파일 이름과 같다
    url: str


@dataclass(frozen=True)
class NoticePage:
    entry_id: str  # 게시판 글 번호. opportunities.external_id
    title: str
    permalink: str | None  # 고유 주소. opportunities.original_url
    department: str | None  # 작성 부서
    posted_on: date | None  # 등록일
    campus: str | None  # 캠퍼스 게시: ERICA·한양(공통)·서울·안함
    category: str | None  # 공지분류: 장학/등록·학사 …
    notice_period: tuple[date, date] | None  # 공지기간(게시판에 올려 두는 기간)
    event_period: tuple[date, date] | None  # 행사기간
    external_url: str | None  # 원문 URL(다른 사이트에 있는 원문)
    attachments: tuple[AttachmentLink, ...]
    body_html: str  # div.entry-content 안쪽
    image_sources: tuple[str, ...]  # 본문 <img>의 src. 본문에 나오는 순서다

    @property
    def scope(self) -> CampusScope:
        return campus_scope(self.campus)

    @property
    def opportunity_category(self) -> str:
        return opportunity_category(self.category)


@dataclass(frozen=True)
class ListRow:
    entry_id: str
    title: str
    url: str
    campus: str | None  # 캠퍼스 배지. 캠퍼스 게시가 "안함"이면 배지가 없다
    category: str | None
    department: str | None
    posted_on: date | None

    @property
    def scope(self) -> CampusScope:
        return campus_scope(self.campus)


def campus_scope(campus: str | None) -> CampusScope:
    """ERICA 학생에게 보일 공지인가. ERICA와 한양(두 캠퍼스 공통)은 가져오고, 서울만이면 뺀다."""
    value = " ".join((campus or "").split())
    if "ERICA" in value.upper() or "한양" in value:
        return "erica"
    if "서울" in value:
        return "seoul"
    return "unmarked"  # 안함·표시 없음: 사람이 보고 정한다


def opportunity_category(board_category: str | None) -> str:
    return CATEGORIES.get(" ".join((board_category or "").split()), "etc")


def parse_notice(html: str, *, page_url: str | None = None) -> NoticePage:
    """상세 페이지 HTML → NoticePage. page_url은 페이지 주소를 알 때(MHTML·직접 가져옴) 준다."""
    soup = BeautifulSoup(html, "html.parser")
    view = soup.select_one("div.noticeBoard-view-message")
    if view is None:
        raise NotNoticePage(
            "한양대 공지 상세 페이지가 아니에요(목록 페이지거나 다른 사이트일 수 있어요)"
        )
    title = _text(view.select_one("h4"))
    if not title:
        raise NotNoticePage("공지 제목을 찾지 못했어요(게시판 구조가 바뀌었을 수 있어요)")
    url_input = view.select_one("input[id$='_viewMessageURL']")
    permalink = _attr(url_input, "value") or None
    meta = _meta(view)
    entry_id = _entry_id(permalink, html, page_url)
    if entry_id is None:
        raise NotNoticePage("글 번호를 찾지 못했어요(게시판 구조가 바뀌었을 수 있어요)")
    body = view.select_one("div.entry-content")
    return NoticePage(
        entry_id=entry_id,
        title=title,
        permalink=permalink,
        department=_department(meta.get("작성자")),
        posted_on=parse_date(_text(meta.get("등록일"))),
        campus=_text(meta.get("캠퍼스 게시")) or None,
        category=_text(meta.get("공지분류")) or None,
        notice_period=parse_period(_text(meta.get("공지기간"))),
        event_period=parse_period(_text(meta.get("행사기간"))),
        external_url=_link(meta.get("원문 URL")),
        attachments=_attachments(view),
        body_html=body.decode_contents() if body else "",
        image_sources=tuple(_attr(img, "src") for img in body.find_all("img")) if body else (),
    )


def body_text(page: NoticePage, image_labels: Mapping[int, str] | None = None) -> str:
    """본문 글자(표는 "셀 | 셀"). image_labels[i]가 있으면 i번째 이미지를 "[이미지: 그 글]"로 쓴다."""
    soup = BeautifulSoup(page.body_html, "html.parser")
    for index, image in enumerate(soup.find_all("img")):
        if image_labels and index in image_labels:
            image["alt"] = image_labels[index]
    return html_text(str(soup))


def parse_list(html: str) -> list[ListRow]:
    """목록 페이지 HTML → 글 목록. 저장한 목록에서 아직 안 가져온 글을 고를 때 쓴다."""
    soup = BeautifulSoup(html, "html.parser")
    board = soup.select_one("div.noticeBoard-view")
    if board is None:
        raise NotNoticePage("한양대 공지 목록 페이지가 아니에요")
    rows = []
    for item in board.select("div.hyu-list-body-item[role=listitem]"):
        link = item.select_one("h4 a[href]")
        if link is None:
            continue
        url = urljoin(SITE, _attr(link, "href"))
        match = _ENTRY_ID.search(url)
        if match is None:
            continue
        campus = item.select_one("span.hyu-badge.custom-bg[data-itemvalue]")
        category = next(
            (
                badge
                for badge in item.select("span.hyu-badge[data-itemvalue]")
                if "custom-bg" not in (badge.get("class") or [])
            ),
            None,
        )
        department = next((span for span in item.select("p > span") if not span.get("class")), None)
        rows.append(
            ListRow(
                entry_id=match.group(1),
                title=_text(link),
                url=url,
                campus=_attr(campus, "data-itemvalue") or None,
                category=_attr(category, "data-itemvalue") or None,
                department=_text(department) or None,
                posted_on=parse_date(_text(item.select_one("span.date"))),
            )
        )
    return rows


def parse_date(text: str | None) -> date | None:
    """ "2026. 9. 30" → date. 날짜가 없거나 잘못된 날짜면 None."""
    match = _DATE.search(text or "")
    if match is None:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def parse_period(text: str | None) -> tuple[date, date] | None:
    """ "2026. 9. 30 ~ 2026. 11. 13" → (시작, 끝). 날짜가 하나면 시작과 끝이 같다."""
    found = [parse_date(match.group(0)) for match in _DATE.finditer(text or "")]
    days = [day for day in found if day is not None]
    if not days:
        return None
    return days[0], days[-1]


def _meta(view: Tag) -> dict[str, Tag]:
    """메타 칸 이름 → 값 <span>. 첨부 칸은 따로 읽는다."""
    items: dict[str, Tag] = {}
    for item in view.select(".hyu-meta-item"):
        if "file-download" in (item.get("class") or []):
            continue
        spans = item.find_all("span", recursive=False)
        if len(spans) >= 2:
            items.setdefault(" ".join(_text(spans[0]).split()), spans[1])
    return items


def _department(value: Tag | None) -> str | None:
    text = _text(value)
    return text.split(" / ")[0].strip() or None  # "부서 / 이름"으로 나와도 이름은 버린다


def _link(value: Tag | None) -> str | None:
    if value is None:
        return None
    anchor = value.find("a", href=True)
    url = _attr(anchor, "href") if anchor else _text(value)
    return url if urlsplit(url).scheme in ("http", "https") else None


def _attachments(view: Tag) -> tuple[AttachmentLink, ...]:
    links: dict[str, AttachmentLink] = {}
    for anchor in view.select(".hyu-meta-item.file-download a[href]"):
        url = urljoin(SITE, _attr(anchor, "href"))
        name = _text(anchor) or _name_from_url(url)
        if name and url not in links:  # 같은 파일 링크가 두 번 있으면 한 번만
            links[url] = AttachmentLink(name, url)
    return tuple(links.values())


def _name_from_url(url: str) -> str:
    """/documents/portlet_file_entry/20122/<파일 이름>/<uuid> 에서 파일 이름."""
    parts = [part for part in urlsplit(url).path.split("/") if part]
    return unquote_plus(parts[-2]) if len(parts) >= 2 else ""


def _entry_id(permalink: str | None, html: str, page_url: str | None) -> str | None:
    if permalink:
        match = _PERMALINK.search(urlsplit(permalink).path)
        if match:
            return str(int(match.group(1), 16))
    for pattern in (_CLASS_PK, _CURRENT_URL):
        match = pattern.search(html)
        if match:
            return match.group(1)
    match = _ENTRY_ID.search(page_url or "")
    return match.group(1) if match else None


def _text(tag: Tag | None) -> str:
    return " ".join(tag.get_text(" ").split()) if tag is not None else ""


def _attr(tag: Tag | None, name: str) -> str:
    value = tag.get(name) if tag is not None else None
    return value.strip() if isinstance(value, str) else ""
