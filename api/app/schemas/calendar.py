"""마감일 캘린더 등록 (F-32). API 명세 7장 `POST /calendar/events`·`DELETE /calendar/events/{id}`."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

CalendarProvider = Literal["google", "ics"]


class CalendarEventRequest(BaseModel):
    """대상은 **정확히 하나**다 — 공고 마감(F-32) · LMS 과제 마감(F-51) · 계획서 일정(F-14)."""

    model_config = ConfigDict(extra="forbid")

    provider: CalendarProvider = "google"
    opportunity_id: UUID | None = None  # 형식이 틀리면 422다
    lms_assignment_id: UUID | None = None
    syllabus_item_id: UUID | None = None

    @model_validator(mode="after")
    def exactly_one_target(self) -> "CalendarEventRequest":
        given = [self.opportunity_id, self.lms_assignment_id, self.syllabus_item_id]
        if sum(one is not None for one in given) != 1:
            raise ValueError("공고·LMS 과제·계획서 일정 중 하나를 골라 주세요.")
        return self


class CalendarEventView(BaseModel):
    id: str
    provider: CalendarProvider
    external_event_id: str | None  # Google 일정 번호. 넣는 중이면 null이다
    title: str
    starts_at: datetime  # 마감 시각 1시간 전
    all_day: bool
