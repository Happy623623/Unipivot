"""Gemini 클라이언트: 네트워크 없이 요청 모양과 응답 변환을 본다 (HTTP는 respx로 가로챈다)."""

import json
from typing import Any

import google.auth
import httpx
import pytest
import respx
from google.oauth2.credentials import Credentials

from app.config import Settings
from app.extraction import AttachmentInput, ExtractionAgent, NoticeInput
from app.extraction.setup import build_agent
from app.llm import Blob, ToolCall, ToolResult, ToolResultTurn, ToolSpec, Usage, UserTurn
from app.llm.gemini import GeminiClient
from tests import samples
from tests.llm_fakes import MemoryRunLog
from tests.samples import hp

pytestmark = pytest.mark.anyio

URL = (
    "https://aiplatform.googleapis.com/v1beta1/projects/demo-project/locations/global/"
    "publishers/google/models/gemini-3.8-flash:generateContent"
)
TOOL = ToolSpec(
    name="read_attachment_text",
    description="첨부 읽기",
    parameters={
        "type": "object",
        "properties": {"attachment_no": {"type": "integer"}},
        "required": ["attachment_no"],
    },
)


@pytest.fixture(autouse=True)
def adc(monkeypatch: pytest.MonkeyPatch) -> None:
    """gcloud 로그인 대신 가짜 토큰을 쓰고, 개발 PC의 환경변수가 끼어들지 않게 한다."""
    monkeypatch.setattr(
        google.auth,
        "default",
        lambda scopes=None, **_: (Credentials(token="fake-token"), "adc-project"),
    )
    for name in (
        "GOOGLE_GENAI_USE_ENTERPRISE",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
    ):
        monkeypatch.delenv(name, raising=False)


def _response(parts: list[dict[str, Any]], usage: dict[str, int]) -> dict[str, Any]:
    return {
        "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}],
        "usageMetadata": usage,
    }


