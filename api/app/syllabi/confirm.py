"""계획서 일정 확정 (F-14, API 명세 8장 `POST /syllabi/{id}/confirm`).

학생이 확인 화면에서 고친 일정을 저장하고, **고른 것만** 플래너 할 일로 만든다. 캘린더까지
부탁하면(`register_calendar`) 그 일정도 Google에 넣는다.

두 번 눌러도 할 일·일정은 하나다 — 할 일은 `syllabus_item_id`로 찾아 고치고, 캘린더는 우리 행 id로
만든 번호를 쓴다(공고·과제 등록과 같은 방식). 뺀 일정의 **끝내지 않은** 할 일은 지우고, 캘린더에서는
빼지 않는다 — 학생 캘린더에서 지우는 일은 학생이 누를 때만 한다(`DELETE /calendar/events/{id}`).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.calendar import EVENT_MINUTES, event_id_for
from app.calendar.service import CalendarService
from app.eligibility import KST
from app.errors import ApiError
from app.repositories.calendar import CalendarRepository
from app.repositories.syllabi import StoredItem, SyllabusHead, SyllabusRepository
from app.schemas.calendar import CalendarEventView
from app.schemas.syllabi import SyllabusConfirmItem, SyllabusConfirmResult, syllabus_title

logger = logging.getLogger(__name__)
UNKNOWN_ITEM = "그 계획서에 없는 일정이에요. 화면을 새로 고치고 다시 해 주세요."
NO_DATE = "날짜가 없는 일정은 고를 수 없어요. 날짜를 적거나 선택을 풀어 주세요."
TWICE = "같은 일정이 두 번 들어 있어요. 화면을 새로 고치고 다시 해 주세요."


@dataclass(frozen=True)
class Plan:
    """확정할 일정 하나. 저장소가 돌려준 행과 학생이 고친 값을 함께 든다."""

    item: StoredItem
    selected: bool


def planned(
    stored: list[StoredItem], asked: list[SyllabusConfirmItem]
) -> tuple[list[Plan], dict[str, StoredItem]]:
    """보내온 일정을 저장해 둔 행과 맞춘다. 모르는 id가 있으면 422다."""
    rows = {one.id: one for one in stored}
    unknown = [str(one.id) for one in asked if str(one.id) not in rows]
    if unknown:
        raise ApiError(422, "VALIDATION_FAILED", UNKNOWN_ITEM, {"fields": {"items": UNKNOWN_ITEM}})
    sent = [str(one.id) for one in asked]
    if len(set(sent)) != len(sent):
        # 같은 일정을 두 번 보내면 뒤 값이 앞 값을 덮어쓰고 센 수도 맞지 않는다(고른 수가 부풀고,
        # true → false 순이면 확정은 풀렸는데 캘린더에는 들어간다). 받지 않는 쪽이 분명하다
        raise ApiError(422, "VALIDATION_FAILED", TWICE, {"fields": {"items": TWICE}})
    plans: list[Plan] = []
    for one in asked:
        row = rows[str(one.id)]
        # 학생이 고친 제목·시각을 쓴다(시각을 비워 보내면 저장해 둔 값을 그대로 둔다)
        fixed = StoredItem(
            id=row.id,
            item_type=row.item_type,
            title=one.title.strip(),
            starts_at=(one.starts_at or row.starts_at),
            is_confirmed=one.selected,
        )
        if one.selected and fixed.starts_at is None:
            raise ApiError(422, "VALIDATION_FAILED", NO_DATE, {"fields": {"items": NO_DATE}})
        plans.append(Plan(fixed, one.selected))
    return plans, rows


async def confirm(
    repo: SyllabusRepository,
    *,
    user_id: str,
    head: SyllabusHead,
    plans: list[Plan],
) -> tuple[int, int]:
    """일정을 저장하고 플래너 할 일을 맞춘다. (확정한 수, 새로 만든 할 일 수)."""
    confirmed = made = 0
    for plan in plans:
        item = plan.item
        await repo.confirm_item(
            user_id,
            item.id,
            syllabus_id=head.id,
            title=item.title,
            starts_at=item.starts_at,
            selected=plan.selected,
        )
        if await repo.sync_task(user_id, item, selected=plan.selected, course_id=head.course_id):
            made += 1
        confirmed += 1 if plan.selected else 0
    return confirmed, made


async def register(
    calendar: CalendarRepository,
    service: CalendarService,
    *,
    user_id: str,
    head: SyllabusHead,
    plans: list[Plan],
    provider: str,
    now: datetime,
    token: str,
) -> tuple[int, int]:
    """고른 일정을 Google 캘린더에 넣는다. (새로 넣은 수, 시각·제목을 고친 수).

    토큰은 부른 쪽이 **한 번** 꺼내 넘긴다(일정마다 꺼내면 만료 갱신이 여러 번 돈다).
    지난 일정은 건너뛴다. 이미 넣어 둔 일정은 **시각·제목이 달라졌을 때만** 고친다.

    한 건이 Google에서 막히면(502) 그 건만 넘어가고 나머지를 계속한다 — 확정은 이미 끝났다.
    다만 **권한이 끊긴 것**(409)은 남은 건도 다 막히므로 그대로 올려 보내 다시 연결하게 한다.
    """
    chosen = [plan for plan in plans if plan.selected and plan.item.starts_at is not None]
    made = moved = 0
    for plan in chosen:
        item = plan.item
        assert item.starts_at is not None
        starts_at = item.starts_at.astimezone(KST)
        ends_at = starts_at + timedelta(minutes=EVENT_MINUTES)
        if ends_at <= now:  # 이미 지난 일정은 넣지 않는다
            continue
        title = syllabus_title(item.item_type, head.short_name, item.title)
        existing = await calendar.event_for(user_id, provider, syllabus_item_id=item.id)
        try:
            if existing is not None and existing.external_event_id:
                moved += await _fix(
                    calendar,
                    service,
                    user_id=user_id,
                    existing=existing,
                    title=title,
                    starts_at=starts_at,
                    token=token,
                )
                continue
            event = await calendar.reserve(
                user_id,
                provider=provider,
                title=title,
                starts_at=starts_at,
                syllabus_item_id=item.id,
            )
            # 라우터와 같이 Google을 부르기 **전에** 자리를 확정한다. 그러지 않으면 뒤에서 예외가 날 때
            # 요청이 통째로 롤백돼 자리가 사라지고, 다시 누르면 새 번호로 들어가 일정이 두 개가 된다
            await calendar.commit_reservation()
            external = await service.insert(
                token, event_id=event_id_for(event.id), title=title, ends_at=ends_at
            )
            await calendar.attach(user_id, event.id, external)
            made += 1
        except ApiError as exc:
            if exc.code == "CALENDAR_NOT_CONNECTED":
                raise  # 권한이 끊겼다. 다시 연결하면 같은 자리로 이어 넣는다
            logger.warning("계획서 일정을 캘린더에 넣지 못했어요: item %s, %s", item.id, exc.code)
    return made, moved


async def _fix(
    calendar: CalendarRepository,
    service: CalendarService,
    *,
    user_id: str,
    existing: CalendarEventView,
    title: str,
    starts_at: datetime,
    token: str,
) -> int:
    """이미 넣어 둔 일정의 시각·제목을 맞춘다. 고쳤으면 1이다.

    학생이 확인 화면에서 시험 시각을 고쳐 다시 확정하면 플래너만 움직이고 캘린더가 옛 시각에
    남는 일을 막는다. 학생이 Google에서 그 일정을 지웠으면(404·410) 되살리지 않는다.
    """
    if existing.title == title and existing.starts_at == starts_at:
        return 0  # 달라진 것이 없다
    assert existing.external_event_id is not None
    found = await service.move(
        token,
        event_id=existing.external_event_id,
        title=title,
        ends_at=starts_at + timedelta(minutes=EVENT_MINUTES),
    )
    if found is None:  # 학생이 캘린더에서 지웠다. 되살리지 않는다
        return 0
    await calendar.move(user_id, existing.id, starts_at=starts_at, title=title)
    return 1


def result(confirmed: int, tasks: int, events: tuple[int, int]) -> SyllabusConfirmResult:
    made, moved = events
    return SyllabusConfirmResult(
        confirmed=confirmed,
        planner_tasks_created=tasks,
        calendar_events_created=made,
        calendar_events_moved=moved,
    )
