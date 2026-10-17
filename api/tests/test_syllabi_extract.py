"""계획서 글자 → 일정(F-14). 모델은 가짜로 바꿔 끼운다.

받은 값을 코드가 어떻게 걸러내는지가 핵심이다 — 모델이 지어낸 일정이 플래너·캘린더에 들어가면
학생이 엉뚱한 날에 시험을 준비한다.
"""

from datetime import date, datetime
from typing import Any

import pytest

from app.eligibility import KST
from app.schemas.syllabi import EXTRACT_TOOL
from app.syllabi.extract import MAX_INPUT_CHARS, SyllabusError, extract, semester_range
from app.syllabi.prompt import MAX_ITEMS
from tests.llm_fakes import ScriptedLlm, call

pytestmark = pytest.mark.anyio

START, END = date(2026, 9, 1), date(2027, 1, 29)
TODAY = date(2026, 10, 17)
TEXT = """2026학년도 2학기 강의계획서
교과목명: 데이터베이스 (202620HY23525)
담당교수: 홍길동

주차별 계획
3주차 09/15 관계대수
8주차 10/20(화) 중간고사 10:30~12:00
12주차 11/17 과제2 제출
15주차 12/08 팀 프로젝트 발표
16주차 12/15 기말고사 10:30~12:00
"""


def item(**over: Any) -> dict[str, Any]:
    base = {
        "item_type": "midterm",
        "title": "중간고사",
        "date": "2026-10-20",
        "time": "10:30",
        "evidence_text": "8주차 10/20(화) 중간고사 10:30~12:00",
    }
    return {**base, **over}


async def _extract(*items: dict[str, Any], **args: Any) -> Any:
    llm = ScriptedLlm(call(EXTRACT_TOOL, items=list(items), **args))
    return await extract(
        llm,
        model="gemini-3.8-flash",
        text=TEXT,
        semester_start=START,
        semester_end=END,
        uploaded_on=TODAY,
    ), llm


async def test_it_asks_once_and_keeps_the_items() -> None:
    found, llm = await _extract(
        item(),
        item(
            item_type="final",
            title="기말고사",
            date="2026-12-15",
            evidence_text="16주차 12/15 기말고사 10:30~12:00",
        ),
        course_name="데이터베이스",
        semester="2026-2",
    )
    assert len(llm.requests) == 1  # 한 번만 묻는다
    assert llm.requests[0].force_tool == EXTRACT_TOOL
    assert "학기 범위(KST): 2026-09-01 ~ 2027-01-29" in str(llm.requests[0].turns[0].text)
    assert (found.course_name, found.semester) == ("데이터베이스", "2026-2")
    assert [(one.item_type, one.title) for one in found.items] == [
        ("midterm", "중간고사"),
        ("final", "기말고사"),
    ]
    assert found.items[0].starts_at == datetime(2026, 10, 20, 10, 30, tzinfo=KST)


async def test_a_missing_time_becomes_nine_in_the_morning() -> None:
    """계획서에 시각이 없는 일정이 많다. 그날 아침으로 두고 학생이 고친다."""
    found, _ = await _extract(
        item(
            item_type="presentation",
            title="팀 프로젝트 발표",
            date="2026-12-08",
            time=None,
            evidence_text="15주차 12/08 팀 프로젝트 발표",
        )
    )
    assert found.items[0].starts_at == datetime(2026, 12, 8, 9, 0, tzinfo=KST)


async def test_an_item_the_syllabus_does_not_mention_is_dropped() -> None:
    """근거 줄이 계획서에 없으면 지어낸 일정이다."""
    found, _ = await _extract(item(evidence_text="9주차 10/27 쪽지시험"))
    assert found.items == []


async def test_evidence_is_matched_without_whitespace() -> None:
    """PDF는 줄바꿈·공백이 제각각이라 공백은 무시하고 대조한다."""
    found, _ = await _extract(item(evidence_text="8주차  10/20(화)\n중간고사 10:30~12:00"))
    assert len(found.items) == 1


async def test_a_date_outside_the_semester_is_dropped() -> None:
    """연도를 잘못 읽은 일정(지난해 10/20 등)은 버린다."""
    found, _ = await _extract(item(date="2025-10-20"), item(date="2027-10-20"))
    assert found.items == []


async def test_an_unknown_type_is_dropped() -> None:
    found, _ = await _extract(item(item_type="lecture"), item(item_type=None))
    assert found.items == []


async def test_the_same_item_twice_is_kept_once() -> None:
    found, _ = await _extract(item(), item())
    assert len(found.items) == 1


async def test_too_many_items_are_cut() -> None:
    many = [
        item(title=f"과제{no}", item_type="assignment", date="2026-11-17", time=None,
             evidence_text="12주차 11/17 과제2 제출")
        for no in range(MAX_ITEMS + 10)
    ]  # fmt: skip
    found, _ = await _extract(*many)
    assert len(found.items) == MAX_ITEMS


async def test_no_items_is_a_normal_answer() -> None:
    """시험 일정이 안 적힌 계획서도 있다. 억지로 만들지 않는다."""
    found, _ = await _extract()
    assert found.items == []


async def test_a_reply_without_the_tool_is_an_error() -> None:
    llm = ScriptedLlm("일정을 찾지 못했습니다")
    with pytest.raises(SyllabusError):
        await extract(
            llm,
            model="gemini-3.8-flash",
            text=TEXT,
            semester_start=START,
            semester_end=END,
            uploaded_on=TODAY,
        )


