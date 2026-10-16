"""LearningX 연결과 과목 목록 (F-50·F-14, API 명세 8장).

토큰은 요청으로만 받고 응답에는 끝 4자리만 넣는다(`token_last4`). 과목 이름은 LearningX가 준
`202620HY23525_데이터베이스`를 그대로 두고, 화면에 쓸 짧은 이름(`short_name`)과 포털 계획서 링크를
함께 내려준다. 계획서 링크는 사용자 브라우저에서만 연다(서버는 포털에 요청하지 않는다).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# DB enum(lms_connection_status)·GET /me의 lms.status·web 타입과 같은 세 가지
ConnectionStatus = Literal["active", "error", "disconnected"]


class ConnectRequest(BaseModel):
    """LearningX 개인 액세스 토큰. 앞뒤 공백은 떼고 받는다(복사할 때 자주 섞인다)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    access_token: str = Field(min_length=8, max_length=500)


class ConnectResult(BaseModel):
    status: Literal["active"]  # 연결에 성공한 응답이라 늘 active다
    token_last4: str
    courses: int
    first_sync_run_id: str | None


class ConnectionView(BaseModel):
    status: ConnectionStatus
    token_last4: str | None
    last_synced_at: datetime | None  # KST 오프셋
    last_error: str | None


class NextDue(BaseModel):
    kind: Literal["assignment", "syllabus_item"]
    title: str
    due_at: datetime


class CourseItem(BaseModel):
    id: str
    canvas_course_id: int
    name: str  # LearningX 과목명 그대로
    short_name: str  # `_` 뒤만. 꼴이 다르면 이름 전체
    has_syllabus: bool
    portal_syllabus_url: str | None
    open_assignments: int
    new_materials: int
    next_due: NextDue | None


class CourseList(BaseModel):
    items: list[CourseItem]
