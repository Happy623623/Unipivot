"""온통청년 정책 → 공고 값과 요건(판정엔진_규칙.md 11장). 가져오는 범위, 칸별 요건, 판정 결과를 본다."""

from dataclasses import replace
from datetime import date, datetime
from typing import Any

import pytest

from app.eligibility import (
    KST,
    Department,
    Profile,
    Requirement,
    check_eligibility,
    requirement_problem,
)
from app.youth.convert import DETAIL_URL, PolicyRecord, Skip, convert
from app.youth.regions import region_table
from tests.youth_samples import BASE, INCHEON_BEFORE_JULY, policy

TODAY = date(2026, 10, 13)
TABLE = region_table()
DEPARTMENTS = [
    Department("컴퓨터학부", "소프트웨어융합대학", "공학계열"),
    Department("경영학부", "경상대학", "사회계열"),
]
STUDENT = Profile(  # 안산에 사는 22세 컴퓨터학부 3학년(학부 재학)
    department="컴퓨터학부",
    degree_program="bachelor",
    grade=3,
    enrollment_status="enrolled",
    birth_date=date(2004, 5, 1),
    region_sido="경기도",
    region_sigungu="안산시 상록구",
)


def record(**values: Any) -> PolicyRecord:
    result = convert(policy(**values), TODAY, TABLE)
    assert isinstance(result, PolicyRecord), result
    return result


def conditions(**values: Any) -> list[tuple[int, str, str, Any]]:
    return [(d.clause_no, d.field, d.operator, d.value) for d in record(**values).requirements]


def judge(result: PolicyRecord, profile: Profile = STUDENT) -> str:
    requirements = [
        Requirement(
            id=str(index),
            clause_no=draft.clause_no,
            field=draft.field,
            operator=draft.operator,
            value=draft.value,
            basis=draft.basis,
            is_ambiguous=draft.is_ambiguous,
        )
        for index, draft in enumerate(result.requirements)
    ]
    # 청년정책은 마감일이 아니라 판정하는 날이 기준일이다(판정엔진_규칙.md 8장)
    return check_eligibility(
        requirements, profile, basis_date=TODAY, departments=DEPARTMENTS
    ).display_status


@pytest.mark.parametrize(
    ("values", "reason", "expired"),
    [
        ({"plcyAprvSttsCd": "0044001"}, "승인 안 됨", False),
        ({"aplyPrdSeCd": "0057003"}, "마감", True),
        ({"aplyPrdSeCd": "0057001", "aplyYmd": "20260901 ~ 20261012"}, "마감", True),
        ({"bizPrdSeCd": "0056001", "bizPrdEndYmd": "20261012"}, "사업 종료", True),
        ({"zipCd": "26110,26140"}, "수도권 밖", False),
    ],
)
def test_out_of_scope(values: dict[str, Any], reason: str, expired: bool) -> None:
    assert convert(policy(**values), TODAY, TABLE) == Skip(reason, expired)


