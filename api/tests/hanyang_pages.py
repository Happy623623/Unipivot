"""한양대 공지사항(Liferay 게시판) 페이지를 흉내 낸 HTML. 실제 저장 페이지(2026-10-08) 구조를 줄여 옮겼다.

실제 페이지는 레포에 넣지 않는다. 학교 저작물이고, 작성자 칸에 담당자 이름이 들어 있다.
"""

from pathlib import Path
from urllib.parse import quote_plus

from tests import samples

PORTLET = "_kr_ac_hanyang_noticeBoard_web_portlet_NoticeBoardPortlet"
BOARD = (
    "https://www.hanyang.ac.kr/notice_all?p_p_id=kr_ac_hanyang_noticeBoard_web_portlet_"
    "NoticeBoardPortlet&amp;p_p_lifecycle=0&amp;p_p_state=normal&amp;p_p_mode=view"
)
_BS = chr(92)  # 역슬래시. 자바스크립트 문자열 속 \x3d 같은 글자를 그대로 쓰려고 따로 둔다
PAGE = "공지사항 - 한양대학교.html"
FILES = "공지사항 - 한양대학교_files"  # "웹페이지, 전체"로 저장할 때 브라우저가 만드는 폴더
POSTER = samples.JPEG + b"\x01" * 6000  # 4KB가 넘는 본문 이미지(포스터)


def save_notice(
    folder: Path, html: str, files: dict[str, bytes], images: dict[str, bytes] | None = None
) -> Path:
    """공지 폴더 하나를 만든다: 페이지, 내려받은 첨부, (있으면) 본문 이미지 폴더."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / PAGE).write_text(html, encoding="utf-8")
    if images:
        (folder / FILES).mkdir(exist_ok=True)
        for name, data in images.items():
            (folder / FILES / name).write_bytes(data)
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return folder


def view_url(entry_id: int) -> str:
    return f"{BOARD}&amp;{PORTLET}_action=view_message&amp;{PORTLET}_entryId={entry_id}"


def file_url(name: str, uuid: str = "4dbaf8aa-b9bf-e196-a518-4dfeb4e1911b") -> str:
    return (
        "https://www.hanyang.ac.kr/documents/portlet_file_entry/20122/"
        f"{quote_plus(name)}/{uuid}?status=0&amp;download=true"
    )


def detail(
    *,
    entry_id: int = 119702,
    title: str = "2026학년도 2학기 ○○장학생 선발 안내",
    department: str = "학생지원팀",
    writer: str = "홍길동",
    posted: str = "2026. 9. 30",
    campus: str = "ERICA",
    category: str = "장학/등록",
    notice_period: str | None = "2026. 9. 30 ~ 2026. 10. 24",
    event_period: str | None = None,
    original_url: str | None = None,
    files: tuple[str, ...] = ("1. 선발요강.hwpx",),
    body: str = "<p>자세한 내용은 첨부를 보세요.</p>",
    permalink: bool = True,
    class_pk: bool = True,
    current_url: bool = True,
) -> str:
    """상세 페이지. 본문 아래에는 실제 페이지처럼 이전글·다음글 링크(다른 글 번호)가 있다."""
    meta = [("등록일", posted), ("캠퍼스 게시", campus), ("공지분류", category)]
    if notice_period:
        meta.append(("공지기간", f" {notice_period} "))
    if event_period:
        meta.append(("행사기간", f" {event_period} "))
    meta.append(("조회수", "326"))
    items = "".join(
        f'<div class="hyu-meta-item"><span>{label}</span> <span>{value}</span>\n</div>'
        for label, value in meta
    )
    if original_url:
        items += (
            '<div class="hyu-meta-item"><span>원문 URL</span> <span>'
            f'<a href="{original_url}" target="_blank">{original_url}</a></span></div>'
        )
    links = "".join(
        f'<a href="{file_url(name, f"uuid-{no}")}"> <i class="bi bi-download" title="다운로드"></i>'
        f" {name} </a> "
        for no, name in enumerate(files, 1)
    )
    head_script = ""
    if current_url:
        escaped = f"{_BS}x3d"
        head_script = (
            f"<script>Liferay.currentURL = '{_BS}x2fnotice_all{_BS}x3fp_p_id{escaped}"
            f"kr_ac_hanyang_noticeBoard_web_portlet_NoticeBoardPortlet{_BS}x26{PORTLET}"
            f"_action{escaped}view_message{_BS}x26{PORTLET}_entryId{escaped}{entry_id}';</script>"
        )
    url_input = (
        f'<input type="text" name="{PORTLET}_viewMessageURL" id="{PORTLET}_viewMessageURL"'
        f' class="hide" value="https://www.hanyang.ac.kr/notice/url/4a4/{entry_id:x}">'
        if permalink
        else ""
    )
    ratings = (
        "<script>Liferay.Ratings.register({ className: 'kr.ac.hanyang.noticeBoard.model.NBEntry',"
        f" classPK: '{entry_id}', type: 'thumbs' }});</script>"
        if class_pk
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="ko-KR"><head><meta charset="utf-8"><title>공지사항 - 한양대학교</title>{head_script}</head>
<body>
<div class="hyu-tabs-item active" role="tab"><a href="{BOARD}">전체</a></div>
<div class="hyu-tabs-item " role="tab"><a href="{BOARD}&amp;{PORTLET}_sCategoryId=224311300">장학/등록</a></div>
<div class="noticeBoard-view-message"><div class="hyu-list-container"><div class="hyu-list-inner">
 <div class="hyu-list-header"><div class="hyu-list-header-item">{url_input}</div></div>
 <div class="hyu-list-body"><div class="hyu-list-body-inner" role="article">
  <div class="hyu-list-body-item"><div class="hyu-list-body-item-col">
   <h4>{title}</h4>
   <div class="hyu-meta-container" role="note"><div class="hyu-meta-inner with-separator">
    <div class="hyu-meta-item" title="{department} / {writer}"><span>작성자</span> <span> {department} </span>
    </div>{items}
   </div></div>
   <div class="hyu-meta-container top-border" role="note"><div class="hyu-meta-inner">
    <div class="hyu-meta-item file-download">{links}</div>
   </div></div>
  </div></div>
  <div class="hyu-list-body-item entry-content"><div class="hyu-list-body-item-col">{body}</div></div>
  <div class="hyu-list-body-item"><div class="hyu-ratings-container">{ratings}</div></div>
 </div></div>
</div></div></div>
<div class="hyu-prevNext-container">
 <a href="{view_url(entry_id + 99)}">다음글</a> <a href="{view_url(entry_id - 1)}">이전글</a>
</div>
</body></html>"""


