"""흐름 실행기 (O5, 오케스트레이션 명세 3단계 4.2) — 흐름을 데이터(노드·가지)로 적고 위상 정렬(Kahn)로 돌린다.

    spec = FlowSpec(id="lms_announcement", entry="classify", nodes=(...), edges=(...))
    state = await run_flow(spec, refs)

- **노드마다 정확히 한 번, 들어오는 가지의 노드가 모두 끝난 뒤에 돈다** — 들어오는 가지 수(진입 차수)를 세다가 0이 되는
  순간 준비 줄에 한 번 들어간다. 부모가 여럿인 노드도 한 번이다(v1 4.1의 너비 우선은 부모마다 돌릴 수 있었다).
- **가지에는 조건(when)이 있다.** 들어오는 가지 중 참인 것이 없으면 그 노드는 건너뛰고, 건너뜀은 아래로 전해진다(나가는
  가지가 모두 거짓). 그래서 "끝" 노드를 따로 그리지 않아도 된다.
- **노드가 실패하면** on_fail이 stop이면 그 예외를 그대로 올리고(흐름을 부른 쪽이 처리한다), skip이면 건너뜀으로 친다.
- **map 노드**는 항목마다 each를 돌린다 — 동시에 concurrency개(세마포어), 결과는 항목 순서의 목록이다.
- **예산**(budget)이 바닥이면 미룰 수 있는 노드(deferrable — 모델·map)는 돌리지 않고 미룸으로 친다. 저장 노드는 늘 돈다.
- 흐름을 만들 때(check) 본다: 노드 이름이 겹치지 않고, 가지가 있는 노드를 가리키고, 들어오는 가지가 없는 노드는 entry
  하나뿐이고, entry에서 시작한 위상 정렬이 모든 노드를 꺼낸다(고리가 없다).

비용은 O(노드 + 가지) + 노드 시간이다. 지금 흐름은 노드 서너 개라 실행기 자체는 무시할 만하다.
"""

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)

Guard = Callable[[Any], bool]


def always(_result: Any) -> bool:
    return True


