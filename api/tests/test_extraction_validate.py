"""제출 검증: 근거 대조 정규화, 날짜, 서류, 값 모양, 마지막 제출의 고쳐 넣기."""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.eligibility import KST
from app.extraction import AttachmentInput
from app.extraction.validate import Context, Evidence, check_submission


def evidence(*texts: str) -> Evidence:
    corpus = Evidence()
    for text in texts:
        corpus.add(text)
    return corpus


@pytest.mark.parametrize(
    "quote",
    [
        "직전 학기 평점평균 3.0 이상",
        "직전학기평점평균3.0이상",  # 띄어쓰기 차이
        "성적우수 | 평점 3.5 이상",  # 표 구분선
        "“직전 학기” 평점평균",  # 따옴표
        "직전 학기 … 3.0 이상",  # 줄임표로 나눈 조각이 순서대로 있음
        "ＡＢＣ장학",  # 전각 문자(NFKC)
    ],
)
def test_evidence_matches_despite_extraction_noise(quote: str) -> None:
    corpus = evidence("1. 직전 학기\n평점평균 3.0 이상\n성적우수 평점 3.5 이상", "ABC장학 안내")
    assert corpus.contains(quote)


@pytest.mark.parametrize(
    "quote",
    [
        "평점 3.0 이상인 학생",  # 고쳐 쓴 문장
        "3.0 이상 … 직전 학기",  # 조각 순서가 다름
        "직전 학기 … ABC장학",  # 두 자료에 걸침
        "",
        "…",
    ],
)
def test_evidence_rejects_text_not_in_sources(quote: str) -> None:
    corpus = evidence("1. 직전 학기\n평점평균 3.0 이상", "ABC장학 안내")
    assert not corpus.contains(quote)


CONTEXT = Context(
    evidence=evidence("직전 학기 평점평균 3.0 이상", "신청서 양식 첨부"),
    attachments={2: AttachmentInput(2, "신청서.hwp", b"", "https://example.ac.kr/f/2")},
    posted_on=date(2026, 10, 8),
)
GPA = {
    "clause_no": 1,
    "field": "gpa_last_semester",
    "operator": "gte",
    "value_json": "3.0",
    "evidence_text": "직전 학기 평점평균 3.0 이상",
    "is_ambiguous": False,
}


def check(final: bool = False, **args: Any) -> tuple[Any, list[str]]:
    base: dict[str, Any] = {"requirements": [GPA], "confidence": 0.8, "needs_review": False}
    return check_submission({**base, **args}, CONTEXT, final=final)


def test_dates_are_kst_and_date_only_deadline_is_end_of_day() -> None:
    submission, problems = check(
        apply_start="2026-10-13", deadline="2026-10-24T18:00", eligibility_basis_date="2026-10-01"
    )
    assert problems == []
    assert submission.apply_start_at == datetime(2026, 10, 13, 0, 0, tzinfo=KST)
    assert submission.deadline_at == datetime(2026, 10, 24, 18, 0, tzinfo=KST)
    assert submission.eligibility_basis_date == date(2026, 10, 1)
    end_of_day = check(deadline="2026-10-24")[0].deadline_at
    assert (end_of_day.time().isoformat(), end_of_day.utcoffset()) == (
        "23:59:00",
        timedelta(hours=9),
    )
    assert check(deadline="2026-10-24T18:00+09:00") == check(deadline="2026-10-24T18:00")


def test_other_time_zones_are_read_as_kst_wall_time() -> None:
    """모델이 Z를 잘못 붙이면 기준일이 하루 밀린다. 시각만 KST로 읽는다."""
    assert check(deadline="2026-10-24T18:00Z")[0] is None
    submission, problems = check(final=True, deadline="2026-10-24T18:00Z")
    assert "시간대를 붙이지 말고" in problems[0]
    assert submission.deadline_at == datetime(2026, 10, 24, 18, 0, tzinfo=KST)
    assert submission.fixes == ("deadline의 시간대를 떼고 KST로 읽음",)