def listing(rows: list[dict[str, object]]) -> str:
    """목록 페이지. 행마다 entry_id·title·campus(없으면 캠퍼스 배지 없음)·category·department·posted."""
    items = []
    for row in rows:
        campus = row.get("campus")
        badge = (
            f'<span class="hyu-badge badge badge-light custom-bg" data-itemvalue="{campus}">{campus}</span> '
            if campus
            else ""
        )
        items.append(
            f"""<div class="hyu-list-body-item" data-itemsnum="2" role="listitem">
 <div class="hyu-list-body-item-col">
  <h4><a href="{view_url(int(str(row["entry_id"])))}">{row["title"]}</a></h4>
  <p><span class="hyu-badge badge badge-primary {PORTLET}_featured-badge hide" data-entryid="{row["entry_id"]}">주요알림</span> {badge}<span class="hyu-badge badge badge-light" data-itemvalue="{row["category"]}">{row["category"]}</span> <span>{row["department"]}</span> <span class="date">&nbsp;/&nbsp;{row["posted"]}</span> <span class="hyu-separator"></span></p>
 </div>
 <div class="hyu-list-body-item-col"><span>{row["posted"]}</span></div>
</div>"""
        )
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<div class="noticeBoard-view"><div class="hyu-list-container"><div class="hyu-list-inner">
 <div class="hyu-list-header"><div class="hyu-list-header-item"><span>전체 {len(rows)}건</span></div></div>
 <div class="hyu-list-body"><div class="hyu-list-body-inner" role="list">{"".join(items)}</div></div>
</div></div></div></body></html>"""