async def test_tool_call_round_trip_keeps_thought_signature() -> None:
    first = _response(
        [
            {
                "functionCall": {
                    "id": "call-1",
                    "name": "read_attachment_text",
                    "args": {"attachment_no": 1},
                },
                "thoughtSignature": "c2lnLTE=",
            }
        ],
        {"promptTokenCount": 1200, "candidatesTokenCount": 20, "thoughtsTokenCount": 300},
    )
    second = _response(
        [{"text": "끝"}],
        {"promptTokenCount": 2000, "toolUsePromptTokenCount": 50, "candidatesTokenCount": 5},
    )
    client = GeminiClient(project="demo-project")
    with respx.mock(assert_all_called=True) as router:
        route = router.post(URL).mock(
            side_effect=[httpx.Response(200, json=first), httpx.Response(200, json=second)]
        )
        turns: list[Any] = [
            UserTurn("공고를 읽어 줘", blobs=(Blob(b"%PDF-1.7", "application/pdf"),))
        ]
        reply = await client.generate(
            model="gemini-3.8-flash",
            system="너는 추출기다",
            turns=turns,
            tools=[TOOL],
            thinking="low",
        )
        call = ToolCall(name="read_attachment_text", args={"attachment_no": 1}, id="call-1")
        assert reply.turn.tool_calls == (call,)
        assert reply.usage == Usage(input_tokens=1200, output_tokens=320)  # 생각 토큰도 출력
        assert reply.finish_reason == "STOP"

        turns += [reply.turn, ToolResultTurn((ToolResult(call, {"result": "장학 안내"}),))]
        reply = await client.generate(
            model="gemini-3.8-flash",
            system="너는 추출기다",
            turns=turns,
            tools=[TOOL],
            thinking="low",
        )
        assert reply.turn.text == "끝"
        assert reply.usage == Usage(input_tokens=2050, output_tokens=5)  # 도구 결과 토큰도 입력

    sent = json.loads(route.calls[0].request.content)
    assert route.calls[0].request.headers["authorization"] == "Bearer fake-token"
    assert sent["systemInstruction"]["parts"] == [{"text": "너는 추출기다"}]
    assert sent["generationConfig"]["thinkingConfig"] in (
        {"thinkingLevel": "LOW"},
        {"thinking_level": "LOW"},
    )
    declaration = sent["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "read_attachment_text"
    assert TOOL.parameters in declaration.values()
    assert sent["contents"][0]["parts"][1]["inlineData"]["data"] == "JVBERi0xLjc="  # %PDF-1.7

    history = json.loads(route.calls[1].request.content)["contents"]
    assert [turn["role"] for turn in history] == ["user", "model", "user"]
    assert history[1]["parts"][0]["thoughtSignature"] == "c2lnLTE="  # 서명을 그대로 돌려준다
    response_part = history[2]["parts"][0]["functionResponse"]
    assert response_part == {
        "id": "call-1",
        "name": "read_attachment_text",
        "response": {"result": "장학 안내"},
    }


async def test_blocked_prompt_has_no_turn_content() -> None:
    blocked = {
        "promptFeedback": {"blockReason": "SAFETY"},
        "usageMetadata": {"promptTokenCount": 10},
    }
    client = GeminiClient(project="demo-project")
    with respx.mock() as router:
        router.post(URL).mock(return_value=httpx.Response(200, json=blocked))
        reply = await client.generate(model="gemini-3.8-flash", system=None, turns=[UserTurn("x")])
    assert (reply.turn.text, reply.turn.tool_calls, reply.finish_reason) == (None, (), "SAFETY")
    assert reply.usage == Usage(input_tokens=10, output_tokens=0)


def test_project_is_required() -> None:
    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
        GeminiClient(project="")


async def test_force_tool_sends_any_mode() -> None:
    reply = _response(
        [{"functionCall": {"name": "read_attachment_text", "args": {"attachment_no": 2}}}],
        {"promptTokenCount": 10, "candidatesTokenCount": 3},
    )
    client = GeminiClient(project="demo-project")
    with respx.mock() as router:
        route = router.post(URL).mock(return_value=httpx.Response(200, json=reply))
        result = await client.generate(
            model="gemini-3.8-flash",
            system=None,
            turns=[UserTurn("x")],
            tools=[TOOL],
            force_tool="read_attachment_text",
        )
    assert result.turn.tool_calls[0].id is None  # Vertex가 id를 안 주면 None
    config = json.loads(route.calls[0].request.content)["toolConfig"]["functionCallingConfig"]
    # SDK가 Vertex에는 snake_case로 보낸다. 서버(proto JSON)는 두 표기를 모두 받는다
    names = config.get("allowedFunctionNames", config.get("allowed_function_names"))
    assert (config["mode"], names) == ("ANY", ["read_attachment_text"])


def test_build_agent_reads_settings() -> None:
    settings = Settings(
        google_cloud_project="demo-project",
        extraction_model="gemini-3.5-flash-lite",
        extraction_max_reads=2,
    )
    agent = build_agent(settings)
    assert (agent.model, agent.vision_model, agent.llm.provider) == (
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
        "google",
    )
    assert (agent.limits.max_reads, agent.limits.max_tokens) == (2, 150_000)


async def test_agent_conversation_goes_through_the_sdk() -> None:
    """에이전트 대화가 실제 SDK 직렬화를 거쳐도 도구 정의·결과·생각 서명이 맞게 나간다."""
    guide = samples.hwpx(hp("직전 학기 평점평균 3.0 이상"))
    notice = NoticeInput(
        title="장학", body="첨부 참조", attachments=(AttachmentInput(1, "요강.hwpx", guide),)
    )
    read = _response(
        [
            {
                "functionCall": {
                    "id": "c1",
                    "name": "read_attachment_text",
                    "args": {"attachment_no": 1, "reason": "요강 확인"},
                },
                "thoughtSignature": "c2lnLTE=",
            }
        ],
        {"promptTokenCount": 3000, "candidatesTokenCount": 40, "thoughtsTokenCount": 100},
    )
    submit_args = {
        "requirements": [
            {
                "clause_no": 1,
                "field": "gpa_last_semester",
                "operator": "gte",
                "value_json": "3.0",
                "evidence_text": "직전 학기 평점평균 3.0 이상",
                "is_ambiguous": False,
            }
        ],
        "documents": [],
        "confidence": 0.9,
        "needs_review": False,
    }
    submit = _response(
        [{"functionCall": {"id": "c2", "name": "submit_requirements", "args": submit_args}}],
        {"promptTokenCount": 3300, "candidatesTokenCount": 120},
    )
    agent = ExtractionAgent(GeminiClient(project="demo-project"), model="gemini-3.8-flash")
    log = MemoryRunLog()
    with respx.mock() as router:
        route = router.post(URL).mock(
            side_effect=[httpx.Response(200, json=read), httpx.Response(200, json=submit)]
        )
        result = await agent.run(notice, log)

    assert result.succeeded and result.requirements[0].value == 3.0
    assert [entry["input_tokens"] for entry in log.llm] == [3000, 3300]
    first = json.loads(route.calls[0].request.content)
    declarations = first["tools"][0]["functionDeclarations"]
    assert [d["name"] for d in declarations] == [
        "read_attachment_text",
        "read_attachment_image",
        "fetch_original",
        "submit_requirements",
    ]
    schema = declarations[3].get(
        "parametersJsonSchema", declarations[3].get("parameters_json_schema")
    )
    assert (
        schema["properties"]["requirements"]["items"]["properties"]["field"]["enum"][0]
        == "department"
    )
    history = json.loads(route.calls[1].request.content)["contents"]
    assert [turn["role"] for turn in history] == ["user", "model", "user"]
    assert history[1]["parts"][0]["thoughtSignature"] == "c2lnLTE="
    response = history[2]["parts"][0]["functionResponse"]
    assert (response["id"], response["name"]) == ("c1", "read_attachment_text")
    assert response["response"]["output"]["text"] == "직전 학기 평점평균 3.0 이상"
