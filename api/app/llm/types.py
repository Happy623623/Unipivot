"""공급사와 무관한 대화·도구 타입. 에이전트 코드는 이 타입만 쓰고, 공급사 변환은 클라이언트가 한다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSpec:
    """모델에 알려 줄 도구. parameters는 JSON Schema(object)다."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """모델이 부른 도구. id는 공급사가 주면 채운다(결과를 돌려줄 때 짝을 맞춘다)."""

    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class Blob:
    """이미지나 PDF처럼 모델에 그대로 보내는 파일."""

    data: bytes
    mime_type: str


@dataclass(frozen=True)
class UserTurn:
    text: str
    blobs: tuple[Blob, ...] = ()


@dataclass(frozen=True)
class ModelTurn:
    """모델의 답. raw는 공급사 원본이다(Gemini는 생각 서명이 있어서 다음 요청에 그대로 돌려줘야 한다)."""

    text: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    raw: Any = None


@dataclass(frozen=True)
class ToolResult:
    """도구 실행 결과. content는 {"output": …} 또는 {"error": …}다(Gemini 권장 키)."""

    call: ToolCall
    content: dict[str, Any]


@dataclass(frozen=True)
class ToolResultTurn:
    results: tuple[ToolResult, ...]


Turn = UserTurn | ModelTurn | ToolResultTurn


@dataclass(frozen=True)
class Usage:
    """비용 계산용 토큰. 입력은 도구 결과 토큰까지, 출력은 생각 토큰까지 더한 값이다."""

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class LlmReply:
    turn: ModelTurn
    usage: Usage
    latency_ms: int
    finish_reason: str | None = None


class LlmClient(Protocol):
    """공급사 클라이언트. provider는 단가표·llm_calls의 공급사 이름(anthropic, google)이다."""

    provider: str

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
        """force_tool을 주면 모델이 그 도구를 반드시 부른다(상한에 닿아 제출만 받을 때)."""
        ...
