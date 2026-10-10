"""GET /opportunities 모델 (API 명세 v0.4 5장, web types/api.ts의 FeedResponse와 같은 이름)."""

from datetime import datetime
from typing import Literal

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
