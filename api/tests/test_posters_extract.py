"""포스터 한 장 → 공고 초안(F-16). Vision은 가짜 LLM으로 바꿔 끼운다.

검증은 공지 추출과 같은 코드를 쓰므로(app/extraction/validate) 여기서는 포스터에만 있는 것을 본다:
한 번만 묻는지, 옮겨 적은 글자를 근거 대조에 쓰는지, 확인 화면에서 강조할 항목을 어떻게 고르는지.
"""

from datetime import date
from typing import Any

import pytest

from app.eligibility import Department
from app.llm import Blob
from app.posters.extract import LOW_CONFIDENCE, PosterError, extract
from app.posters.prompt import NO_TEXT, SUBMIT
from tests.llm_fakes import Request, ScriptedLlm, call

pytestmark = pytest.mark.anyio

TODAY = date(2026, 10, 15)
DEPARTMENTS = [Department("컴퓨터학부", "공과대학", "공학")]
POSTER = Blob(b"\xff\xd8\xff poster bytes", "image/jpeg")
TEXT = """2026 전국 대학생 SW 창업 아이디어톤
주최: 과학기술정보통신부
국내 대학 재학생 및 휴학생
접수 기간: 10. 1. ~ 10. 20. 18:00
제출 서류: 아이디어 제안서, 재학증명서"""


def args(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "poster_text": TEXT,
        "title": "2026 전국 대학생 SW 창업 아이디어톤",
        "organizer": "과학기술정보통신부",
        "category": "contest",
        "requirements": [
            {
                "clause_no": 1,
                "field": "enrollment_status",
                "operator": "in",
                "value_json": '["enrolled", "on_leave"]',
                "evidence_text": "국내 대학 재학생 및 휴학생",
                "is_ambiguous": False,
            }
        ],
        "documents": [
            {"name": "아이디어 제안서", "is_required": True},
            {"name": "재학증명서", "is_required": True},
        ],
        "apply_start": "2026-10-01",
        "deadline": "2026-10-20T18:00",
        "easy_summary": "국내 대학 재학생과 휴학생이 참가하는 창업 아이디어 대회예요.",
        "confidence": 0.82,
        "low_confidence_fields": [],
    }
    base.update(over)
    return base


async def run(*replies: Any) -> Any:
    llm = ScriptedLlm(*replies)
    extracted = await extract(
        llm, model="gemini-vision", blob=POSTER, departments=DEPARTMENTS, today=TODAY
    )
    return extracted, llm


async def test_the_model_is_told_which_day_the_photo_was_uploaded() -> None:
    """포스터에는 게시일이 없다. 연도 없는 날짜를 읽을 기준을 주지 않으면 모델이 연도를 지어낸다."""
    _, llm = await run(call(SUBMIT, **args()))
    request: Request = llm.requests[0]
    first = request.turns[0].text  # type: ignore[union-attr]
    assert TODAY.isoformat() in first
    assert "사진을 올린 날" in (request.system or "")
    assert "게시일" not in (request.system or "")  # 공지 전용 기준이 남아 있지 않다
    assert "review_note" not in (request.system or "")  # 포스터 도구에 없는 항목을 시키지 않는다


async def test_the_poster_goes_to_the_model_once_and_the_tool_is_forced() -> None:
    extracted, llm = await run(call(SUBMIT, **args()))
    assert len(llm.requests) == 1  # 한 번만 묻는다
    request: Request = llm.requests[0]
    assert request.blobs == [POSTER]
    assert request.force_tool == SUBMIT and request.tools == [SUBMIT]
    assert "## 요건 규칙" in (request.system or "")  # 공지 추출과 같은 요건 규칙을 쓴다
    assert extracted.poster_text == TEXT


async def test_the_draft_carries_what_the_confirm_screen_shows() -> None:
    extracted, _ = await run(call(SUBMIT, **args()))
    draft = extracted.draft
    assert draft.title == "2026 전국 대학생 SW 창업 아이디어톤"
    assert draft.organizer == "과학기술정보통신부"
    assert draft.category == "contest"
    assert (
        draft.deadline_at is not None
        and draft.deadline_at.isoformat() == "2026-10-20T18:00:00+09:00"
    )
    assert draft.apply_start_at is not None
    assert draft.extraction_confidence == pytest.approx(0.82)
    (requirement,) = draft.requirements
    assert requirement.clause_no == 1  # 묶음 번호를 잃지 않는다(등록에서 '또는'을 되살린다)
    assert requirement.value == ["enrolled", "on_leave"]
    # 조건 문장은 공고 상세와 같은 방법으로 만든다(app/eligibility/describe)
    assert requirement.condition_text == "재학·휴학"
    assert requirement.evidence_text == "국내 대학 재학생 및 휴학생"


