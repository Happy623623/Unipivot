"""웹 푸시 구독 SQL (F-33, ERD 3-1). 구독 저장·해제와 발송 대상 찾기.

`endpoint`가 유일 키다(브라우저·기기마다 다른 주소를 준다). 같은 주소가 다시 오면 키만 갱신하고,
**다른 사용자가 같은 주소로 구독하면 주인이 바뀐다** — 한 브라우저를 두 사람이 번갈아 쓰는 경우다.
그 주소로 가는 푸시는 지금 로그인한 사람의 알림이어야 한다.

발송 대상(`targets`)은 **푸시를 끄지 않은 사용자**의 구독만 모은다(`user_settings.push_enabled`).
알림함 행은 푸시와 상관없이 쌓이므로(F-35) 여기서 빠져도 알림은 남는다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection

from app.db import get_conn
from app.push.payload import payload_for
from app.push.send import PushTarget, Subscription

_UPSERT = (
    "insert into push_subscriptions (user_id, endpoint, p256dh, auth, user_agent)"
    " values (%(uid)s, %(endpoint)s, %(p256dh)s, %(auth)s, %(agent)s)"
    " on conflict (endpoint) do update set user_id = excluded.user_id,"
    " p256dh = excluded.p256dh, auth = excluded.auth, user_agent = excluded.user_agent"
    " returning (xmax = 0) as inserted"
)
# 보낸 알림 + 그 사용자의 구독. 링크 칸은 알림함(_LIST)과 같은 규칙으로 풀어 준다
_TARGETS = (
    "select n.id, n.type, n.title, n.body, n.opportunity_id, n.planner_task_id,"
    " n.lms_assignment_id, n.lms_module_item_id, n.lms_announcement_id,"
    " coalesce("
    "   (select a.lms_course_id from lms_assignments a where a.id = n.lms_assignment_id"
    "    and a.user_id = n.user_id),"
    "   (select lc.id from lms_module_items mi join lms_courses lc on lc.user_id = n.user_id"
    "    and lc.canvas_course_id = mi.canvas_course_id where mi.id = n.lms_module_item_id),"
    "   (select lc.id from lms_announcements an join lms_courses lc on lc.user_id = n.user_id"
    "    and lc.canvas_course_id = an.canvas_course_id where an.id = n.lms_announcement_id)"
    " ) as course_id,"
    " q.id as subscription_id, q.endpoint, q.p256dh, q.auth"
    " from notifications n"
    " join push_subscriptions q on q.user_id = n.user_id"
    " left join user_settings s on s.user_id = n.user_id"
    " where n.id = any(%(ids)s::uuid[]) and coalesce(s.push_enabled, true)"
    " order by n.id, q.created_at, q.id"
)
_LINKS: tuple[tuple[str, str], ...] = (
    ("opportunity", "opportunity_id"),
    ("planner_task", "planner_task_id"),
    ("lms_assignment", "lms_assignment_id"),
    ("lms_module_item", "lms_module_item_id"),
    ("lms_announcement", "lms_announcement_id"),
)


@dataclass(frozen=True)
class SavedSubscription:
    id: str
    created: bool  # 처음 등록이면 True, 같은 주소를 갱신했으면 False


class PushRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def save(
        self, user_id: str, *, endpoint: str, p256dh: str, auth: str, user_agent: str | None
    ) -> bool:
        """구독을 저장한다. 처음 등록이면 True(같은 주소를 갱신했으면 False)."""
        row = await self._row(
            _UPSERT,
            {
                "uid": user_id,
                "endpoint": endpoint,
                "p256dh": p256dh,
                "auth": auth,
                "agent": user_agent,
            },
        )
        assert row is not None
        return bool(row["inserted"])

    async def remove(self, user_id: str, endpoint: str) -> int:
        """내 구독만 지운다. 남의 주소를 보내도 아무것도 지워지지 않는다(204는 그대로 준다)."""
        cursor = await self.conn.execute(
            "delete from push_subscriptions where user_id = %s and endpoint = %s",
            (user_id, endpoint),
        )
        return max(cursor.rowcount, 0)

    async def drop_endpoints(self, endpoints: Sequence[str]) -> int:
        """푸시 서비스가 "사라졌다"(404·410)고 한 구독을 지운다. 사용자를 가리지 않는다."""
        if not endpoints:
            return 0
        cursor = await self.conn.execute(
            "delete from push_subscriptions where endpoint = any(%s::text[])", (list(endpoints),)
        )
        return max(cursor.rowcount, 0)

    async def count(self, user_id: str) -> int:
        row = await self._row(
            "select count(*) as count from push_subscriptions where user_id = %s", (user_id,)
        )
        return int(row["count"]) if row else 0

    async def targets(self, notification_ids: Sequence[str]) -> list[PushTarget]:
        """그 알림들의 푸시 대상. 알림 하나에 구독이 여러 개면 한 묶음으로 모은다."""
        if not notification_ids:
            return []
        rows = await self._rows(_TARGETS, {"ids": list(notification_ids)})
        grouped: dict[str, tuple[dict[str, Any], list[Subscription]]] = {}
        for row in rows:
            key = str(row["id"])
            if key not in grouped:
                grouped[key] = (row, [])
            grouped[key][1].append(
                Subscription(
                    id=str(row["subscription_id"]),
                    endpoint=row["endpoint"],
                    p256dh=row["p256dh"],
                    auth=row["auth"],
                )
            )
        targets: list[PushTarget] = []
        for row, subscriptions in grouped.values():
            link_type, link_id = _link_of(row)
            targets.append(
                PushTarget(
                    payload=payload_for(
                        notification_id=str(row["id"]),
                        kind=row["type"],
                        title=row["title"],
                        body=row["body"],
                        link_type=link_type,
                        link_id=link_id,
                        course_id=str(row["course_id"]) if row["course_id"] else None,
                    ),
                    subscriptions=tuple(subscriptions),
                )
            )
        return targets

    async def _row(self, sql: str, params: Any) -> dict[str, Any] | None:
        return await (await self.conn.execute(sql, params)).fetchone()

    async def _rows(self, sql: str, params: Any) -> list[dict[str, Any]]:
        return await (await self.conn.execute(sql, params)).fetchall()


def _link_of(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """알림함(`notifications._link`)과 같은 순서로 대상을 고른다."""
    for kind, column in _LINKS:
        if row[column] is not None:
            return kind, str(row[column])
    return None, None


def get_push_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> PushRepository:
    return PushRepository(conn)


PushRepoDep = Annotated[PushRepository, Depends(get_push_repo)]
