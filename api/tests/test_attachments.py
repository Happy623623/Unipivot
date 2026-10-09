"""첨부 읽기: 형식 판별, PDF·HWPX·HWP 글자 추출, Vision으로 보낼 파일, HTML 글자."""

import random
import struct
import zipfile
from io import BytesIO

import pytest
from pypdf import PdfReader

from app.attachments import (
    UnreadableAttachment,
    clean_text,
    detect_format,
    html_text,
    read_attachment_text,
    vision_payload,
)
from app.attachments.hwp import HwpError, _Counter, hwp_text, read_ole, section_lines
from tests import samples
from tests.samples import hp, hp_cell

NOTICE = "1. 지원 자격\n가. 직전 학기 평점평균 3.0 이상(4.5 만점)\n다. 경기도 안산시에 주민등록이 되어 있는 자"


# ---------- 형식 판별 ----------


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (samples.pdf(["가나다"]), "pdf"),
        (b"\x00\x00%PDF-1.7 junk before header", "pdf"),
        (samples.hwpx(hp("본문")), "hwpx"),
        (samples.PNG, "png"),
        (samples.JPEG, "jpeg"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "webp"),
        (b"GIF89a\x00\x00", "gif"),
        (b"HWP Document File V3.00 \x1a\x01\x02\x03\x04\x05", "hwp3"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, "ole"),  # 깨진 OLE도 HWP가 아니다
        (b"plain text", "unknown"),
    ],
)
def test_detect_format_trusts_content_over_name(data: bytes, kind: str) -> None:
    assert detect_format(data, "확장자가_틀린_파일.hwp") == kind


def test_detect_format_tells_office_zips_apart() -> None:
    def zipped(name: str) -> bytes:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(name, "<x/>")
        return buffer.getvalue()

    assert detect_format(zipped("word/document.xml")) == "docx"
    assert detect_format(zipped("xl/workbook.xml")) == "xlsx"
    assert detect_format(zipped("서류.txt")) == "zip"


# ---------- PDF ----------


def test_pdf_text_and_pages_without_text() -> None:
    data = samples.pdf([NOTICE, None, "2. 신청 기간: 2026. 10. 13. ~ 10. 24. 18:00까지"])
    result = read_attachment_text(data, "공고문.pdf")
    assert (result.kind, result.method, result.page_count) == ("pdf", "pdf_text", 3)
    assert result.image_pages == (2,)  # 글자 없는 쪽만 Vision 후보
    assert "평점평균 3.0 이상(4.5 만점)" in result.text
    assert "10. 24. 18:00까지" in result.text
    assert not result.needs_vision


def test_scanned_pdf_needs_vision() -> None:
    result = read_attachment_text(samples.pdf([None, None]))
    assert (result.method, result.text, result.image_pages) == (None, "", (1, 2))
    assert result.needs_vision


def test_pdf_with_user_password_is_unreadable() -> None:
    with pytest.raises(UnreadableAttachment, match="암호"):
        read_attachment_text(samples.pdf([NOTICE], user_password="1234"))


def test_broken_pdf_is_unreadable() -> None:
    with pytest.raises(UnreadableAttachment, match="PDF를 열 수 없어요"):
        read_attachment_text(b"%PDF-1.7\nbroken")


# ---------- HWPX ----------


def test_hwpx_paragraphs_tables_and_text_boxes() -> None:
    table = (
        "<hp:p><hp:run><hp:tbl>"
        f"<hp:tr>{hp_cell(0, 0, '구분')}{hp_cell(0, 1, '지원 금액')}</hp:tr>"
        f"<hp:tr>{hp_cell(1, 0, '성적우수', row_span=2)}{hp_cell(1, 1, '200만원')}</hp:tr>"
        f"<hp:tr>{hp_cell(2, 1, '100만원')}</hp:tr>"
        "</hp:tbl></hp:run></hp:p>"
    )
    box = (
        "<hp:p><hp:run><hp:rect><hp:drawText><hp:subList>"
        f"{hp('※ 휴학생 제외')}"
        "</hp:subList></hp:drawText></hp:rect>"
        "<hp:t>문의<hp:tab/>장학팀<hp:lineBreak/>031-400-0000</hp:t></hp:run></hp:p>"
    )
    first = hp("1. 지원 자격") + table + box
    result = read_attachment_text(samples.hwpx(first, hp("2쪽 구역")), "공고.hwpx")
    assert (result.kind, result.method) == ("hwpx", "hwpx_text")
    assert result.text.splitlines() == [
        "1. 지원 자격",
        "구분 | 지원 금액",
        "성적우수 | 200만원",
        "성적우수 | 100만원",  # 병합된 구분 칸을 행마다 되풀이
        "※ 휴학생 제외",
        "문의\t장학팀",
        "031-400-0000",
        "2쪽 구역",
    ]


