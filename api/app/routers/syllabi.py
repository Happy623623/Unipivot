"""강의계획서 일정 추출 (F-14, API 명세 8장).

학생이 포털 계획서를 PDF로 저장해 `POST /files`(kind=syllabus)로 올린 뒤 이 경로를 부른다.
추출은 오래 걸려서 202와 `run_id`로 답하고 `GET /runs/{run_id}`로 결과를 본다(명세 2장).

과목을 붙이면(`lms_course_id`) 그 과목의 계획서가 되고, 과목당 하나다 — 이미 있으면
`409 SYLLABUS_EXISTS`이고 `{"replace": true}`로 갈아 끼운다.
"""

import logging

from fastapi import APIRouter, Response

from app.auth import CurrentUserDep
from app.clock import NowDep
from app.eligibility import to_kst_date
from app.errors import ApiError
from app.repositories.syllabi import SyllabusRepoDep
from app.schemas.syllabi import SyllabusExtractRequest, SyllabusStarted
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
