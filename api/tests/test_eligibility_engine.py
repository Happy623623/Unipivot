"""판정 엔진 단위 테스트. 사례는 docs/판정엔진_규칙.md 9장과 같다."""

import itertools
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.eligibility import (
    Department,
    Profile,
    Requirement,
    age_on,
    check_eligibility,
    requirement_problem,
    resolve_basis_date,
)

BASIS = date(2026, 10, 15)
DEPARTMENTS = [
    Department("인공지능학과", "소프트웨어융합대학", "공학계열"),
    Department("경영학부", "경상대학", "사회계열"),
]
_ids = itertools.count(1)


def req(clause_no, field, operator, value, *, basis=None, ambiguous=False):
    return Requirement(
        id=f"r{next(_ids)}",
        clause_no=clause_no,
        field=field,
        operator=operator,
        value=value,
        basis=basis,
        is_ambiguous=ambiguous,
    )


def judge(requirements, basis_date=BASIS, **profile):
    return check_eligibility(
        requirements, Profile(**profile), basis_date=basis_date, departments=DEPARTMENTS
    )


# PRD 5-3 판정 규칙 예시
OR_GPA_INCOME = [req(1, "gpa_last_semester", "gte", 3.0), req(1, "income_bracket", "lte", 8)]
FOURTH_YEAR_EXCEPTION = [  # 직전학기 12학점 이상 (단, 4학년은 9학점)
    req(1, "grade", "eq", 4),
    req(1, "credits_last_semester", "gte", 12),
    req(2, "grade", "neq", 4),
    req(2, "credits_last_semester", "gte", 9),
]
MILITARY = [req(1, "age", "between", {"min": 19, "max": 34, "military_extension": True})]


@pytest.mark.parametrize(
    ("requirements", "profile", "display", "missing"),
    [
        (OR_GPA_INCOME, {"income_bracket": 6}, "eligible", ()),
        (OR_GPA_INCOME, {"gpa_last_semester": Decimal("2.8")}, "missing_info", ("income_bracket",)),
        (
            OR_GPA_INCOME,
            {"gpa_last_semester": Decimal("2.8"), "income_bracket": 9},
            "ineligible",
            (),
        ),
        (FOURTH_YEAR_EXCEPTION, {"grade": 4, "credits_last_semester": 10}, "eligible", ()),
        (FOURTH_YEAR_EXCEPTION, {"grade": 3, "credits_last_semester": 10}, "ineligible", ()),
        (FOURTH_YEAR_EXCEPTION, {"credits_last_semester": 13}, "eligible", ()),
        (FOURTH_YEAR_EXCEPTION, {"credits_last_semester": 10}, "missing_info", ("grade",)),
    ],
    ids=[
        "or-pass",
        "or-missing",
        "or-fail",
        "exc-4th",
        "exc-3rd",
        "exc-no-grade-13",
        "exc-no-grade-10",
    ],
)
def test_prd_examples(requirements, profile, display, missing):
    judgment = judge(requirements, **profile)
    assert (judgment.display_status, judgment.missing_fields) == (display, missing)


def test_clause_results_and_storage_row():
    judgment = judge(FOURTH_YEAR_EXCEPTION, credits_last_semester=Decimal("10.0"))
    assert [(c.clause_no, c.outcome, c.condition_count) for c in judgment.clauses] == [
        (1, "unknown", 2),
        (2, "pass", 2),
    ]
    row = judgment.storage_row()
    json.dumps(row)  # Decimal·date가 남아 있으면 실패
    assert row["status"] == "undetermined"
    assert row["missing_fields"] == ["grade"]
    assert row["condition_results"][1]["user_value"] == 10


def test_no_requirements_is_eligible():
    assert judge([]).status == "eligible"


def test_ambiguous_condition_can_be_covered_by_or_partner():
    requirements = [
        req(1, "gpa_last_semester", "gte", 3.0, ambiguous=True),
        req(1, "income_bracket", "lte", 8),
    ]
    assert judge(requirements, income_bracket=5).status == "eligible"


