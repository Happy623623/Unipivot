"""정기 작업 예약표 SQL (`job_schedule`, 오케스트레이션 2단계 2.8·3단계 4.5).

작업마다 한 줄이고 키는 다음 실행 시각이다 — 알림 큐·과목 공지 큐와 같은 "테이블 = 큐"를 타이머(최소 힙)로
쓴 것이다. 줄이 넷뿐이라 인덱스는 두지 않는다. **줄을 집는 것이 곧 임대다**(`claim`): 때가 됐고 아무도 돌리지
않는 줄만, 시도 횟수를 올리고 `lease_until`을 걸며 한 문장으로 집는다. 그래서 서버가 몇 대 떠도, 서버 안 tick과
바깥 크론을 같이 켜도 작업마다 한 번만 돈다. 남이 막 집은 줄은 그 트랜잭션이 끝날 때까지 기다렸다가 다시 보고
빠진다(조건부 갱신).

**이 파일의 조회에는 user_id 조건이 없다** — 사용자 데이터가 아니라 서버 작업의 시각표다.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from psycopg import AsyncConnection

# 없는 줄만 넣는다. 이미 있는 줄(다음 차례·횟수)은 건드리지 않는다
_ENSURE = (
    "insert into job_schedule (name, next_run_at)"
    " select * from unnest(%(names)s::text[], %(firsts)s::timestamptz[])"
    " on conflict (name) do nothing"
)
# 집기: 때가 됐고 아무도 돌리지 않는 줄만, 임대를 걸며 한 문장으로
_CLAIM = (
    "update job_schedule set lease_until = %(now)s + %(lease)s, attempts = attempts + 1"
    " where name = any(%(names)s::text[]) and next_run_at <= %(now)s"
    " and (lease_until is null or lease_until <= %(now)s)"
    " returning name, next_run_at"
)
# 끝: 다음 차례로 건너뛰고 임대·횟수를 비운다
_FINISH = (
    "update job_schedule set next_run_at = %(next)s, lease_until = null, attempts = 0,"
    " last_finished_at = %(now)s, last_error = null where name = %(name)s"
)
# 실패: first × 2^(횟수 − 1) 뒤로 늦추되 cap을 넘기지 않는다(횟수는 집을 때 이미 올렸다)
_FAIL = (
    "update job_schedule set next_run_at = least("
    "%(now)s + %(first)s * power(2, greatest(attempts, 1) - 1), %(cap)s),"
    " lease_until = null, last_error = %(error)s where name = %(name)s"
    " returning attempts, next_run_at"
)
# 서버를 끌 때 돌던 작업의 임대를 푼다 — 다음 서버가 바로 다시 집는다
_RELEASE = "update job_schedule set lease_until = null where name = %(name)s"


@dataclass(frozen=True)
class Failed:
    attempts: int  # 잇달아 집힌 횟수(이번 실패까지)
    next_run_at: datetime


class JobScheduleRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def ensure(self, firsts: dict[str, datetime]) -> None:
        """작업마다 줄이 없으면 넣는다(이름 → 처음 차례). 있는 줄은 그대로다."""
        if not firsts:
            return
        await self.conn.execute(_ENSURE, {"names": list(firsts), "firsts": list(firsts.values())})

    async def claim(self, names: list[str], *, now: datetime, lease: timedelta) -> list[str]:
        """때가 된 줄을 **집는다**. 집은 이름을 이른 차례부터 돌려준다.

        집은 줄은 그 자리에서 횟수가 오르고 `lease` 동안 다른 tick이 집지 못한다. 부르는 쪽은 이 문장만 담은
        트랜잭션을 바로 확정한다 — 그래야 임대가 다른 서버에 보인다. 돌다 서버가 죽으면 임대가 끝난 뒤 다시
        집히고, 그 시도도 한 번으로 센다.
        """
        if not names:
            return []
        rows = await self._rows(_CLAIM, {"names": names, "now": now, "lease": lease})
        # update … returning은 순서를 지키지 않는다
        rows.sort(key=lambda row: (row["next_run_at"], row["name"]))
        return [row["name"] for row in rows]

    async def finish(self, name: str, *, now: datetime, next_run_at: datetime) -> None:
        await self.conn.execute(_FINISH, {"name": name, "now": now, "next": next_run_at})

    async def fail(
        self, name: str, *, now: datetime, error: str, first: timedelta, cap: datetime
    ) -> Failed | None:
        """실패한 작업을 늦춘다: 다음 차례 = min(now + first × 2^(횟수 − 1), cap). 줄이 사라졌으면 None."""
        row = await self._row(
            _FAIL, {"name": name, "now": now, "error": error, "first": first, "cap": cap}
        )
        if row is None:
            return None
        return Failed(attempts=int(row["attempts"]), next_run_at=row["next_run_at"])

    async def release(self, name: str) -> None:
        await self.conn.execute(_RELEASE, {"name": name})

    async def _rows(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return await (await self.conn.execute(query, params)).fetchall()

    async def _row(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        return await (await self.conn.execute(query, params)).fetchone()
