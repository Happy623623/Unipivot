"""LearningX 연결·과목·과제 (F-50·F-51·F-14, API 명세 9장).

토큰 연결·상태·해제, 수강 과목 목록, 동기화(202 + `run_id`), 과제 목록이다.
"""

from datetime import datetime, timedelta
from typing import Annotated, get_args
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.auth import CurrentUserDep
from app.clock import NowDep
from app.config import Settings, get_settings
from app.errors import ApiError
from app.lms.service import NOT_CONNECTED, LmsServiceDep
from app.lms.sync import LmsSyncServiceDep
from app.repositories.lms import LmsRepoDep, update_filter, update_since
from app.repositories.opportunities import decode_cursor, encode_cursor
from app.schemas.lms import (
    AssignmentList,
    AssignmentState,
    ConnectionView,
    ConnectRequest,
    ConnectResult,
    CourseDetail,
    CourseList,
    LmsUpdateList,
    SyncResponse,
    SyncSkipped,
    UpdateType,
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


@router.get("/courses/{course_id}", response_model=CourseDetail)
async def course_detail(
    course_id: UUID,
    user: CurrentUserDep,
    repo: LmsRepoDep,
    now: NowDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> CourseDetail:
    """과목 상세: 과제·주차 자료·공지·계획서 일정·내 자료(F-14·F-51·F-52).

    부르면 그 과목을 "지금 봤다"고 적는다(`last_viewed_at`). 그래서 다음부터 새 자료 수가 줄고,
    이 응답의 `is_new`는 **바꾸기 전** 기준이다. 수강을 뺀 과목과 남의 과목은 404다.
    """
    found = await repo.course_detail(
        user.id, str(course_id), now=now, lms_base=settings.lms_api_base
    )
    if found is None:
        raise ApiError(404, "NOT_FOUND", "과목을 찾을 수 없어요.")
    return found


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


UPDATE_KINDS = get_args(UpdateType)  # 쓸 수 있는 종류(schemas/lms.py와 한 곳에서 본다)
SINCE_DAYS = 14  # since를 주지 않으면 최근 이만큼


@router.get("/updates", response_model=LmsUpdateList)
async def updates(
    user: CurrentUserDep,
    repo: LmsRepoDep,
    now: NowDep,
    since: Annotated[datetime | None, Query(description="이 시각 뒤에 처음 본 것")] = None,
    type: Annotated[str, Query(description="쉼표로 나눈 종류")] = "module_item,assignment",
    lms_course_id: Annotated[UUID | None, Query(description="과목 하나만 볼 때")] = None,
    cursor: Annotated[str | None, Query(description="다음 쪽")] = None,
) -> LmsUpdateList:
    """새 주차 항목·과제 피드(F-52·F-51). 처음 본 순이고, 마감 D-3 이내 미제출 과제도 넣는다.

    `since`를 주지 않으면 최근 14일이다. `cursor`를 주면 그 커서에 적힌 `since`를 쓴다(기본값은 요청마다
    달라서 그대로 두면 다음 쪽을 부를 수 없다). 종류·과목이 다른 목록의 커서는 422다.
    한 쪽은 50개이고, 공지(`announcement`)는 F-53이 채운다.
    """
    kinds = [one.strip() for one in type.split(",") if one.strip()]
    unknown = [one for one in kinds if one not in UPDATE_KINDS]
    if not kinds or unknown:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "볼 종류를 확인해 주세요.",
            {"fields": {"type": f"{', '.join(UPDATE_KINDS)} 중에서 골라 주세요."}},
        )
    course = str(lms_course_id) if lms_course_id else None
    start = since or now - timedelta(days=SINCE_DAYS)
    last = None
    if cursor is not None:
        try:
            last = decode_cursor(cursor)
        except ValueError:
            last = None
        # `since`는 커서에 적힌 값을 쓴다. 기본값(지금 - 14일)은 요청마다 달라서, 지문에 넣고 그대로
        # 비교하면 둘째 쪽이 늘 422가 된다
        from_cursor = update_since(last.scope) if last else None
        if (
            last is None
            or from_cursor is None
            or not last.scope.startswith(f"{update_filter(kinds, course)}|")
        ):
            raise ApiError(
                422,
                "VALIDATION_FAILED",
                "목록 조건이 바뀌었어요. 처음부터 다시 불러 주세요.",
                {"fields": {"cursor": "조건이 다른 목록의 커서예요."}},
            )
        start = from_cursor
    items, next_cursor = await repo.updates(
        user.id, since=start, now=now, kinds=kinds, course_id=course, cursor=last
    )
    return LmsUpdateList(
        items=items, next_cursor=encode_cursor(next_cursor) if next_cursor else None
    )
