"""플래너(F-43). API 명세 7장 `GET/POST/PATCH/DELETE /planner/tasks`.

할 일은 출처(source)마다 고칠 수 있는 범위가 다르다. 직접 추가한 할 일만 제목·날짜를 모두 고치고 지울 수 있다.
준비 할 일은 날짜만 옮긴다(제목은 공고의 서류 이름이라 바꾸면 무엇을 준비하는지 흐려진다).
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.opportunities import Category

TaskSource = Literal["prep_plan", "syllabus", "lms_assignment", "lms_announcement", "manual"]
LinkType = Literal["opportunity", "syllabus_item", "lms_assignment", "lms_announcement"]
TITLE_MAX = 120


class PlannerLink(BaseModel):
    type: LinkType | None
    id: str | None
    title: str | None  # 공고 제목 또는 과목명
    category: Category | None  # 공고에서 온 할 일만. 나머지는 칩에 title(과목명)을 쓴다
    html_url: str | None = None


class PlannerTask(BaseModel):
    id: str
    title: str
    due_date: date
    is_done: bool
    source: TaskSource
    link: PlannerLink
    auto_completed: bool | None = None  # LMS 제출로 자동 완료(F-51). 지금은 늘 null


class PlannerMarker(BaseModel):
    """체크할 수 없는 표시 항목. 지금은 준비 중인 공고의 마감일만 있다."""

    kind: Literal["deadline"] = "deadline"
    date: date
    title: str
    opportunity_id: str
    category: Category


class PlannerResponse(BaseModel):
    items: list[PlannerTask]
    markers: list[PlannerMarker]


def _clean(title: str) -> str:
    text = " ".join(title.split())
    if not text:
        raise ValueError("할 일 이름을 적어 주세요.")
    return text


class PlannerTaskCreate(BaseModel):
    """직접 추가(source = manual). 모르는 항목은 받지 않는다(오타를 조용히 넘기지 않게)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=TITLE_MAX)
    due_date: date

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _clean(value)


class PlannerTaskPatch(BaseModel):
    """보낸 필드만 바꾼다. 셋 다 비어 있으면 422다(바꿀 것이 없다). 모르는 항목도 422다."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, max_length=TITLE_MAX)
    due_date: date | None = None
    is_done: bool | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        return None if value is None else _clean(value)

    def fields(self) -> set[str]:
        return {
            name for name in ("title", "due_date", "is_done") if getattr(self, name) is not None
        }
