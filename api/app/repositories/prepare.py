"""준비하기 SQL(F-30·F-31). 계획(prep_plans)·서류 안내(opportunity_documents)·할 일(planner_tasks).

계획 행은 준비하기를 누를 때(POST) 실행 id와 함께 먼저 만든다. (사용자, 공고) 유니크라 두 번 눌러도 하나다.
실행이 실패하면 계획을 지워 다시 누를 수 있게 한다. 실행이 성공해야 준비한 공고로 본다
(app/repositories/opportunities.py의 _PREP_DONE).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from psycopg import AsyncConnection

from app.prepare.documents import Guide
from app.prepare.guide import GuideDraft
from app.prepare.plan import TaskDraft

# 실행 중인 채로 이만큼 지난 계획은 멈춘 것(서버가 꺼짐 등)으로 보고 다시 만든다.
# 준비하기가 한 번에 쓸 수 있는 시간보다 길어야 한다(서류 안내 모델 호출 상한은
# app/prepare/guide.py의 TIMEOUT_SECONDS이고, test_prepare_rules가 이 관계를 지킨다)
STALE_AFTER_SECONDS = 300
STALE_AFTER = f"{STALE_AFTER_SECONDS} seconds"


@dataclass(frozen=True)
class PlanState:
    id: str
    run_id: str | None
    run_status: str | None  # 실행 기록이 지워졌으면 None
    stale: bool  # 실행 중으로 STALE_AFTER가 지났다

    @property
    def done(self) -> bool:
        """준비를 마쳤다(실행 성공, 또는 실행 기록이 없다)."""
        return self.run_id is None or self.run_status == "succeeded"

    @property
    def running(self) -> bool:
        return self.run_status == "running" and not self.stale


@dataclass(frozen=True)
class OpportunityText:
    title: str
    organizer: str | None
    source_type: str
    raw_text: str | None


@dataclass(frozen=True)
class DocumentRow:
    id: str
    name: str
    issuer: str | None
    lead_days: int | None

    @property
    def guided(self) -> bool:
        """안내를 한 번이라도 채웠다. 모델이 소요 일수를 숫자로 주지 않아도 다시 묻지 않는다."""
        return self.issuer is not None or self.lead_days is not None


class PrepareRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def plan(self, user_id: str, opportunity_id: str) -> PlanState | None:
        row = await (
            await self.conn.execute(
                "select p.id, p.agent_run_id, r.status::text as run_status,"
                " coalesce(r.status = 'running' and r.started_at < now() - %s::interval, false)"
                " as stale"
                " from prep_plans p left join agent_runs r on r.id = p.agent_run_id"
                " where p.user_id = %s and p.opportunity_id = %s",
                (STALE_AFTER, user_id, opportunity_id),
            )
        ).fetchone()
        if row is None:
            return None
        run_id = row["agent_run_id"]
        return PlanState(
            id=str(row["id"]),
            run_id=str(run_id) if run_id else None,
            run_status=row["run_status"],
            stale=row["stale"],
        )

    async def create_plan(self, user_id: str, opportunity_id: str, run_id: str) -> str | None:
        """계획 행. 그새 다른 요청이 만들었으면 None."""
        row = await (
            await self.conn.execute(
                "insert into prep_plans (user_id, opportunity_id, agent_run_id) values (%s, %s, %s)"
                " on conflict (user_id, opportunity_id) do nothing returning id",
                (user_id, opportunity_id, run_id),
            )
        ).fetchone()
        return str(row["id"]) if row else None

    async def lock_plan(self, plan_id: str) -> bool:
        """계획 행이 아직 있나(잠근다). 멈춘 실행으로 보고 지운 뒤면 False다."""
        row = await (
            await self.conn.execute(
                "select id from prep_plans where id = %s for update", (plan_id,)
            )
        ).fetchone()
        return row is not None

    async def drop_plan(self, plan_id: str) -> None:
        """계획과 그 할 일(on delete cascade)을 지운다."""
        await self.conn.execute("delete from prep_plans where id = %s", (plan_id,))

    async def opportunity(self, opportunity_id: str) -> OpportunityText | None:
        """공고 글. 잠그지 않는다(모델에 묻기 전에 읽는 쪽)."""
        return await self._opportunity(opportunity_id, lock=False)

    async def lock_opportunity(self, opportunity_id: str) -> OpportunityText | None:
        """공고 행을 잠근다. 같은 공고를 여럿이 함께 준비해도 서류는 한 번만 넣는다.

        모델 호출은 이 잠금 밖에서 한다(app/prepare/service.py). 잠근 뒤에는 서류를 다시 읽어
        그새 다른 학생이 넣거나 채운 값을 그대로 쓴다.
        """
        return await self._opportunity(opportunity_id, lock=True)

    async def _opportunity(self, opportunity_id: str, *, lock: bool) -> OpportunityText | None:
        row = await (
            await self.conn.execute(
                "select title, organizer, source_type::text as source_type, raw_text"
                " from opportunities where id = %s" + (" for no key update" if lock else ""),
                (opportunity_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return OpportunityText(row["title"], row["organizer"], row["source_type"], row["raw_text"])

    async def documents(self, opportunity_id: str) -> list[DocumentRow]:
        """공고 서류. 상세와 같은 순서(필수 먼저, 이름 순)다."""
        rows = await (
            await self.conn.execute(
                "select id, name, issuer, lead_days from opportunity_documents"
                " where opportunity_id = %s"
                " order by coalesce(is_required, true) desc, name, id",
                (opportunity_id,),
            )
        ).fetchall()
        return [
            DocumentRow(str(row["id"]), row["name"], row["issuer"], row["lead_days"])
            for row in rows
        ]

    async def add_documents(self, opportunity_id: str, drafts: Sequence[GuideDraft]) -> None:
        """청년정책의 제출 서류 글에서 만든 서류(안내 포함)."""
        for draft in drafts:
            await self.conn.execute(
                "insert into opportunity_documents (opportunity_id, name, issuer, how_to, lead_days,"
                " effort_minutes, is_required) values (%s, %s, %s, %s, %s, %s, %s)",
                (
                    opportunity_id,
                    draft.name,
                    draft.issuer,
                    draft.how_to,
                    draft.lead_days,
                    draft.effort_minutes,
                    draft.is_required,
                ),
            )

    async def save_guides(self, guides: Sequence[tuple[str, Guide]]) -> None:
        """서류 안내의 빈 칸만 채운다. 공고 서류라 다른 학생도 같은 안내를 본다(다시 묻지 않는다).

        모델 호출이 잠금 밖이라, 묻는 동안 다른 학생이 먼저 채웠을 수 있다. 그 값을 덮지 않는다.
        """
        for document_id, guide in guides:
            await self.conn.execute(
                "update opportunity_documents set issuer = coalesce(issuer, %s),"
                " how_to = coalesce(how_to, %s), lead_days = coalesce(lead_days, %s),"
                " effort_minutes = coalesce(effort_minutes, %s) where id = %s",
                (guide.issuer, guide.how_to, guide.lead_days, guide.effort_minutes, document_id),
            )

    async def add_tasks(self, user_id: str, plan_id: str, tasks: Sequence[TaskDraft]) -> None:
        for task in tasks:
            await self.conn.execute(
                "insert into planner_tasks (user_id, source, prep_plan_id, document_id, title,"
                " due_date, sort_order) values (%s, 'prep_plan', %s, %s, %s, %s, %s)",
                (user_id, plan_id, task.document_id, task.title, task.due_date, task.sort_order),
            )
