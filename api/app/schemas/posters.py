"""포스터로 공고 등록 (F-16, API 명세 6장). 추출 결과는 GET /runs/{id}의 result로 나간다."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.opportunities import Category

# 추출 실행이 남기는 도구 이름. 초안은 그 tool_calls.output에 있다(repositories/runs.py)
EXTRACT_TOOL = "submit_poster"
# 처리 과정(F-42)에 보이는 단계 이름. 실행 조회와 공고 상세가 같은 이름을 쓴다
EXTRACT_LABEL = "포스터에서 글자·날짜 읽기"

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
    # 비교 기준(region·department만). 없으면 판정이 달라진다(학과는 학과 이름, 지역은 주민등록 주소로 본다).
    # 화면에는 조건 문장으로만 보이고, 등록할 때 이 값으로 requirements 행을 만든다
    basis: str | None = None
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


class PosterConfirmRequest(BaseModel):
    """확인 화면에서 고친 값. 요건·서류는 **지운 것만** 반영한다.

    서버가 `run_id`로 추출 초안을 다시 읽어 기준으로 삼는다. 요건의 항목·연산자·값은 학생이 보낸
    값을 쓰지 않는다 — 판정에 쓰이는 값이라 화면에서 지어내 보낼 수 있으면 안 된다.
    """

    run_id: UUID
    draft: PosterDraft


class PosterConfirmResult(BaseModel):
    opportunity_id: str
    merged: bool  # 같은 공고가 이미 있어 그 공고를 돌려줬다(새로 만들지 않았다)
