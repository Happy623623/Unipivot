"""S09·S10이 가져오는 지은 학교 공지(app/eval/notice.py). DB 없이 본다.

공지는 실제 가져오기 코드로 들어가므로, 첨부가 실제 글자 뽑기(app/attachments)로 읽히고 근거 문장이
그대로 나와야 녹화한 답의 근거 대조가 통과한다. 글자 뽑기가 바뀌어 근거가 어긋나면 여기서 먼저 걸린다.
"""

from datetime import date

from app.attachments import read_attachment_text
from app.crawl.hanyang import BOARD_URL
from app.eval.notice import (
    ATTACHED_ONLY_BODY,
    EXTENDED_GRADE_LINE,
    FORM_FILE,
    FORM_TEXT,
    GUIDE_CREDIT_LINE,
    GUIDE_FILE,
    GUIDE_GRADE_LINE,
    dotted,
    extended_body,
    form_pdf,
    guide_lines,
    hwpx,
    notice,
)
from app.extraction.store import content_hash
from app.extraction.validate import Evidence

DEADLINE = date(2026, 10, 24)


def squeezed(text: str) -> str:
    return "".join(text.split())


def test_the_guide_reads_back_with_the_requirement_lines() -> None:
    scanned = read_attachment_text(hwpx(guide_lines(DEADLINE)), GUIDE_FILE)
    assert scanned.kind == "hwpx" and not scanned.needs_vision
    assert scanned.text.splitlines() == guide_lines(DEADLINE)
    # 근거 대조는 읽은 글자로 한다. 녹화한 답의 근거 문장이 그대로 찾아져야 한다
    evidence = Evidence()
    evidence.add(scanned.text)
    assert evidence.contains(GUIDE_GRADE_LINE) and evidence.contains(GUIDE_CREDIT_LINE)
    assert "2026. 10. 24. 17:00까지" in scanned.text


def test_the_requirements_are_only_in_the_guide() -> None:
    """S09의 전제: 본문만 읽어서는 근거 문장을 찾을 수 없다."""
    evidence = Evidence()
    evidence.add(ATTACHED_ONLY_BODY)
    assert not evidence.contains(GUIDE_GRADE_LINE)
    assert not evidence.contains(GUIDE_CREDIT_LINE)


def test_the_recorded_form_pdf_still_reads() -> None:
    """신청서 PDF는 담아 둔 이진 파일이다(강의계획서 PDF와 같은 방법). 글자가 그대로 뽑히는지 본다."""
    scanned = read_attachment_text(form_pdf(), FORM_FILE)
    assert (scanned.kind, scanned.page_count, scanned.needs_vision) == ("pdf", 1, False)
    assert squeezed(scanned.text) == squeezed(FORM_TEXT)


def test_a_notice_looks_like_a_saved_hanyang_notice() -> None:
    content = notice(
        "eval-S09-1234abcd",
        "선발 안내",
        body=["첫 줄", "둘째 줄"],
        posted_on=date(2026, 10, 11),
        files=[(GUIDE_FILE, b"guide"), (FORM_FILE, b"form")],
    )
    page = content.page
    assert page.scope == "erica" and page.opportunity_category == "scholarship"
    assert page.permalink == f"{BOARD_URL}?mode=view&articleNo=eval-S09-1234abcd"
    assert content.text == "첫 줄\n둘째 줄"
    assert [(file.seq, file.name) for file in content.files] == [(1, GUIDE_FILE), (2, FORM_FILE)]
    assert content.files[1].source_url == (
        f"{BOARD_URL}?mode=download&articleNo=eval-S09-1234abcd&attachNo=2"
    )
    assert content.missing == ()
    notice_input = content.notice_input()
    assert notice_input.posted_on == date(2026, 10, 11)
    assert [attachment.seq for attachment in notice_input.attachments] == [1, 2]


def test_the_edited_notice_changes_only_the_dates() -> None:
    """S10: 고친 글은 내용 지문이 달라 다시 추출하고, 자격 줄은 그대로다."""
    extended = date(2026, 10, 31)
    before = extended_body(DEADLINE, extended=False)
    after = extended_body(extended, extended=True)
    assert after[0] == f"[마감 연장] 신청 기간을 {dotted(extended)}까지 연장합니다."
    assert (
        f"지원 자격: {EXTENDED_GRADE_LINE}" in before
        and f"지원 자격: {EXTENDED_GRADE_LINE}" in after
    )
    assert f"신청 기간: {dotted(extended)} 17:00까지" in after

    def digest(lines: list[str]) -> str:
        notice_input = notice("1", "모집", body=lines, posted_on=date(2026, 10, 11)).notice_input()
        return content_hash(notice_input.body, notice_input.attachments)

    assert digest(before) != digest(after)
    assert digest(after) == digest(extended_body(extended, extended=True))  # 같은 글은 같은 지문


def test_dates_are_written_the_way_the_school_writes_them() -> None:
    assert dotted(date(2026, 11, 3)) == "2026. 11. 3."
