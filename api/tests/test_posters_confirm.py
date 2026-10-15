"""확인 화면에서 고친 값 받기(F-16). 기본 칸은 받고 요건·서류는 지운 것만 반영한다."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.errors import ApiError
from app.posters.confirm import MAX_TITLE, confirm_draft
from app.schemas.posters import PosterDocumentDraft, PosterDraft, PosterRequirementDraft

NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)  # 10/15 12:00 KST
DEADLINE = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)  # 10/20 18:00 KST


def requirement(**over: Any) -> PosterRequirementDraft:
    base: dict[str, Any] = {
        "clause_no": 1,
        "field": "enrollment_status",
        "operator": "in",
        "value": ["enrolled", "on_leave"],
        "condition_text": "재학·휴학",
        "evidence_text": "국내 대학 재학생 및 휴학생",
        "is_ambiguous": False,
    }
    return PosterRequirementDraft(**(base | over))


def draft(**over: Any) -> PosterDraft:
    base: dict[str, Any] = {
        "title": "2026 전국 대학생 SW 창업 아이디어톤",
        "organizer": "과학기술정보통신부",
        "category": "contest",
        "apply_start_at": None,
        "deadline_at": DEADLINE,
        "easy_summary": "창업 아이디어 대회예요.",
        "requirements": [
            requirement(),
            requirement(clause_no=2, field="degree_program", operator="eq", value="bachelor"),
        ],
        "documents": [
            PosterDocumentDraft(name="재학증명서", issuer="한양인 포털", lead_days=0),
            PosterDocumentDraft(name="아이디어 제안서"),
        ],
        "extraction_confidence": 0.82,
        "low_confidence_fields": ["organizer"],
    }
    return PosterDraft(**(base | over))


def test_the_basic_fields_come_from_what_the_student_typed() -> None:
    edited = draft(
        title="  2026  SW 창업 아이디어톤 ",
        organizer="과기정통부",
        category="scholarship",
        easy_summary="고쳐 적은 설명이에요.",
    )
    confirmed = confirm_draft(draft(), edited, now=NOW)
    assert confirmed.title == "2026 SW 창업 아이디어톤"  # 공백은 정리한다
    assert confirmed.organizer == "과기정통부"
    assert confirmed.category == "scholarship"
    assert confirmed.easy_summary == "고쳐 적은 설명이에요."
    assert confirmed.deadline_at == DEADLINE


def test_a_long_title_is_cut() -> None:
    confirmed = confirm_draft(draft(), draft(title="가" * 500), now=NOW)
    assert confirmed.title == "가" * MAX_TITLE


def test_the_confidence_is_the_models_not_the_students() -> None:
    confirmed = confirm_draft(draft(), draft(extraction_confidence=1.0), now=NOW)
    assert confirmed.confidence == Decimal("0.82")


@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"title": "   "}, "title"),
        ({"deadline_at": datetime(2026, 10, 14, 9, 0, tzinfo=UTC)}, "deadline_at"),
        ({"deadline_at": datetime(2026, 10, 15, 2, 0, tzinfo=UTC)}, "deadline_at"),
        (
            {"apply_start_at": datetime(2026, 10, 25, 0, 0, tzinfo=UTC)},
            "apply_start_at",
        ),
    ],
)
def test_bad_input_says_which_box_to_fix(over: dict[str, Any], field: str) -> None:
    with pytest.raises(ApiError) as caught:
        confirm_draft(draft(), draft(**over), now=NOW)
    assert caught.value.status == 422 and caught.value.code == "VALIDATION_FAILED"
    assert field in (caught.value.details or {})["fields"]


def test_a_requirement_the_student_deleted_is_left_out() -> None:
    stored = draft()
    edited = draft(requirements=[stored.requirements[1]])
    confirmed = confirm_draft(stored, edited, now=NOW)
    assert [item.field for item in confirmed.requirements] == ["degree_program"]


def test_a_requirement_the_student_rewrote_is_treated_as_deleted() -> None:
    """항목·연산자·값은 판정에 쓰이는 값이다. 화면에서 지어내 보내면 받지 않는다."""
    stored = draft()
    tampered = requirement(field="gpa_total", operator="gte", value="0")
    confirmed = confirm_draft(stored, draft(requirements=[tampered]), now=NOW)
    assert confirmed.requirements == ()


def test_a_requirement_the_student_added_is_ignored() -> None:
    stored = draft()
    added = requirement(clause_no=9, field="income_bracket", operator="lte", value=8)
    edited = draft(requirements=[*stored.requirements, added])
    confirmed = confirm_draft(stored, edited, now=NOW)
    assert [item.field for item in confirmed.requirements] == [
        "enrollment_status",
        "degree_program",
    ]


def test_the_draft_order_and_clause_numbers_are_kept() -> None:
    stored = draft()
    edited = draft(requirements=list(reversed(stored.requirements)))
    confirmed = confirm_draft(stored, edited, now=NOW)
    assert [(item.clause_no, item.field) for item in confirmed.requirements] == [
        (1, "enrollment_status"),
        (2, "degree_program"),
    ]


def test_two_identical_rows_stay_two_until_one_is_deleted() -> None:
    stored = draft(requirements=[requirement(), requirement()])
    both = confirm_draft(stored, draft(requirements=[requirement(), requirement()]), now=NOW)
    assert len(both.requirements) == 2
    one = confirm_draft(stored, draft(requirements=[requirement()]), now=NOW)
    assert len(one.requirements) == 1


def test_documents_are_matched_by_name() -> None:
    stored = draft()
    edited = draft(
        documents=[
            PosterDocumentDraft(name="재학증명서"),  # 안내 값을 비워 보내도 이름이 같으면 남는다
            PosterDocumentDraft(name="학생이 적어 넣은 서류"),  # 더 넣은 것은 무시한다
        ]
    )
    confirmed = confirm_draft(stored, edited, now=NOW)
    assert [item.name for item in confirmed.documents] == ["재학증명서"]


def test_a_deadline_that_is_cleared_is_allowed() -> None:
    """마감일을 못 읽은 포스터는 학생이 비워 둘 수 있다(상시 공고가 된다)."""
    confirmed = confirm_draft(draft(), draft(deadline_at=None), now=NOW)
    assert confirmed.deadline_at is None


def test_a_deadline_still_ahead_today_is_allowed() -> None:
    """오늘 안이어도 아직 오지 않은 마감은 받는다. 지난 마감은 받지 않는다(판정이 생기지 않는다)."""
    tonight = datetime(2026, 10, 15, 14, 59, tzinfo=UTC)  # 10/15 23:59 KST
    confirmed = confirm_draft(draft(), draft(deadline_at=tonight), now=NOW)
    assert confirmed.deadline_at == tonight


def test_the_comparison_basis_comes_from_the_draft_not_the_student() -> None:
    """지역·학과 조건의 기준은 판정을 바꾼다. 초안 값을 쓰고 학생이 보낸 값은 보지 않는다."""
    region = requirement(
        field="region",
        operator="in",
        value=["서울특별시"],
        basis="high_school",
        condition_text="서울특별시 (출신 고교 소재지 기준)",
        evidence_text="서울 지역 고등학교 졸업자",
    )
    stored = draft(requirements=[region])
    sent = region.model_copy(update={"basis": "resident_registration"})
    confirmed = confirm_draft(stored, draft(requirements=[sent]), now=NOW)
    (saved,) = confirmed.requirements
    assert saved.basis == "high_school"
