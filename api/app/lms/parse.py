"""과목명 파싱과 포털 계획서 링크 (F-14·F-50).

LearningX 과목명은 `202620HY23525_데이터베이스` 꼴이다(2026-10-16 녹화, 8과목 모두 같았다).
앞에서 연도(2026)·학기 코드(20)·과목번호(23525)를 떼어 포털 계획서 링크를 만들고, `_` 뒤를 화면 이름으로 쓴다.
꼴이 다르면 이름 전체를 화면 이름으로 쓰고 링크를 만들지 않는다 — 없는 번호로 포털을 열면 빈 창이 뜬다.

포털에는 서버가 요청하지 않는다(robots.txt). 링크는 사용자 브라우저에서만 연다(API 명세 8장).
"""

import re
from dataclasses import dataclass
from typing import Any

BIGINT_MAX = 2**63 - 1  # Canvas 번호는 bigint 칸에 들어가야 한다


def is_canvas_id(value: Any) -> bool:
    """Canvas 번호로 쓸 수 있는 값인지. bool과 bigint를 넘는 수는 거른다(그대로 넣으면 DB가 터진다)."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= BIGINT_MAX


# 명세 8장의 링크 그대로. 사용자 브라우저에서 열면 그 과목 계획서 팝업이 뜬다
PORTAL_SYLLABUS_URL = (
    "https://portal.hanyang.ac.kr/openPop.do?header=hidden"
    "&url=/haksa/SughAct/findSuupPlanDocHyIn.do&flag=BB"
    "&year={year}&term={term}&suup={course_no}&language=ko"
)
# 학기 코드 → 표시. 1·2학기만 녹화로 확인했고 계절학기는 한양대 코드 규칙을 따랐다
TERM_NAMES: dict[int, str] = {10: "1", 11: "여름", 20: "2", 21: "겨울"}
_COURSE_NAME = re.compile(r"^(?P<year>\d{4})(?P<term>\d{2})HY(?P<no>\d{3,6})_(?P<short>.+)$")


@dataclass(frozen=True)
class CourseName:
    """과목명에서 뽑은 값. 꼴이 다르면 short_name만 있고 나머지는 None이다."""

    short_name: str
    portal_year: int | None = None
    portal_term: int | None = None
    portal_course_no: str | None = None

    @property
    def syllabus_url(self) -> str | None:
        """포털 계획서 링크. 번호를 못 뽑았으면 없다."""
        if self.portal_year is None or self.portal_term is None or not self.portal_course_no:
            return None
        return PORTAL_SYLLABUS_URL.format(
            year=self.portal_year, term=self.portal_term, course_no=self.portal_course_no
        )

    def term(self, fallback: str | None = None) -> str | None:
        """학기 표시(`2026-2`). 꼴이 다르면 LearningX가 준 학기 이름을 쓴다."""
        if self.portal_year is None or self.portal_term is None:
            return fallback
        name = TERM_NAMES.get(self.portal_term)
        return f"{self.portal_year}-{name}" if name else fallback


def course_name(name: str) -> CourseName:
    found = _COURSE_NAME.match(name.strip())
    if not found:
        return CourseName(short_name=name.strip())
    return CourseName(
        short_name=found["short"].strip(),
        portal_year=int(found["year"]),
        portal_term=int(found["term"]),
        portal_course_no=found["no"],
    )
