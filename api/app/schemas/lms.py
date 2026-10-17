"""LearningX 연결·과목·과제 (F-50·F-51·F-14, API 명세 8장).

토큰은 요청으로만 받고 응답에는 끝 4자리만 넣는다(`token_last4`). 과목 이름은 LearningX가 준
`202620HY23525_데이터베이스`를 그대로 두고, 화면에 쓸 짧은 이름(`short_name`)과 포털 계획서 링크를
함께 내려준다. 계획서 링크는 사용자 브라우저에서만 연다(서버는 포털에 요청하지 않는다).

과제는 마감(`due_at`)이 없을 수 있다(녹화 17건 중 5건은 `due_at`이 null이고 `lock_at`만 있어서 그걸 쓴다).
`submission_state`는 LearningX가 준 값 그대로다(`unsubmitted`·`submitted`·`graded`·`pending_review`).
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# DB enum(lms_connection_status)·GET /me의 lms.status·web 타입과 같은 세 가지
ConnectionStatus = Literal["active", "error", "disconnected"]
# DB enum(lms_submission_state)·web 타입과 같은 네 가지. LearningX가 준 값을 그대로 쓴다
SubmissionState = Literal["unsubmitted", "submitted", "graded", "pending_review"]
# `GET /lms/assignments?state=`. 주지 않으면 open이다(화면이 "할 일"로 먼저 보여 준다)
AssignmentState = Literal["open", "submitted", "all"]
# 동기화 결과를 남기는 도구 이름. app/lms/sync.py가 쓰고 GET /runs/{id}가 읽는다
SAVE_TOOL = "save_lms_sync"


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


class SyncStarted(BaseModel):
    """`POST /lms/sync` 202. 결과는 `GET /runs/{run_id}`로 본다."""

    run_id: str
    status: Literal["running"]


class SyncSkipped(BaseModel):
    """`POST /lms/sync` 200. 마지막 동기화가 얼마 안 돼 건너뛴 응답이다(명세 8장)."""

    skipped: Literal[True] = True
    last_synced_at: datetime | None  # KST 오프셋


# 같은 엔드포인트가 202·200으로 서로 다른 모양을 준다(명세 8장). 두 모양은 겹치는 칸이 없다
SyncResponse = SyncStarted | SyncSkipped


class SyncCounts(BaseModel):
    """이번 동기화에서 과제가 어떻게 바뀌었는지."""

    new: int
    due_changed: int
    submitted: int


class LmsSyncResult(BaseModel):
    """`GET /runs/{id}`의 동기화 결과(명세 8장). 공지는 F-53이라 아직 0이다."""

    kind: Literal["lms_sync"] = "lms_sync"
    courses: int
    assignments: SyncCounts
    new_module_items: int = 0
    new_announcements: int = 0
    # 캘린더에 새로 넣은 과제 마감 수와 시각을 고친 수(설정을 켠 사람만, F-51)
    calendar_events: int = 0
    calendar_moved: int = 0


class AssignmentCourse(BaseModel):
    id: str
    short_name: str


class AssignmentItem(BaseModel):
    id: str
    course: AssignmentCourse
    title: str
    due_at: datetime | None  # KST 오프셋. 마감이 없는 과제는 null
    submission_state: SubmissionState
    html_url: str | None
    planner_task_id: str | None
    calendar_registered: bool


class AssignmentList(BaseModel):
    items: list[AssignmentItem]


# `GET /lms/updates?type=`에 쓸 수 있는 값. 공지(`announcement`)는 F-53이 채운다(그때까지 결과가 빈다)
UpdateType = Literal["module_item", "assignment", "announcement"]


class ModuleItemUpdate(BaseModel):
    """새 주차 항목 하나(F-52)."""

    type: Literal["module_item"] = "module_item"
    id: str
    course: AssignmentCourse
    module_name: str | None
    title: str
    item_type: str | None  # ExternalTool · Assignment · Quiz · Page (녹화에 File은 없었다)
    html_url: str | None
    first_seen_at: datetime  # KST 오프셋
    uploaded_file_id: str | None  # 이 항목 알림에서 올린 PDF가 있으면 그 파일


class AssignmentUpdate(BaseModel):
    """새 과제나 마감이 가까운 미제출 과제 하나(F-51)."""

    type: Literal["assignment"] = "assignment"
    id: str
    course: AssignmentCourse
    title: str
    due_at: datetime | None
    submission_state: SubmissionState
    html_url: str | None
    first_seen_at: datetime


LmsUpdateItem = Annotated[ModuleItemUpdate | AssignmentUpdate, Field(discriminator="type")]


class LmsUpdateList(BaseModel):
    items: list[LmsUpdateItem]
    next_cursor: str | None


class SyncJobResult(BaseModel):
    """`POST /internal/jobs/lms-sync`(30분 배치) 결과. 실패한 사용자는 다음 차례에 다시 본다."""

    users: int  # 이번에 본 사용자 수(최근에 동기화한 사람은 빼고 센다)
    synced: int
    failed: int
    skipped: int  # 그새 대시보드가 동기화를 시작했거나 연결이 사라진 사람
    new_assignments: int
    due_changed: int
    submitted: int


# ── 과목 상세 (F-14·F-51·F-52, 명세 9장) ────────────────────────────────────
SyllabusItemType = Literal["midterm", "final", "presentation", "assignment", "etc"]
# `materials.status`(job_status). 요약이 아직 없으면 파일만 있고 상태는 pending이다
MaterialStatus = Literal["pending", "running", "succeeded", "failed"]
AnnouncementCategory = Literal["schedule_change", "material", "opportunity", "general"]


class CourseHeader(BaseModel):
    id: str
    short_name: str
    has_syllabus: bool
    # 그 과목 계획서의 번호(없으면 null). 확인 전 일정이 남았을 때 다시 올리지 않고
    # `POST /syllabi/{id}/confirm`을 부르려면 이 번호가 필요하다(F-14)
    syllabus_id: str | None = None
    portal_syllabus_url: str | None  # 과목명 꼴이 다르면 null
    html_url: str  # "LMS에서 열기". 과목 주소는 저장하지 않고 LMS 주소 + 과목 번호로 만든다


class CourseAssignment(BaseModel):
    """과목 상세의 과제. 목록(`GET /lms/assignments`)과 달리 과목 칸이 없다(이미 그 과목이다)."""

    id: str
    title: str
    due_at: datetime | None
    submission_state: SubmissionState
    html_url: str | None


class CourseModuleItem(BaseModel):
    id: str
    module_name: str | None
    title: str
    item_type: str | None
    html_url: str | None
    is_new: bool  # 이번에 열기 전 기준이다(열면 last_viewed_at이 지금으로 바뀐다)
    uploaded_file_id: str | None


class CourseAnnouncement(BaseModel):
    id: str
    title: str
    summary: str | None  # 분류 전이면 null (F-53)
    category: AnnouncementCategory | None
    posted_at: datetime | None
    opportunity_id: str | None


class CourseSyllabusItem(BaseModel):
    id: str
    item_type: SyllabusItemType
    title: str
    starts_at: datetime | None
    is_confirmed: bool


class CourseMaterial(BaseModel):
    file_id: str
    original_name: str | None
    status: MaterialStatus


class CourseDetail(BaseModel):
    course: CourseHeader
    assignments: list[CourseAssignment]
    module_items: list[CourseModuleItem]
    announcements: list[CourseAnnouncement]
    syllabus_items: list[CourseSyllabusItem]
    materials: list[CourseMaterial]