@pytest.mark.parametrize(
    ("deadline", "fix"),
    [
        ("2026-01-16", "게시일보다 앞선 마감을 버림"),  # 12월 말 공지의 "1. 16."을 올해로 읽음
        ("2027-12-31", "게시일보다 1년 넘게 뒤인 마감을 버림"),
    ],
)
def test_deadline_with_a_wrong_year_is_dropped(deadline: str, fix: str) -> None:
    """마감 날짜는 판정 기준일이 되므로 연도가 틀리면 나이 판정이 바뀐다. 남기지 않는다."""
    assert check(deadline=deadline)[0] is None
    submission, _ = check(final=True, deadline=deadline)
    assert (submission.deadline_at, submission.fixes) == (None, (fix,))


def test_basis_date_far_from_posting_is_dropped() -> None:
    assert check(eligibility_basis_date="2026-01-01")[1] == []  # "1월 1일 기준"은 흔하다
    submission, problems = check(final=True, eligibility_basis_date="2016-01-01")
    assert "너무 멀다" in problems[0] and submission.eligibility_basis_date is None


@pytest.mark.parametrize(
    ("args", "problem"),
    [
        ({"deadline": "10월 24일"}, "deadline는 YYYY-MM-DD"),
        (
            {"apply_start": "2026-10-25", "deadline": "2026-10-24"},
            "apply_start가 deadline보다 늦다",
        ),
        ({"deadline": "2025-10-24"}, "게시일(2026-10-08)보다 앞선다"),
        ({"eligibility_basis_date": "올해 1월 1일"}, "eligibility_basis_date는 YYYY-MM-DD"),
        ({"confidence": 1.5}, "confidence는 0–1"),
        ({"confidence": True}, "confidence는 0–1"),
        ({"requirements": "없음"}, "requirements는 목록"),
        ({"documents": [{"is_required": True}]}, "documents[1]: name"),
        ({"documents": [{"name": "신청서", "form_attachment_no": 7}]}, "첨부 목록에 없다"),
        ({"requirements": [{**GPA, "value_json": "3.0 이상"}]}, "value_json이 JSON 값이 아니다"),
        ({"requirements": [{**GPA, "field": "gpa"}]}, "field는"),
        ({"requirements": [{**GPA, "operator": "in"}]}, "in 연산자를 쓸 수 없다"),
        ({"requirements": [{**GPA, "basis": "college"}]}, "basis를 쓰지 않는다"),
        ({"requirements": [{**GPA, "clause_no": -1}]}, "clause_no는 1–999"),
        ({"requirements": [{**GPA, "clause_no": 40000}]}, "clause_no는 1–999"),
        ({"requirements": [{**GPA, "field": ["gpa_total"]}]}, "field는"),
        ({"requirements": [{**GPA, "value_json": "NaN"}]}, "value_json이 JSON 값이 아니다"),
        (
            {"requirements": [{**GPA, "field": "other", "operator": "eq", "value_json": '"봉사"'}]},
            "other 값은",
        ),
        ({"requirements": [{**GPA, "evidence_text": ""}]}, "evidence_text가 비었다"),
    ],
)
def test_problems_reject_the_first_submission(args: dict[str, Any], problem: str) -> None:
    submission, problems = check(**args)
    assert submission is None
    assert any(problem in item for item in problems), problems


def test_final_submission_is_fixed_instead_of_rejected() -> None:
    submission, problems = check(
        final=True,
        requirements=[{**GPA, "operator": "in"}, {**GPA, "clause_no": 2, "evidence_text": ""}],
        documents=[{"name": "신청서", "form_attachment_no": 7}, {"is_required": False}],
        deadline="10월 24일",
        confidence="높음",
    )
    assert problems  # 문제는 기록으로 남긴다
    shape, empty = submission.requirements
    assert (shape.field, shape.is_ambiguous, shape.value) == (
        "other",
        True,
        {"text": "직전 학기 평점평균 3.0 이상"},
    )
    assert (empty.field, empty.is_ambiguous) == ("gpa_last_semester", True)
    assert [(d.name, d.form_url) for d in submission.documents] == [("신청서", None)]
    assert (submission.deadline_at, submission.confidence) == (None, Decimal("0.50"))
    assert set(submission.fixes) >= {
        "모양이 틀린 직전학기 평점 조건을 기타 조건으로 저장",
        "근거 문장이 없는 조건을 모호한 조건으로 저장",
        "읽을 수 없는 deadline를 버림",
        "이름 없는 서류를 버림",
    }


