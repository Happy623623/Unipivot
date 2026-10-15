"""시나리오 실행 결과 모양. CLI 출력과 베이스라인 JSON이 이 값을 쓴다(PRD 8장)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class Check:
    """시나리오가 확인한 것 하나. agent_runs 아래 tool_calls(check) 한 줄로도 남는다.

    kind는 집계가 골라 읽을 종류다(지금은 판정 확인뿐, app/schemas/metrics.py의 ELIGIBILITY_CHECK).
    """

    what: str
    expected: Any
    actual: Any
    kind: str | None = None

    @property
    def ok(self) -> bool:
        return self.actual == self.expected

    def json(self) -> dict[str, Any]:
        found = {"what": self.what, "expected": self.expected, "actual": self.actual, "ok": self.ok}
        return {**found, "kind": self.kind} if self.kind else found


class CheckFailed(AssertionError):
    """기대한 결과에 닿지 못했다. 시나리오는 여기서 멈추고 실패로 남는다."""

    def __init__(self, check: Check) -> None:
        super().__init__(f"{check.what}: 기대 {check.expected!r} · 실제 {check.actual!r}")
        self.check = check


@dataclass
class ScenarioResult:
    code: str
    title: str
    ok: bool
    latency_ms: int  # 시나리오가 끝까지 가는 데 걸린 시간(세계를 만드는 시간도 들어 있다)
    api_ms: float = 0.0  # 그중 엔드포인트가 쓴 시간 합(응답시간 지표)
    run_id: str | None = None  # 시나리오 실행(agent_runs, trigger eval)
    # 이 시나리오에 딸린 다른 실행(공고에 붙인 수집, 준비하기, 포스터 추출). 같은 번호가 붙어 있다
    child_run_ids: list[str] = field(default_factory=list)
    cost_usd: Decimal = Decimal(0)
    llm_calls: int = 0
    checks: list[Check] = field(default_factory=list)
    error: str | None = None  # 실패 이유 한 줄(기대와 다른 결과이거나 터진 예외)

    def json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "ok": self.ok,
            "latency_ms": self.latency_ms,
            "api_ms": self.api_ms,
            "run_id": self.run_id,
            "child_run_ids": self.child_run_ids,
            "cost_usd": float(self.cost_usd),
            "llm_calls": self.llm_calls,
            "checks": [check.json() for check in self.checks],
            "error": self.error,
        }


@dataclass
class Report:
    """한 번 돌린 결과 전체. W6 베이스라인으로 이 JSON을 고정 저장한다(PRD 8장)."""

    now: datetime  # 주입한 시계
    # 단가를 고른 날(app/pricing.py). 단가가 바뀌면 같은 now로 돌려도 비용이 달라진다
    priced_on: date | None = None  # noqa
    results: list[ScenarioResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.ok)

    @property
    def success_rate(self) -> float:
        """E2E 성공률. 0건이면 0.0이다."""
        return round(self.passed / self.total, 4) if self.total else 0.0

    @property
    def latencies(self) -> list[int]:
        return [result.latency_ms for result in self.results]

    @property
    def p50(self) -> int:
        return percentile(self.latencies, 50)

    @property
    def p95(self) -> int:
        return percentile(self.latencies, 95)

    @property
    def api_ms(self) -> float:
        return round(sum(result.api_ms for result in self.results), 1)

    @property
    def cost_usd(self) -> Decimal:
        return sum((result.cost_usd for result in self.results), Decimal(0))

    @property
    def llm_calls(self) -> int:
        return sum(result.llm_calls for result in self.results)

    def json(self) -> dict[str, Any]:
        return {
            "now": self.now.isoformat(),
            "priced_on": self.priced_on.isoformat() if self.priced_on else None,
            "scenarios": self.total,
            "passed": self.passed,
            "success_rate": self.success_rate,
            "latency_ms": {"p50": self.p50, "p95": self.p95},
            "api_ms": self.api_ms,
            "cost_usd": float(self.cost_usd),
            "llm_calls": self.llm_calls,
            "results": [result.json() for result in self.results],
        }


def percentile(values: Sequence[int], pct: float) -> int:
    """가장 가까운 순위(nearest-rank) 백분위수. 시나리오가 몇 개뿐이라 값을 섞지 않고 그중 하나를 고른다."""
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(math.ceil(pct / 100 * len(ordered)), 1)
    return ordered[rank - 1]


def plain(value: Any) -> Any:
    """JSON으로 남길 수 있는 값으로 바꾼다(tool_calls.output·베이스라인 JSON에 넣는다)."""
    if isinstance(value, BaseModel):
        return plain(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(plain(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
