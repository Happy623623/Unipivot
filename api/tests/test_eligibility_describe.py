"""판정 문구 테스트: 판정표의 조건·내 값, 공고 상세 API 행."""

from datetime import date
from decimal import Decimal

import pytest

from app.eligibility import (
    Department,
    Profile,
    Requirement,
    check_eligibility,
    clause_rows,
    condition_rows,
    condition_text,
)

DEPARTMENTS = [Department("인공지능학과", "소프트웨어융합대학", "공학계열")]


def req(field, operator, value, *, basis=None, rid="r1", clause_no=1, evidence=None):
    return Requirement(
        id=rid,
        clause_no=clause_no,
        field=field,
        operator=operator,
        value=value,
        basis=basis,
        evidence_text=evidence,
    )


@pytest.mark.parametrize(
    ("requirement", "text"),
    [
        (req("credits_last_semester", "gte", 12), "12학점 이상"),
        (req("grade", "neq", 4), "4학년 제외"),
        (req("grade", "in", [1, 2]), "1학년·2학년"),
        (req("grade", "between", {"min": 2, "max": 4}), "2학년–4학년"),
        (req("gpa_total", "gte", 3), "3.0 이상"),
        (req("gpa_total", "gte", {"value": 80, "scale": 100}), "80 이상 (100점 만점)"),
        (
            req("age", "between", {"min": 19, "max": 34, "military_extension": True}),
            "만 19–34세 (병역 기간만큼 상한 연장)",
        ),
        (
            req("age", "between", {"min": 19, "max": 34, "military_extension": {"max_months": 36}}),
            "만 19–34세 (병역 기간만큼 상한 연장, 최대 36개월)",
        ),
        (
            req("region", "in", ["경기도 안산시", "경기도 시흥시"], basis="unspecified"),
            "경기도 안산시, 경기도 시흥시",
        ),
        (req("region", "in", ["경기도"], basis="actual_residence"), "경기도 (실거주 기준)"),
        (
            req("enrollment_status", "not_in", ["deferred_graduation", "graduated"]),
            "졸업유예·졸업 제외",
        ),
        (req("welfare_status", "in", ["basic_livelihood", "near_poverty"]), "기초생활수급·차상위"),
        (req("median_income_pct", "lte", 150), "150% 이하"),
        (req("is_international", "eq", False), "유학생 아님"),
        (req("department", "in", ["공학계열"], basis="field_group"), "공학계열"),
        (req("other", "eq", {"text": "면접 통과자"}), "면접 통과자"),
    ],
)
def test_condition_text(requirement, text):
    assert condition_text(requirement) == text


def test_condition_text_falls_back_to_evidence():
    broken = req("grade", "in", "4학년", evidence="4학년 재학생")
    assert condition_text(broken) == "4학년 재학생"


def test_condition_rows_match_api_example():
    """API 명세 v0.4 5장 예시: 12학점 이상(단, 4학년 9학점), 학년 미입력·10학점."""
    evidence = "직전학기 12학점 이상 (단, 4학년은 9학점)"
    requirements = [
        req("grade", "eq", 4, rid="a", clause_no=1, evidence=evidence),
        req("credits_last_semester", "gte", 12, rid="b", clause_no=1, evidence=evidence),
        req("grade", "neq", 4, rid="c", clause_no=2, evidence=evidence),
        req("credits_last_semester", "gte", 9, rid="d", clause_no=2, evidence=evidence),
    ]
    profile = Profile(credits_last_semester=Decimal("10"))
    judgment = check_eligibility(requirements, profile, basis_date=date(2026, 10, 15))
    rows = condition_rows(judgment, requirements, profile)
    assert [
        (r["label"], r["condition_text"], r["user_value_text"], r["outcome"], r["unknown_reason"])
        for r in rows
    ] == [
        ("학년", "4학년", None, "unknown", "missing_profile"),
        ("직전학기 이수학점", "12학점 이상", "10학점", "fail", None),
        ("학년", "4학년 제외", None, "unknown", "missing_profile"),
        ("직전학기 이수학점", "9학점 이상", "10학점", "pass", None),
    ]
    assert clause_rows(judgment) == [
        {"clause_no": 1, "outcome": "unknown", "condition_count": 2},
        {"clause_no": 2, "outcome": "pass", "condition_count": 2},
    ]
    assert (judgment.display_status, judgment.reason_text) == ("missing_info", "학년 입력 필요")


def test_user_value_texts():
    requirements = [
        req("age", "between", {"min": 19, "max": 34, "military_extension": True}, rid="age"),
        req("department", "in", ["소프트웨어융합대학"], basis="college", rid="dept", clause_no=2),
        req("region", "in", ["경기도"], basis="unspecified", rid="region", clause_no=3),
        req("gpa_total", "gte", 3.0, rid="gpa", clause_no=4),
    ]
    profile = Profile(
        birth_date=date(1991, 3, 10),
        military_service_months=21,
        department="인공지능학과",
        region_sido="경기",
        region_sigungu="안산시  단원구",
        gpa_total=Decimal("3.5"),
        gpa_scale=Decimal("4.3"),
    )
    judgment = check_eligibility(
        requirements, profile, basis_date=date(2026, 10, 15), departments=DEPARTMENTS
    )
    shown = {
        r["requirement_id"]: r["user_value_text"]
        for r in condition_rows(judgment, requirements, profile, DEPARTMENTS)
    }
    assert shown == {
        "age": "만 35세 · 병역 21개월",
        "dept": "인공지능학과 (소프트웨어융합대학)",
        "region": "경기도 안산시 단원구",
        "gpa": "3.50 (4.3 만점)",
    }