def test_requirements_that_are_not_a_list_fail_even_at_the_end() -> None:
    """빈 목록으로 저장하면 모든 학생이 지원 가능이 된다. 받지 않고 추출 실패로 둔다."""
    for raw in ("없음", {"clause_no": 1}, None):
        submission, problems = check(final=True, requirements=raw)
        assert submission is None and "requirements는 목록" in problems[0]


def test_zero_based_clause_numbers_keep_their_groups() -> None:
    """재학생(0) 그리고 평점(1): 1씩 올려서 '그리고'를 지킨다. 1로 합치면 '또는'이 된다."""
    enrolled = {
        **GPA,
        "clause_no": 0,
        "field": "enrollment_status",
        "operator": "eq",
        "value_json": '"enrolled"',
    }
    first, problems = check(requirements=[enrolled, {**GPA, "clause_no": 1}])
    assert first is None and problems == ["clause_no는 1부터 쓴다"]
    submission, _ = check(final=True, requirements=[enrolled, {**GPA, "clause_no": 1}])
    assert [(r.clause_no, r.is_ambiguous) for r in submission.requirements] == [
        (1, False),
        (2, False),
    ]
    assert submission.fixes == ("0부터 센 묶음 번호를 1부터로 고침",)


def test_broken_clause_number_joins_clause_one_as_ambiguous() -> None:
    """번호를 모르는 조건은 1번 묶음의 모호 조건이 된다. 모호 조건은 묶음을 불충족으로 만들지 않는다."""
    submission, _ = check(final=True, requirements=[GPA, {**GPA, "clause_no": "둘"}])
    assert [(r.clause_no, r.field, r.is_ambiguous) for r in submission.requirements] == [
        (1, "gpa_last_semester", False),
        (1, "gpa_last_semester", True),
    ]
    assert "묶음 번호가 틀린 조건을 1번 묶음의 모호한 조건으로 저장" in submission.fixes


def test_other_and_unknown_fields_are_coerced_on_the_final_submission() -> None:
    submission, _ = check(
        final=True,
        requirements=[
            {**GPA, "field": ["gpa_total"]},
            {**GPA, "field": "other", "operator": "eq", "value_json": '"봉사 20시간"'},
            {**GPA, "value_json": "Infinity"},
        ],
    )
    assert [(r.field, r.value, r.is_ambiguous) for r in submission.requirements] == [
        ("other", {"text": "직전 학기 평점평균 3.0 이상"}, True),
        ("other", {"text": "직전 학기 평점평균 3.0 이상"}, True),
        ("other", {"text": "직전 학기 평점평균 3.0 이상"}, True),
    ]


def test_links_are_removed_from_the_summary() -> None:
    submission, _ = check(
        easy_summary="신청은 https://evil.example/apply 에서 하세요. www.x.kr 참고"
    )
    assert submission.easy_summary == "신청은 에서 하세요. 참고"


def test_lenient_inputs_from_the_model() -> None:
    submission, problems = check(
        requirements=json.dumps([{**GPA, "clause_no": 2.0, "value_json": 3.0, "basis": ""}]),
        documents=[{"name": "  장학금 신청서 ", "is_required": False, "form_attachment_no": 2.0}],
        easy_summary="  ",
        review_note="",
    )
    assert problems == []
    (requirement,) = submission.requirements
    assert (requirement.clause_no, requirement.value, requirement.basis) == (2, 3.0, None)
    (document,) = submission.documents
    assert (document.name, document.is_required, document.form_url) == (
        "장학금 신청서",
        False,
        "https://example.ac.kr/f/2",
    )
    assert (submission.easy_summary, submission.review_note) == (None, None)
    assert submission.confidence == Decimal("0.80")