def test_ambiguous_alone_needs_review_and_asks_nothing():
    judgment = judge([req(1, "gpa_last_semester", "gte", 3.0, ambiguous=True)])
    assert (judgment.display_status, judgment.missing_fields) == ("needs_review", ())
    assert judgment.conditions[0].unknown_reason == "ambiguous"


def test_certain_failure_wins_over_unknown_clause():
    requirements = [
        req(1, "other", "eq", {"text": "봉사활동 20시간 이상"}),
        req(2, "grade", "lte", 2),
    ]
    judgment = judge(requirements, grade=3)
    assert (judgment.status, judgment.missing_fields) == ("ineligible", ())


def test_other_field_needs_review():
    judgment = judge([req(1, "other", "eq", {"text": "봉사활동 20시간 이상"})])
    assert judgment.display_status == "needs_review"
    assert judgment.conditions[0].unknown_reason == "unsupported_field"
    assert judgment.reason_text == "원문 확인 필요: 봉사활동 20시간 이상"


def test_missing_info_shown_before_review():
    requirements = [req(1, "other", "eq", {"text": "면접"}), req(2, "income_bracket", "lte", 8)]
    judgment = judge(requirements)
    assert (judgment.display_status, judgment.missing_fields) == (
        "missing_info",
        ("income_bracket",),
    )


@pytest.mark.parametrize(("gpa", "outcome"), [(Decimal("3.00"), "pass"), (Decimal("2.99"), "fail")])
def test_gpa_boundary_is_inclusive(gpa, outcome):
    judgment = judge([req(1, "gpa_last_semester", "gte", 3.0)], gpa_last_semester=gpa)
    assert judgment.conditions[0].outcome == outcome


def test_gpa_other_scale_is_not_converted_and_not_asked():
    hundred = [req(1, "gpa_last_semester", "gte", {"value": 80, "scale": 100})]
    judgment = judge(hundred, gpa_last_semester=Decimal("4.0"))
    assert (judgment.display_status, judgment.conditions[0].unknown_reason) == (
        "needs_review",
        "basis_mismatch",
    )
    assert judge(hundred).missing_fields == ()  # 입력해도 판정할 수 없으니 묻지 않는다
    profile_scale = judge(
        [req(1, "gpa_total", "gte", 3.0)], gpa_total=Decimal("3.5"), gpa_scale=Decimal("4.3")
    )
    assert profile_scale.conditions[0].unknown_reason == "basis_mismatch"


def test_age_upper_bound_on_basis_date():
    youth = [req(1, "age", "between", {"min": 19, "max": 34})]
    assert judge(youth, birth_date=date(1991, 10, 16)).status == "eligible"  # 만 34세 마지막 날
    assert judge(youth, birth_date=date(1991, 10, 15)).status == "ineligible"  # 35번째 생일


def test_age_lower_bound_and_feb_29():
    adult = [req(1, "age", "gte", 19)]
    birth = date(2004, 2, 29)
    assert judge(adult, date(2023, 2, 28), birth_date=birth).status == "ineligible"
    assert judge(adult, date(2023, 3, 1), birth_date=birth).status == "eligible"
    assert (age_on(birth, date(2023, 2, 28)), age_on(birth, date(2024, 2, 29))) == (18, 20)


def test_military_extension():
    birth = date(1991, 3, 10)  # 기준일에 만 35세
    assert judge(MILITARY, birth_date=birth, military_service_months=21).status == "eligible"
    assert judge(MILITARY, birth_date=birth, military_service_months=0).status == "ineligible"
    no_extension = [req(1, "age", "between", {"min": 19, "max": 34})]
    assert judge(no_extension, birth_date=birth, military_service_months=21).status == "ineligible"


def test_military_months_unknown_asks_only_when_it_matters():
    judgment = judge(MILITARY, birth_date=date(1991, 3, 10))
    assert (judgment.display_status, judgment.missing_fields) == ("missing_info", ("age",))
    assert judgment.reason_text == "병역 복무 개월 입력 필요"
    assert judge(MILITARY, birth_date=date(2000, 1, 1)).status == "eligible"  # 연장이 필요 없음


