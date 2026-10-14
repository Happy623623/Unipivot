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
        (["서울특별시 중랑구"], "unspecified", "서울특별시", "서울 중랑구", "pass", None),
        (["서울특별시 중랑구"], "unspecified", "서울", "서울특별시 중랑구", "pass", None),
        (["경기도 안산시"], "unspecified", "경기도", "경기 안산시 단원구", "pass", None),
        (
            ["서울특별시 중랑구"],
            "unspecified",
            "서울특별시",
            "서울특별시",
            "unknown",
            "missing_profile",
        ),
        (["경기도 광주시"], "unspecified", "경기도", "광주", "pass", None),
        (["서울특별시 중랑구"], "unspecified", "서울특별시", "중랑구 서울", "pass", None),
        (["제주특별자치도 제주시"], "unspecified", "제주특별자치도", "제주", "pass", None),
        (["경기도 광주시"], "unspecified", "경기도", "광주 오포읍", "pass", None),
        # 2026-07-01 광주광역시 + 전라남도 → 전남광주통합특별시
        (
            ["전남광주통합특별시 목포시"],
            "unspecified",
            "전남광주통합특별시",
            "목포시",
            "pass",
            None,
        ),
        (["전라남도 목포시"], "unspecified", "전남광주통합특별시", "목포시", "pass", None),
        (["전남광주통합특별시 북구"], "unspecified", "광주광역시", "북구", "pass", None),
        (["전라남도"], "unspecified", "광주광역시", "북구", "pass", None),
        (["전남광주통합특별시"], "unspecified", "경기도", "광주시", "fail", None),
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
        "sido-repeated",
        "full-sido-repeated",
        "alias-repeated",
        "only-sido-in-sigungu",
        "other-sido-name-kept",
        "sido-not-first",
        "lone-alias-kept",
        "other-sido-name-kept-with-more",
        "merged-sido",
        "merged-pre-merge-req",
        "merged-pre-merge-profile",
        "merged-gwangju-matches-jeonnam",
        "merged-not-gyeonggi-gwangju",
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


GRADUATE = ["master", "doctoral", "integrated"]


@pytest.mark.parametrize(
    ("requirement", "degree", "outcome", "reason"),
    [
        (req(1, "degree_program", "in", GRADUATE), "master", "pass", None),
        (req(1, "degree_program", "in", GRADUATE), "bachelor", "fail", None),
        (req(1, "degree_program", "in", GRADUATE), None, "unknown", "missing_profile"),
        (req(1, "degree_program", "eq", "bachelor"), "bachelor", "pass", None),
        (req(1, "degree_program", "neq", "bachelor"), "doctoral", "pass", None),
        (req(1, "degree_program", "not_in", ["master", "doctoral"]), "bachelor", "pass", None),
        (req(1, "degree_program", "in", ["integrated"]), "doctoral", "fail", None),
        # 석박사통합: 석사·박사를 둘 다 받으면 해당하고, 하나만 적었으면 모르고, 학부만이면 아니다
        (req(1, "degree_program", "in", ["integrated"]), "integrated", "pass", None),
        (req(1, "degree_program", "in", ["master", "doctoral"]), "integrated", "pass", None),
        (req(1, "degree_program", "in", ["doctoral"]), "integrated", "unknown", "basis_mismatch"),
        (req(1, "degree_program", "eq", "master"), "integrated", "unknown", "basis_mismatch"),
        (req(1, "degree_program", "eq", "bachelor"), "integrated", "fail", None),
        (req(1, "degree_program", "neq", "bachelor"), "integrated", "pass", None),
        (
            req(1, "degree_program", "not_in", ["master", "doctoral"]),
            "integrated",
            "fail",
            None,
        ),
        (req(1, "degree_program", "not_in", ["master"]), "integrated", "unknown", "basis_mismatch"),
        # 모든 과정을 받는 조건: 입력해도 결과가 같으니 묻지 않는다
        (req(1, "degree_program", "in", ["bachelor", "master", "doctoral"]), None, "pass", None),
        (req(1, "degree_program", "in", ["bachelor", *GRADUATE]), "integrated", "pass", None),
    ],
    ids=[
        "grad-master",
        "grad-bachelor",
        "grad-missing",
        "eq",
        "neq",
        "not-in-grad",
        "integrated-only-doctoral",
        "integrated-listed",
        "integrated-both-stages",
        "integrated-doctoral-only",
        "integrated-master-only",
        "integrated-not-bachelor",
        "integrated-neq-bachelor",
        "integrated-not-in-both",
        "integrated-not-in-one",
        "every-missing",
        "every-integrated",
    ],
)
def test_degree_program(requirement, degree, outcome, reason):
    condition = judge([requirement], degree_program=degree).conditions[0]
    assert (condition.outcome, condition.unknown_reason) == (outcome, reason)
    assert condition.user_value == degree


