"""마감일 캘린더 등록 (F-32·F-51, API 명세 7장).

대상은 공고 마감이나 LMS 과제 마감 하나다. 일정은 마감 시각으로 끝나는 1시간짜리이고, 일정 번호는
우리 행 id에서 만들어 보내므로 다시 눌러도 캘린더에 하나만 들어간다.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Response

from app.auth import CurrentUserDep
from app.calendar import EVENT_MINUTES, assignment_title, event_id_for, event_title
from app.calendar.service import CalendarServiceDep
from app.clock import NowDep
from app.eligibility import KST
from app.errors import ApiError
from app.repositories.calendar import CalendarRepoDep, CalendarRepository
from app.schemas.calendar import CalendarEventRequest, CalendarEventView
from app.schemas.syllabi import syllabus_title

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
    if body.lms_assignment_id is not None:
        target = await _assignment_target(repo, user.id, str(body.lms_assignment_id), now)
    elif body.syllabus_item_id is not None:
        target = await _syllabus_target(repo, user.id, str(body.syllabus_item_id), now)
    else:
        target = await _opportunity_target(repo, user.id, str(body.opportunity_id), now)
    existing = await repo.event_for(user.id, body.provider, **target.key())
    if existing is not None and existing.external_event_id:
        response.status_code = 200
        return existing
    token = await service.access_token(user.id, now)
    # 자리를 먼저 잡고 그 행의 id로 Google 일정 번호를 정한다(다시 눌러도 일정은 하나다).
    # 넣다 만 자리가 남아 있으면 그 자리를 제목·시각만 새로 맞춰 다시 쓴다
    event = await repo.reserve(
        user.id,
        provider=body.provider,
        title=target.title,
        starts_at=target.ends_at - timedelta(minutes=EVENT_MINUTES),
        **target.key(),
    )
    # Google을 부르기 전에 확정한다. 실패하면 요청 전체가 롤백돼 자리가 사라지고,
    # 다시 눌렀을 때 새 번호로 들어가 캘린더에 같은 마감이 두 개가 된다
    await repo.commit_reservation()
    external_id = await service.insert(
        token, event_id=event_id_for(event.id), title=target.title, ends_at=target.ends_at
    )
    await repo.attach(user.id, event.id, external_id)
    return event.model_copy(update={"external_event_id": external_id})


@dataclass(frozen=True)
class _Target:
    """캘린더에 넣을 대상 하나. 공고 마감이거나 LMS 과제 마감이다."""

    title: str
    ends_at: datetime
    opportunity_id: str | None = None
    lms_assignment_id: str | None = None
    syllabus_item_id: str | None = None

    def key(self) -> dict[str, str]:
        given = {
            "opportunity_id": self.opportunity_id,
            "lms_assignment_id": self.lms_assignment_id,
            "syllabus_item_id": self.syllabus_item_id,
        }
        found = {column: value for column, value in given.items() if value is not None}
        assert len(found) == 1
        return found


async def _opportunity_target(
    repo: CalendarRepository, user_id: str, opportunity_id: str, now: datetime
) -> _Target:
    """준비를 마친 공고의 마감(F-32). 아니면 422, 마감이 지났으면 409다."""
    opportunity = await repo.prepared_opportunity(user_id, opportunity_id)
    if opportunity is None:
        raise _invalid("준비 일정을 먼저 만들어 주세요.")
    if opportunity.deadline_at is None:
        raise _invalid("마감일이 없는 공고예요. 캘린더에 넣을 수 없어요.")
    ends_at = opportunity.deadline_at.astimezone(KST)
    if ends_at <= now:
        raise ApiError(409, "DEADLINE_PASSED", "마감이 지난 공고예요. 캘린더에 넣을 수 없어요.")
    return _Target(
        title=event_title(opportunity.title), ends_at=ends_at, opportunity_id=opportunity.id
    )


async def _assignment_target(
    repo: CalendarRepository, user_id: str, assignment_id: str, now: datetime
) -> _Target:
    """LMS 과제의 마감(F-51). 사라진 과제·수강 뺀 과목은 404다."""
    assignment = await repo.assignment_deadline(user_id, assignment_id)
    if assignment is None:
        raise ApiError(404, "NOT_FOUND", "과제를 찾을 수 없어요.")
    if assignment.due_at is None:
        raise _invalid("마감이 없는 과제예요. 캘린더에 넣을 수 없어요.", field="lms_assignment_id")
    ends_at = assignment.due_at.astimezone(KST)
    if ends_at <= now:
        raise ApiError(409, "DEADLINE_PASSED", "마감이 지난 과제예요. 캘린더에 넣을 수 없어요.")
    return _Target(
        title=assignment_title(assignment.course, assignment.title),
        ends_at=ends_at,
        lms_assignment_id=assignment.id,
    )


async def _syllabus_target(
    repo: CalendarRepository, user_id: str, item_id: str, now: datetime
) -> _Target:
    """확인한 계획서 일정(F-14). 확인 전 일정·남의 계획서는 404, 지난 일정은 409다."""
    item = await repo.syllabus_deadline(user_id, item_id)
    if item is None:
        raise ApiError(404, "NOT_FOUND", "계획서 일정을 찾을 수 없어요.")
    if item.starts_at is None:
        raise _invalid(
            "날짜가 없는 일정이에요. 날짜를 정한 뒤 넣어 주세요.", field="syllabus_item_id"
        )
    ends_at = item.starts_at.astimezone(KST) + timedelta(minutes=EVENT_MINUTES)
    if ends_at <= now:
        raise ApiError(409, "DEADLINE_PASSED", "이미 지난 일정이에요. 캘린더에 넣을 수 없어요.")
    return _Target(
        title=syllabus_title(item.item_type, item.course, item.title),
        ends_at=ends_at,
        syllabus_item_id=item.id,
    )


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


def _invalid(reason: str, *, field: str = "opportunity_id") -> ApiError:
    return ApiError(
        422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": {field: reason}}
    )