class _Mark:
    """노드가 돌지 않은 까닭(결과 자리에 둔다)."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return self.name


# 들어오는 가지가 모두 거짓이었거나, 실패를 넘기는 노드(on_fail=skip)가 실패했다
SKIPPED = _Mark("SKIPPED")
DEFERRED = _Mark("DEFERRED")  # 예산이 바닥나 미뤘다


@dataclass(frozen=True)
class Node:
    """흐름의 한 칸. run 노드는 상태를 받아 결과를 낸다. map 노드는 items가 낸 항목마다 each를 돌린다."""

    id: str
    run: Callable[["FlowState"], Awaitable[Any]] | None = None
    items: Callable[["FlowState"], Sequence[Any]] | None = None
    each: Callable[["FlowState", Any], Awaitable[Any]] | None = None
    concurrency: int = 1  # map 노드가 동시에 돌리는 항목 수
    on_fail: Literal["stop", "skip"] = "stop"
    deferrable: bool = False  # 예산이 바닥이면 미룰 수 있다(모델·map 노드). 저장 노드는 늘 돈다

    @property
    def is_map(self) -> bool:
        return self.items is not None


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    when: Guard = always  # 앞 노드의 결과만 본다
    label: str = ""  # 그림·시험에 쓰는 이름


class Budget(Protocol):
    def exhausted(self) -> bool: ...


@dataclass(frozen=True)
class FlowSpec:
    id: str
    entry: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...] = ()

    def __post_init__(self) -> None:
        self.check()

    def node(self, node_id: str) -> Node:
        return next(node for node in self.nodes if node.id == node_id)

    def check(self) -> None:
        """흐름이 맞게 그려졌는지 본다(틀리면 ValueError — 모듈을 읽을 때 터진다)."""
        names = [node.id for node in self.nodes]
        if len(set(names)) != len(names):
            raise ValueError(f"{self.id}: 노드 이름이 겹친다")
        if self.entry not in names:
            raise ValueError(f"{self.id}: entry {self.entry!r}가 노드에 없다")
        for edge in self.edges:
            if edge.src not in names or edge.dst not in names:
                raise ValueError(f"{self.id}: 없는 노드를 잇는 가지 {edge.src}→{edge.dst}")
        for node in self.nodes:
            if node.is_map == (node.run is not None) or node.is_map != (node.each is not None):
                raise ValueError(f"{self.id}: {node.id}는 run이나 items+each 하나만 가진다")
        heads = {node for node in names if all(edge.dst != node for edge in self.edges)}
        if heads != {self.entry}:
            raise ValueError(f"{self.id}: 들어오는 가지가 없는 노드는 entry 하나여야 한다: {heads}")
        if len(self.order()) != len(names):
            raise ValueError(f"{self.id}: 고리가 있다")

    def order(self) -> list[str]:
        """entry에서 시작한 위상 정렬(Kahn). 고리가 있으면 그 노드들이 빠진다."""
        remaining = {node.id: 0 for node in self.nodes}
        for edge in self.edges:
            remaining[edge.dst] += 1
        ready, seen = deque([self.entry]), []
        while ready:
            current = ready.popleft()
            seen.append(current)
            for edge in self.edges:
                if edge.src == current:
                    remaining[edge.dst] -= 1
                    if remaining[edge.dst] == 0:
                        ready.append(edge.dst)
        return seen


@dataclass
class FlowState:
    """흐름 한 번의 상태. results는 노드 이름 → 결과(건너뛰었으면 SKIPPED, 미뤘으면 DEFERRED)다."""

    refs: Any
    budget: Budget | None = None
    results: dict[str, Any] = field(default_factory=dict)
    trace: list[str] = field(default_factory=list)  # 돈 노드(차례대로)
    skipped: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)  # 실패를 넘긴 노드(on_fail=skip)

    def ran(self, node_id: str) -> bool:
        return node_id in self.trace


async def run_flow(spec: FlowSpec, refs: Any, *, budget: Budget | None = None) -> FlowState:
    """흐름을 한 번 돈다. on_fail=stop인 노드가 실패하면 그 예외를 그대로 올린다."""
    state = FlowState(refs=refs, budget=budget)
    remaining = {node.id: 0 for node in spec.nodes}
    true_in = dict(remaining)
    for edge in spec.edges:
        remaining[edge.dst] += 1
    ready = deque([spec.entry])
    while ready:
        node = spec.node(ready.popleft())
        outcome = await _step(spec, node, state, live=node.id == spec.entry or true_in[node.id] > 0)
        state.results[node.id] = outcome
        for edge in spec.edges:
            if edge.src != node.id:
                continue
            if outcome is not SKIPPED and outcome is not DEFERRED and edge.when(outcome):
                true_in[edge.dst] += 1
            remaining[edge.dst] -= 1
            if remaining[edge.dst] == 0:
                ready.append(edge.dst)
    return state


async def _step(spec: FlowSpec, node: Node, state: FlowState, *, live: bool) -> Any:
    if not live:  # 들어오는 가지가 모두 거짓
        state.skipped.append(node.id)
        return SKIPPED
    if node.deferrable and state.budget is not None and state.budget.exhausted():
        state.deferred.append(node.id)
        return DEFERRED
    try:
        if node.is_map:
            outcome = await _map(node, state)
        else:
            assert node.run is not None
            outcome = await node.run(state)
    except Exception as exc:
        if node.on_fail == "stop":
            raise
        logger.warning("흐름 %s의 %s가 실패해 건너뛰어요: %r", spec.id, node.id, exc)
        state.failed.append(node.id)
        state.skipped.append(node.id)
        return SKIPPED
    state.trace.append(node.id)
    return outcome


async def _map(node: Node, state: FlowState) -> list[Any]:
    """항목마다 each를 돌린다. 동시에 concurrency개이고, 결과는 항목 순서다. 하나가 터지면 나머지를 멈추고 올린다."""
    assert node.items is not None and node.each is not None
    each = node.each
    items = list(node.items(state))
    gate = asyncio.Semaphore(max(1, node.concurrency))

    async def one(item: Any) -> Any:
        async with gate:
            return await each(state, item)

    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(one(item)) for item in items]
    except ExceptionGroup as failed:  # 처음 터진 예외를 그대로 올린다(on_fail이 본다)
        raise failed.exceptions[0] from failed
    return [task.result() for task in tasks]