def test_listing_values() -> None:
    always = record()
    assert always.external_id == BASE["plcyNo"] and always.title == BASE["plcyNm"]
    assert always.organizer == "조달청"
    assert record(rgtrInstCdNm="등록 기관").organizer == "조달청"  # 주관 기관이 먼저
    assert record(sprvsnInstCdNm=" ", rgtrInstCdNm="등록 기관").organizer == "등록 기관"
    assert always.original_url == DETAIL_URL.format(BASE["plcyNo"])
    assert always.easy_summary == BASE["plcyExplnCn"]
    assert (always.apply_start_at, always.deadline_at, always.requirements) == (None, None, ())
    assert always.raw_text.splitlines()[0].startswith("정책 설명: 청년을 대상으로")
    assert "참고 사이트: https://www.jobkorea.co.kr" in always.raw_text
    assert "추가 자격" not in always.raw_text  # 빈 칸은 넣지 않는다
    period = record(aplyPrdSeCd="0057001", aplyYmd="20261001 ~ 20261013")  # 마감 당일
    assert period.apply_start_at == datetime(2026, 10, 1, 0, 0, tzinfo=KST)
    assert period.deadline_at == datetime(2026, 10, 13, 23, 59, tzinfo=KST)
    # 기간이 여럿이면 끝나지 않은 첫 기간
    two = record(aplyPrdSeCd="0057001", aplyYmd="20261001 ~ 20261012\\N20261201 ~ 20261231")
    assert two.deadline_at == datetime(2026, 12, 31, 23, 59, tzinfo=KST)
    unread = record(aplyPrdSeCd="0057001", aplyYmd="추후 공지")
    assert unread.deadline_at is None and unread.review_reasons == ("신청 기간을 읽지 못함",)


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        ("0", "0", []),
        ("1", "99", []),  # 사실상 제한 없음
        ("19", "34", [(1, "age", "between", {"min": 19, "max": 34})]),
        ("0", "39", [(1, "age", "between", {"max": 39})]),
        ("19", "99", [(1, "age", "gte", 19)]),
        ("35", "39", [(1, "age", "between", {"min": 35, "max": 39})]),  # 인천 청년월세 35~39세
    ],
)
def test_age(low: str, high: str, expected: list[Any]) -> None:
    found = record(sprtTrgtMinAge=low, sprtTrgtMaxAge=high)
    assert [(d.clause_no, d.field, d.operator, d.value) for d in found.requirements] == expected
    assert not any(d.is_ambiguous for d in found.requirements) and found.review_reasons == ()


def test_age_that_cannot_be_trusted() -> None:
    """숫자를 그대로 믿으면 지원할 수 있는 학생이 지원 어려움이 되는 두 모양(10/13 실제 자료)."""
    # 인천 정책 16건의 34~99세: 나이 조건은 남기되 모호한 조건(원문 확인)
    (open_ended,) = record(sprtTrgtMinAge="34", sprtTrgtMaxAge="99").requirements
    assert (open_ended.field, open_ended.operator, open_ended.value) == ("age", "gte", 34)
    assert open_ended.is_ambiguous
    reasons = record(sprtTrgtMinAge="34", sprtTrgtMaxAge="99").review_reasons
    assert reasons == (
        "지원 연령이 상한 없이 높은 나이만 적혀 있어 정책 대상과 맞는지 확인이 필요함",
    )
    assert not record(sprtTrgtMinAge="24", sprtTrgtMaxAge="0").requirements[0].is_ambiguous
    # 부모급여 0~1세·아이돌봄 0~12세: 자녀 나이라 기타 조건
    assert conditions(sprtTrgtMinAge="0", sprtTrgtMaxAge="1") == [
        (1, "other", "eq", {"text": "지원 대상 나이: 만 0~1세(자녀 나이일 수 있음)"})
    ]
    assert conditions(sprtTrgtMinAge="2", sprtTrgtMaxAge="14")[0][1] == "other"
    assert conditions(sprtTrgtMinAge="2", sprtTrgtMaxAge="15")[0][1] == "age"


def test_military_extension() -> None:
    text = "제대군인 지원법에 따라 군 복무자는 신청가능 연령 연장"
    found = conditions(sprtTrgtMinAge="19", sprtTrgtMaxAge="34", addAplyQlfcCndCn=text)
    assert found[0][3] == {"min": 19, "max": 34, "military_extension": {"max_months": 36}}
    assert found[1] == (2, "other", "eq", {"text": f"추가 자격: {text}"})
    # 병역 이야기만 있고 연령 연장이 아니면 늘리지 않는다
    other = conditions(
        sprtTrgtMinAge="19", sprtTrgtMaxAge="34", ptcpPrpTrgtCn="군 복무 중인 자 제외"
    )
    assert other[0][3] == {"min": 19, "max": 34}


