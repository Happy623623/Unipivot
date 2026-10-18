"""알림함과 알림 배치 (F-33·F-35, API 명세 v0.4 10장·12장).

알림 행 하나가 푸시 발송(`status`)과 알림함 표시(`read_at`)를 함께 담는다(ERD v0.9). 설정에서 끈
종류는 행을 만들지 않고, 푸시를 끈 사용자도 행은 만들되 발송 배치가 푸시만 건너뛴다.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

NotificationType = Literal[
    "new_eligible",
    "new_assignment",
    "new_material",
    "schedule_change",
    "task_due",
    "deadline_soon",
    "profile_needed",
]
LinkType = Literal[
    "opportunity", "planner_task", "lms_assignment", "lms_module_item", "lms_announcement"
]
# 공고에서 오는 알림 세 종류(F-45가 "공고 알림"으로 묶어 부르는 것). ERD 중복 방지 표에 키가 있다
OPPORTUNITY_TYPES: tuple[str, ...] = ("new_eligible", "deadline_soon", "profile_needed")


class NotificationLink(BaseModel):
    """누르면 갈 곳. focus가 profile_input이면 상세에서 정보 입력창을 바로 연다."""

    type: LinkType
    id: str
    course_id: str | None = None  # lms_* 링크만. 그것만으로는 과목 탭으로 갈 수 없다
    focus: Literal["profile_input"] | None = None


class NotificationItem(BaseModel):
    id: str
    type: NotificationType
    title: str
    body: str | None
    scheduled_at: datetime  # KST 오프셋(+09:00)
    read_at: datetime | None
    link: NotificationLink | None


class NotificationList(BaseModel):
    items: list[NotificationItem]
    unread_count: int
    next_cursor: str | None


class ReadRequest(BaseModel):
    """둘 중 하나를 보낸다: 고른 알림(ids) 또는 전체(all)."""

    model_config = ConfigDict(extra="forbid")

    ids: list[UUID] | None = None
    all: bool = False

    @model_validator(mode="after")
    def one_of(self) -> "ReadRequest":
        if self.all == bool(self.ids):
            raise ValueError("ids 또는 all 하나만 보내 주세요.")
        return self


class ReadResult(BaseModel):
    unread_count: int


# POST /internal/jobs/schedule-notifications · POST /internal/jobs/send-notifications


class ScheduleResult(BaseModel):
    """예약 배치. created는 새로 만든 행, rescheduled는 마감이 바뀌어 시각을 고친 행이다."""

    created: int
    rescheduled: int
    removed: int  # 조건에서 빠져 지운 pending 행(준비 취소·숨김·마감 지남 등)
    by_type: dict[str, int]


class SendResult(BaseModel):
    """발송 배치(명세 12장).

    `pushable`은 푸시를 **보낼 수 있었던** 알림 수(구독이 있고 푸시를 끄지 않았다),
    `pushed`는 그중 푸시 서비스가 받아 준 구독 수다. 한 알림에 구독이 여러 개면 여러 번 센다.
    `push_failed`는 보내다 실패한 구독 수고, `push_dropped`는 사라져서 지운 구독 수다.
    """

    due: int
    sent: int
    pushable: int
    skipped: int  # 숨긴 공고·하루 한도로 보내지 않고 둔 알림
    pushed: int = 0
    push_failed: int = 0
    push_dropped: int = 0
