"""마감일 캘린더 등록 (F-32·F-51, API 명세 7장)과 .ics 내려받기 (F-34).

대상은 공고 마감이나 LMS 과제 마감 하나다. 일정은 마감 시각으로 끝나는 1시간짜리이고, 일정 번호는
우리 행 id에서 만들어 보내므로 다시 눌러도 캘린더에 하나만 들어간다. .ics 내려받기는 같은 대상을
여럿 받아 파일 하나로 주고, 기록은 남기지 않는다.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Response

from app.auth import CurrentUserDep
from app.calendar import EVENT_MINUTES, assignment_title, event_id_for, event_title
from app.calendar.ics import IcsEvent, event_uid, render_calendar
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
NOTHING_TO_DOWNLOAD = "내려받을 일정이 없어요."
ICS_LIMIT = 200  # 한 번에 받는 대상 수 상한. 주소 길이와 조회 횟수를 묶어 둔다


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
    if body.provider != "google":  # .ics는 등록이 아니라 내려받기다(GET /calendar/ics)
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


@router.get("/ics")
async def download_ics(
    user: CurrentUserDep,
    repo: CalendarRepoDep,
    now: NowDep,
    opportunity_ids: str = "",
    lms_assignment_ids: str = "",
    syllabus_item_ids: str = "",
) -> Response:
    """고른 마감·일정을 .ics 파일 하나로 준다(F-34). Google 캘린더를 쓰지 않는 학생용이다.

    대상과 일정 모양은 `POST /calendar/events`와 같다. 넣을 수 없는 대상(준비하지 않은 공고,
    마감·날짜가 없는 것, 이미 지난 것, 남의 것·없는 것)은 건너뛰고, 하나도 남지 않으면 404다.
    `calendar_events`에는 기록하지 않는다(PRD F-34).
    """
    wanted = _ics_targets(opportunity_ids, lms_assignment_ids, syllabus_item_ids)
    events: list[IcsEvent] = []
    for kind, resolve, target_id in wanted:
        try:
            target = await resolve(repo, user.id, target_id, now)
        except ApiError as exc:
            if exc.status not in (404, 409, 422):
                raise
            continue  # 넣을 수 없는 대상은 건너뛴다
        events.append(
            IcsEvent(
                uid=event_uid(kind, target_id),
                title=target.title,
                starts_at=target.ends_at - timedelta(minutes=EVENT_MINUTES),
                ends_at=target.ends_at,
            )
        )
    if not events:
        raise ApiError(404, "NOT_FOUND", NOTHING_TO_DOWNLOAD)
    filename = f"unipivot-{now.astimezone(KST):%Y%m%d}.ics"
    return Response(
        render_calendar(events, now=now),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


_Resolve = Callable[[CalendarRepository, str, str, datetime], Awaitable[_Target]]
_ICS_KINDS: list[tuple[str, str, _Resolve]] = [
    ("opportunity_ids", "opportunity", _opportunity_target),
    ("lms_assignment_ids", "lms_assignment", _assignment_target),
    ("syllabus_item_ids", "syllabus_item", _syllabus_target),
]


def _ics_targets(*given: str) -> list[tuple[str, _Resolve, str]]:
    """쉼표로 나눈 uuid 목록 셋을 (종류, 조회 함수, id)로 편다. 같은 id는 한 번만 둔다.

    uuid가 아닌 값이 있으면 그 파라미터 이름으로 422, 합쳐서 하나도 없거나 상한을 넘어도 422다.
    """
    targets: list[tuple[str, _Resolve, str]] = []
    seen: set[str] = set()
    for (param, kind, resolve), raw in zip(_ICS_KINDS, given, strict=True):
        for value in raw.split(","):
            value = value.strip()
            if not value:
                continue
            try:
                target_id = str(UUID(value))
            except ValueError:
                raise _invalid("uuid가 아닌 값이 있어요.", field=param) from None
            if target_id not in seen:
                seen.add(target_id)
                targets.append((kind, resolve, target_id))
    if not targets:
        raise _invalid("공고·LMS 과제·계획서 일정 id를 하나 이상 주세요.", field="ids")
    if len(targets) > ICS_LIMIT:
        raise _invalid(f"한 번에 {ICS_LIMIT}개까지 받을 수 있어요.", field="ids")
    return targets