def test_military_cap():
    capped = [
        req(1, "age", "between", {"min": 19, "max": 34, "military_extension": {"max_months": 36}})
    ]
    assert judge(capped, birth_date=date(1985, 1, 1)).status == "ineligible"  # 3년 늘려도 넘는다
    assert (
        judge(capped, birth_date=date(1990, 1, 1), military_service_months=48).status == "eligible"
    )
    short_cap = [
        req(1, "age", "between", {"min": 19, "max": 34, "military_extension": {"max_months": 12}})
    ]
    assert (
        judge(short_cap, birth_date=date(1990, 1, 1), military_service_months=48).status
        == "ineligible"
    )


def test_age_missing_birth_date():
    judgment = judge([req(1, "age", "gte", 19)])
    assert (judgment.missing_fields, judgment.reason_text) == (("age",), "생년월일 입력 필요")


@pytest.mark.parametrize(
    ("value", "basis", "sido", "sigungu", "outcome", "reason"),
    [
        (["경기도 안산시"], "unspecified", "경기도", "안산시 단원구", "pass", None),
        (["경기 안산시"], "resident_registration", "경기", "안산시", "pass", None),
        (["경기도"], "unspecified", "서울특별시", "강남구", "fail", None),
        (["강원도"], "unspecified", "강원특별자치도", "춘천시", "pass", None),
        (["경기도 안산시 단원구"], "unspecified", "경기도", "안산시", "unknown", "missing_profile"),
        (["경기도 안산시"], "actual_residence", "경기도", "안산시", "unknown", "basis_mismatch"),
        (["경기도 안산시"], "actual_residence", None, None, "unknown", "basis_mismatch"),
        (["안산시"], "unspecified", "경기도", "안산시", "unknown", "ambiguous"),
        (["안산시", "경기도 시흥시"], "unspecified", "경기도", "시흥시", "pass", None),
        (["경기도 안산시"], "unspecified", None, None, "unknown", "missing_profile"),
        (["경기도 안산"], "unspecified", "경기도", "안산시 단원구", "pass", None),
        (["경기도 안산시 상록구"], "unspecified", "경기도", "안산시 단원구", "fail", None),
        (["경기도 안산시"], "unspecified", "경기도", "안성시", "fail", None),
    ],
    ids=[
        "sigungu-prefix",
        "alias",
        "other-sido",
        "old-name",
        "req-more-specific",
        "actual-residence",
        "basis-before-missing",
        "no-sido",
        "one-good-entry",
        "profile-missing",
        "no-suffix",
        "other-gu",
        "similar-name",
    ],
)
def test_region(value, basis, sido, sigungu, outcome, reason):
    judgment = judge(
        [req(1, "region", "in", value, basis=basis)], region_sido=sido, region_sigungu=sigungu
    )
    condition = judgment.conditions[0]
    assert (condition.outcome, condition.unknown_reason) == (outcome, reason)


def test_region_not_in():
    excluded = [req(1, "region", "not_in", ["서울특별시"], basis="unspecified")]
    assert judge(excluded, region_sido="경기도", region_sigungu="안산시").status == "eligible"
    assert judge(excluded, region_sido="서울", region_sigungu="강남구").status == "ineligible"


@pytest.mark.parametrize(
    ("operator", "value", "basis", "outcome", "reason"),
    [
        ("in", ["소프트웨어융합대학"], "college", "pass", None),
        ("in", ["공학계열"], "field_group", "pass", None),
        ("in", ["사회계열"], "field_group", "fail", None),
        ("in", ["공과대학"], "college", "unknown", "ambiguous"),
        ("not_in", ["인공지능학과"], "department", "fail", None),
        ("eq", "경영학부", "department", "fail", None),
    ],
)
def test_department(operator, value, basis, outcome, reason):
    judgment = judge(
        [req(1, "department", operator, value, basis=basis)], department="인공지능학과"
    )
    condition = judgment.conditions[0]
    assert (condition.outcome, condition.unknown_reason) == (outcome, reason)


