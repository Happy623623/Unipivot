"""녹화한 강의계획서 PDF (S15).

학생이 포털 계획서를 브라우저에서 "PDF로 저장"해 올린 파일 한 장이다. **날짜 없이 주차만** 적힌
계획서라서(실제 계획서의 흔한 꼴) 모델이 학기 시작일에서 날짜를 세야 한다 — 시나리오를 어느 날로
돌려도 같은 결과가 나오게 하는 데도 이 꼴이 맞는다(explicit 날짜를 적으면 그 학기에만 맞는다).

PDF는 글꼴·압축이 들어간 이진 파일이라 코드로 다시 만들 수 없어서, 만들어 둔 파일을 zlib+base64로
담았다. 다시 만들려면 개발 환경에서:

    uv run python -c "import base64, zlib; from tests import samples; \
      from app.eval.syllabus import SYLLABUS_TEXT; \
      print(base64.b64encode(zlib.compress(samples.pdf([SYLLABUS_TEXT]), 9)).decode())"

`tests/test_eval_cli.py`가 이 블록을 풀어 글자가 그대로 나오는지 본다(글꼴이 바뀌면 거기서 걸린다).
"""

import base64
import zlib

# PDF에서 뽑히는 글자(쪽 하나). 시나리오가 쓰는 근거 문장이 이 안에 있어야 한다
SYLLABUS_TEXT = """강의계획서

교과목명: 데이터베이스
담당교수: 김한양
강의시간: 화·목 10:30~12:00 (IT공학관 503)

주차별 운영 계획
1주차 강의 소개, 관계 모델
4주차 SQL 기초와 조인
8주차 중간고사 (강의실, 10:30~12:00)
11주차 팀 프로젝트 중간 발표
13주차 트랜잭션과 회복
15주차 기말고사 (강의실, 10:30~12:00)

평가 방법: 중간 30%, 기말 30%, 프로젝트 30%, 출석 10%
과제는 LMS로 제출하며 마감은 각 과제 공지를 따릅니다.
"""

# 중간고사·발표·기말고사가 들어 있는 줄(모델이 근거로 적는 문장). 뽑은 글자에 그대로 있어야 한다
MIDTERM_LINE = "8주차 중간고사 (강의실, 10:30~12:00)"
PRESENTATION_LINE = "11주차 팀 프로젝트 중간 발표"
FINAL_LINE = "15주차 기말고사 (강의실, 10:30~12:00)"
# 그 줄의 주차. 모델은 이 주차를 학기 시작일에서 날짜로 센다(시나리오가 같은 셈을 한다)
MIDTERM_WEEK = 8
PRESENTATION_WEEK = 11
FINAL_WEEK = 15
# 계획서에 **없는** 줄. 근거 검사를 보려고 녹화 답에 하나 끼워 넣는다(저장되면 안 된다)
MADE_UP_LINE = "17주차 보충 시험 11/30(월) 10:30"
# 계획서에 **있지만 날짜도 주차도 없는** 줄. 이것만 근거로 적은 일정도 저장되면 안 된다
NO_DATE_LINE = "평가 방법: 중간 30%, 기말 30%, 프로젝트 30%, 출석 10%"

_PDF_BASE64 = (
    "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"
    "mUx72En9FwUwSYM="
)


def syllabus_pdf() -> bytes:
    """녹화한 계획서 PDF 바이트."""
    return zlib.decompress(base64.b64decode(_PDF_BASE64))
