"""에이전트 테스트용 가짜 LLM과 실행 로그. 실제 API 없이 루프·검증·기록을 확인한다."""

import itertools
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from app.llm import LlmReply, ModelTurn, ToolCall, ToolSpec, Turn, Usage, UserTurn

_ids = itertools.count(1)
DEFAULT_USAGE = Usage(1000, 200)


def call(name: str, **args: Any) -> ModelTurn:
    """도구 하나를 부르는 모델 답."""
    return ModelTurn(text=None, tool_calls=(ToolCall(name, args, id=f"call-{next(_ids)}"),))


def calls(*pairs: tuple[str, dict[str, Any]]) -> ModelTurn:
    """한 번에 여러 도구를 부르는 모델 답(병렬 호출)."""
    return ModelTurn(
        text=None,
        tool_calls=tuple(ToolCall(name, args, id=f"call-{next(_ids)}") for name, args in pairs),
    )


@dataclass
class Request:
    model: str
    system: str | None
    turns: list[Turn]
    tools: list[str]
    force_tool: str | None

    @property
    def blobs(self) -> list[Any]:
        return [blob for turn in self.turns if isinstance(turn, UserTurn) for blob in turn.blobs]


Reply = ModelTurn | str | Callable[[Request], ModelTurn | str]


class ScriptedLlm:
    """정해 둔 답을 차례로 돌려준다. 문자열은 글 답, 함수는 요청을 보고 답을 만든다."""

    provider = "google"

    def __init__(self, *replies: Reply, usage: Usage = DEFAULT_USAGE) -> None:
        self.replies = list(replies)
        self.usage = usage
        self.requests: list[Request] = []

    async def generate(
        self,
        *,
        model: str,
        system: str | None,
        turns: Sequence[Turn],
        tools: Sequence[ToolSpec] = (),
        thinking: str | None = None,
        max_output_tokens: int | None = None,
        force_tool: str | None = None,
    ) -> LlmReply:
        request = Request(model, system, list(turns), [tool.name for tool in tools], force_tool)
        self.requests.append(request)
        if not self.replies:
            raise AssertionError("준비한 답보다 모델을 더 많이 불렀다")
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(request)
        turn = ModelTurn(text=reply) if isinstance(reply, str) else reply
        return LlmReply(turn=turn, usage=self.usage, latency_ms=7, finish_reason="STOP")


@dataclass
class LoggedTool:
    name: str
    input: dict[str, Any] | None
    id: str
    output: Any = None


@dataclass
class MemoryRunLog:
    """app.agent_log.AgentRun의 대역. DB 대신 목록에 남긴다."""

    tools: list[LoggedTool] = field(default_factory=list)
    llm: list[dict[str, Any]] = field(default_factory=list)

    @asynccontextmanager
    async def tool(
        self, name: str, input: dict[str, Any] | None = None
    ) -> AsyncIterator[LoggedTool]:
        entry = LoggedTool(name, input, id=f"tool-{len(self.tools) + 1}")
        self.tools.append(entry)
        yield entry

    async def record_llm(self, *, tool_call: Any = None, **values: Any) -> None:
        self.llm.append({**values, "tool_call": tool_call.id if tool_call else None})
