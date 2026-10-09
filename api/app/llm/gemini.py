"""Gemini 플랫폼(구 Vertex AI) 클라이언트. google-genai SDK로 부르고 공통 타입으로 바꾼다.

인증은 Application Default Credentials다(로컬: gcloud auth application-default login).
location은 global로 둔다. 리전을 지정하면 단가가 10% 비싸다(LLM_모델_선정.md).
"""

import time
from collections.abc import Sequence
from typing import Any

from google import genai
from google.genai import types

from app.llm.types import (
    LlmReply,
    ModelTurn,
    ToolCall,
    ToolResultTurn,
    ToolSpec,
    Turn,
    Usage,
    UserTurn,
)

PROVIDER = "google"
_TIMEOUT_MS = 120_000
# 408·429·5xx는 SDK가 지수 대기 후 다시 보낸다(처음 요청 포함 3번)
_RETRY = types.HttpRetryOptions(attempts=3)


class GeminiClient:
    provider = PROVIDER

    def __init__(
        self, *, project: str, location: str = "global", client: genai.Client | None = None
    ) -> None:
        if client is None and not project:
            raise RuntimeError(
                "GOOGLE_CLOUD_PROJECT가 비어 있어요. api/.env에 프로젝트 ID를 넣어 주세요."
            )
        self._client = client or genai.Client(
            enterprise=True,
            project=project,
            location=location,
            http_options=types.HttpOptions(timeout=_TIMEOUT_MS, retry_options=_RETRY),
        )

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
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            tools=[types.Tool(function_declarations=[_declaration(spec) for spec in tools])]
            if tools
            else None,
            thinking_config=types.ThinkingConfig(thinking_level=thinking) if thinking else None,
            max_output_tokens=max_output_tokens,
            tool_config=_force(force_tool) if force_tool else None,
        )
        started = time.perf_counter()
        response = await self._client.aio.models.generate_content(
            model=model, contents=[_content(turn) for turn in turns], config=config
        )
        return _reply(response, int((time.perf_counter() - started) * 1000))


def _force(name: str) -> types.ToolConfig:
    return types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode=types.FunctionCallingConfigMode.ANY, allowed_function_names=[name]
        )
    )


def _declaration(spec: ToolSpec) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=spec.name, description=spec.description, parameters_json_schema=spec.parameters
    )


def _content(turn: Turn) -> types.Content:
    if isinstance(turn, UserTurn):
        parts = [types.Part.from_text(text=turn.text)]
        parts += [
            types.Part.from_bytes(data=blob.data, mime_type=blob.mime_type) for blob in turn.blobs
        ]
        return types.Content(role="user", parts=parts)
    if isinstance(turn, ToolResultTurn):
        # SDK의 자동 함수 호출과 같은 모양: 결과는 user 역할의 function_response로 돌려준다
        return types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=result.call.id, name=result.call.name, response=result.content
                    )
                )
                for result in turn.results
            ],
        )
    if isinstance(turn.raw, types.Content):
        return turn.raw  # 생각 서명(thought_signature)을 그대로 돌려줘야 도구 호출이 이어진다
    parts = [types.Part.from_text(text=turn.text)] if turn.text else []
    parts += [
        types.Part(function_call=types.FunctionCall(id=call.id, name=call.name, args=call.args))
        for call in turn.tool_calls
    ]
    return types.Content(role="model", parts=parts)


def _reply(response: types.GenerateContentResponse, latency_ms: int) -> LlmReply:
    candidate = response.candidates[0] if response.candidates else None
    content = candidate.content if candidate else None
    parts = (content.parts if content else None) or []
    text = "".join(part.text for part in parts if part.text and not part.thought) or None
    calls = tuple(
        ToolCall(
            name=part.function_call.name or "",
            args=dict(part.function_call.args or {}),
            id=part.function_call.id,
        )
        for part in parts
        if part.function_call
    )
    meta = response.usage_metadata
    usage = Usage(
        input_tokens=_count(meta, "prompt_token_count")
        + _count(meta, "tool_use_prompt_token_count"),
        output_tokens=_count(meta, "candidates_token_count") + _count(meta, "thoughts_token_count"),
    )
    finish = candidate.finish_reason if candidate else None
    if finish is None and response.prompt_feedback and response.prompt_feedback.block_reason:
        finish = response.prompt_feedback.block_reason
    return LlmReply(
        turn=ModelTurn(text=text, tool_calls=calls, raw=content),
        usage=usage,
        latency_ms=latency_ms,
        finish_reason=getattr(finish, "value", finish),
    )


def _count(meta: Any, name: str) -> int:
    return int(getattr(meta, name, None) or 0) if meta is not None else 0
