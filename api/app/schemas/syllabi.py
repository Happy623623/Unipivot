"""강의계획서 일정 추출·확정 (F-14, API 명세 8장 `POST /syllabi/extract`·`POST /syllabi/{id}/confirm`)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.eligibility.dates import KST

# 계획서에서 뽑는 일정 종류(ERD syllabus_item_type). 일반 강의 주차는 넣지 않는다
SyllabusItemType = Literal["midterm", "final", "presentation", "assignment", "etc"]
TITLE_MAX = 200  # 추출이 받는 제목 길이와 같게 둔다(app/syllabi/extract.py)
EXTRACT_TOOL = "save_syllabus_items"  # 모델이 결과를 내는 도구(실행 기록에 이 이름으로 남는다)
SAVE_TOOL = "save_syllabus"  # 저장 단계. `GET /runs/{id}`가 이 출력으로 결과를 만든다
READ_TOOL = "read_syllabus_pdf"  # PDF에서 글자를 뽑는 단계(명세 11장 처리 과정)


class SyllabusExtractRequest(BaseModel):
    """올려 둔 계획서 PDF 하나를 과목에 붙여 일정을 뽑는다."""

    model_config = ConfigDict(extra="forbid")

    file_id: UUID
    lms_course_id: UUID | None = None  # LMS를 연결하지 않았으면 비운다(과목 없이 저장한다)
    replace: bool = False  # 이미 계획서가 있는 과목을 덮어쓸지(없으면 409)


class SyllabusItemView(BaseModel):
    id: str
    item_type: SyllabusItemType
    title: str
    starts_at: datetime | None  # KST 오프셋. 날짜만 적힌 일정은 그날 09:00이다
    is_confirmed: bool = False
    # 캘린더에 실제로 들어간 일정인지(과제 목록·공고 상세와 같은 기준). 추출 결과에서는 늘 false다
    # — 확정하기 전에는 캘린더에 넣지 않는다
    calendar_registered: bool = False


# 캘린더 일정 제목 앞머리. 공고는 `[마감]`, LMS 과제는 `[과제]`다(명세 7장)
ITEM_PREFIXES: dict[str, str] = {
    "midterm": "시험",
    "final": "시험",
    "presentation": "발표",
    "assignment": "과제",
    "etc": "일정",
}


def syllabus_title(item_type: str, course: str | None, title: str) -> str:
    """계획서 일정의 캘린더 제목(F-14). 종류를 앞머리로 둔다 — `[시험] 데이터베이스 · 중간고사`.

    과목을 붙이지 않은 계획서(LMS 미연결)는 과목 자리를 비운다.
    """
    head = ITEM_PREFIXES.get(item_type, "일정")
    return f"[{head}] {course} · {title}" if course else f"[{head}] {title}"


class SyllabusConfirmItem(BaseModel):
    """학생이 확인 화면에서 고친 일정 하나."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    starts_at: datetime | None = None
    selected: bool = True

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        """공백만 적은 제목은 받지 않는다(플래너에 제목 없는 줄이 생긴다)."""
        text = " ".join(value.split())
        if not text:
            raise ValueError("일정 이름을 적어 주세요.")
        return text

    @field_validator("starts_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        """시간대를 적지 않은 값은 **KST로 본다**.

        화면이 `2026-11-04T13:00`처럼 오프셋 없이 보낼 수 있다. 그대로 두면 DB(UTC)와
        날짜 계산(KST)이 서로 다른 기준으로 읽어 시험 시각이 아홉 시간 밀린다.
        """
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=KST)


class SyllabusConfirmRequest(BaseModel):
    """확인 화면이 보내는 최종 일정. 고른 것만 플래너·캘린더로 간다(명세 8장)."""

    model_config = ConfigDict(extra="forbid")

    items: list[SyllabusConfirmItem] = Field(min_length=1, max_length=50)
    register_calendar: bool = False
    calendar_provider: Literal["google"] = "google"


class SyllabusConfirmResult(BaseModel):
    confirmed: int
    planner_tasks_created: int
    calendar_events_created: int
    calendar_events_moved: int = 0  # 이미 넣어 둔 일정의 시각·제목을 고친 수


class SyllabusStarted(BaseModel):
    """`POST /syllabi/extract` 202. 결과는 `GET /runs/{run_id}`로 본다."""

    run_id: str
    status: Literal["running"]


class SyllabusExtractResult(BaseModel):
    """`GET /runs/{id}`의 계획서 추출 결과(명세 8장)."""

    kind: Literal["syllabus_extract"] = "syllabus_extract"
    syllabus_id: str
    course_name: str | None
    items: list[SyllabusItemView] = Field(default_factory=list)