def test_region() -> None:
    assert conditions(zipCd="41271,41273") == [(1, "region", "in", ["경기도 안산시"])]
    assert record(zipCd="41271").requirements[0].basis == "unspecified"  # 주민등록 주소로 비교
    incheon = conditions(zipCd=INCHEON_BEFORE_JULY, frstRegDt="2026-05-04 10:00:00")
    assert incheon == [(1, "region", "in", ["인천광역시"])]
    mixed = conditions(zipCd="11110,12110")
    assert mixed == [
        (1, "region", "in", ["서울특별시 종로구"]),
        (1, "other", "eq", {"text": "거주지역 원문 확인: 전남광주통합특별시 목포시"}),
    ]
    # 원문 확인할 곳이 많으면 판정표에는 앞부분만, 근거(공고 원문)에는 전체 목록
    unknown = ",".join(["11110"] + [f"999{n:02d}" for n in range(20)])
    (_, many) = record(zipCd=unknown).requirements
    assert len(many.value["text"]) == 150 and many.value["text"].endswith("…")
    assert many.evidence_text is not None
    assert many.evidence_text.startswith("온통청년 거주지역 원문 확인: 지역 코드 99900")
    assert many.evidence_text.endswith("지역 코드 99919")


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        ("0049010", []),
        (
            "0049005",
            [(1, "enrollment_status", "in", ["enrolled", "on_leave", "deferred_graduation"])],
        ),
        (
            "0049005,0049006",
            [
                (1, "enrollment_status", "in", ["enrolled", "on_leave", "deferred_graduation"]),
                (1, "other", "eq", {"text": "학력: 대졸 예정"}),
            ],
        ),
        (
            "0049007,0049008",
            [
                (1, "enrollment_status", "in", ["graduated"]),
                (1, "degree_program", "in", ["master", "doctoral", "integrated"]),
            ],
        ),
        # 대학 졸업(최종 학력): 대학원생도 대학을 마쳤다
        (
            "0049007",
            [
                (1, "enrollment_status", "in", ["graduated"]),
                (1, "degree_program", "in", ["master", "doctoral", "integrated"]),
            ],
        ),
        # 고교 학력은 대학 학력과 함께면 대학생 판정에 쓰지 않는다
        (
            "0049004,0049005",
            [(1, "enrollment_status", "in", ["enrolled", "on_leave", "deferred_graduation"])],
        ),
        ("0049002,0049003", [(1, "other", "eq", {"text": "학력: 고교 재학·고졸 예정"})]),
        (",".join(f"00490{n:02d}" for n in range(1, 10)), []),  # 모든 학력을 고름 = 제한 없음
    ],
)
def test_school(codes: str, expected: list[Any]) -> None:
    assert conditions(schoolCd=codes) == expected


def test_graduating_students_in_text() -> None:
    """대학 학력을 골랐는데 대졸 예정은 안 골랐고 글에 졸업예정자가 있으면 대졸 예정도 받는다(원문 확인)."""
    text = "학사 학위 소지자 또는 '27.2월 졸업예정자"
    found = record(schoolCd="0049007,0049008", addAplyQlfcCndCn=text).requirements
    assert [(d.clause_no, d.field, d.value) for d in found[:3]] == [
        (1, "enrollment_status", ["graduated"]),
        (1, "degree_program", ["master", "doctoral", "integrated"]),
        (1, "other", {"text": "학력: 대졸 예정"}),
    ]
    assert found[0].evidence_text == "온통청년 학력 요건: 대학 졸업·석·박사(글에 졸업예정자가 있음)"
    # 이미 대졸 예정을 골랐거나 대학 학력이 아니면 그대로다
    already = conditions(schoolCd="0049005,0049006", ptcpPrpTrgtCn="졸업 예정자 제외")
    assert [row for row in already if row[:2] == (1, "other")] == [
        (1, "other", "eq", {"text": "학력: 대졸 예정"})
    ]
    assert conditions(schoolCd="0049003", addAplyQlfcCndCn="고교 졸업예정자") == [
        (1, "other", "eq", {"text": "학력: 고졸 예정"}),
        (2, "other", "eq", {"text": "추가 자격: 고교 졸업예정자"}),
    ]


