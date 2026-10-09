"""요건 항목 목록: 쓸 수 있는 연산자, 값, 기준, 화면 이름. 판정·문구·추출 검증이 함께 쓴다."""

from __future__ import annotations

from decimal import Decimal

DEFAULT_GPA_SCALE = Decimal("4.5")

_ALL = frozenset({"eq", "neq", "in", "not_in", "gte", "lte", "between"})
_SET = frozenset({"eq", "neq", "in", "not_in"})

ALLOWED_OPERATORS: dict[str, frozenset[str]] = {
    "department": _SET,
    "grade": _ALL,
    "enrollment_status": _SET,
    "semesters_completed": _ALL,
    "credits_total": _ALL,
    "credits_last_semester": _ALL,
    "gpa_total": frozenset({"eq", "gte", "lte", "between"}),
    "gpa_last_semester": frozenset({"eq", "gte", "lte", "between"}),
    "age": frozenset({"gte", "lte", "between"}),
    "region": _SET,
    "income_bracket": _ALL,
    "median_income_pct": _ALL,
    "welfare_status": _SET,
    "is_international": frozenset({"eq", "neq"}),
    "other": _ALL,
}

NUMBER_FIELDS = frozenset(
    {
        "grade",
        "semesters_completed",
        "credits_total",
        "credits_last_semester",
        "income_bracket",
        "median_income_pct",
    }
)
GPA_FIELDS = frozenset({"gpa_total", "gpa_last_semester"})

ENUM_LABELS: dict[str, dict[str, str]] = {
    "enrollment_status": {
        "enrolled": "재학",
        "on_leave": "휴학",
        "deferred_graduation": "졸업유예",
        "graduated": "졸업",
    },
    "welfare_status": {
        "none": "해당 없음",
        "near_poverty": "차상위",
        "basic_livelihood": "기초생활수급",
    },
}

# 거주지역 기준. 명시 없음은 주민등록으로 보고 비교한다 (PRD 5-3)
REGION_BASIS_LABELS = {
    "resident_registration": "주민등록 주소",
    "unspecified": "주민등록 주소",
    "actual_residence": "실거주",
    "high_school": "출신 고교 소재지",
    "guardian": "보호자 주소",
}
COMPARABLE_REGION_BASES = frozenset({"resident_registration", "unspecified"})

DEPARTMENT_LEVELS = {"department": "학과", "college": "단과대학", "field_group": "계열"}

FIELD_LABELS = {
    "department": "학과",
    "grade": "학년",
    "enrollment_status": "학적 상태",
    "semesters_completed": "이수 학기",
    "credits_total": "누적 이수학점",
    "credits_last_semester": "직전학기 이수학점",
    "gpa_total": "누적 평점",
    "gpa_last_semester": "직전학기 평점",
    "age": "나이",
    "region": "거주지역",
    "income_bracket": "학자금 지원구간",
    "median_income_pct": "기준 중위소득",
    "welfare_status": "수급 여부",
    "is_international": "외국인 유학생",
    "other": "기타 조건",
}

# 정보 필요일 때 물어볼 칸 이름. 나이는 생년월일(있으면 병역 복무 개월)을 묻는다
INPUT_LABELS = {**FIELD_LABELS, "is_international": "유학생 여부"}

UNITS = {
    "grade": "학년",
    "semesters_completed": "학기",
    "credits_total": "학점",
    "credits_last_semester": "학점",
    "income_bracket": "구간",
    "median_income_pct": "%",
}
