"""강의계획서 일정 추출 (F-14, API 명세 8장).

학생이 포털 계획서를 PDF로 저장해 `POST /files`(kind=syllabus)로 올린 뒤 이 경로를 부른다.
추출은 오래 걸려서 202와 `run_id`로 답하고 `GET /runs/{run_id}`로 결과를 본다(명세 2장).

과목을 붙이면(`lms_course_id`) 그 과목의 계획서가 되고, 과목당 하나다 — 이미 있으면
`409 SYLLABUS_EXISTS`이고 `{"replace": true}`로 갈아 끼운다.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Response

from app.auth import CurrentUserDep
from app.calendar.service import CalendarServiceDep
from app.clock import NowDep
from app.eligibility import to_kst_date
from app.errors import ApiError
from app.repositories.calendar import CalendarRepoDep
from app.repositories.syllabi import SyllabusRepoDep
from app.schemas.syllabi import (
    SyllabusConfirmRequest,
    SyllabusConfirmResult,
    SyllabusExtractRequest,
    SyllabusStarted,
)
from app.syllabi import confirm as confirm_steps
from app.syllabi.service import SyllabusJob, SyllabusServiceDep

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/syllabi", tags=["강의계획서"])
FILE_NOT_FOUND = "올린 계획서를 찾을 수 없어요. 다시 올려 주세요."
COURSE_NOT_FOUND = "과목을 찾을 수 없어요."
EXISTS = "이 과목에는 이미 계획서가 있어요. 다시 올리면 기존 일정을 바꿔요."


@router.post("/extract", status_code=202, response_model=SyllabusStarted)
async def extract_syllabus(
    body: SyllabusExtractRequest,
    user: CurrentUserDep,
    repo: SyllabusRepoDep,
    service: SyllabusServiceDep,
    now: NowDep,
    response: Response,
) -> SyllabusStarted:
    """올려 둔 계획서에서 시험·발표·과제 일정을 뽑는다. 202와 `run_id`로 답한다."""
    found = await repo.syllabus_file(user.id, str(body.file_id))
    if found is None:
        raise ApiError(404, "NOT_FOUND", FILE_NOT_FOUND)
    course = None
    if body.lms_course_id is not None:
        course = await repo.course(user.id, str(body.lms_course_id))
        if course is None:
            raise ApiError(404, "NOT_FOUND", COURSE_NOT_FOUND)
        if not body.replace and await repo.existing(user.id, course.id) is not None:
            raise ApiError(409, "SYLLABUS_EXISTS", EXISTS)
    job = SyllabusJob(
        run_id="",  # begin이 실행을 만들고 채운다
        user_id=user.id,
        file=found,
        course_id=course.id if course else None,
        course_short_name=course.short_name if course else None,
        semester_start=course.semester_start if course else None,
        today=to_kst_date(now),
        now=now,
    )
    run_id = await service.begin(job)
    response.status_code = 202
    return SyllabusStarted(run_id=run_id, status="running")


@router.post("/{syllabus_id}/confirm", response_model=SyllabusConfirmResult)
async def confirm_syllabus(
    syllabus_id: UUID,
    body: SyllabusConfirmRequest,
    user: CurrentUserDep,
    repo: SyllabusRepoDep,
    calendar: CalendarRepoDep,
    service: CalendarServiceDep,
    now: NowDep,
) -> SyllabusConfirmResult:
    """고친 일정을 저장하고, 고른 것만 플래너(과 원하면 캘린더)에 넣는다.

    캘린더를 부탁했는데 연결이 없으면 **아무것도 바꾸지 않고** `409 CALENDAR_NOT_CONNECTED`다 —
    학생이 연결한 뒤 다시 누르면 된다.
    """
    head = await repo.one(user.id, str(syllabus_id))
    if head is None:
        raise ApiError(404, "NOT_FOUND", "계획서를 찾을 수 없어요.")
    plans, _ = confirm_steps.planned(await repo.items(user.id, head.id), body.items)
    token = None
    if body.register_calendar:
        # 연결·토큰을 먼저 **한 번** 꺼낸다(없으면 409). 확정만 해 두고 캘린더가 비는 상태를
        # 만들지 않는다. 꺼낸 토큰을 그대로 넘겨 일정마다 다시 꺼내지 않는다
        token = await service.access_token(user.id, now)
    confirmed, tasks = await confirm_steps.confirm(repo, user_id=user.id, head=head, plans=plans)
    events = (0, 0)
    if token is not None:
        events = await confirm_steps.register(
            calendar,
            service,
            user_id=user.id,
            head=head,
            plans=plans,
            provider=body.calendar_provider,
            now=now,
            token=token,
        )
    return confirm_steps.result(confirmed, tasks, events)
