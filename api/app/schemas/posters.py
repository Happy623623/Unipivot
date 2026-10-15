"""포스터로 공고 등록 (F-16, API 명세 6장). 추출 결과는 GET /runs/{id}의 result로 나간다."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.opportunities import Category

# 추출 실행이 남기는 도구 이름. 초안은 그 tool_calls.output에 있다(repositories/runs.py)
EXTRACT_TOOL = "submit_poster"

# 확인 화면에서 강조할 수 있는 항목. 모델이 고르는 이름이기도 하다
LOW_CONFIDENCE_FIELDS = (
    "title",
    "organizer",
    "category",
    "apply_start_at",
    "deadline_at",
    "requirements",
    "documents",
)


class PosterExtractRequest(BaseModel):
    file_id: UUID  # POST /files로 올린 포스터


class PosterRequirementDraft(BaseModel):
    """확인 화면에서 문장으로 보여 주고 줄 단위로 지울 수 있는 조건 하나."""

    clause_no: int  # 묶음 번호. 같은 번호끼리 "또는", 다른 번호끼리 "그리고"
    field: str
    operator: str
    value: Any
    condition_text: str  # "재학생 또는 휴학생" — 공고 상세와 같은 방법으로 만든 문장
    evidence_text: str | None
    is_ambiguous: bool


class PosterDocumentDraft(BaseModel):
    """제출 서류. 발급처·소요 일수·작성 시간은 서류 사전에 있으면 채운다."""

    name: str
    issuer: str | None = None
    lead_days: int | None = None
    effort_minutes: int | None = None
    form_url: str | None = None


class PosterDraft(BaseModel):
    title: str
    organizer: str | None = None
    category: Category
    apply_start_at: datetime | None = None
    deadline_at: datetime | None = None
    easy_summary: str | None = None
    requirements: list[PosterRequirementDraft]
    documents: list[PosterDocumentDraft]
    extraction_confidence: float
    low_confidence_fields: list[str]  # 확인 화면에서 강조 표시


class DuplicateCandidate(BaseModel):
    opportunity_id: str
    title: str


class PosterExtractResult(BaseModel):
    kind: Literal["poster_extract"] = "poster_extract"
    draft: PosterDraft
    duplicate_candidate: DuplicateCandidate | None = None


class PosterExtractStarted(BaseModel):
    run_id: str
    status: Literal["running"]
