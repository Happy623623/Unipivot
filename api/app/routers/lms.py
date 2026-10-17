"""LearningX 연결·과목·과제 (F-50·F-51·F-14, API 명세 9장).

토큰 연결·상태·해제, 수강 과목 목록, 동기화(202 + `run_id`), 과제 목록이다.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.auth import CurrentUserDep
from app.clock import NowDep
from app.errors import ApiError
from app.lms.service import NOT_CONNECTED, LmsServiceDep
from app.lms.sync import LmsSyncServiceDep
from app.repositories.lms import LmsRepoDep
from app.schemas.lms import (
    AssignmentList,
    AssignmentState,
    ConnectionView,
    ConnectRequest,
    ConnectResult,
    CourseList,
    SyncResponse,
    SyncSkipped,
)

router = APIRouter(prefix="/lms", tags=["LMS"])


@router.post("/connection", status_code=201, response_model=ConnectResult)
async def connect(
    body: ConnectRequest, user: CurrentUserDep, service: LmsServiceDep, now: NowDep
) -> ConnectResult:
    """토큰을 확인하고 암호화해 저장한 뒤 수강 과목을 받아 둔다. 이미 연결돼 있으면 토큰을 교체한다."""
    return await service.connect(user.id, body.access_token, now)


@router.get("/connection", response_model=ConnectionView)
async def connection(user: CurrentUserDep, repo: LmsRepoDep) -> ConnectionView:
    """연결 상태와 토큰 끝 4자리. 연결이 없으면 404 LMS_NOT_CONNECTED다."""
    found = await repo.connection(user.id)
    if found is None:
        raise ApiError(404, "LMS_NOT_CONNECTED", NOT_CONNECTED)
    return found.view()


@router.delete("/connection", status_code=204)
async def disconnect(user: CurrentUserDep, repo: LmsRepoDep) -> Response:
    """토큰을 즉시 지운다. 과목·과제 기록은 남기고 동기화만 멈춘다."""
    if not await repo.delete_connection(user.id):
        raise ApiError(404, "LMS_NOT_CONNECTED", NOT_CONNECTED)
    return Response(status_code=204)


@router.get("/courses", response_model=CourseList)
async def courses(user: CurrentUserDep, repo: LmsRepoDep, now: NowDep) -> CourseList:
    """수강 과목과 포털 계획서 링크. 과제·새 자료 숫자는 저장된 동기화 결과로 센다."""
    return CourseList(items=await repo.courses(user.id, now=now))


@router.post(
    "/sync",
    status_code=202,
    response_model=SyncResponse,
    # 건너뛴 응답도 계약에 있다(명세 9장). 생성되는 클라이언트가 두 모양을 다 보게 적어 둔다
    responses={200: {"model": SyncSkipped, "description": "마지막 동기화가 5분 안이라 건너뜀"}},
)
async def sync(
    user: CurrentUserDep, service: LmsSyncServiceDep, now: NowDep, response: Response
) -> SyncResponse:
    """과목·과제를 다시 받는다(F-51). 결과는 `GET /runs/{run_id}`로 본다.

    대시보드를 열 때 프론트가 부른다. 마지막 동기화가 5분 안이면 LearningX를 부르지 않고 200으로
    건너뛴 사실을 알려 준다. 연결이 없으면 404 LMS_NOT_CONNECTED다.
    """
    result = await service.start(user.id, now=now)
    if isinstance(result, SyncSkipped):
        response.status_code = 200
    return result


@router.get("/assignments", response_model=AssignmentList)
async def assignments(
    user: CurrentUserDep,
    repo: LmsRepoDep,
    state: AssignmentState = "open",
    lms_course_id: Annotated[UUID | None, Query(description="과목 하나만 볼 때")] = None,
) -> AssignmentList:
    """과제 목록(F-51). 마감이 가까운 순이고, 마감이 없는 과제는 뒤에 온다.

    `state`를 주지 않으면 아직 내지 않은 과제(`open`)만 준다. LMS에서 사라진 과제는 빠진다.
    """
    return AssignmentList(
        items=await repo.assignments(
            user.id,
            state=state,
            course_id=str(lms_course_id) if lms_course_id else None,
        )
    )
