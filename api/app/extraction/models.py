"""요건 추출 입출력. DB·LLM과 무관한 데이터다."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class AttachmentInput:
    seq: int  # 게시판의 첨부 순서(1부터). 모델에는 이 번호로 보여준다
    file_name: str
    data: bytes
    source_url: str | None = None
    id: str | None = None  # opportunity_attachments.id. 크롤러가 행을 만든 뒤 넘긴다


@dataclass(frozen=True)
class NoticeInput:
    title: str
    body: str  # 본문 글자. 게시판 HTML이면 html_text로 바꿔서 넣는다
    posted_on: date | None = None  # 연도 없는 날짜("10. 24.까지")를 읽는 기준
    organizer: str | None = None
    original_url: str | None = None
    attachments: tuple[AttachmentInput, ...] = ()


@dataclass(frozen=True)
class Limits:
    """에이전트 상한. PRD 14장 미결(W2–3 실제 공지로 결정)이라 설정으로 바꿀 수 있게 둔다."""

    max_reads: int = 4  # 읽기 도구(첨부 글자·첨부 이미지·원문 다시 읽기)를 합친 호출 수
    max_submits: int = 2  # 첫 제출 + 재시도 1번
    max_tokens: int = 150_000  # 실행 전체의 입력+출력 토큰. 넘으면 지금까지 읽은 것으로 제출받는다
    max_body_chars: int = 20_000  # 첫 메시지에 넣는 본문 길이
    max_read_chars: int = 12_000  # 읽기 도구가 한 번에 돌려주는 글자 수
    vision_max_pages: int = 4  # read_attachment_image 한 번에 보내는 PDF 쪽 수
    low_confidence: float = 0.6  # 모델이 낸 신뢰도가 이보다 낮으면 원문 확인 필요


@dataclass(frozen=True)
class RequirementDraft:
    """requirements 행 하나가 될 조건."""

    clause_no: int
    field: str
    operator: str
    value: Any
    basis: str | None
    evidence_text: str | None
    is_ambiguous: bool


@dataclass(frozen=True)
class DocumentDraft:
    """opportunity_documents 행. 발급처·방법·소요 일수는 준비하기(서류 안내)에서 채운다."""

    name: str
    is_required: bool = True
    form_url: str | None = None


@dataclass(frozen=True)
class AttachmentOutcome:
    """opportunity_attachments에 쓸 값. 읽지 않은 첨부는 method·text가 None이다(ERD v0.9)."""

    seq: int
    file_name: str
    kind: str
    mime_type: str | None
    sha256: str
    id: str | None = None
    method: str | None = None
    text: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ExtractionResult:
    succeeded: bool  # False면 받은 제출이 없다. 저장할 때 기존 요건을 그대로 둔다
    requirements: tuple[RequirementDraft, ...] = ()
    documents: tuple[DocumentDraft, ...] = ()
    apply_start_at: datetime | None = None
    deadline_at: datetime | None = None
    eligibility_basis_date: date | None = None
    easy_summary: str | None = None
    confidence: Decimal | None = None
    needs_review: bool = False  # 원문 확인 필요 배지
    review_reasons: tuple[str, ...] = ()  # 배지를 단 이유. 처리 과정(F-42)에 보여준다
    attachments: tuple[AttachmentOutcome, ...] = ()
