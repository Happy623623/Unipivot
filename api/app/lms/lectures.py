"""주차학습 강의를 들었는지 (LearningX 주차학습, 11/24).

LearningX의 '주차학습' 탭은 Canvas 모듈을 LearningX가 다시 그린 것이다. 항목 구성은 Canvas 모듈과 같지만
**학생 본인의 상태**(다 들었는지·출결·출석 마감)가 함께 온다 — Canvas API에는 없는 값이다.
`GET /learningx/api/v1/courses/{id}/modules?include_detail=true`의 응답을 저장할 값으로 바꾼다.

11/12 한양대 실측(8과목·항목 149개, 학생 본인 계정, 읽기만):

- 항목 `content_type`은 `attendance_item` 115 · `assignment` 27 · `quiz` 5 · `wiki_page` 2였다. 강의는
  `attendance_item`이고, 과제·퀴즈는 Canvas 과제 목록이 이미 다룬다(F-51)
- `content_data.use_attendance`가 true인 항목(출석 대상)이 40개 — 녹화 강의(`item_content_data.content_type`
  `movie` 19 · `mp4` 9)와 실시간 수업(`content_data.item_content_type` `video_conference` 12)이다. 출석 대상이
  아닌 `attendance_item`은 PDF·파일 학습자료였다
- 출석 대상 40개의 `completed`·`attendance_status`는 true·`attendance` 35, false·`none` 5로 늘 짝이 맞았다
- `content_data.lecture_period_status`는 `not_open`·`open`·`late`·`late_after`·`closed`였다. 출석 마감
  `content_data.due_at`은 40개 중 28개에, 지각 마감 `late_at`은 5개에 있었다
- `module_item_id`가 Canvas 주차 항목 번호(`lms_module_items.canvas_item_id`)와 같았다(한 과목 15/15)
- `completion_determinable`이 false인 항목이 2개 있었다 — 그때 `completed`는 믿지 않는다

**모르는 것은 모른다고 둔다**: 완료 여부를 알 수 없으면(`completed`가 참·거짓이 아니거나 LearningX가 판단할 수
없다고 했으면) "안 들음"으로 세지 않고 `completed=None`이다.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.lms.parse import is_canvas_id
from app.schemas.lms import LectureKind, LectureStatus

NO_WEEK = "주차 미정"
NO_TITLE = "(제목 없음)"
LIVE_TYPE = "video_conference"  # content_data.item_content_type — 실시간 수업
VIDEO_TYPES = frozenset({"movie", "mp4", "everlec", "screenlecture", "video"})  # 녹화 강의
LECTURE_ITEM = "attendance_item"  # 주차학습의 학습 항목(강의·학습자료). 과제·퀴즈는 따로 온다
# 아직 들을 수 있는(출석·지각 인정 기간 안) 강의. 과목 목록이 센다
OPEN = frozenset({"todo", "late"})


@dataclass(frozen=True)
class Lecture:
    """학생 한 명의 강의 하나. `key`는 저장 키다(Canvas 주차 항목 번호, 없으면 LearningX 항목 번호)."""

    key: str
    canvas_item_id: int | None
    module_name: str
    title: str
    kind: LectureKind
    completed: bool | None  # None: LearningX가 완료 여부를 알 수 없다고 했다
    attendance: str | None  # attendance·late·absent·early_leave·none — LearningX 값 그대로
    period: str | None  # not_open·open·late·late_after·closed
    unlock_at: datetime | None
    due_at: datetime | None  # 출석 인정 마감
    late_at: datetime | None  # 지각 인정 마감
    duration_seconds: int | None
    position: int  # 응답 순서(주차 순)


def lectures(modules: list[Any]) -> list[Lecture]:
    """주차학습 응답에서 강의(녹화·실시간)와 출석 대상 학습자료만 고른다. 공개하지 않은 항목은 뺀다."""
    found: list[Lecture] = []
    seen: set[str] = set()
    for module in modules:
        if not isinstance(module, dict):
            continue
        name = _text(module.get("title")) or NO_WEEK
        raw_items = module.get("module_items")
        if not isinstance(raw_items, list):
            raw_items = module.get("items") if isinstance(module.get("items"), list) else []
        for raw in raw_items:
            lecture = _lecture(raw, module_name=name, position=len(found))
            if lecture is not None and lecture.key not in seen:
                seen.add(lecture.key)
                found.append(lecture)
    return found


def _lecture(raw: Any, *, module_name: str, position: int) -> Lecture | None:
    if not isinstance(raw, dict) or raw.get("content_type") != LECTURE_ITEM:
        return None
    data = raw.get("content_data")
    if not isinstance(data, dict):
        return None
    if raw.get("published") is False or data.get("published") is False:
        return None
    content = (
        data.get("item_content_data") if isinstance(data.get("item_content_data"), dict) else {}
    )
    kind = _kind(data, content)
    if kind is None:
        return None
    canvas_item = raw.get("module_item_id")
    canvas_item_id = canvas_item if is_canvas_id(canvas_item) else None
    lx_item = data.get("item_id")
    if canvas_item_id is not None:
        key = str(canvas_item_id)
    elif is_canvas_id(lx_item):
        key = f"lx:{lx_item}"
    else:
        return None  # 같은 강의인지 가릴 번호가 없다
    completed = raw.get("completed")
    known = isinstance(completed, bool) and raw.get("completion_determinable") is not False
    duration = content.get("duration")
    return Lecture(
        key=key,
        canvas_item_id=canvas_item_id,
        module_name=module_name,
        title=_text(raw.get("title")) or _text(data.get("title")) or NO_TITLE,
        kind=kind,
        completed=completed if known else None,
        attendance=_text(raw.get("attendance_status")) or None,
        period=_text(data.get("lecture_period_status")) or None,
        unlock_at=_time(data.get("unlock_at")),
        due_at=_time(data.get("due_at")),
        late_at=_time(data.get("late_at")),
        duration_seconds=round(duration)
        if isinstance(duration, int | float) and not isinstance(duration, bool) and duration > 0
        else None,
        position=position,
    )


def _kind(data: dict[str, Any], content: dict[str, Any]) -> LectureKind | None:
    """실시간 수업 · 녹화 강의 · 출석 대상 학습자료. 그 밖(출석 대상이 아닌 PDF·파일)은 강의가 아니다."""
    if data.get("item_content_type") == LIVE_TYPE:
        return "live"
    if str(content.get("content_type") or "").lower() in VIDEO_TYPES:
        return "video"
    if data.get("use_attendance") is True:
        return "material"
    return None


def lecture_status(lecture: Lecture, now: datetime) -> LectureStatus:
    """화면의 한 단어. 다 들었으면 done, 기간 안에 아직이면 todo, 지각 인정 기간이면 late, 출석 기간이 지났으면
    missed, 아직 열리지 않았으면 upcoming, 완료 여부를 모르면 unknown이다.

    기간은 LearningX의 `lecture_period_status`를 먼저 믿고, 없으면 마감 시각으로 가늠한다.
    """
    if lecture.completed is None:
        return "unknown"
    if lecture.completed:
        return "done"
    period = lecture.period
    if period == "not_open" or (period is None and lecture.unlock_at and lecture.unlock_at > now):
        return "upcoming"
    if period == "late":
        return "late"
    if period in ("late_after", "closed"):
        return "missed"
    if period is None and lecture.due_at and lecture.due_at < now:
        if lecture.late_at and lecture.late_at >= now:
            return "late"
        return "missed"
    return "todo"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _time(value: Any) -> datetime | None:
    """ISO 8601 시각. 시간대가 없으면 UTC로 본다(Canvas·LearningX는 Z를 붙여 준다). 못 읽으면 None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
