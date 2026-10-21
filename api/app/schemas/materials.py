"""강의자료 요약 (F-15 축소판, API 명세 8장 `POST /materials`·`GET /materials/{file_id}`·`GET /materials`)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

READ_TOOL = "read_material_pdf"  # PDF에서 글자를 뽑고 토큰을 센 단계(명세 11장 처리 과정)
SUMMARIZE_TOOL = "summarize_material"  # 문서 전체를 한 번 요약해 저장하는 단계
MaterialStatus = Literal["pending", "running", "succeeded", "failed"]


class MaterialSummarizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: UUID


class MaterialStarted(BaseModel):
    run_id: str
    status: Literal["running"] = "running"


class MaterialCourse(BaseModel):
    lms_course_id: str
    name: str


class ProcessedRange(BaseModel):
    start: int
    end: int


class MaterialDetail(BaseModel):
    file_id: str
    file_name: str | None
    course: MaterialCourse | None
    source_language: str | None  # 축소판은 언어를 가리지 않는다(늘 null)
    total_pages: int | None
    processed_range: ProcessedRange | None  # 축소판은 늘 문서 전체다
    status: MaterialStatus  # 요약을 아직 안 했으면 pending
    overall_summary: str | None  # Markdown
    over_limit: bool  # 글자가 상한을 넘어 요약하지 않았다
    run_id: str | None  # 마지막 요약 실행(진행·실패 이유는 GET /runs/{id})


class MaterialItem(BaseModel):
    file_id: str
    file_name: str | None
    course: MaterialCourse | None
    created_at: datetime  # 요약을 처음 요청한 시각(KST)
    status: MaterialStatus


class MaterialList(BaseModel):
    items: list[MaterialItem]
    next_cursor: str | None


class MaterialSummaryResult(BaseModel):
    """GET /runs/{id}의 result(kind = material_summary)."""

    kind: Literal["material_summary"] = "material_summary"
    file_id: str
    overall_summary: str
