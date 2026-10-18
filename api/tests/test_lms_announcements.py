"""과목 공지 읽기와 갈래 나누기 (F-53): `app/lms/announcements.py`·`app/lms/classify.py`.

DB도 네트워크도 쓰지 않는다. 저장·피드 SQL은 test_lms_db.py, 동기화 흐름은 test_lms_sync.py가 본다.
"""

from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.lms.announcements import NO_TITLE, announcement, announcements
from app.lms.classify import BODY_MAX, SUBMIT, SUMMARY_MAX, classify, first_message
from tests.llm_fakes import ScriptedLlm
from tests.llm_fakes import call as model_call
from tests.lms_samples import DB_ANNOUNCEMENTS, RESEARCH_TITLE, RESEARCH_TOPIC_ID

MODEL = "gemini-3.5-flash-lite"


def one(**extra: Any) -> dict[str, Any]:
    return {"id": 520_964, "title": "공지", "message": "<p>본문</p>", **extra}


# ── 응답 읽기 ───────────────────────────────────────────────────────────────


def test_it_reads_the_recorded_shape() -> None:
    items = announcements(DB_ANNOUNCEMENTS)
    assert [item.canvas_topic_id for item in items][0] == RESEARCH_TOPIC_ID
    first = items[0]
    assert first.title == RESEARCH_TITLE
    assert first.posted_at == datetime(2026, 10, 14, 4, 41, 13, tzinfo=UTC)
    assert first.attachment_count == 0
    assert first.is_section_specific is False
    # 첨부가 있는 공지는 수만 센다(첨부 다운로드는 허용 경로가 아니다)
    assert items[2].attachment_count == 1


def test_html_becomes_plain_text() -> None:
    item = announcement(one(message="<p>첫 줄</p><ul><li>둘째</li></ul>"))
    assert item is not None
    assert item.message is not None
    assert "<" not in item.message
    assert "첫 줄" in item.message and "둘째" in item.message


def test_an_item_without_a_number_is_dropped() -> None:
    assert announcement({"title": "번호 없음"}) is None
    assert announcement({"id": True, "title": "참은 번호가 아니다"}) is None
    assert announcements([{"title": "하나"}, one()]) == announcements([one()])


def test_an_empty_body_becomes_none() -> None:
    for value in ("", "   ", "<p> </p>", None, 12):
        item = announcement(one(message=value))
        assert item is not None
        assert item.message is None, value


def test_a_missing_title_gets_a_placeholder() -> None:
    item = announcement(one(title="   "))
    assert item is not None and item.title == NO_TITLE


def test_an_unreadable_posted_at_becomes_none() -> None:
    for value in ("어제", "", None, 20261014):
        item = announcement(one(posted_at=value))
        assert item is not None
        assert item.posted_at is None, value


def test_a_section_specific_announcement_is_marked() -> None:
    item = announcement(one(is_section_specific=True))
    assert item is not None and item.is_section_specific is True


# ── 갈래 나누기 ─────────────────────────────────────────────────────────────


async def _classify(*replies: Any, body: str | None = "본문입니다") -> Any:
    llm = ScriptedLlm(*replies)
    result = await classify(
        llm, model=MODEL, title="공지 제목", body=body, posted_on=date(2026, 10, 14)
    )
    return result, llm


@pytest.mark.anyio
async def test_it_takes_the_category_and_the_summary() -> None:
    result, llm = await _classify(
        model_call(
            SUBMIT,
            category="opportunity",
            summary="연구 참여 학생을 모집한다",
            opportunity_category="research",
        )
    )
    assert result.category == "opportunity"
    assert result.summary == "연구 참여 학생을 모집한다"
    assert result.opportunity_category == "research"
    assert result.is_opportunity is True
    assert llm.requests[0].force_tool == SUBMIT


@pytest.mark.anyio
async def test_an_unknown_category_becomes_general() -> None:
    """모르는 값이 오면 general이다 — 잘못 기회성으로 보면 학생 피드에 공고가 생긴다."""
    for value in ("휴강", "", None, 3, ["opportunity"]):
        result, _ = await _classify(model_call(SUBMIT, category=value, summary="요약"))
        assert result.category == "general", value
        assert result.is_opportunity is False


@pytest.mark.anyio
async def test_an_unknown_opportunity_kind_becomes_etc() -> None:
    result, _ = await _classify(
        model_call(SUBMIT, category="opportunity", summary="요약", opportunity_category="연구")
    )
    assert result.opportunity_category == "etc"


@pytest.mark.anyio
async def test_a_long_summary_is_cut_and_whitespace_is_squeezed() -> None:
    result, _ = await _classify(
        model_call(SUBMIT, category="general", summary="가" * (SUMMARY_MAX + 20))
    )
    assert result.summary is not None and len(result.summary) == SUMMARY_MAX
    result, _ = await _classify(model_call(SUBMIT, category="general", summary=" 한 줄\n요약 "))
    assert result.summary == "한 줄 요약"


@pytest.mark.anyio
async def test_no_submission_becomes_general_without_a_summary() -> None:
    result, _ = await _classify("그냥 글로 답했다")
    assert result.category == "general"
    assert result.summary is None


def test_the_first_message_carries_the_title_and_the_body() -> None:
    message = first_message(title="휴강 안내", body="10월 20일 휴강", posted_on=date(2026, 10, 14))
    assert "휴강 안내" in message and "10월 20일 휴강" in message
    assert "2026-10-14" in message


def test_a_very_long_body_is_truncated() -> None:
    message = first_message(title="공지", body="가" * (BODY_MAX + 500), posted_on=None)
    assert len(message) < BODY_MAX + 300
    assert "여기까지만" in message


def test_a_body_less_announcement_says_so() -> None:
    message = first_message(title="공지", body=None, posted_on=None)
    assert "본문: (없음" in message
