"""마감일 캘린더 등록 (F-32, API 명세 7장)."""

import logging
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Response

from app.auth import CurrentUserDep
from app.calendar import EVENT_MINUTES, event_id_for, event_title
from app.calendar.service import CalendarServiceDep
from app.clock import NowDep
from app.eligibility import KST
from app.errors import ApiError
from app.repositories.calendar import CalendarRepoDep
from app.schemas.calendar import CalendarEventRequest, CalendarEventView

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/calendar", tags=["캘린더"])

NOT_FOUND = "캘린더 일정을 찾을 수 없어요."


@router.post("/events", status_code=201, response_model=CalendarEventView)
async def add_event(
    body: CalendarEventRequest,
    user: CurrentUserDep,
    repo: CalendarRepoDep,
    service: CalendarServiceDep,
    now: NowDep,
    response: Response,
) -> CalendarEventView:
    """준비한 공고의 마감일을 Google 캘린더에 넣는다. 이미 넣었으면 200과 그 일정이다.

    일정은 마감 시각으로 끝나는 1시간짜리다. 연결이 없거나 만료면 409 CALENDAR_NOT_CONNECTED,
    Google이 거절하면 502 GOOGLE_API_ERROR다.
    """
    if body.provider != "google":  # .ics 내려받기는 F-34(P1)다
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "입력값을 확인해 주세요.",
            {"fields": {"provider": "지금은 Google 캘린더만 등록할 수 있어요."}},
        )
    opportunity_id = str(body.opportunity_id)
    existing = await repo.event_for(user.id, opportunity_id, body.provider)
    if existing is not None and existing.external_event_id:
        response.status_code = 200
        return existing
    opportunity = await repo.prepared_opportunity(user.id, opportunity_id)
    if opportunity is None:
        raise _invalid("준비 일정을 먼저 만들어 주세요.")
    if opportunity.deadline_at is None:
        raise _invalid("마감일이 없는 공고예요. 캘린더에 넣을 수 없어요.")
    ends_at = opportunity.deadline_at.astimezone(KST)
    if ends_at <= now:
        raise ApiError(409, "DEADLINE_PASSED", "마감이 지난 공고예요. 캘린더에 넣을 수 없어요.")
    token = await service.access_token(user.id, now)
    title = event_title(opportunity.title)
    # 자리를 먼저 잡고 그 행의 id로 Google 일정 번호를 정한다(다시 눌러도 일정은 하나다)
    event = existing or await repo.reserve(
        user.id,
        provider=body.provider,
        opportunity_id=opportunity.id,
        title=title,
        starts_at=ends_at - timedelta(minutes=EVENT_MINUTES),
    )
    external_id = await service.insert(
        token, event_id=event_id_for(event.id), title=title, ends_at=ends_at
    )
    await repo.attach(user.id, event.id, external_id)
    return event.model_copy(update={"external_event_id": external_id})


@router.delete("/events/{event_id}", status_code=204, response_class=Response)
async def remove_event(
    event_id: UUID,
    user: CurrentUserDep,
    repo: CalendarRepoDep,
    service: CalendarServiceDep,
    now: NowDep,
) -> Response:
    """Google 캘린더에서도 지운다. 남의 일정·없는 일정은 404다.

    캘린더 권한이 없어졌으면 Google에서는 지우지 못한다. 그래도 우리 기록은 지운다. 그러지 않으면
    학생이 "캘린더에서 빼기"를 누를 때마다 실패하고 그 줄을 영영 지우지 못한다(Google 쪽 일정은
    학생이 직접 지운다). Google이 잠깐 멈춘 것(502)은 기록을 두고 다시 누르게 한다.
    """
    event = await repo.one(user.id, str(event_id))
    if event is None:
        raise ApiError(404, "NOT_FOUND", NOT_FOUND)
    try:
        token = await service.access_token(user.id, now)
        await service.delete(token, event.external_event_id)
    except ApiError as exc:
        if exc.code != "CALENDAR_NOT_CONNECTED":
            raise
        logger.info("캘린더 권한이 없어 기록만 지워요: event %s", event.id)
    await repo.remove(user.id, event.id)
    return Response(status_code=204)


def _invalid(reason: str) -> ApiError:
    return ApiError(
        422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": {"opportunity_id": reason}}
    )