def test_major_special_job_marriage_income() -> None:
    assert conditions(plcyMajorCd="0011005") == [(1, "department", "in", ["공학계열"])]
    major = record(plcyMajorCd="0011003,0011004,0011008").requirements
    assert [(d.field, d.value, d.basis) for d in major] == [
        ("department", ["자연계열"], "field_group"),
        ("department", ["경상대학"], "college"),
        ("other", {"text": "전공: 기타"}, None),
    ]
    assert conditions(sbizCd="0014003,0014002") == [
        (1, "welfare_status", "eq", "basic_livelihood"),
        (1, "other", "eq", {"text": "특화 대상: 여성"}),
    ]
    assert conditions(jobCd="0013003,0013006") == [
        (1, "other", "eq", {"text": "취업 상태: 미취업자·(예비)창업자"})
    ]
    assert conditions(mrgSttsCd="0055002") == [(1, "other", "eq", {"text": "결혼: 미혼"})]
    assert conditions(earnCndSeCd="0043002", earnMinAmt="0", earnMaxAmt="5000") == [
        (1, "other", "eq", {"text": "연소득 5,000만 원 이하"})
    ]
    text = "(청년독립가구) 기준 중위소득 60%이하 (원가구) 기준 중위소득 100% 이하"
    assert conditions(earnCndSeCd="0043003", earnEtcCn=text) == [
        (1, "other", "eq", {"text": f"소득: {text}"})
    ]
    # 칸 이름을 앞에 쓴 글은 "소득: 소득 : …"이 되지 않게 뗀다
    income = record(earnCndSeCd="0043003", earnEtcCn=f"소득 : {text}").requirements
    assert [(d.value, d.evidence_text) for d in income] == [
        ({"text": f"소득: {text}"}, f"온통청년 소득: {text}")
    ]
    assert conditions(earnCndSeCd="0043003", earnEtcCn="-") == [
        (1, "other", "eq", {"text": "소득 조건이 있음"})
    ]


def test_free_text() -> None:
    for trivial in ("-", "--", "해당없음", "해당 없음", "제한 없음", "X", " ", "○"):
        assert conditions(addAplyQlfcCndCn=trivial, ptcpPrpTrgtCn=trivial) == []
    found = record(addAplyQlfcCndCn="공고문 참조", ptcpPrpTrgtCn="건강보험 직장가입자는\n제외")
    assert [(d.clause_no, d.value, d.evidence_text) for d in found.requirements] == [
        (1, {"text": "추가 자격: 공고문 참조"}, "온통청년 추가 자격: 공고문 참조"),
        (
            2,
            {"text": "참여 제한: 건강보험 직장가입자는 제외"},
            "온통청년 참여 제한: 건강보험 직장가입자는 제외",
        ),
    ]
    # 긴 글: 판정표·카드에는 150자까지, 판정표 행을 펼치면 보이는 근거(공고 원문)에는 1,000자까지
    (long,) = record(addAplyQlfcCndCn="가" * 1200).requirements
    assert len(long.value["text"]) == 150 and long.value["text"].endswith("…")
    assert long.evidence_text is not None and len(long.evidence_text) == 1000
    assert long.evidence_text.startswith("온통청년 추가 자격: 가가")


def test_raw_text_keeps_lines() -> None:
    raw = record(plcySprtCn="1. 이론 강의\n\n2.  기업   견학").raw_text
    assert "지원 내용: 1. 이론 강의\n2. 기업 견학" in raw


