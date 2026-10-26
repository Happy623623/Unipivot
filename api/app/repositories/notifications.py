"""알림 예약·발송·알림함 SQL (F-33·F-35, API 명세 10장·12장, ERD v0.9 알림 중복 방지 표).

**예약**(하루 한 번): 공고에서 오는 알림 세 종류를 `(user_id, dedupe_key)`로 upsert한다. 사용자 ×
공고를 모두 보는 일이라 종류마다 한 문장(`insert … select`)으로 넣는다. 조건에서 빠진 pending 행은
지운다(준비 취소·숨김·마감 지남·이미 본 공고).

| 종류 | 키 | 누구에게 |
| --- | --- | --- |
| new_eligible | `new_eligible:opp:{id}` | 등록 7일 이내 + 적격 + 아직 상세를 열지 않음 |
| deadline_soon | `deadline_soon:opp:{id}:D-3`·`:D-1` | 적격이거나 준비한 공고. 마감일이 있어야 한다 |
| profile_needed | `profile_needed:opp:{id}` | 판정 불가 + 물어볼 항목이 있음 |

세 종류 모두 **숨긴 공고(관심 없음)와 설정에서 끈 종류는 만들지 않는다**(F-45, ERD). 알림 시각은
KST 09:00이고, **그 시점이 이미 지났으면 만들지 않는다** — 마감 이틀 전에 들어온 공고가 D-3·D-1을
한꺼번에 받으면 안 된다.

**발송**(5분마다): `scheduled_at`이 지난 pending 행을 닫는다. 보내기 전에 숨김을 다시 보고,
profile_needed는 사용자당 KST 하루 1건까지만 보낸다(ERD). 푸시 구독이 없거나 푸시를 끈 사용자는
푸시만 건너뛰고 행은 알림함에 남는다. 실제 푸시 발송은 F-33이다.

공고 공개 범위 조건은 `repositories/opportunities.py`의 VISIBLE과 같은 뜻이지만, 그 상수는 한 사용자
(`%(uid)s`)를 보는 문장용이라 여기서는 `p.id`로 다시 쓴다.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.db import get_conn
from app.eligibility import KST
from app.eligibility.catalog import INPUT_LABELS
from app.repositories.opportunities import Cursor, decode_cursor, encode_cursor
from app.schemas.notifications import (
    NotificationItem,
    NotificationLink,
    NotificationList,
    ScheduleResult,
    SendResult,
)

logger = logging.getLogger(__name__)
NOTIFY_HOUR = 9  # 알림을 보내는 시각(KST). 새벽에 깨우지 않는다
DEADLINE_DAYS = (3, 1)  # 마감 임박 알림을 보내는 날(D-3·D-1, PRD F-33)
NEW_DAYS = 7  # "새 공고"로 보는 등록 기간(ERD: 등록 7일 이내)
SEND_LIMIT = 500  # 한 번에 보내는 알림 수 상한
PROFILE_DAILY = 1  # profile_needed는 사용자당 KST 하루 이만큼만 보낸다(ERD)
LIST_LIMIT = 50

NEW_TITLE = "지원할 수 있는 공고가 있어요"
DEADLINE_TITLE = "마감이 가까워요"
PROFILE_TITLE = "프로필 정보가 필요해요"
ASSIGNMENT_TYPE = "new_assignment"  # notifications.type·user_settings.muted_notification_types
MATERIAL_TYPE = "new_material"  # 새 주차 항목(F-52). 과목 수강생 모두에게 간다
SCHEDULE_TYPE = "schedule_change"  # 일정 변경 공지(F-53 2부). 과목 수강생 모두에게 간다
_NEEDED = " 입력하면 판정할 수 있어요"

# 공고 하나를 사용자 한 명에게 보일지 보는 조건. opportunities.VISIBLE과 같은 뜻이다
_VISIBLE = (
    " (o.source_type <> 'poster' or o.uploaded_by = p.id)"
    " and (o.visible_canvas_course_id is null or lc.id is not null)"
)
_JOINS = (
    " from profiles p"
    " cross join opportunities o"
    " left join lms_courses lc on o.visible_canvas_course_id is not null"
    " and lc.user_id = p.id and lc.canvas_course_id = o.visible_canvas_course_id and lc.is_active"
    " left join opportunity_marks m on m.user_id = p.id and m.opportunity_id = o.id"
    " left join eligibility_results e on e.user_id = p.id and e.opportunity_id = o.id"
    " left join prep_plans pl on pl.user_id = p.id and pl.opportunity_id = o.id"
    " left join user_settings s on s.user_id = p.id"
)
# 설정 행이 없는 사용자는 기본값(끈 종류 없음)이다
_NOT_MUTED = " not (%(type)s = any(coalesce(s.muted_notification_types, '{}')))"
_NOT_DISMISSED = " (m.mark is null or m.mark <> 'not_interested')"
_ACTIVE = " o.status = 'active'"
_UNEXPIRED = " (o.deadline_at is null or o.deadline_at >= %(now)s)"
# KST 날짜에 알림 시각을 붙여 timestamptz로 만든다
_AT_HOUR = f"((%s)::date + time '{NOTIFY_HOUR:02d}:00') at time zone 'Asia/Seoul'"
_DEADLINE_DAY = "(o.deadline_at at time zone 'Asia/Seoul')::date - d.days"
_NEXT_DAY = "%(next_day)s"


def needed_phrases() -> dict[str, str]:
    """물어볼 항목 이름 + 목적격 조사. SQL에서 문구를 만들 수 있게 미리 붙여 둔다."""
    return {field: f"{label}{_particle(label)}" for field, label in INPUT_LABELS.items()}


def _particle(word: str) -> str:
    """목적격 조사: 받침이 있으면 "을", 없으면 "를"."""
    last = word[-1]
    if "가" <= last <= "힣":
        return "을" if (ord(last) - 0xAC00) % 28 else "를"
    return "을"


@dataclass(frozen=True)
class AssignmentNotice:
    """새 과제 알림 하나. 문구는 과목 이름을 아는 쪽(app/lms/sync.py)에서 만든다."""

    assignment_id: str
    title: str
    body: str


@dataclass(frozen=True)
class MaterialNotice:
    """새 주차 항목 알림 하나. 문구는 과목 이름을 아는 쪽(app/lms/sync.py)에서 만든다."""

    item_id: str
    title: str
    body: str


@dataclass(frozen=True)
class Sent:
    """발송 한 번의 결과와 **이번에 닫은 알림 번호**. 번호는 푸시 발송에만 쓴다(응답에는 없다)."""

    result: SendResult
    ids: list[str]


@dataclass(frozen=True)
class ScheduleNotice:
    """일정 변경 알림 하나(F-53 2부). 문구는 과목 이름을 아는 쪽에서 만든다."""

    announcement_id: str
    title: str
    body: str


@dataclass(frozen=True)
class Due:
    """보낼 알림 하나. dismissed는 그새 숨긴 공고다(보내지 않고 둔다)."""

    id: str
    user_id: str
    type: str
    dismissed: bool


class NotificationRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    # ── 예약 ────────────────────────────────────────────────────────────────

    async def schedule(self, *, now: datetime) -> ScheduleResult:
        """공고 알림 세 종류를 예약하고, 조건에서 빠진 pending 행을 지운다."""
        today = now.astimezone(KST).date()
        next_day = today if now.astimezone(KST).hour < NOTIFY_HOUR else today + timedelta(days=1)
        common = {"now": now, "next_day": next_day}
        result = ScheduleResult(created=0, rescheduled=0, removed=0, by_type={})
        for kind, query, params in (
            ("new_eligible", _NEW_ELIGIBLE, {}),
            ("deadline_soon", _DEADLINE_SOON, {"days": list(DEADLINE_DAYS)}),
            ("profile_needed", _PROFILE_NEEDED, {"needed": Jsonb(needed_phrases())}),
        ):
            rows = await self._rows(query, {**common, **params, "type": kind})
            created = sum(1 for row in rows if row["inserted"])
            result.created += created
            result.rescheduled += len(rows) - created
            result.by_type[kind] = len(rows)
        result.removed = await self._removed(now)
        return result

    async def _removed(self, now: datetime) -> int:
        """보낼 이유가 없어진 pending 행을 지운다. 보낸 행은 알림함에 남으므로 건드리지 않는다."""
        cursor = await self.conn.execute(_STALE, {"now": now, "types": list(_KINDS)})
        return cursor.rowcount

    # ── LMS 과제 알림 (F-51) ────────────────────────────────────────────────

    async def add_assignment_notices(
        self, user_id: str, notices: Sequence[AssignmentNotice], *, now: datetime
    ) -> int:
        """새 과제 알림을 만든다. 만든 수를 돌려준다.

        공고 알림과 달리 KST 09:00을 기다리지 않는다 — 과제는 마감이 코앞일 수 있어서 찾은 때
        바로 보낸다(명세 10장 예시의 `new_material`도 그 시각이다). 끈 종류는 만들지 않고(F-45),
        같은 과제의 알림은 `dedupe_key`로 한 번만 만든다.
        """
        created = 0
        for notice in notices:
            cursor = await self.conn.execute(
                "insert into notifications (user_id, type, lms_assignment_id, title, body,"
                " scheduled_at, dedupe_key)"
                " select %(uid)s, %(type)s, %(aid)s::uuid, %(title)s, %(body)s, %(now)s,"
                # 키 꼴은 ERD 5장 표 그대로다: new_assignment:asg:{lms_assignment_id}
                " %(type)s || ':asg:' || %(aid)s"
                " where not exists (select 1 from user_settings s where s.user_id = %(uid)s"
                "   and %(type)s = any(coalesce(s.muted_notification_types, '{}')))"
                " on conflict (user_id, dedupe_key) do nothing",
                {
                    "uid": user_id,
                    "type": ASSIGNMENT_TYPE,
                    "aid": notice.assignment_id,
                    "title": notice.title,
                    "body": notice.body,
                    "now": now,
                },
            )
            created += max(cursor.rowcount, 0)
        return created

    async def add_material_notices(
        self, canvas_course_id: int, notices: Sequence[MaterialNotice], *, now: datetime
    ) -> int:
        """새 주차 항목 알림을 **그 과목 수강생 모두에게** 만든다(ERD 3-2: 항목은 과목 공통이다).

        과제 알림과 달리 사용자를 받지 않는다 — 항목을 처음 본 쪽이 누구든 수강생 전체가 받는다.
        연결을 끊은 사람과 끈 종류는 만들지 않고, 같은 항목은 `dedupe_key`로 한 번만 만든다.
        """
        created = 0
        for notice in notices:
            cursor = await self.conn.execute(
                "insert into notifications (user_id, type, lms_module_item_id, title, body,"
                " scheduled_at, dedupe_key)"
                " select c.user_id, %(type)s, %(item)s::uuid, %(title)s, %(body)s, %(now)s,"
                # 키 꼴은 ERD 5장 표 그대로다: new_material:mod:{lms_module_item_id}
                " %(type)s || ':mod:' || %(item)s"
                " from lms_courses c"
                # 연결을 끊은 사람에게는 보내지 않는다(명세 9장: 해제하면 동기화를 멈춘다).
                # 해제하면 연결 행이 지워지므로 inner join이다
                " join lms_connections n on n.user_id = c.user_id and n.status <> 'disconnected'"
                " left join user_settings s on s.user_id = c.user_id"
                " where c.canvas_course_id = %(canvas)s and coalesce(c.is_active, true)"
                "   and not (%(type)s = any(coalesce(s.muted_notification_types, '{}')))"
                " on conflict (user_id, dedupe_key) do nothing",
                {
                    "canvas": canvas_course_id,
                    "type": MATERIAL_TYPE,
                    "item": notice.item_id,
                    "title": notice.title,
                    "body": notice.body,
                    "now": now,
                },
            )
            created += max(cursor.rowcount, 0)
        return created

    async def add_schedule_notices(
        self, canvas_course_id: int, notice: ScheduleNotice, *, now: datetime
    ) -> int:
        """일정 변경 알림을 **그 과목 수강생 모두에게** 만든다(F-53 2부, ERD 3-2).

        키 꼴은 ERD 5장 표 그대로다: `schedule_change:ann:{lms_announcement_id}`. 찾은 때 바로
        보낸다(새 과제 알림과 같다) — 휴강은 다음 아침에 알리면 늦는다.
        """
        cursor = await self.conn.execute(
            "insert into notifications (user_id, type, lms_announcement_id, title, body,"
            " scheduled_at, dedupe_key)"
            " select c.user_id, %(type)s, %(ann)s::uuid, %(title)s, %(body)s, %(now)s,"
            " %(type)s || ':ann:' || %(ann)s"
            " from lms_courses c"
            " join lms_connections n on n.user_id = c.user_id and n.status <> 'disconnected'"
            " left join user_settings s on s.user_id = c.user_id"
            " where c.canvas_course_id = %(canvas)s and coalesce(c.is_active, true)"
            "   and not (%(type)s = any(coalesce(s.muted_notification_types, '{}')))"
            " on conflict (user_id, dedupe_key) do nothing",
            {
                "canvas": canvas_course_id,
                "type": SCHEDULE_TYPE,
                "ann": notice.announcement_id,
                "title": notice.title,
                "body": notice.body,
                "now": now,
            },
        )
        return max(cursor.rowcount, 0)

    async def drop_assignment_notices(self, user_id: str, assignment_ids: Sequence[str]) -> int:
        """제출한 과제의 **아직 보내지 않은** 알림을 지운다(명세 10장). 보낸 알림은 알림함에 남는다."""
        if not assignment_ids:
            return 0
        cursor = await self.conn.execute(
            "delete from notifications where user_id = %(uid)s"
            " and lms_assignment_id = any(%(ids)s::uuid[])"
            " and status = 'pending' and sent_at is null",
            {"uid": user_id, "ids": list(assignment_ids)},
        )
        return max(cursor.rowcount, 0)

    # ── 발송 ────────────────────────────────────────────────────────────────

    async def due(self, *, now: datetime, limit: int = SEND_LIMIT) -> list[Due]:
        """보낼 때가 된 pending 알림. 오래된 것부터다."""
        rows = await self._rows(_DUE, {"now": now, "limit": limit})
        return [
            Due(
                id=str(row["id"]),
                user_id=str(row["user_id"]),
                type=row["type"],
                dismissed=row["dismissed"],
            )
            for row in rows
        ]

    async def sent_today(self, *, now: datetime, kind: str) -> dict[str, int]:
        """오늘(KST) 사용자별로 이미 보낸 그 종류의 알림 수. 하루 한도를 보는 데 쓴다."""
        rows = await self._rows(
            "select user_id::text as user_id, count(*) as count from notifications"
            " where type = %(type)s and sent_at is not null"
            " and (sent_at at time zone 'Asia/Seoul')::date = %(today)s group by 1",
            {"type": kind, "today": now.astimezone(KST).date()},
        )
        return {row["user_id"]: int(row["count"]) for row in rows}

    async def pushable(self, ids: Sequence[str]) -> int:
        """그중 푸시를 보낼 수 있는 알림 수(구독이 있고 푸시를 끄지 않았다). 실제 발송은 F-33."""
        if not ids:
            return 0
        row = await self._row(
            "select count(*) as count from notifications n"
            " left join user_settings s on s.user_id = n.user_id"
            " where n.id = any(%(ids)s::uuid[]) and coalesce(s.push_enabled, true)"
            " and exists (select 1 from push_subscriptions q where q.user_id = n.user_id)",
            {"ids": list(ids)},
        )
        return int(row["count"]) if row else 0

    async def mark_sent(self, ids: Sequence[str], *, now: datetime) -> list[str]:
        """보낸 알림을 닫고, **이번에 실제로 닫은** 번호를 돌려준다(넘긴 순서대로).

        푸시를 못 보내도 알림함에는 남아야 하므로 succeeded다(ERD). 다른 발송이 먼저 닫은 알림은
        빠진다 — 새 버전을 올리는 동안 인스턴스 둘이 겹치거나 스케줄러와 수동 호출이 겹쳐 같은 알림을
        함께 골라도, 행을 닫은 쪽만 푸시를 보낸다. 늦은 쪽의 UPDATE는 먼저 쪽이 끝날 때까지 기다렸다가
        `status = 'pending'`을 다시 보고 그 행을 건너뛴다.
        """
        if not ids:
            return []
        rows = await self._rows(
            "update notifications set status = 'succeeded', sent_at = %(now)s"
            " where id = any(%(ids)s::uuid[]) and status = 'pending' returning id",
            {"ids": list(ids), "now": now},
        )
        closed = {row["id"] for row in rows}  # UUID로 비교한다(넘긴 글자 모양·대소문자와 상관없이)
        return [item for item in ids if UUID(item) in closed]

    async def commit_sent(self) -> None:
        """닫은 알림을 먼저 확정한다. 푸시를 보내기 **전에** 부른다(app/jobs.py).

        확정하기 전에 푸시를 보내면, 그 뒤 이 발송이 롤백될 때(배포 중 옛 인스턴스가 꺼지며 작업이 취소됨,
        연결 끊김) 행이 pending으로 돌아가 다음 발송이 같은 푸시를 또 보낸다. 확정한 뒤에는 푸시가 실패하거나
        작업이 멈춰도 다시 보내지 않는다 — 같은 알림을 두 번 보내느니 푸시 한 번을 빠뜨리는 쪽을 택했다(명세 10장).
        늦은 발송이 푸시 시간 동안 행 잠금을 기다리지도 않는다.
        """
        await self.conn.commit()

    async def send(self, *, now: datetime, limit: int = SEND_LIMIT) -> Sent:
        """보낼 때가 된 알림을 닫는다. 숨긴 공고와 하루 한도를 넘는 알림은 보내지 않고 둔다.

        **푸시는 여기서 보내지 않는다.** 보낸 알림 번호를 함께 돌려주고, 부른 쪽(내부 작업)이
        푸시 발송기에 넘긴다 — DB 트랜잭션을 쥔 채로 바깥을 부르지 않는다.
        """
        # due()를 sent_today()보다 먼저 읽는다. 순서를 바꾸면 겹친 발송이 남이 막 닫은 정보 필요 알림을
        # 못 보고 같은 사용자의 다른 알림을 골라 하루 한도를 넘길 수 있다
        due = await self.due(now=now, limit=limit)
        already = await self.sent_today(now=now, kind="profile_needed")
        sending: list[str] = []
        for item in due:
            if item.dismissed:
                continue
            if item.type == "profile_needed":
                if already.get(item.user_id, 0) >= PROFILE_DAILY:
                    continue
                already[item.user_id] = already.get(item.user_id, 0) + 1
            sending.append(item.id)
        closed = await self.mark_sent(sending, now=now)
        return Sent(
            result=SendResult(
                due=len(due),
                sent=len(closed),
                pushable=await self.pushable(closed),
                skipped=len(due) - len(sending),
            ),
            ids=closed,
        )

    # ── 알림함 ──────────────────────────────────────────────────────────────

    async def unread(self, user_id: str, *, now: datetime) -> int:
        row = await self._row(
            "select count(*) as count from notifications where user_id = %(uid)s"
            " and read_at is null and scheduled_at <= %(now)s",
            {"uid": user_id, "now": now},
        )
        return int(row["count"]) if row else 0

    async def listing(
        self,
        user_id: str,
        *,
        now: datetime,
        unread_only: bool = False,
        limit: int = 20,
        cursor: str | None = None,
    ) -> NotificationList:
        """지난 알림을 최신순으로. 안 읽은 수는 필터와 상관없이 전체 기준이다."""
        scope = f"unread={unread_only}"
        after = ""
        params: dict[str, Any] = {"uid": user_id, "now": now, "limit": limit + 1}
        if cursor:
            found = decode_cursor(cursor)
            if found.scope != scope or found.value is None:
                raise ValueError("조건이 다른 목록의 cursor")
            after = " and (n.scheduled_at, n.id) < (%(at)s, %(id)s::uuid)"
            params |= {"at": found.value, "id": found.id}
        rows = await self._rows(
            _LIST.format(unread=" and n.read_at is null" if unread_only else "", after=after),
            params,
        )
        items = [_item(row) for row in rows[:limit]]
        last = rows[limit - 1] if len(rows) > limit else None
        return NotificationList(
            items=items,
            unread_count=await self.unread(user_id, now=now),
            next_cursor=encode_cursor(
                Cursor(scope=scope, value=last["scheduled_at"], id=str(last["id"]))
            )
            if last
            else None,
        )

    async def read(self, user_id: str, *, now: datetime, ids: Sequence[UUID] | None = None) -> int:
        """읽음 처리. ids가 없으면 전체다. 아직 보낼 때가 안 된 알림은 건드리지 않는다."""
        where = "" if ids is None else " and id = any(%(ids)s::uuid[])"
        await self.conn.execute(
            "update notifications set read_at = %(now)s where user_id = %(uid)s"
            " and read_at is null and scheduled_at <= %(now)s" + where,
            {"uid": user_id, "now": now, "ids": [str(item) for item in ids or ()]},
        )
        return await self.unread(user_id, now=now)

    # ── 조회 ────────────────────────────────────────────────────────────────

    async def _rows(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return await (await self.conn.execute(query, params)).fetchall()

    async def _row(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        return await (await self.conn.execute(query, params)).fetchone()


def _item(row: dict[str, Any]) -> NotificationItem:
    return NotificationItem(
        id=str(row["id"]),
        type=row["type"],
        title=row["title"],
        body=row["body"],
        scheduled_at=row["scheduled_at"].astimezone(KST),
        read_at=row["read_at"].astimezone(KST) if row["read_at"] else None,
        link=_link(row),
    )


def _link(row: dict[str, Any]) -> NotificationLink | None:
    """누르면 갈 곳. 대상 id가 하나도 없으면 링크가 없다(명세 10장)."""
    for kind, column in _LINKS:
        if row[column] is not None:
            return NotificationLink(
                type=kind,
                id=str(row[column]),
                course_id=str(row["course_id"]) if row["course_id"] else None,
                focus="profile_input" if row["type"] == "profile_needed" else None,
            )
    return None


_LINKS: tuple[tuple[str, str], ...] = (
    ("opportunity", "opportunity_id"),
    ("planner_task", "planner_task_id"),
    ("lms_assignment", "lms_assignment_id"),
    ("lms_module_item", "lms_module_item_id"),
    ("lms_announcement", "lms_announcement_id"),
)
_KINDS: tuple[str, ...] = ("new_eligible", "deadline_soon", "profile_needed")

# xmax = 0이면 이번에 넣은 행이다(고친 행은 그렇지 않다). 만든 수와 고친 수를 가른다
_INSERTED = " returning (xmax = 0) as inserted"
_COLUMNS = (
    "insert into notifications"
    " (user_id, type, opportunity_id, title, body, scheduled_at, dedupe_key)"
)

# 새 공고: 등록 7일 이내 + 적격 + 아직 상세를 열지 않음. 공고당 1회라 이미 있으면 그대로 둔다
_NEW_ELIGIBLE = (
    f"{_COLUMNS} select p.id, %(type)s, o.id, '{NEW_TITLE}', o.title,"
    f" {_AT_HOUR % _NEXT_DAY}, 'new_eligible:opp:' || o.id"
    f"{_JOINS} where{_ACTIVE} and{_UNEXPIRED} and{_NOT_DISMISSED} and{_VISIBLE} and{_NOT_MUTED}"
    " and e.status = 'eligible' and o.created_at >= %(now)s - make_interval(days => "
    f"{NEW_DAYS})"
    " and not exists (select 1 from opportunity_views v"
    " where v.user_id = p.id and v.opportunity_id = o.id)"
    f" and {_AT_HOUR % _NEXT_DAY} > %(now)s"
    " on conflict (user_id, dedupe_key) do nothing" + _INSERTED
)

# 마감 임박: 적격이거나 준비한 공고. 마감이 바뀌면 아직 보내지 않은 행의 시각만 고친다
_DEADLINE_SOON = (
    f"{_COLUMNS} select p.id, %(type)s, o.id, '{DEADLINE_TITLE}',"
    " o.title || ' · D-' || d.days,"
    f" {_AT_HOUR % _DEADLINE_DAY}, 'deadline_soon:opp:' || o.id || ':D-' || d.days"
    f"{_JOINS} cross join unnest(%(days)s::int[]) as d(days)"
    f" where{_ACTIVE} and{_UNEXPIRED} and{_NOT_DISMISSED} and{_VISIBLE} and{_NOT_MUTED}"
    " and o.deadline_at is not null and (e.status = 'eligible' or pl.id is not null)"
    f" and {_AT_HOUR % _DEADLINE_DAY} > %(now)s"
    " on conflict (user_id, dedupe_key) do update set scheduled_at = excluded.scheduled_at"
    " where notifications.status = 'pending'"
    " and notifications.scheduled_at <> excluded.scheduled_at" + _INSERTED
)

# 정보 필요: 판정 불가 + 물어볼 항목이 있음. 문구의 항목 이름은 조사까지 붙여 넘긴다
_PROFILE_NEEDED = (
    f"{_COLUMNS} select p.id, %(type)s, o.id, '{PROFILE_TITLE}',"
    f" o.title || ' · ' || (%(needed)s::jsonb ->> e.missing_fields[1]) || '{_NEEDED}',"
    f" {_AT_HOUR % _NEXT_DAY}, 'profile_needed:opp:' || o.id"
    f"{_JOINS} where{_ACTIVE} and{_UNEXPIRED} and{_NOT_DISMISSED} and{_VISIBLE} and{_NOT_MUTED}"
    " and e.status = 'undetermined' and coalesce(array_length(e.missing_fields, 1), 0) > 0"
    " and %(needed)s::jsonb ? e.missing_fields[1]"
    f" and {_AT_HOUR % _NEXT_DAY} > %(now)s"
    " on conflict (user_id, dedupe_key) do nothing" + _INSERTED
)

# 보낼 이유가 없어진 pending 행: 숨김·준비 취소·마감 지남·숨겨진 공고·이미 본 새 공고
_STALE = (
    # 지우는 대상(n)은 USING의 조인 조건에서 볼 수 없다. 그래서 과목 공개 범위는 exists로 본다
    "delete from notifications n using opportunities o"
    " where n.opportunity_id = o.id and n.status = 'pending' and n.type = any(%(types)s)"
    " and ("
    "   o.status <> 'active'"
    "   or (o.deadline_at is not null and o.deadline_at < %(now)s)"
    "   or exists (select 1 from opportunity_marks m where m.user_id = n.user_id"
    "              and m.opportunity_id = o.id and m.mark = 'not_interested')"
    "   or (o.source_type = 'poster' and o.uploaded_by is distinct from n.user_id)"
    "   or (o.visible_canvas_course_id is not null and not exists ("
    "        select 1 from lms_courses lc where lc.user_id = n.user_id"
    "        and lc.canvas_course_id = o.visible_canvas_course_id and lc.is_active))"
    "   or (n.type = 'deadline_soon' and not exists ("
    "        select 1 from eligibility_results e where e.user_id = n.user_id"
    "        and e.opportunity_id = o.id and e.status = 'eligible')"
    "      and not exists (select 1 from prep_plans pl where pl.user_id = n.user_id"
    "        and pl.opportunity_id = o.id))"
    "   or (n.type = 'new_eligible' and (exists ("
    "        select 1 from opportunity_views v where v.user_id = n.user_id"
    "        and v.opportunity_id = o.id)"
    # 판정이 바뀌어 적격이 아니게 되면 "지원할 수 있는 공고"가 아니다
    "      or not exists (select 1 from eligibility_results e where e.user_id = n.user_id"
    "        and e.opportunity_id = o.id and e.status = 'eligible')))"
    "   or (n.type = 'profile_needed' and not exists ("
    "        select 1 from eligibility_results e where e.user_id = n.user_id"
    "        and e.opportunity_id = o.id and e.status = 'undetermined'"
    "        and coalesce(array_length(e.missing_fields, 1), 0) > 0))"
    " )"
)


# 보낼 때가 된 알림. 숨긴 공고는 함께 알려 주고(보내지 않고 둔다) 오래된 것부터 본다
_DUE = (
    "select n.id, n.user_id, n.type, coalesce(m.mark = 'not_interested', false) as dismissed"
    " from notifications n"
    " left join opportunity_marks m"
    " on n.opportunity_id is not null and m.user_id = n.user_id"
    " and m.opportunity_id = n.opportunity_id"
    " where n.status = 'pending' and n.scheduled_at <= %(now)s"
    " order by n.scheduled_at, n.id limit %(limit)s"
)

_LIST = (
    "select n.id, n.type, n.title, n.body, n.scheduled_at, n.read_at, n.opportunity_id,"
    " n.planner_task_id, n.lms_assignment_id, n.lms_module_item_id, n.lms_announcement_id,"
    # lms_* 링크에는 과목 id를 함께 내려준다(명세 10장). 과제는 과목을 바로 가리키고,
    # 자료·공지는 Canvas 과목 번호라서 내 과목 행을 찾아야 한다
    " coalesce("
    "   (select a.lms_course_id from lms_assignments a where a.id = n.lms_assignment_id"
    "    and a.user_id = n.user_id),"
    "   (select lc.id from lms_module_items mi join lms_courses lc on lc.user_id = n.user_id"
    "    and lc.canvas_course_id = mi.canvas_course_id where mi.id = n.lms_module_item_id),"
    "   (select lc.id from lms_announcements an join lms_courses lc on lc.user_id = n.user_id"
    "    and lc.canvas_course_id = an.canvas_course_id where an.id = n.lms_announcement_id)"
    " ) as course_id"
    " from notifications n"
    " where n.user_id = %(uid)s and n.scheduled_at <= %(now)s{unread}{after}"
    " order by n.scheduled_at desc, n.id desc limit %(limit)s"
)


def get_notification_repo(
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> NotificationRepository:
    return NotificationRepository(conn)


NotificationRepoDep = Annotated[NotificationRepository, Depends(get_notification_repo)]
