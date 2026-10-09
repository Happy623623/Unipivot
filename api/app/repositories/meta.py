"""departments 목록과 usage_events 기록 (ERD v0.9)."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from psycopg import AsyncConnection

from app.db import get_conn
from app.schemas.meta import Department


class MetaRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def list_departments(self) -> list[Department]:
        rows = await (
            await self.conn.execute(
                "select name, college, field_group from departments"
                " where is_active order by sort_order, name"
            )
        ).fetchall()
        return [Department.model_validate(row) for row in rows]

    async def department_exists(self, name: str) -> bool:
        row = await (
            await self.conn.execute(
                "select exists(select 1 from departments where name = %s and is_active) as ok",
                (name,),
            )
        ).fetchone()
        return bool(row and row["ok"])

    async def record_event(
        self, user_id: str, event: str, opportunity_id: UUID | None = None
    ) -> None:
        """사용 이벤트 1건. 앱 열기는 KST 하루 1건만 남는다(부분 유니크). 없는 공고 id는 비운다."""
        await self.conn.execute(
            "insert into usage_events (user_id, event, opportunity_id)"
            " select %(user_id)s::uuid, %(event)s,"
            " (select id from opportunities where id = %(opportunity_id)s::uuid)"
            " where exists (select 1 from profiles where id = %(user_id)s::uuid)"
            " on conflict do nothing",
            {"user_id": user_id, "event": event, "opportunity_id": opportunity_id},
        )


def get_meta_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> MetaRepository:
    return MetaRepository(conn)


MetaRepoDep = Annotated[MetaRepository, Depends(get_meta_repo)]
