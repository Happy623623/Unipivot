"""강의계획서 일정 추출·확정 (F-14, API 명세 8장 `POST /syllabi/extract`·`POST /syllabi/{id}/confirm`)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# 계획서에서 뽑는 일정 종류(ERD syllabus_item_type). 일반 강의 주차는 넣지 않는다
SyllabusItemType = Literal["midterm", "final", "presentation", "assignment", "etc"]
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
