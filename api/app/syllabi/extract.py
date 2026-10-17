"""계획서 글자 → 일정 목록 (F-14).

모델을 **한 번만** 부른다. 계획서는 글자가 다 있어서 더 읽을 첨부가 없다.

받은 값은 믿지 않고 코드가 검사한다 — 종류는 ERD enum 안의 것만, 날짜는 학기 범위 안의 날만,
근거 줄은 계획서 글자에 실제로 있는 것만 받는다. 모델이 지어낸 일정이 플래너·캘린더에 들어가면
학생이 엉뚱한 날에 시험을 준비한다.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from app.eligibility import KST
from app.llm import LlmClient, LlmReply, ToolCall, UserTurn
from app.schemas.syllabi import EXTRACT_TOOL, SyllabusItemType
from app.syllabi.prompt import EXTRACT_SPEC, MAX_ITEMS, TYPE_LABELS, first_message, system_prompt

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 50.0  # 웹이 실행을 확인하는 60초 안에 실패를 알려 준다
MAX_OUTPUT_TOKENS = 8_000
MAX_INPUT_CHARS = 40_000  # 계획서 10쪽이면 2만 자 안쪽이다. 넘치면 앞에서 자른다
DEFAULT_TIME = time(9, 0)  # 시각이 적혀 있지 않은 일정은 그날 아침 9시로 둔다
_TITLE_MAX = 200


class SyllabusError(Exception):
    """계획서에서 일정을 읽지 못했다. 학생에게 그대로 보여 줄 문구다."""


@dataclass(frozen=True)
class DraftItem:
    item_type: SyllabusItemType
    title: str
    starts_at: datetime


@dataclass(frozen=True)
class Extracted:
    course_name: str | None
    semester: str | None
    items: list[DraftItem]
    reply: LlmReply
    call: ToolCall


async def extract(
    llm: LlmClient,
    *,
    model: str,
    text: str,
    semester_start: date,
    semester_end: date,
    uploaded_on: date,
) -> Extracted:
    """모델 한 번 호출. 읽지 못하면 SyllabusError다."""
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            reply = await llm.generate(
                model=model,
                system=system_prompt(),
                turns=[
                    UserTurn(
                        text=first_message(
                            text[:MAX_INPUT_CHARS],
                            semester_start=semester_start,
                            semester_end=semester_end,
                            uploaded_on=uploaded_on,
                        )
                    )
                ],
                tools=(EXTRACT_SPEC,),
                force_tool=EXTRACT_TOOL,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )
    except TimeoutError as exc:
        raise TimeoutError("계획서를 읽는 데 너무 오래 걸렸어요.") from exc
    call = next((one for one in reply.turn.tool_calls if one.name == EXTRACT_TOOL), None)
    if call is None:
        raise SyllabusError(
            f"계획서에서 일정을 읽지 못했어요({reply.finish_reason or '이유 없음'})."
        )
    items = extracted_items(
        call.args,
        # 대조는 **모델이 본 글자**로 한다. 뒤를 잘라 보냈으면 그 뒤 글자는 근거가 될 수 없다
        text=text[:MAX_INPUT_CHARS],
        semester_start=semester_start,
        semester_end=semester_end,
    )
    return Extracted(
        course_name=_text(call.args.get("course_name"), 100),
        semester=_text(call.args.get("semester"), 20),
        items=items,
        reply=reply,
        call=call,
    )


def extracted_items(
    args: dict[str, Any], *, text: str, semester_start: date, semester_end: date
) -> list[DraftItem]:
    """모델이 낸 일정 중 **쓸 수 있는 것만** 고른다. 버린 것은 로그에만 남긴다."""
    raw = args.get("items")
    if not isinstance(raw, list):
        return []
    found: list[DraftItem] = []
    seen: set[tuple[str, datetime]] = set()
    for one in raw[: MAX_ITEMS * 2]:  # 넘치게 온 것도 걸러 보고 상한에서 자른다
        item = _item(one, text=text, semester_start=semester_start, semester_end=semester_end)
        if item is None:
            continue
        key = (item.title, item.starts_at)
        if key in seen:  # 같은 일정을 두 번 적었다
            continue
        seen.add(key)
        found.append(item)
        if len(found) >= MAX_ITEMS:
            break
    return found


def _item(raw: Any, *, text: str, semester_start: date, semester_end: date) -> DraftItem | None:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("item_type")
    title = _text(raw.get("title"), _TITLE_MAX)
    if kind not in TYPE_LABELS or title is None:
        return _skip("종류나 이름이 없어요", raw)
    evidence = _text(raw.get("evidence_text"), 500)
    if evidence is None or not _in_text(evidence, text):
        # 계획서에 없는 줄을 근거로 댔다 = 지어낸 일정이다
        return _skip("근거 줄이 계획서에 없어요", raw)
    day = _date(raw.get("date"))
    if day is None or not semester_start <= day <= semester_end:
        return _skip("날짜가 학기 범위 밖이에요", raw)
    if not _dated(evidence, day):
        # 이름만 옮겨 적고 날짜는 아무 날로 적는 것을 막는다. 근거 줄에 날짜나 주차가 보여야 한다
        return _skip("근거 줄에 날짜도 주차도 없어요", raw)
    at = _time(raw.get("time")) or DEFAULT_TIME
    return DraftItem(kind, title, datetime.combine(day, at, tzinfo=KST))


def _skip(why: str, raw: Any) -> None:
    """버린 이유만 남긴다. 계획서 본문은 로그에도 남기지 않는다(실행 기록과 같은 기준)."""
    kind = raw.get("item_type") if isinstance(raw, dict) else None
    logger.info("계획서 일정 하나를 버렸어요: %s (종류 %s)", why, kind)
    return None


_WEEK = re.compile(r"(\d{1,2})\s*(?:주\s*차|주차|週|weeks?|wk)", re.IGNORECASE)


def _dated(evidence: str, day: date) -> bool:
    """근거 줄이 그 날짜를 뒷받침하는지.

    계획서는 "8주차 10/20 중간고사"처럼 날짜나 주차로 날을 가리킨다. 둘 다 없는 줄(예: "중간고사"만)
    은 날짜의 근거가 되지 못한다 — 모델이 이름만 옮기고 날짜를 아무 날로 적을 수 있다.
    """
    squeezed = _squeeze(evidence)
    month, date_no = day.month, day.day
    shapes = (
        f"{month}/{date_no}",
        f"{month:02d}/{date_no:02d}",
        f"{month}/{date_no:02d}",
        f"{month:02d}/{date_no}",
        f"{month}.{date_no}",
        f"{month:02d}.{date_no:02d}",
        f"{month}-{date_no}",
        f"{month:02d}-{date_no:02d}",
        f"{month}월{date_no}일",
        f"{day.isoformat()}",
    )
    if any(shape in squeezed for shape in shapes):
        return True
    return bool(_WEEK.search(evidence))  # 주차만 적힌 줄은 모델이 학기 시작일로 센다


def _in_text(evidence: str, text: str) -> bool:
    """근거 줄이 계획서 글자에 있는지. 공백 차이는 무시한다(PDF는 줄바꿈이 제각각이다)."""
    return _squeeze(evidence) in _squeeze(text)


def _squeeze(value: str) -> str:
    return "".join(value.split())


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:limit]


def _date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _time(value: Any) -> time | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return time.fromisoformat(value.strip()[:5])
    except ValueError:
        return None


def semester_range(semester_start: date | None, uploaded_on: date) -> tuple[date, date]:
    """연도 없는 날짜를 읽을 기준 범위.

    LMS 과목이 있으면 그 과목의 학기 시작일을 쓴다. 없으면 올린 날이 든 학기를 쓴다 —
    한국 대학은 3월·9월에 시작하므로 그 전후로 끊는다.
    """
    if semester_start is not None:
        return semester_start, semester_start + timedelta(days=150)
    year = uploaded_on.year
    if uploaded_on.month <= 2:  # 1~2월은 지난 2학기의 끝자락이다
        return date(year - 1, 9, 1), _last_of_february(year)
    if uploaded_on.month <= 8:
        return date(year, 3, 1), date(year, 8, 31)
    return date(year, 9, 1), _last_of_february(year + 1)


def _last_of_february(year: int) -> date:
    """2월 마지막 날. 윤년이면 29일이다(그날 일정을 버리지 않게)."""
    return date(year, 3, 1) - timedelta(days=1)
