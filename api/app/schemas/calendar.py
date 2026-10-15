"""마감일 캘린더 등록 (F-32). API 명세 7장 `POST /calendar/events`·`DELETE /calendar/events/{id}`."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

CalendarProvider = Literal["google", "ics"]


class CalendarEventRequest(BaseModel):
    """지금은 공고 마감일만 넣는다. 강의계획서 일정·LMS 과제는 그 기능(F-14·F-51)과 함께 연다."""

    model_config = ConfigDict(extra="forbid")

    provider: CalendarProvider = "google"
    opportunity_id: UUID  # 형식이 틀리면 422다


class CalendarEventView(BaseModel):
    id: str
    provider: CalendarProvider
    external_event_id: str | None  # Google 일정 번호. 넣는 중이면 null이다
    title: str
    starts_at: datetime  # 마감 시각 1시간 전
    all_day: bool
