"""마감일 캘린더 등록 (F-32). API 명세 7장 `POST /calendar/events`·`DELETE /calendar/events/{id}`."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

CalendarProvider = Literal["google", "ics"]


class CalendarEventRequest(BaseModel):
    """대상은 **정확히 하나**다 — 공고 마감(F-32)이나 LMS 과제 마감(F-51).

    강의계획서 일정(`syllabus_item_id`)은 F-14와 함께 연다(지금 보내면 모르는 칸이라 422다).
    """

    model_config = ConfigDict(extra="forbid")

    provider: CalendarProvider = "google"
    opportunity_id: UUID | None = None  # 형식이 틀리면 422다
    lms_assignment_id: UUID | None = None

    @model_validator(mode="after")
    def exactly_one_target(self) -> "CalendarEventRequest":
        if (self.opportunity_id is None) == (self.lms_assignment_id is None):
            raise ValueError("공고나 LMS 과제 하나를 골라 주세요.")
        return self


class CalendarEventView(BaseModel):
    id: str
    provider: CalendarProvider
    external_event_id: str | None  # Google 일정 번호. 넣는 중이면 null이다
    title: str
    starts_at: datetime  # 마감 시각 1시간 전
    all_day: bool
