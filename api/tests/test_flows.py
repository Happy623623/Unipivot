"""흐름 실행기(O5, app/engines/flows.py) — 위상 정렬로 노드마다 한 번, 조건 가지와 건너뜀, 실패 처리, map, 예산,
흐름 검사. 과목 공지 흐름이 그 모양인지도 본다. DB 없이 돈다."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import pytest

from app.eligibility import KST
from app.engines.flows import (
    DEFERRED,
    SKIPPED,
    Edge,
    FlowSpec,
    FlowState,
    Node,
    run_flow,
)
from app.lms import announce
from tests.llm_fakes import ScriptedLlm

pytestmark = pytest.mark.anyio


def step(name: str, calls: list[str], value: Any = None, fail: bool = False):
    async def run(state: FlowState) -> Any:
        calls.append(name)
        if fail:
            raise RuntimeError(f"{name} 실패")
        return name if value is None else value

    return run


def diamond(calls: list[str], **edges: Any) -> FlowSpec:
    """A → B, A → C, B → D, C → D. edges로 가지 조건을 바꾼다(예: ab=lambda r: False)."""
    return FlowSpec(
        id="diamond",
        entry="A",
        nodes=tuple(Node(name, run=step(name, calls)) for name in "ABCD"),
        edges=(
            Edge("A", "B", when=edges.get("ab", lambda _r: True)),
            Edge("A", "C", when=edges.get("ac", lambda _r: True)),
            Edge("B", "D", when=edges.get("bd", lambda _r: True)),
            Edge("C", "D", when=edges.get("cd", lambda _r: True)),
        ),
    )


async def test_a_node_with_many_parents_runs_once_after_all_of_them() -> None:
    calls: list[str] = []
    state = await run_flow(diamond(calls), refs=None)
    assert calls == ["A", "B", "C", "D"]  # D는 B·C가 모두 끝난 뒤 한 번
    assert state.trace == calls and state.results["D"] == "D"


async def test_a_false_branch_is_skipped_and_the_skip_flows_down() -> None:
    calls: list[str] = []
    state = await run_flow(diamond(calls, ab=lambda _r: False), refs=None)
    assert calls == ["A", "C", "D"]  # D는 C 쪽 가지가 참이라 돈다(들어오는 가지 중 하나만 참이어도)
    assert state.results["B"] is SKIPPED and state.skipped == ["B"]

    calls.clear()
    state = await run_flow(diamond(calls, ab=lambda _r: False, ac=lambda _r: False), refs=None)
    assert calls == ["A"]
    assert state.skipped == ["B", "C", "D"]  # 건너뜀이 아래로 전해진다


async def test_the_edge_condition_sees_the_result_of_its_source() -> None:
    calls: list[str] = []
    spec = FlowSpec(
        id="branch",
        entry="pick",
        nodes=(
            Node("pick", run=step("pick", calls, value="opportunity")),
            Node("extract", run=step("extract", calls)),
            Node("schedule", run=step("schedule", calls)),
        ),
        edges=(
            Edge("pick", "extract", when=lambda kind: kind == "opportunity"),
            Edge("pick", "schedule", when=lambda kind: kind == "schedule_change"),
        ),
    )
    state = await run_flow(spec, refs=None)
    assert calls == ["pick", "extract"] and state.results["schedule"] is SKIPPED


async def test_a_failing_node_stops_the_flow_or_is_skipped() -> None:
    calls: list[str] = []
    stop = FlowSpec(
        id="stop",
        entry="A",
        nodes=(Node("A", run=step("A", calls, fail=True)), Node("B", run=step("B", calls))),
        edges=(Edge("A", "B"),),
    )
    with pytest.raises(RuntimeError, match="A 실패"):
        await run_flow(stop, refs=None)
    assert calls == ["A"]

    calls.clear()
    skip = FlowSpec(
        id="skip",
        entry="A",
        nodes=(
            Node("A", run=step("A", calls)),
            Node("B", run=step("B", calls, fail=True), on_fail="skip"),
            Node("C", run=step("C", calls)),
            Node("D", run=step("D", calls)),
        ),
        edges=(Edge("A", "B"), Edge("A", "D"), Edge("B", "C")),
    )
    state = await run_flow(skip, refs=None)
    assert calls == ["A", "B", "D"]  # 실패한 B 아래(C)는 건너뛰고, 다른 가지(D)는 돈다
    assert (state.failed, state.skipped) == (["B"], ["B", "C"])


async def test_a_map_node_keeps_item_order_and_its_concurrency() -> None:
    running = peak = 0

    async def each(_state: FlowState, item: int) -> int:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01 * (5 - item))  # 앞 항목이 늦게 끝나도
        running -= 1
        return item * 10

    spec = FlowSpec(
        id="map",
        entry="each",
        nodes=(Node("each", items=lambda _state: [1, 2, 3, 4], each=each, concurrency=2),),
    )
    state = await run_flow(spec, refs=None)
    assert state.results["each"] == [10, 20, 30, 40]  # 결과는 항목 순서
    assert peak == 2


async def test_a_map_item_that_fails_raises_its_own_error() -> None:
    async def each(_state: FlowState, item: int) -> int:
        if item == 2:
            raise ValueError("두 번째 항목")
        return item

    spec = FlowSpec(
        id="map",
        entry="each",
        nodes=(Node("each", items=lambda _state: [1, 2, 3], each=each),),
    )
    with pytest.raises(ValueError, match="두 번째 항목"):  # 예외 묶음이 아니라 그 예외
        await run_flow(spec, refs=None)


async def test_an_empty_budget_defers_model_nodes_but_saves_still_run() -> None:
    class Empty:
        def exhausted(self) -> bool:
            return True

    calls: list[str] = []
    spec = FlowSpec(
        id="budget",
        entry="fetch",
        nodes=(
            Node("fetch", run=step("fetch", calls)),
            Node("model", run=step("model", calls), deferrable=True),
            Node("after_model", run=step("after_model", calls)),
            Node("save", run=step("save", calls)),
        ),
        edges=(Edge("fetch", "model"), Edge("model", "after_model"), Edge("fetch", "save")),
    )
    state = await run_flow(spec, refs=None, budget=Empty())
    assert calls == ["fetch", "save"]
    assert state.results["model"] is DEFERRED and state.deferred == ["model"]
    assert state.skipped == ["after_model"]  # 미룬 노드 아래는 건너뛴다


def test_a_badly_drawn_flow_is_refused() -> None:
    def node(name: str) -> Node:
        return Node(name, run=step(name, []))

    bad = [
        (dict(nodes=(node("A"), node("A"))), "겹친다"),
        (dict(nodes=(node("A"),), edges=(Edge("A", "Z"),)), "없는 노드"),
        (dict(nodes=(node("A"), node("B"))), "entry 하나"),  # 들어오는 가지가 없는 노드가 둘
        (
            dict(
                nodes=(node("A"), node("B"), node("C")),
                edges=(Edge("A", "B"), Edge("B", "C"), Edge("C", "B")),
            ),
            "고리",
        ),
        (dict(nodes=(Node("A"),)), "하나만"),  # run도 items도 없다
        (dict(nodes=(Node("A", run=step("A", []), items=lambda _s: []),)), "하나만"),  # 둘 다
    ]
    for values, problem in bad:
        with pytest.raises(ValueError, match=problem):
            FlowSpec(id="bad", entry="A", **values)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        FlowSpec(id="bad", entry="Z", nodes=(node("A"),))


def test_the_order_is_a_topological_sort_from_the_entry() -> None:
    assert diamond([]).order() == ["A", "B", "C", "D"]


def test_the_announcement_flows_have_the_shape_of_the_spec() -> None:
    """명세 3단계 4.2의 그림: 집기 → 공지마다(차례로) / 분류 → 갈래 적기 → 기회성이면 공고, 이미 분류했으면 공고만."""
    batch = announce.ANNOUNCEMENTS
    assert batch.order() == ["claim", "each"]
    assert batch.node("each").is_map and batch.node("each").concurrency == 1
    one = announce.ONE_ANNOUNCEMENT
    assert one.order() == ["classify", "record", "opportunity"]
    assert {(edge.src, edge.dst, edge.label) for edge in one.edges} == {
        ("classify", "record", "새로 분류함"),
        ("classify", "opportunity", "이미 기회성"),
        ("record", "opportunity", "기회성"),
    }
    classify_to_record, classify_to_opportunity, _ = one.edges
    assert classify_to_record.when(announce.ALREADY) is False
    assert classify_to_opportunity.when(announce.ALREADY) is True


async def test_the_announcement_service_with_nothing_to_claim_is_quiet() -> None:
    """집을 공지가 없으면 공지마다 노드는 건너뛰고 빈 결과다(동기화가 예외를 삼켜 빈 결과로 보이면 안 된다)."""

    class Repo:
        def __init__(self, _conn: Any) -> None:
            pass

        async def claim(self, **_options: Any) -> list[Any]:
            return []

    @asynccontextmanager
    async def transaction() -> Any:
        yield object()

    service = announce.AnnouncementService(
        transaction=transaction,
        llm=ScriptedLlm(),
        classify_model="gemini-3.5-flash-lite",
        agent_for=lambda _departments: None,  # type: ignore[arg-type,return-value]
        lms_base="https://lms.example",
        repo_for=Repo,  # type: ignore[arg-type]
    )
    outcome = await service.run(
        None,  # type: ignore[arg-type]
        now=datetime(2026, 11, 20, 12, 0, tzinfo=KST),
        courses={214023: "데이터베이스"},
    )
    assert outcome == announce.AnnouncementOutcome()