async def test_known_documents_come_with_the_guide_from_the_dictionary() -> None:
    extracted, _ = await run(call(SUBMIT, **args()))
    documents = {doc.name: doc for doc in extracted.draft.documents}
    assert documents["재학증명서"].issuer  # 사전에 있는 서류는 발급처가 채워진다
    assert documents["재학증명서"].lead_days is not None
    unknown = documents["아이디어 제안서"]  # 사전에 없는 서류는 비운다(준비하기에서 묻는다)
    assert (unknown.issuer, unknown.lead_days, unknown.effort_minutes) == (None, None, None)


async def test_a_model_that_does_not_submit_is_a_read_failure() -> None:
    with pytest.raises(PosterError):
        await run("포스터가 잘 안 보여요")


async def test_a_poster_with_no_text_is_a_read_failure() -> None:
    for text in (NO_TEXT, "   ", ""):
        with pytest.raises(PosterError):
            await run(call(SUBMIT, **args(poster_text=text)))


async def test_a_title_that_is_not_there_is_a_read_failure() -> None:
    with pytest.raises(PosterError):
        await run(call(SUBMIT, **args(title="   ")))


async def test_evidence_is_checked_against_what_the_model_transcribed() -> None:
    """근거 문장이 옮겨 적은 글에 없으면 조건을 그대로 믿지 않는다. 포스터에는 대조할 원문이 없다."""
    made_up = args(
        requirements=[
            {
                "clause_no": 1,
                "field": "gpa_total",
                "operator": "gte",
                "value_json": "3.5",
                "evidence_text": "평점 3.5 이상",  # 포스터 글에 없는 문장
                "is_ambiguous": False,
            }
        ]
    )
    extracted, _ = await run(call(SUBMIT, **made_up))
    (requirement,) = extracted.draft.requirements
    assert requirement.is_ambiguous  # 근거를 못 찾은 조건은 모호로 두어 판정에 쓰지 않는다
    assert "requirements" in extracted.draft.low_confidence_fields


async def test_a_missing_deadline_is_flagged_for_the_student() -> None:
    extracted, _ = await run(call(SUBMIT, **args(deadline=None)))
    assert extracted.draft.deadline_at is None
    assert "deadline_at" in extracted.draft.low_confidence_fields


async def test_low_confidence_flags_the_title_and_the_deadline() -> None:
    extracted, _ = await run(call(SUBMIT, **args(confidence=LOW_CONFIDENCE - 0.01)))
    assert set(extracted.draft.low_confidence_fields) >= {"title", "deadline_at"}


async def test_what_the_model_flags_is_kept_and_unknown_names_are_dropped() -> None:
    extracted, _ = await run(
        call(SUBMIT, **args(low_confidence_fields=["organizer", "모르는항목"]))
    )
    assert extracted.draft.low_confidence_fields == ["organizer"]


async def test_an_ambiguous_condition_flags_the_requirements() -> None:
    vague = args(
        requirements=[
            {
                "clause_no": 1,
                "field": "other",
                "operator": "eq",
                "value_json": '{"text": "성적 우수자"}',
                "evidence_text": "국내 대학 재학생 및 휴학생",
                "is_ambiguous": True,
            }
        ]
    )
    extracted, _ = await run(call(SUBMIT, **vague))
    assert "requirements" in extracted.draft.low_confidence_fields


async def test_an_unknown_category_falls_back_to_other() -> None:
    extracted, _ = await run(call(SUBMIT, **args(category="자유공모")))
    assert extracted.draft.category == "etc"


async def test_a_short_title_is_flagged() -> None:
    """ "장학금"처럼 짧은 제목은 큰 글씨만 읽은 것일 수 있다."""
    extracted, _ = await run(call(SUBMIT, **args(title="장학금")))
    assert "title" in extracted.draft.low_confidence_fields


async def test_an_unknown_category_is_flagged_so_the_student_picks_one() -> None:
    extracted, _ = await run(call(SUBMIT, **args(category="자유공모")))
    assert extracted.draft.category == "etc"
    assert "category" in extracted.draft.low_confidence_fields


async def test_a_flag_list_that_is_not_names_does_not_lose_the_draft() -> None:
    """모델이 목록에 객체를 넣어도 읽은 내용을 버리지 않는다."""
    extracted, _ = await run(
        call(SUBMIT, **args(low_confidence_fields=[{"name": "title"}, "organizer"]))
    )
    assert extracted.draft.low_confidence_fields == ["organizer"]


async def test_a_deadline_before_today_is_dropped_and_flagged() -> None:
    """포스터에는 게시일이 없어 사진을 올린 날을 기준으로 본다. 그보다 앞선 마감일은 연도를 잘못 읽은 것이다."""
    extracted, _ = await run(call(SUBMIT, **args(deadline="2026-01-05", apply_start=None)))
    assert extracted.draft.deadline_at is None
    assert "deadline_at" in extracted.draft.low_confidence_fields
    assert "requirements" in extracted.draft.low_confidence_fields  # 코드가 고쳐서 받았다


async def test_a_deadline_far_past_today_is_dropped_too() -> None:
    extracted, _ = await run(call(SUBMIT, **args(deadline="2028-10-20T18:00", apply_start=None)))
    assert extracted.draft.deadline_at is None