def test_department_missing_or_not_in_list():
    requirements = [req(1, "department", "in", ["공학계열"], basis="field_group")]
    assert judge(requirements).missing_fields == ("department",)
    assert judge(requirements, department="폐지된학과").missing_fields == ("department",)


@pytest.mark.parametrize(
    ("requirement", "profile", "outcome"),
    [
        (
            req(1, "enrollment_status", "in", ["enrolled", "on_leave"]),
            {"enrollment_status": "on_leave"},
            "pass",
        ),
        (
            req(1, "enrollment_status", "neq", "graduated"),
            {"enrollment_status": "graduated"},
            "fail",
        ),
        (
            req(1, "welfare_status", "in", ["basic_livelihood", "near_poverty"]),
            {"welfare_status": "none"},
            "fail",
        ),
        (req(1, "is_international", "eq", True), {"is_international": False}, "fail"),
        (req(1, "income_bracket", "lte", 8), {"income_bracket": 8}, "pass"),
        (req(1, "median_income_pct", "lte", 150), {"median_income_pct": 151}, "fail"),
        (req(1, "semesters_completed", "lte", 7), {"semesters_completed": 7}, "pass"),
        (req(1, "grade", "between", {"min": 2, "max": 4}), {"grade": 1}, "fail"),
        (req(1, "credits_total", "gte", 60), {"credits_total": Decimal("59.5")}, "fail"),
    ],
)
def test_field_comparisons(requirement, profile, outcome):
    assert judge([requirement], **profile).conditions[0].outcome == outcome


def test_income_bases_are_not_converted():
    either = [req(1, "income_bracket", "lte", 8), req(1, "median_income_pct", "lte", 150)]
    assert judge(either, median_income_pct=120).status == "eligible"  # OR이면 하나만 맞아도 충족
    only_bracket = [req(1, "income_bracket", "lte", 8)]
    assert judge(only_bracket, median_income_pct=120).missing_fields == ("income_bracket",)


@pytest.mark.parametrize(
    "requirement",
    [
        req(1, "gpa_last_semester", "gte", "three"),
        req(1, "age", "in", [19, 20]),
        req(1, "enrollment_status", "eq", "재학생"),
        req(1, "grade", "between", {"min": 4, "max": 2}),
        req(1, "region", "in", "경기도"),
        req(1, "is_international", "eq", "yes"),
        req(1, "age", "between", {"min": 19, "military_extension": True}),
        req(1, "grade", "eq", 3, basis="college"),
    ],
    ids=[
        "not-number",
        "op-not-allowed",
        "bad-enum",
        "min-gt-max",
        "not-list",
        "not-bool",
        "extension-no-max",
        "basis-on-grade",
    ],
)
def test_malformed_requirement_is_ambiguous_never_fail(requirement):
    judgment = judge(
        [requirement],
        grade=3,
        gpa_last_semester=Decimal("3.5"),
        birth_date=date(2000, 1, 1),
        enrollment_status="enrolled",
        region_sido="경기도",
        is_international=False,
    )
    assert (judgment.status, judgment.conditions[0].unknown_reason) == ("undetermined", "ambiguous")
    assert requirement_problem(requirement) is not None


def test_requirement_problem():
    valid = [
        *OR_GPA_INCOME,
        *FOURTH_YEAR_EXCEPTION,
        *MILITARY,
        req(1, "region", "in", ["경기도 안산시"], basis="unspecified"),
        req(1, "other", "eq", {"text": "면접 통과자"}),
    ]
    assert [requirement_problem(r) for r in valid] == [None] * len(valid)
    assert "시도" in requirement_problem(req(1, "region", "in", ["안산시"], basis="unspecified"))
    assert "basis" in requirement_problem(req(1, "region", "in", ["경기도"]))
    assert "clause_no" in requirement_problem(req(0, "grade", "eq", 3))


