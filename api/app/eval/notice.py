"""시나리오가 가져오는 학교 공지(S09·S10). 한양대 게시판 글 모양을 **우리가 지어** 만든다.

실제 공지·첨부는 학교가 쓴 글이라 레포에 두지 않는다(PRD 8장 정답셋과 같은 이유). 그래서 페이지 칸(글 번호·
부서·게시일·캠퍼스·분류)과 첨부(HWPX 선발요강, PDF 신청서)를 지어서 **실제 가져오기 코드**
(app/crawl/importer.py, A안)에 넘긴다 — 첨부 글자 뽑기·요건 추출 에이전트·근거 대조·저장이 운영과 같은 길로
돈다. 모델 답만 녹화한 것이다.

HWPX는 zip 안의 XML이라 코드로 만든다. PDF는 글꼴이 들어간 이진 파일이라 코드로 다시 만들 수 없어서, 만들어 둔
파일을 zlib+base64로 담았다(강의계획서 S15와 같은 방법, app/eval/syllabus.py). 다시 만들려면 개발 환경에서:

    uv run python -c "import base64, zlib; from tests import samples; \
      from app.eval.notice import FORM_TEXT; \
      print(base64.b64encode(zlib.compress(samples.pdf([FORM_TEXT]), 9)).decode())"

`tests/test_eval_notice.py`가 두 첨부를 실제 글자 뽑기로 읽어 근거 문장이 그대로 나오는지 본다.

날짜는 모두 시나리오 시계(`world.today`)에서 센다. 며칠 뒤에 다시 돌려도 같은 결과가 나오게 한다.
"""

import base64
import zipfile
import zlib
from collections.abc import Sequence
from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from app.crawl.hanyang import BOARD_URL, NoticePage
from app.crawl.saved import NoticeContent, SavedFile

DEPARTMENT = "학생지원팀"
CATEGORY = "장학/등록"
CAMPUS = "ERICA"
# 선발요강 첨부(S09). 지원 자격은 **이 첨부에만** 있다 — 본문은 "첨부 참조"뿐이다
GUIDE_FILE = "2026-2 미래인재 장학 선발요강.hwpx"
GUIDE_GRADE_LINE = "가. 직전 학기 평점평균 3.0 이상인 재학생"
GUIDE_CREDIT_LINE = "나. 직전 학기 12학점 이상 이수자"
ATTACHED_ONLY_BODY = "2026학년도 2학기 미래인재 장학생을 선발합니다. 지원 자격과 제출 서류는 첨부한 선발요강을 확인하세요."
# 신청서 양식 첨부(S09). 에이전트가 읽지 않는 첨부다 — 서류 "장학금 신청서"의 양식 링크로만 쓴다
FORM_FILE = "장학금 신청서.pdf"
FORM_TEXT = """장학금 신청서

성명:                    학번:
소속 학과:               학년:
연락처:
신청 장학: 미래인재 장학

위와 같이 장학금을 신청합니다.

신청인:                  (서명)
학생지원팀 귀중
"""
# 마감 연장 공지(S10). 자격은 본문에 있고, 고친 글은 신청 기간만 바뀐다
EXTENDED_GRADE_LINE = "직전 학기 평점평균 3.0 이상인 재학생"
_HWPX_NS = (
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
)


def hwpx(lines: Sequence[str]) -> bytes:
    """문단마다 한 줄인 HWPX(한글 문서). 첨부 글자 뽑기(app/attachments)가 읽는 최소 모양이다."""
    paragraphs = "".join(
        f"<hp:p><hp:run><hp:t>{escape(line)}</hp:t></hp:run></hp:p>" for line in lines
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr(
            "META-INF/manifest.xml",
            '<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>',
        )
        archive.writestr(
            "Contents/section0.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><hs:sec {_HWPX_NS}>{paragraphs}</hs:sec>',
        )
    return buffer.getvalue()


def form_pdf() -> bytes:
    """신청서 양식 PDF(한 쪽). FORM_TEXT를 쓴 파일이다."""
    return zlib.decompress(base64.b64decode(_FORM_PDF_BASE64))


def dotted(day: date) -> str:
    """학교 공지의 날짜 꼴(2026. 11. 3.)."""
    return f"{day.year}. {day.month}. {day.day}."


def notice(
    entry_id: str,
    title: str,
    *,
    body: Sequence[str],
    posted_on: date,
    files: Sequence[tuple[str, bytes]] = (),
) -> NoticeContent:
    """게시판 글 한 건. files는 (첨부 이름, 내용)이고 페이지의 첨부 목록 순서대로 1번부터다."""
    links = tuple(
        SavedFile(
            seq=seq,
            name=name,
            data=data,
            source_url=f"{BOARD_URL}?mode=download&articleNo={entry_id}&attachNo={seq}",
            file_name=name,
        )
        for seq, (name, data) in enumerate(files, 1)
    )
    page = NoticePage(
        entry_id=entry_id,
        title=title,
        permalink=f"{BOARD_URL}?mode=view&articleNo={entry_id}",
        department=DEPARTMENT,
        posted_on=posted_on,
        campus=CAMPUS,
        category=CATEGORY,
        notice_period=None,
        event_period=None,
        external_url=None,
        attachments=(),
        body_html="".join(f"<p>{escape(line)}</p>" for line in body),
        image_sources=(),
    )
    return NoticeContent(page=page, text="\n".join(body), files=links)


def guide_lines(deadline: date) -> list[str]:
    """S09 선발요강 글. 자격 두 줄과 신청 기간이 있다."""
    return [
        "2026학년도 2학기 미래인재 장학생 선발요강",
        "1. 지원 자격",
        GUIDE_GRADE_LINE,
        GUIDE_CREDIT_LINE,
        "2. 제출 서류: 장학금 신청서 1부, 성적증명서 1부",
        f"3. 신청 기간: {dotted(deadline)} 17:00까지 (학생지원팀 방문 제출)",
    ]


def extended_body(deadline: date, *, extended: bool) -> list[str]:
    """S10 공지 본문. 고친 글(extended)은 마감이 미뤄졌다고 맨 위에 적는다."""
    lines = [
        "2026학년도 2학기 ERICA 근로장학생을 모집합니다.",
        f"지원 자격: {EXTENDED_GRADE_LINE}",
        f"신청 기간: {dotted(deadline)} 17:00까지",
        "제출 서류: 근로장학 신청서",
    ]
    if extended:
        lines.insert(0, f"[마감 연장] 신청 기간을 {dotted(deadline)}까지 연장합니다.")
    return lines


_FORM_PDF_BASE64 = (
    "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"
)