# 116702 "석사 재학(휴학) 이상": 학위과정과 학적을 다른 묶음(그리고)으로 둔다
GRADUATE_ENROLLED = [
    req(1, "degree_program", "in", GRADUATE),
    req(2, "enrollment_status", "in", ["enrolled", "on_leave"]),
]


def test_graduate_only_notice():
    undergraduate = judge(
        GRADUATE_ENROLLED, degree_program="bachelor", enrollment_status="enrolled"
    )
    assert (undergraduate.display_status, undergraduate.reason_text) == (
        "ineligible",
        "학위과정: 석사·박사·석박사통합 (현재 학부)",
    )
    unknown = judge(GRADUATE_ENROLLED, enrollment_status="enrolled")
    assert (unknown.display_status, unknown.missing_fields, unknown.reason_text) == (
        "missing_info",
        ("degree_program",),
        "학위과정 입력 필요",
    )
    on_leave = judge(GRADUATE_ENROLLED, degree_program="integrated", enrollment_status="on_leave")
    assert on_leave.display_status == "eligible"
    # 박사과정만 적은 공고: 석박사통합 학생은 묻지 않고 원문 확인 필요다(입력해도 판정할 수 없다)
    doctoral = judge([req(1, "degree_program", "in", ["doctoral"])], degree_program="integrated")
    assert (doctoral.display_status, doctoral.missing_fields, doctoral.reason_text) == (
        "needs_review",
        (),
        "원문 확인 필요: 학위과정 박사",
    )


def test_fourth_year_or_graduate_is_one_clause():
    """학부 4학년 또는 대학원생: 묶음 하나(4학년 또는 대학원 과정)로 두면 둘 다 해당한다."""
    either = [req(1, "grade", "eq", 4), req(1, "degree_program", "in", GRADUATE)]
    assert judge(either, degree_program="bachelor", grade=4).display_status == "eligible"
    assert judge(either, degree_program="master").display_status == "eligible"
    assert judge(either, degree_program="bachelor", grade=3).display_status == "ineligible"
    unknown = judge(either, grade=3)
    assert (unknown.display_status, unknown.missing_fields) == ("missing_info", ("degree_program",))


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
        req(1, "degree_program", "gte", "master"),
        req(1, "degree_program", "in", ["graduate"]),
        req(1, "degree_program", "in", []),
        req(1, "degree_program", "eq", ["master"]),
        req(1, "degree_program", "in", "master"),
        req(1, "degree_program", "not_in", ["bachelor", "master", "doctoral"]),
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
        "degree-op",
        "degree-value",
        "degree-empty",
        "degree-eq-list",
        "degree-in-text",
        "degree-not-in-every",
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
        degree_program="master",
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
        *GRADUATE_ENROLLED,
    ]
    assert [requirement_problem(r) for r in valid] == [None] * len(valid)
    assert "basis" in requirement_problem(req(1, "degree_program", "eq", "master", basis="college"))
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


def test_region_merged_sido_from_youth_api():
    """온통청년 수집이 만드는 거주지역 값(전남광주통합특별시 …)을 판정 엔진이 읽는다.

    2026-10-13에 온통청년 수집(app/youth/region_codes.py)이 통합 이름을 쓰기 시작했는데 판정 엔진은
    통합 전 이름만 알아서, 전남·광주 대상 정책이 전부 '원문 확인 필요'로 빠졌다. 그 회귀를 막는다."""
    from app.eligibility.regions import parse_region

    for value in ("전남광주통합특별시", "전남광주통합특별시 목포시", "전남광주통합특별시 광산구"):
        assert parse_region(value) is not None, value

    requirement = [req(1, "region", "in", ["전남광주통합특별시 목포시"], basis="unspecified")]
    judgment = judge(requirement, region_sido="전남광주통합특별시", region_sigungu="목포시")
    assert judgment.status == "eligible"
    assert judgment.conditions[0].unknown_reason is None