def test_every_condition_is_judgeable() -> None:
    """모든 칸을 채운 정책도 판정 엔진이 받는 모양이다. 칸마다 묶음 하나다."""
    full = record(
        sprtTrgtMinAge="19",
        sprtTrgtMaxAge="34",
        zipCd="41271,41273,12110",
        schoolCd="0049005,0049006",
        plcyMajorCd="0011005,0011008",
        sbizCd="0014003",
        jobCd="0013003",
        mrgSttsCd="0055002",
        earnCndSeCd="0043002",
        earnMaxAmt="5000",
        addAplyQlfcCndCn="공고문 참조",
        ptcpPrpTrgtCn="재학생 제외",
    )
    assert max(d.clause_no for d in full.requirements) == 10
    for draft in full.requirements:
        requirement = Requirement(
            id="x",
            clause_no=draft.clause_no,
            field=draft.field,
            operator=draft.operator,
            value=draft.value,
            basis=draft.basis,
        )
        assert requirement_problem(requirement) is None, draft


def test_broken_policy_values_become_ambiguous() -> None:
    """정책 자료가 틀려 판정할 수 없는 조건(최소 나이 > 최대 나이)은 모호한 기타 조건이다."""
    broken = record(sprtTrgtMinAge="40", sprtTrgtMaxAge="30")
    (draft,) = broken.requirements
    assert (draft.field, draft.is_ambiguous) == ("other", True)
    assert draft.value == {"text": "온통청년 지원 연령 40~30세"}
    assert broken.review_reasons == ("온통청년 조건 일부를 판정할 수 있는 모양으로 바꾸지 못함",)


@pytest.mark.parametrize(
    ("values", "status"),
    [
        ({}, "eligible"),  # 전국·조건 없음
        ({"zipCd": "41271,41273", "sprtTrgtMinAge": "19", "sprtTrgtMaxAge": "34"}, "eligible"),
        ({"zipCd": "41220"}, "ineligible"),  # 평택시
        ({"sprtTrgtMinAge": "35", "sprtTrgtMaxAge": "39"}, "ineligible"),
        ({"sprtTrgtMinAge": "34", "sprtTrgtMaxAge": "99"}, "needs_review"),  # 믿기 어려운 나이
        ({"sprtTrgtMinAge": "0", "sprtTrgtMaxAge": "1"}, "needs_review"),  # 자녀 나이
        ({"schoolCd": "0049008"}, "ineligible"),  # 석·박사만
        ({"schoolCd": "0049007"}, "ineligible"),  # 대학 졸업만: 학부 재학생은 아니다
        ({"plcyMajorCd": "0011003"}, "ineligible"),  # 상경계열(경상대학)
        ({"jobCd": "0013003"}, "needs_review"),  # 취업 상태는 프로필에 없다
        ({"zipCd": "41271,12110"}, "eligible"),  # 내 지역이 판정할 수 있는 쪽에 있다
        ({"sbizCd": "0014003"}, "missing_info"),  # 수급 여부를 입력하지 않음
    ],
)
def test_judgment_for_a_student(values: dict[str, Any], status: str) -> None:
    assert judge(record(**values)) == status


def test_graduate_students_have_finished_university() -> None:
    """대학 졸업(최종 학력)만 고른 정책: 대학원생은 맞고, 학위과정을 모르면 물어본다."""
    graduate = replace(STUDENT, degree_program="master", grade=None)
    assert judge(record(schoolCd="0049007"), graduate) == "eligible"
    unknown = replace(STUDENT, degree_program=None)
    assert judge(record(schoolCd="0049007"), unknown) == "missing_info"


def test_content_hash() -> None:
    """변환 결과가 같으면 같다. 조회수(inqCnt)처럼 결과에 안 쓰는 칸은 바뀌어도 같다."""
    first = record()
    assert record(inqCnt="99999").content_hash == first.content_hash
    assert record(plcyNm="새 이름").content_hash != first.content_hash
    assert record(sprtTrgtMaxAge="39").content_hash != first.content_hash
