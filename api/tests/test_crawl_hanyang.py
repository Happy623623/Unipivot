"""한양대 공지 페이지 파서: 상세(제목·글 번호·메타·첨부·본문), 목록, 캠퍼스·분류, 날짜."""

from datetime import date

import pytest

from app.crawl.hanyang import (
    NotNoticePage,
    body_text,
    campus_scope,
    opportunity_category,
    parse_date,
    parse_list,
    parse_notice,
    parse_period,
)
from tests import hanyang_pages


def test_detail_page_fields() -> None:
    html = hanyang_pages.detail(
        event_period="2026. 10. 22 ~ 2026. 10. 22",
        original_url="https://eip.hanyang.ac.kr/tenant/recruit.php?ptype=view&amp;idx=404",
        files=("1. 선발요강.hwpx", "2. 신청서(양식).hwp"),
        body=(
            "<p><b>신청 자격</b></p><table><tr><td>구분</td><td>평점</td></tr>"
            "<tr><td>재학생</td><td>3.0 이상</td></tr></table>"
            '<p><img alt="공지사항" src="./공지사항 - 한양대학교_files/포스터.jpg"></p>'
            '<p><img src="./공지사항 - 한양대학교_files/icon.gif"></p>'
        ),
    )
    page = parse_notice(html)
    assert page.entry_id == "119702"  # 고유 주소 끝의 16진수(1d396)
    assert page.title == "2026학년도 2학기 ○○장학생 선발 안내"
    assert page.permalink == "https://www.hanyang.ac.kr/notice/url/4a4/1d396"
    assert page.department == "학생지원팀"  # title 속성의 담당자 이름은 읽지 않는다
    assert "홍길동" not in repr(page)
    assert (page.posted_on, page.campus, page.category) == (date(2026, 9, 30), "ERICA", "장학/등록")
    assert page.notice_period == (date(2026, 9, 30), date(2026, 10, 24))
    assert page.event_period == (date(2026, 10, 22), date(2026, 10, 22))
    assert page.external_url == "https://eip.hanyang.ac.kr/tenant/recruit.php?ptype=view&idx=404"
    assert [link.name for link in page.attachments] == ["1. 선발요강.hwpx", "2. 신청서(양식).hwp"]
    assert page.attachments[0].url.startswith(
        "https://www.hanyang.ac.kr/documents/portlet_file_entry/20122/1.+"
    )
    assert "&download=true" in page.attachments[0].url  # &amp;는 풀어서 저장한다
    assert page.image_sources == (
        "./공지사항 - 한양대학교_files/포스터.jpg",
        "./공지사항 - 한양대학교_files/icon.gif",
    )
    assert (page.scope, page.opportunity_category) == ("erica", "scholarship")
    assert body_text(page).splitlines() == [
        "신청 자격",
        "구분 | 평점",
        "재학생 | 3.0 이상",
        "[이미지: 공지사항]",
    ]
    assert body_text(page, {0: "첨부 3번 포스터.jpg"}).endswith("[이미지: 첨부 3번 포스터.jpg]")


def test_entry_id_fallbacks_never_use_prev_next_links() -> None:
    no_permalink = hanyang_pages.detail(entry_id=120001, permalink=False)
    assert parse_notice(no_permalink).entry_id == "120001"  # 좋아요 칸의 classPK
    only_current = hanyang_pages.detail(entry_id=120002, permalink=False, class_pk=False)
    assert parse_notice(only_current).entry_id == "120002"  # Liferay.currentURL
    bare = hanyang_pages.detail(entry_id=120003, permalink=False, class_pk=False, current_url=False)
    assert (
        parse_notice(
            bare, page_url="https://www.hanyang.ac.kr/notice_all?x_entryId=120003"
        ).entry_id
        == "120003"
    )
    with pytest.raises(NotNoticePage, match="글 번호"):  # 이전글·다음글 번호를 집지 않는다
        parse_notice(bare)


@pytest.mark.parametrize(
    "html",
    [
        "<html><body><p>다른 사이트</p></body></html>",
        hanyang_pages.listing([]),
        hanyang_pages.detail(title=""),
    ],
)
def test_not_a_detail_page(html: str) -> None:
    with pytest.raises(NotNoticePage):
        parse_notice(html)


def test_missing_optional_fields_and_duplicate_links() -> None:
    html = hanyang_pages.detail(notice_period=None, files=("같은 파일.pdf", "같은 파일.pdf"))
    html = html.replace("uuid-2", "uuid-1")  # 같은 다운로드 주소가 두 번
    html = html.replace("<span>등록일</span> <span>2026. 9. 30</span>", "")
    page = parse_notice(html)
    assert (page.notice_period, page.event_period, page.external_url) == (None, None, None)
    assert page.posted_on is None
    assert len(page.attachments) == 1
    nameless = hanyang_pages.detail(files=("공고문.pdf",)).replace(" 공고문.pdf </a>", "</a>")
    assert [link.name for link in parse_notice(nameless).attachments] == ["공고문.pdf"]  # 주소에서


@pytest.mark.parametrize(
    ("campus", "scope"),
    [
        ("ERICA", "erica"),
        ("한양", "erica"),  # 두 캠퍼스 공통
        ("서울", "seoul"),
        ("서울, ERICA", "erica"),
        ("안함", "unmarked"),
        (None, "unmarked"),
    ],
)
def test_campus_scope(campus: str | None, scope: str) -> None:
    assert campus_scope(campus) == scope


def test_board_category_to_opportunity_category() -> None:
    assert opportunity_category("장학/등록") == "scholarship"
    assert opportunity_category(" 산학/연구 ") == "research"
    assert opportunity_category("사회봉사") == "activity"
    assert opportunity_category("행사") == "school_program"
    assert opportunity_category("새 분류") == "etc"
    assert opportunity_category(None) == "etc"


def test_list_page_rows() -> None:
    html = hanyang_pages.listing(
        [
            {
                "entry_id": 120202,
                "title": "[IC-PBL교수학습센터] 2026 애스크톤 예선 결과 발표",
                "campus": "한양",
                "category": "일반",
                "department": "IC-PBL교수학습센터",
                "posted": "2026. 10. 8",
            },
            {
                "entry_id": 119902,
                "title": "입학설명회 안내",
                "campus": None,  # 캠퍼스 게시 "안함"이면 배지가 없다
                "category": "행사",
                "department": "기술혁신대학 RC 행정팀",
                "posted": "2026. 10. 1",
            },
        ]
    )
    first, second = parse_list(html)
    assert (first.entry_id, first.campus, first.category, first.department) == (
        "120202",
        "한양",
        "일반",
        "IC-PBL교수학습센터",
    )
    assert first.posted_on == date(2026, 10, 8) and first.scope == "erica"
    assert first.url.endswith("entryId=120202") and "&amp;" not in first.url
    assert (second.campus, second.category, second.scope) == (None, "행사", "unmarked")
    with pytest.raises(NotNoticePage):
        parse_list(hanyang_pages.detail())


def test_dates() -> None:
    assert parse_date("2026. 9. 30") == date(2026, 9, 30)
    assert parse_date(" / 2026.09.30") == date(2026, 9, 30)
    assert parse_date("2026. 2. 30") is None
    assert parse_date("") is None
    assert parse_period(" 2026. 9. 30 ~ 2026. 11. 13 ") == (date(2026, 9, 30), date(2026, 11, 13))
    assert parse_period("2026. 10. 22") == (date(2026, 10, 22), date(2026, 10, 22))
    assert parse_period("상시") is None
