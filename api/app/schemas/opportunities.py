"""GET /opportunities · GET /opportunities/{id} 모델 (API 명세 v0.4 5장, web types/api.ts와 같은 이름)."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

Category = Literal[
    "scholarship",
    "school_program",
    "youth_policy",
    "contest",
    "activity",
    "research",
    "exam",
    "etc",
]
SourceType = Literal["school_notice", "youth_policy", "contest", "poster", "lms_announcement"]
EligibilityStatus = Literal["eligible", "undetermined", "ineligible"]
DisplayStatus = Literal["eligible", "missing_info", "needs_review", "ineligible"]

CATEGORIES: tuple[str, ...] = Category.__args__
SOURCE_TYPES: tuple[str, ...] = SourceType.__args__
ELIGIBILITY_STATUSES: tuple[str, ...] = EligibilityStatus.__args__


class FeedEligibility(BaseModel):
    status: EligibilityStatus
    display_status: DisplayStatus  # 화면 라벨 4종
    summary: str  # 카드의 상태 사유 한 줄 (eligibility_results.reason_text)
    missing_fields: list[str]  # 정보 입력창(F-03)에 띄울 요건 항목


class OpportunityItem(BaseModel):
    id: str
    title: str
    organizer: str | None
    category: Category
    source_type: SourceType
    deadline_at: datetime | None  # KST 오프셋(+09:00)으로 내려준다
    d_day: int | None  # 마감일(KST) - 오늘(KST). 마감일이 없으면 null(상시)
    easy_summary: str | None
    eligibility: FeedEligibility
    recommend_reason: str | None = None  # F-24 (P1)
    needs_review: bool  # 추출 신뢰도가 낮은 공고. 라벨은 그대로 두고 배지를 붙인다(F-25)
    uploaded_by_me: bool  # 포스터 카드는 주최 자리에 "내가 올린 포스터"
    course_name: str | None  # 과목 공지에서 온 공고만
    prepared: bool  # 준비하기를 했는지
    is_new: bool  # 최근 7일 안에 등록됐고 상세를 아직 열지 않음


class FeedCounts(BaseModel):
    """홈 요약 카드. 카테고리·출처·판정 필터와 상관없이 활성 공고 전체 기준이다."""

    eligible: int
    new_eligible: int
    undetermined: int
    missing_info: int
    needs_review: int
    ineligible: int
    deadline_soon: int  # 지원 가능·확인 필요 중 D-3~D-day


class FeedResponse(BaseModel):
    items: list[OpportunityItem]
    next_cursor: str | None
    counts: FeedCounts


# GET /opportunities/{id} (API 명세 v0.4 5장, web types/api.ts의 OpportunityDetail과 같은 이름)

Outcome = Literal["pass", "fail", "unknown"]
UnknownReason = Literal["missing_profile", "ambiguous", "unsupported_field", "basis_mismatch"]
OpportunityStatus = Literal["active", "hidden", "merged", "expired"]
RunStatus = Literal["pending", "running", "succeeded", "failed"]


class Condition(BaseModel):
    """판정표 한 줄. 같은 clause_no끼리 "다음 중 하나" 묶음이다."""

    requirement_id: str
    clause_no: int
    field: str
    label: str  # "직전학기 이수학점"
    operator: str
    value: Any  # 요건 값(requirements.value)
    user_value: Any  # 비교에 쓴 내 값(나이는 기준일의 만 나이). 미입력이면 null
    condition_text: str  # "12학점 이상"
    user_value_text: str | None  # "10학점", 미입력이면 null
    outcome: Outcome
    unknown_reason: UnknownReason | None  # 결과가 충족·불충족이면 null
    evidence_text: str | None
    is_ambiguous: bool


class Clause(BaseModel):
    clause_no: int
    outcome: Outcome
    condition_count: int  # 2 이상이면 화면이 "다음 중 하나" 상자로 그린다


class DetailEligibility(BaseModel):
    status: EligibilityStatus
    display_status: DisplayStatus
    reason_text: str | None  # 사유 한 줄(피드 카드의 summary와 같다)
    basis_date: date | None  # 판정 기준일. 요건 추출에 실패한 공고는 null
    requirements_version: int
    missing_fields: list[str]
    clauses: list[Clause]
    conditions: list[Condition]
    evaluated_at: datetime | None  # 판정 시각. 요건 추출에 실패한 공고는 null


class DocumentItem(BaseModel):
    id: str
    name: str
    issuer: str | None
    how_to: str | None
    lead_days: int | None  # 0이면 즉시 발급
    effort_minutes: int | None
    form_url: str | None
    is_required: bool
    task_id: str | None  # 준비하기 전에는 null. 체크는 PATCH /planner/tasks/{task_id}
    is_done: bool | None


class CalendarEventRef(BaseModel):
    id: str
    provider: str


class Prep(BaseModel):
    prepared: bool
    prep_plan_id: str | None
    tasks_total: int
    tasks_done: int
    calendar_events: list[CalendarEventRef]


class ProcessStep(BaseModel):
    seq: int
    tool: str
    label: str  # "첨부 '2026-2 장학 안내.hwp' 읽기"
    status: RunStatus
    latency_ms: int | None
    chosen_by: Literal["agent", "pipeline"]  # 모델이 고른 도구인지, 정해진 순서인지
    note: str | None  # 모델이 고른 이유 한 줄(공고 원문에서 온 내용만)


class Process(BaseModel):
    extraction: list[ProcessStep]
    evaluated_at: datetime | None
    prepare_run_id: str | None


class AttachmentItem(BaseModel):
    id: str
    file_name: str
    source_url: str  # 학교 다운로드 주소. 주소가 없는 행(본문 이미지)은 내려주지 않는다
    extract_status: Literal["succeeded", "failed", "skipped"]  # skipped: 에이전트가 읽지 않음


class OpportunityDetail(BaseModel):
    id: str
    title: str
    organizer: str | None
    category: Category
    source_type: SourceType
    status: OpportunityStatus  # 준비한 공고가 마감·숨김이 되면 화면 위에 안내를 띄운다
    original_url: str | None
    poster_url: str | None  # 포스터 원본 이미지(서명 URL 5분). 포스터 업로드(W6)에서 채운다
    easy_summary: str | None
    apply_start_at: datetime | None  # KST 오프셋(+09:00)
    deadline_at: datetime | None
    needs_review: bool
    extraction_confidence: float | None
    uploaded_by_me: bool
    course_name: str | None
    attachments: list[AttachmentItem]
    eligibility: DetailEligibility
    documents: list[DocumentItem]
    prep: Prep
    process: Process
    reported_by_me: bool  # 신고(P1) 전에는 늘 false
