"""준비하기 API 단위 테스트용 가짜 서비스·실행 저장소. 실제 실행·SQL은 test_prepare_db.py가 본다."""

import itertools
from datetime import date, datetime
from typing import Any

from app.prepare.service import Started
from app.repositories.prepare import PlanState
from app.repositories.runs import RunRow
from app.schemas.opportunities import OpportunityDetail, ProcessStep
from app.schemas.posters import PosterExtractResult
from app.schemas.prepare import PrepareResult

_ids = itertools.count(1)


def new_id() -> str:
    return f"00000000-0000-4000-8000-{next(_ids):012d}"


class FakePrepareService:
    def __init__(self) -> None:
        self.details: dict[str, OpportunityDetail] = {}  # 공고 id → 지금 판정한 상세. 없으면 404
        self.plans: dict[tuple[str, str], PlanState] = {}
        self.judge_calls: list[tuple[str, str, str | None]] = []
        self.resets: list[str] = []
        self.begins: list[tuple[str, str, date, date]] = []  # (user, 공고, 마감, 오늘)
        self.conflict: Started | None = None  # begin 사이에 다른 요청이 계획을 만든 경우

    async def judge(
        self, user_id: str, opportunity_id: str, *, now: datetime, display_name: str | None
    ) -> OpportunityDetail | None:
        self.judge_calls.append((user_id, opportunity_id, display_name))
        return self.details.get(opportunity_id)

    async def plan(self, user_id: str, opportunity_id: str) -> PlanState | None:
        return self.plans.get((user_id, opportunity_id))

    async def reset(self, plan: PlanState) -> None:
        self.resets.append(plan.id)
        self.plans = {key: value for key, value in self.plans.items() if value.id != plan.id}

    async def begin(
        self, user_id: str, opportunity_id: str, *, deadline: date, today: date
    ) -> Started:
        self.begins.append((user_id, opportunity_id, deadline, today))
        if self.conflict is not None:
            return self.conflict
        run_id = new_id()
        self.plans[(user_id, opportunity_id)] = PlanState(new_id(), run_id, "running", False)
        return Started(run_id, "running", created=True)


class FakeRunRepository:
    def __init__(self) -> None:
        self.runs: dict[str, RunRow] = {}
        self.steps_by_run: dict[str, list[ProcessStep]] = {}
        self.results: dict[str, PrepareResult] = {}
        self.poster_results: dict[str, PosterExtractResult] = {}
        self.result_calls: list[tuple[str, str]] = []

    async def run(self, run_id: str) -> RunRow | None:
        return self.runs.get(run_id)

    async def steps(self, run_id: str) -> list[ProcessStep]:
        return list(self.steps_by_run.get(run_id, []))

    async def prepare_result(self, user_id: str, run_id: str) -> PrepareResult | None:
        self.result_calls.append((user_id, run_id))
        return self.results.get(run_id)

    async def poster_result(self, user_id: str, run_id: str) -> PosterExtractResult | None:
        self.result_calls.append((user_id, run_id))
        return self.poster_results.get(run_id)


def run_row(**values: Any) -> RunRow:
    base: dict[str, Any] = {
        "id": new_id(),
        "user_id": None,
        "trigger_type": "prepare",
        "status": "running",
        "started_at": None,
        "finished_at": None,
        "latency_ms": None,
        "error_message": None,
    }
    return RunRow(**{**base, **values})
