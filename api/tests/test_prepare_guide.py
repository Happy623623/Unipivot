"""서류 안내 모델 호출(get_document_guide의 LLM 쪽). 가짜 모델로 묻는 말·받는 답의 정리를 본다."""

import asyncio

import pytest

from app.llm import LlmReply
from app.prepare import guide
from app.prepare.guide import MAX_DOCUMENTS, SYSTEM, TOOL_NAME, GuideError, ask_guides
from tests.llm_fakes import ScriptedLlm, call

pytestmark = pytest.mark.anyio


class SlowLlm:
    """상한을 넘기도록 오래 끄는 모델."""

    provider = "google"

    async def generate(self, **kwargs: object) -> LlmReply:
        await asyncio.sleep(10)
        raise AssertionError("상한 안에 끊겼어야 한다")


async def test_a_slow_model_is_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """한 호출의 상한을 넘기면 TimeoutError다(부르는 쪽에서 LLM_TIMEOUT)."""
    monkeypatch.setattr(guide, "TIMEOUT_SECONDS", 0.01)
    with pytest.raises(TimeoutError):
        await ask_guides(SlowLlm(), model="m", title="t", organizer=None, names=["참가 확인서"])


async def test_names_mode_keeps_only_the_asked_documents() -> None:
    llm = ScriptedLlm(
        call(
            TOOL_NAME,
            documents=[
                {
                    "name": "활동계획서",
                    "issuer": "직접 작성",
                    "how_to": "양식대로 작성",
                    "lead_days": 3,
                },
                {
                    "name": "참가확인서",
                    "issuer": "주최측",
                    "how_to": "주최측에 요청",
                    "lead_days": 2,
                },
                {"name": "묻지 않은 서류", "issuer": "어딘가", "how_to": "-", "lead_days": 1},
            ],
        )
    )
    drafts, reply = await ask_guides(
        llm,
        model="test-model",
        title="2026 창업 경진대회",
        organizer="창업지원단",
        names=["활동계획서", "참가 확인서"],
    )
    # 띄어쓰기만 다른 이름도 같은 서류로 받고, 이름은 물어본 그대로 돌려준다
    assert [(d.name, d.issuer, d.lead_days) for d in drafts] == [
        ("활동계획서", "직접 작성", 3),
        ("참가 확인서", "주최측", 2),
    ]
    request = llm.requests[0]
    assert (request.model, request.system, request.tools) == ("test-model", SYSTEM, [TOOL_NAME])
    assert request.force_tool == TOOL_NAME
    text = request.turns[0].text  # type: ignore[union-attr]
    assert "2026 창업 경진대회 (창업지원단)" in text and "1. 활동계획서\n2. 참가 확인서" in text
    assert reply.usage.input_tokens > 0


async def test_text_mode_cleans_the_answer() -> None:
    long_how = "가" * 300
    documents = [
        {"name": "  신청서 ", "issuer": "주민센터", "how_to": long_how, "lead_days": 99},
        {
            "name": "신청서",
            "issuer": "중복",
            "how_to": "중복",
            "lead_days": 0,
        },  # 같은 이름은 하나만
        {
            "name": "소득 증빙",
            "issuer": "홈택스",
            "how_to": "발급",
            "lead_days": -3,
            "effort_minutes": 0,
            "is_required": False,
        },
        {"name": "", "issuer": "이름 없음", "how_to": "-", "lead_days": 1},
        {"name": "진단서", "issuer": "병원", "how_to": "발급", "lead_days": "3"},
        "목록이 아닌 값",
    ]
    llm = ScriptedLlm(call(TOOL_NAME, documents=documents))
    drafts, _ = await ask_guides(
        llm, model="m", title="청년 월세 지원", organizer=None, text="1) 신청서\n2) 소득 증빙"
    )
    assert [(d.name, d.lead_days, d.is_required, d.effort_minutes) for d in drafts] == [
        ("신청서", 30, True, None),
        ("소득 증빙", 0, False, None),
        ("진단서", None, True, None),  # 숫자가 아니면 모른다(계획에서 하루)
    ]
    assert len(drafts[0].how_to or "") == 120
    prompt = llm.requests[0].turns[0].text  # type: ignore[union-attr]
    assert "공고: 청년 월세 지원\n" in prompt and "---\n1) 신청서\n2) 소득 증빙\n---" in prompt


async def test_text_mode_caps_the_number_of_documents() -> None:
    many = [
        {"name": f"서류 {n}", "issuer": "곳", "how_to": "방법", "lead_days": 1} for n in range(20)
    ]
    drafts, _ = await ask_guides(
        ScriptedLlm(call(TOOL_NAME, documents=many)), model="m", title="t", organizer=None, text="x"
    )
    assert len(drafts) == MAX_DOCUMENTS


async def test_answer_without_the_tool_is_an_error() -> None:
    with pytest.raises(GuideError):
        await ask_guides(
            ScriptedLlm("서류는 신청서예요"), model="m", title="t", organizer=None, text="x"
        )
    with pytest.raises(GuideError):
        await ask_guides(
            ScriptedLlm(call(TOOL_NAME, documents="신청서")),
            model="m",
            title="t",
            organizer=None,
            names=["신청서"],
        )