def test_resolve_basis_date():
    today = date(2026, 10, 7)
    deadline = datetime(2026, 10, 15, 14, 59, tzinfo=UTC)  # 23:59 KST
    assert resolve_basis_date(date(2026, 9, 1), deadline, today) == date(2026, 9, 1)
    assert resolve_basis_date(None, deadline, today) == date(2026, 10, 15)
    next_day = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)  # 10/16 00:00 KST
    assert resolve_basis_date(None, next_day, today) == date(2026, 10, 16)
    assert resolve_basis_date(None, None, today) == today
    with pytest.raises(ValueError):
        resolve_basis_date(None, datetime(2026, 10, 15), today)  # 시간대 없는 시각


def test_reason_texts():
    assert judge(OR_GPA_INCOME, income_bracket=6).reason_text == "모든 조건 충족"
    single = judge([req(1, "gpa_last_semester", "gte", 3.0)], gpa_last_semester=Decimal("2.8"))
    assert single.reason_text == "직전학기 평점: 3.0 이상 (현재 2.80)"
    either = judge(OR_GPA_INCOME, gpa_last_semester=Decimal("2.8"), income_bracket=9)
    assert either.reason_text == "다음 중 하나: 직전학기 평점 3.0 이상, 학자금 지원구간 8구간 이하"
    two = judge(
        [req(1, "grade", "lte", 2), req(2, "income_bracket", "lte", 8)], grade=3, income_bracket=9
    )
    assert two.reason_text == "학년: 2학년 이하 (현재 3학년) 외 1개"
    assert (
        judge(OR_GPA_INCOME, gpa_last_semester=Decimal("2.8")).reason_text
        == "학자금 지원구간 입력 필요"
    )
    region = judge(
        [req(1, "region", "in", ["경기도 안산시"], basis="actual_residence")], region_sido="경기도"
    )
    assert region.reason_text == "원문 확인 필요: 거주지역 경기도 안산시 (실거주 기준)"


def test_from_db_rows_to_storage():
    """psycopg dict_row 모양(uuid, Decimal, jsonb, 다른 칸 포함)에서 저장 값까지."""
    requirement_rows = [
        {
            "id": uuid.uuid4(),
            "opportunity_id": uuid.uuid4(),
            "clause_no": 1,
            "field": "gpa_last_semester",
            "operator": "gte",
            "value": 3.0,
            "basis": None,
            "evidence_text": "직전학기 평점 3.0 이상",
            "is_ambiguous": None,
            "created_at": datetime(2026, 10, 7, tzinfo=UTC),
        },
        {
            "id": uuid.uuid4(),
            "opportunity_id": uuid.uuid4(),
            "clause_no": 2,
            "field": "department",
            "operator": "in",
            "value": ["공학계열"],
            "basis": "field_group",
            "evidence_text": "공학계열 재학생",
            "is_ambiguous": False,
            "created_at": datetime(2026, 10, 7, tzinfo=UTC),
        },
    ]
    profile_row = {
        "id": uuid.uuid4(),
        "display_name": "테스트",
        "department": "인공지능학과",
        "gpa_last_semester": Decimal("3.75"),
        "gpa_scale": Decimal("4.5"),
        "terms_agreed_at": None,
    }
    department_rows = [
        {
            "name": "인공지능학과",
            "college": "소프트웨어융합대학",
            "field_group": "공학계열",
            "is_active": True,
            "sort_order": 1,
        }
    ]
    judgment = check_eligibility(
        [Requirement.from_row(row) for row in requirement_rows],
        Profile.from_row(profile_row),
        basis_date=BASIS,
        departments=[Department.from_row(row) for row in department_rows],
    )
    row = judgment.storage_row()
    assert json.loads(json.dumps(row))["status"] == "eligible"
    assert row["condition_results"][0]["requirement_id"] == str(requirement_rows[0]["id"])
    assert row["condition_results"][0]["user_value"] == 3.75