async def test_long_text_is_cut_before_the_model() -> None:
    llm = ScriptedLlm(call(EXTRACT_TOOL, items=[]))
    await extract(
        llm,
        model="gemini-3.8-flash",
        text="가" * (MAX_INPUT_CHARS + 500),
        semester_start=START,
        semester_end=END,
        uploaded_on=TODAY,
    )
    sent = str(llm.requests[0].turns[0].text)
    assert sent.count("가") == MAX_INPUT_CHARS


async def test_a_table_syllabus_still_matches_the_evidence() -> None:
    """표로 된 계획서는 PDF에서 **칸마다 한 줄**로 나온다(pypdf). 그래도 근거를 찾아야 한다.

    모델은 한 행을 "8 10/20 중간고사"처럼 이어 적는다. 공백·줄바꿈을 지우고 비교하므로 맞는다.
    """
    table = "주차\n날짜\n내용\n비고\n8\n10/20\n중간고사\n10:30~12:00, 1~7주차 범위\n"
    llm = ScriptedLlm(
        call(
            EXTRACT_TOOL,
            items=[item(evidence_text="8 10/20 중간고사 10:30~12:00, 1~7주차 범위")],
        )
    )
    found = await extract(
        llm,
        model="gemini-3.8-flash",
        text=table,
        semester_start=START,
        semester_end=END,
        uploaded_on=TODAY,
    )
    assert [one.title for one in found.items] == ["중간고사"]


def test_the_semester_range_comes_from_the_course() -> None:
    assert semester_range(date(2026, 9, 1), TODAY) == (date(2026, 9, 1), date(2027, 1, 29))


def test_without_a_course_the_range_comes_from_the_upload_day() -> None:
    """LMS를 연결하지 않았으면 올린 날이 든 학기로 본다(한국 대학은 3월·9월에 시작한다)."""
    assert semester_range(None, date(2026, 10, 17)) == (date(2026, 9, 1), date(2027, 2, 28))
    assert semester_range(None, date(2026, 4, 2)) == (date(2026, 3, 1), date(2026, 8, 31))
    assert semester_range(None, date(2026, 1, 20)) == (date(2025, 9, 1), date(2026, 2, 28))


async def test_a_name_without_a_date_is_not_evidence() -> None:
    """이름만 옮겨 적고 날짜를 아무 날로 적는 것을 막는다(근거 줄에 날짜나 주차가 있어야 한다)."""
    found, _ = await _extract(item(date="2026-11-03", evidence_text="중간고사"))
    assert found.items == []


async def test_a_week_only_line_is_evidence_enough() -> None:
    """주차만 적힌 줄은 모델이 학기 시작일로 센다. 그건 받아 준다(확인 화면에서 고친다)."""
    text_with_week = TEXT.replace("8주차 10/20(화) 중간고사 10:30~12:00", "8주차 중간고사")
    llm = ScriptedLlm(
        call(
            EXTRACT_TOOL,
            items=[item(date="2026-10-20", time=None, evidence_text="8주차 중간고사")],
        )
    )
    found = await extract(
        llm,
        model="gemini-3.8-flash",
        text=text_with_week,
        semester_start=START,
        semester_end=END,
        uploaded_on=TODAY,
    )
    assert [one.title for one in found.items] == ["중간고사"]


async def test_dates_written_in_korean_count_as_evidence() -> None:
    text_korean = TEXT + "\n보강: 11월 3일 쪽지시험\n"
    llm = ScriptedLlm(
        call(
            EXTRACT_TOOL,
            items=[
                item(
                    item_type="etc",
                    title="쪽지시험",
                    date="2026-11-03",
                    time=None,
                    evidence_text="보강: 11월 3일 쪽지시험",
                )
            ],
        )
    )
    found = await extract(
        llm,
        model="gemini-3.8-flash",
        text=text_korean,
        semester_start=START,
        semester_end=END,
        uploaded_on=TODAY,
    )
    assert [one.title for one in found.items] == ["쪽지시험"]


async def test_the_evidence_is_matched_against_what_the_model_saw() -> None:
    """뒤를 잘라 보냈으면 그 뒤 글자는 근거가 될 수 없다(모델이 못 본 글자다)."""
    cut = "가" * MAX_INPUT_CHARS + "\n16주차 12/15 기말고사\n"
    llm = ScriptedLlm(
        call(
            EXTRACT_TOOL,
            items=[
                item(
                    item_type="final",
                    title="기말고사",
                    date="2026-12-15",
                    time=None,
                    evidence_text="16주차 12/15 기말고사",
                )
            ],
        )
    )
    found = await extract(
        llm,
        model="gemini-3.8-flash",
        text=cut,
        semester_start=START,
        semester_end=END,
        uploaded_on=TODAY,
    )
    assert found.items == []


async def test_a_model_that_times_out_is_a_timeout() -> None:
    class Slow:
        provider = "google"

        async def generate(self, **_: Any) -> Any:
            raise TimeoutError("늦었다")

    with pytest.raises(TimeoutError):
        await extract(
            Slow(),  # type: ignore[arg-type]
            model="gemini-3.8-flash",
            text=TEXT,
            semester_start=START,
            semester_end=END,
            uploaded_on=TODAY,
        )


def test_the_semester_end_handles_a_leap_year() -> None:
    """2월 29일 일정을 버리지 않는다."""
    assert semester_range(None, date(2027, 10, 1))[1] == date(2028, 2, 29)
    assert semester_range(None, date(2028, 1, 10))[1] == date(2028, 2, 29)
