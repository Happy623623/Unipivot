"""준비하기(F-30·F-31)와 실행 조회(GET /runs/{id}). API 명세 7장·11장."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.calendar import CalendarEventView
from app.schemas.lms import LmsSyncResult
from app.schemas.opportunities import DocumentItem, ProcessStep, RunStatus
from app.schemas.posters import PosterExtractResult


class PrepareRequest(BaseModel):
    # 마감일 캘린더 등록은 준비하기와 따로 한다(POST /calendar/events, F-32)
    target_date: date | None = None  # 상시 공고(마감일 없음)는 꼭 준다. 오늘이나 그 뒤
    force: bool = False  # 지원 어려움 공고를 "그래도 준비하기"로 다시 보낼 때


class PrepareStarted(BaseModel):
    run_id: str | None  # 이미 준비한 공고는 그 준비 실행. 실행 기록이 지워졌으면 null
    status: RunStatus  # 처음이면 running(202), 이미 준비했으면 succeeded(200)


class PrepTask(BaseModel):
    id: str
    title: str  # "재학증명서 준비" · "신청 제출"
    due_date: date
    document_id: str | None


class PrepareResult(BaseModel):
    kind: Literal["prepare"] = "prepare"
    prep_plan_id: str
    documents: list[DocumentItem]  # 상세의 documents와 같은 모양(서류 할 일 id·완료 포함)
    tasks: list[PrepTask]  # 서류 순서대로, 마지막이 신청 제출
    # 마감일 캘린더는 따로 등록한다(F-32). 준비하기 결과에는 담지 않는다
    calendar_event: CalendarEventView | None
    calendar_error: str | None


class RunError(BaseModel):
    code: str
    message: str


RunResult = Annotated[
    PrepareResult | PosterExtractResult | LmsSyncResult, Field(discriminator="kind")
]


class RunView(BaseModel):
    id: str
    trigger_type: str
    status: RunStatus
    started_at: datetime | None  # KST 오프셋(+09:00)
    finished_at: datetime | None
    latency_ms: int | None
    steps: list[ProcessStep]
    # 작업별 결과. kind로 가린다(prepare 준비하기, poster_extract 포스터 추출, lms_sync 동기화)
    result: RunResult | None
    error: RunError | None
