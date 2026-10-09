"""GET /meta/departments, POST /events 모델 (API 명세 v0.4 4장)."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Department(BaseModel):
    name: str
    college: str
    field_group: str


class DepartmentList(BaseModel):
    items: list[Department]


# 프론트가 보내는 이벤트. profile_prompt_submitted·lms_connected는 서버가 해당 API 안에서 기록한다
ClientEvent = Literal["app_open", "profile_prompt_shown", "lms_guide_opened"]


class EventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: ClientEvent
    opportunity_id: UUID | None = None