def test_hwpx_sections_are_read_in_number_order() -> None:
    data = samples.hwpx(*[hp(f"구역 {no}") for no in range(12)])
    lines = read_attachment_text(data).text.splitlines()
    assert lines == [f"구역 {no}" for no in range(12)]  # section10이 section2보다 앞서지 않는다


def test_one_column_table_keeps_lines() -> None:
    box = f"<hp:p><hp:run><hp:tbl><hp:tr>{hp_cell(0, 0, '제목')}</hp:tr></hp:tbl></hp:run></hp:p>"
    box = box.replace(hp("제목"), hp("공고 제목") + hp("본문 첫 줄"))
    assert read_attachment_text(samples.hwpx(box)).text.splitlines() == ["공고 제목", "본문 첫 줄"]


def test_locked_or_empty_hwpx_is_unreadable() -> None:
    with pytest.raises(UnreadableAttachment, match="배포용"):
        read_attachment_text(samples.hwpx(hp("x"), encrypted=True))
    with pytest.raises(UnreadableAttachment, match="글자가 없는"):
        read_attachment_text(samples.hwpx("<hp:p><hp:run/></hp:p>"))


# ---------- HWP 5.0 ----------


def _section() -> bytes:
    return (
        samples.para(0, "1. 지원 자격")
        + samples.table(
            0,
            [(0, 0, 2, "성적우수"), (0, 1, 1, "평점 4.0 이상"), (1, 1, 1, "평점 3.5 이상")],
        )
        + samples.para(0, "2. 신청 기간: 10. 24.까지")
    )


EXPECTED_HWP = [
    "1. 지원 자격",
    "성적우수 | 평점 4.0 이상",
    "성적우수 | 평점 3.5 이상",
    "2. 신청 기간: 10. 24.까지",
]


@pytest.mark.parametrize("compressed", [True, False])
def test_hwp_body_text_with_table(compressed: bool) -> None:
    ole = samples.hwp_ole(_section(), samples.para(0, "둘째 구역"), compressed=compressed)
    assert read_ole(ole).splitlines() == [*EXPECTED_HWP, "둘째 구역"]


def test_hwp_distribution_document_is_decrypted() -> None:
    ole = samples.hwp_ole(_section(), distribution=True)
    assert read_ole(ole).splitlines() == EXPECTED_HWP


def test_hwp_parsing_is_bounded() -> None:
    assert section_lines(b"\x00" * 4096) == []  # 태그 0 레코드는 없다: 깨진 뒷부분으로 보고 멈춘다
    two_paragraphs = samples.para(0, "가") + samples.para(0, "나")  # 레코드 4개
    with pytest.raises(HwpError, match="너무 커요"):
        section_lines(two_paragraphs, _Counter(3))


def test_hwp_table_caption_is_not_a_cell() -> None:
    """캡션 리스트 헤더는 TABLE 레코드 앞에 온다. 셀로 읽으면 캡션이 엉뚱한 칸에 끼어든다."""
    section = samples.table(0, [(0, 0, 1, "구분"), (0, 1, 1, "기준")], caption="표 1. 선발 기준")
    assert read_ole(samples.hwp_ole(section)).splitlines() == ["표 1. 선발 기준", "구분 | 기준"]


def test_hwp_long_record_and_controls() -> None:
    long_text = "가" * 3000  # 6000바이트라 레코드 크기가 확장 필드(0xFFF)로 간다
    tab = struct.pack("<8H", 9, 0, 0, 0, 0, 0, 0, 9)  # 탭은 8글자(16바이트)짜리 제어 문자다
    line_break = struct.pack("<H", 10)
    section = (
        samples.para(0, long_text)
        + samples.record(samples.PARA_TEXT, 1, _utf16("탭") + tab + _utf16("뒤"))
        + samples.record(samples.PARA_TEXT, 1, _utf16("줄") + line_break + _utf16("바꿈"))
    )
    assert read_ole(samples.hwp_ole(section)).splitlines() == [long_text, "탭\t뒤", "줄", "바꿈"]


def test_hwp_errors() -> None:
    with pytest.raises(HwpError, match="암호"):
        read_ole(samples.FakeOle({**samples.hwp_ole(b"").streams, "FileHeader": _header(0b10)}))
    with pytest.raises(HwpError, match="버전"):
        read_ole(samples.hwp_ole(_section(), version=0x03000000))
    with pytest.raises(HwpError, match="OLE"):
        hwp_text(b"not an ole file")


def _utf16(text: str) -> bytes:
    return text.encode("utf-16-le")


def _header(props: int) -> bytes:
    return samples.SIGNATURE.ljust(32, b"\x00") + struct.pack("<II", 0x05000300, props)


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"HWP Document File V3.00 \x1a", "HWP 3.0"),
        (b"\x00\x01plain", "알 수 없는 형식"),
        (b"GIF89a....", "GIF"),
    ],
)
def test_unsupported_formats(data: bytes, reason: str) -> None:
    with pytest.raises(UnreadableAttachment, match=reason):
        read_attachment_text(data)


# ---------- 깨진 파일 ----------


