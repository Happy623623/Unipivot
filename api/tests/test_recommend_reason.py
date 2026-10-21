"""추천 사유 한 줄(F-24, app/eligibility/describe.recommend_reason)."""

import pytest

from app.eligibility import recommend_reason


@pytest.mark.parametrize(
    ("status", "passed", "expected"),
    [
        ("eligible", ["gpa_last_semester"], "직전학기 평점 조건이 맞아요"),
        ("eligible", ["department", "grade"], "학과·학년 조건이 맞아요"),
        ("eligible", ["college"], "단과대학 조건이 맞아요"),  # 학과 조건은 비교 단위로
        ("eligible", ["field_group", "region"], "계열·거주지역 조건이 맞아요"),
        (
            "eligible",
            ["grade", "gpa_total", "region", "age", "credits_total"],
            "학년·누적 평점·거주지역 외 2개 조건이 맞아요",
        ),
        ("undetermined", ["grade"], "학년 조건은 맞아요"),  # 확인할 조건이 남았다
        ("eligible", ["other"], None),  # 기타 조건만 맞았다(무엇인지 이름이 없다)
        ("eligible", ["other", "grade"], "학년 조건이 맞아요"),
        ("eligible", [], None),  # 조건 없는 공고
        ("ineligible", ["grade"], None),  # 지원 어려움은 사유를 쓰지 않는다
        ("eligible", ["unknown_field"], None),  # 모르는 항목 이름은 보이지 않는다
        ("eligible", ["department", "department"], "학과 조건이 맞아요"),
        # 유학생 여부는 "유학생이라는 뜻"으로 읽혀서, 소득·수급은 홈 카드에 드러내지 않으려고 쓰지 않는다
        ("eligible", ["is_international"], None),
        (
            "eligible",
            ["income_bracket", "median_income_pct", "annual_income", "welfare_status"],
            None,
        ),
        ("eligible", ["welfare_status", "grade"], "학년 조건이 맞아요"),
        ("eligible", ["degree_program"], None),  # 모든 과정을 받는 조건도 충족이라 뜻이 없다
        ("eligible", ["enrollment_status", "job_status"], "학적 상태·취업 상태 조건이 맞아요"),
    ],
)
def test_recommend_reason(status: str, passed: list[str], expected: str | None) -> None:
    assert recommend_reason(status, passed) == expected