def _mutations(data: bytes, count: int, seed: int) -> list[bytes]:
    """앞부분(형식 판별용 머리)은 두고 나머지 바이트를 하나씩 바꾼 파일들."""
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        broken = bytearray(data)
        position = rng.randrange(16, len(broken))
        broken[position] = rng.randrange(256)
        out.append(bytes(broken))
    return out


@pytest.mark.parametrize(
    "data",
    [
        samples.hwpx(hp("직전 학기 평점평균 3.0 이상"), hp("둘째 구역")),
        samples.pdf([NOTICE, None]),
    ],
    ids=["hwpx", "pdf"],
)
def test_broken_files_only_raise_unreadable(data: bytes) -> None:
    """깨진 첨부 하나 때문에 실행 전체가 멈추면 안 된다. 형식 판별은 예외가 없고, 추출은 사유 한 줄로 끝난다."""
    for broken in _mutations(data, 150, seed=7):
        kind = detect_format(broken)
        try:
            result = read_attachment_text(broken)
        except UnreadableAttachment as exc:
            assert str(exc)
            continue
        if kind == "pdf" and result.page_count:
            try:
                vision_payload(broken, "pdf", start_page=1)
            except UnreadableAttachment:
                pass


def test_zip_with_encrypted_or_misnamed_entries_is_unreadable() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", "<x/>")
    data = bytearray(buffer.getvalue())
    data[6] |= 0x01  # 첫 항목에 '암호 걸림' 표시
    assert detect_format(bytes(data)) in ("zip", "hwpx")
    with pytest.raises(UnreadableAttachment):
        read_attachment_text(bytes(data))


def test_pdf_slicing_failure_is_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_slice(data: bytes, first: int, count: int) -> bytes:
        raise ValueError("쪽 내용이 깨짐")

    monkeypatch.setattr("app.attachments.reader.pdf_slice", broken_slice)
    with pytest.raises(UnreadableAttachment, match="깨진 파일"):
        vision_payload(samples.pdf([None]), "pdf")


def test_clean_text_removes_control_characters() -> None:
    assert clean_text("가\x00나\x07다\t라\n마\r\n") == "가나다\t라\n마\r\n"


# ---------- Vision ----------


def test_vision_payload_slices_pdf_pages() -> None:
    data = samples.pdf([None, None, None, None, None, None])
    payload = vision_payload(data, "pdf", start_page=3, max_pages=2)
    assert (payload.mime_type, payload.first_page, payload.last_page) == ("application/pdf", 3, 4)
    assert payload.page_count == 6
    assert len(PdfReader(BytesIO(payload.data)).pages) == 2
    last = vision_payload(data, "pdf", start_page=5, max_pages=4)
    assert (last.first_page, last.last_page) == (5, 6)
    with pytest.raises(UnreadableAttachment, match="6쪽까지만"):
        vision_payload(data, "pdf", start_page=7)


def test_vision_payload_for_images_and_others() -> None:
    assert vision_payload(samples.PNG, "png").mime_type == "image/png"
    assert vision_payload(samples.JPEG, "jpeg").data == samples.JPEG
    with pytest.raises(UnreadableAttachment, match="Vision"):
        vision_payload(b"x", "hwp")


# ---------- HTML ----------


def test_html_text_keeps_rows_and_drops_scripts() -> None:
    html = """<html><head><title>제목</title><script>var x = 1;</script></head><body>
      <nav><a>메뉴1</a> <a>메뉴2</a></nav>
      <h3>장학금 &amp; 지원 안내</h3>
      <p>신청 기간<br>10. 24.까지</p>
      <table><tr><th>구분</th><td>내용<p>둘째 문단</p></td></tr>
        <tr><td>자격</td><td><table><tr><td>안쪽</td><td>표</td></tr></table></td></tr></table>
      <img src="poster.jpg" alt="포스터: 마감 10/24">
      <footer>문의 031-400-0000</footer></body></html>"""
    assert html_text(html).splitlines() == [
        "메뉴1 메뉴2",  # 메뉴는 버리지 않는다(닫는 태그가 빠진 페이지에서 본문까지 사라지지 않게)
        "장학금 & 지원 안내",
        "신청 기간",
        "10. 24.까지",
        "구분 | 내용 둘째 문단",
        "자격 | 안쪽 표",
        "[이미지: 포스터: 마감 10/24]",
        "문의 031-400-0000",
    ]


@pytest.mark.parametrize(
    "html",
    [
        "<html><head><meta charset='utf-8'><title>공지</title><body><p>평점 3.0 이상</p>",
        "<head><title>공지</title><p>평점 3.0 이상",  # </head>도 <body>도 없음
        "<body><nav><ul><li>메뉴</li></ul><p>평점 3.0 이상</p></body>",  # </nav> 빠짐
    ],
)
def test_html_text_survives_missing_end_tags(html: str) -> None:
    assert html_text(html).splitlines()[-1] == "평점 3.0 이상"
