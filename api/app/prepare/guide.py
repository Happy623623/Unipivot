"""서류 안내를 모델에 묻는다(PRD 6장 get_document_guide의 LLM 쪽). 한 번 부르고 도구 하나로만 받는다.

두 가지로 묻는다.
- names: 이름은 아는데 사전(app/prepare/documents.py)에 없는 서류의 발급처·방법·소요 일수
- text: 서류 행이 없는 청년정책의 "제출 서류" 글. 글에서 서류 목록과 안내를 함께 만든다
프롬프트에는 공고 글만 넣고 프로필 값은 넣지 않는다(PRD 6장).
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from app.llm import LlmClient, LlmReply, ToolSpec, UserTurn
from app.prepare.documents import normalize

TOOL_NAME = "submit_document_guides"
MAX_DOCUMENTS = 15
# 이 호출 하나의 상한. 준비하기 실행을 멈춘 것으로 보는 기준(repositories/prepare.py의
# STALE_AFTER_SECONDS)보다 짧아야 한다. 그렇지 않으면 아직 도는 실행을 다음 누름이 지운다.
# Gemini 클라이언트는 한 번에 120초이고 3번까지 다시 보내므로(app/llm/gemini.py) 여기서 끊는다.
# 짧은 구조화 답 하나라 몇 초면 끝난다. 이 시간만큼 실행 로그 연결도 함께 쥔다(app/db.py의 log_pool)
TIMEOUT_SECONDS = 60.0
_NAME_LIMIT, _ISSUER_LIMIT, _HOW_LIMIT = 60, 40, 120
_LEAD_MAX, _EFFORT_MAX = 30, 600

SYSTEM = (
    "너는 대학생이 공고에 낼 서류를 준비하도록 돕는다. 서류마다 발급처(issuer), 받거나 준비하는 방법"
    "(how_to, 한 문장), 받기까지 걸리는 일수(lead_days, 바로 받으면 0), 직접 쓰는 서류면 쓰는 데 드는"
    " 시간(effort_minutes)을 submit_document_guides로 한 번에 낸다. 학생은 한양대학교 ERICA 학부생이고"
    " 학교 증명서는 한양인 포털에서 받는다. 모르는 기관을 지어내지 말고, 공고 글에 적힌 곳이 있으면 그곳을"
    " 쓴다. 해요체로 쓰지 말고 짧은 명사구·평서문으로 쓴다."
)
_NAMES_TASK = "아래 서류마다 안내를 내. 서류 이름은 그대로 쓰고 빼거나 더하지 마."
_TEXT_TASK = (
    "아래는 공고의 '제출 서류' 글이야. 학생이 준비해서 낼 서류만 골라 이름과 안내를 내. '등', '증빙서류'"
    " 같은 말은 알맞게 줄여 이름으로 쓰고, 방문·상담·사업 일정처럼 서류가 아닌 글이면 빈 목록을 내."
    f" 서류는 {MAX_DOCUMENTS}개까지야."
)

TOOL = ToolSpec(
    name=TOOL_NAME,
    description="서류 목록과 서류마다의 안내를 낸다.",
    parameters={
        "type": "object",
        "properties": {
            "documents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "서류 이름"},
                        "issuer": {"type": "string", "description": "발급처(기관·사이트)"},
                        "how_to": {"type": "string", "description": "받거나 준비하는 방법 한 문장"},
                        "lead_days": {
                            "type": "integer",
                            "description": f"받기까지 걸리는 일수(0–{_LEAD_MAX}). 바로 받으면 0",
                        },
                        "effort_minutes": {
                            "type": "integer",
                            "description": "직접 쓰는 서류면 쓰는 데 드는 분. 아니면 빼",
                        },
                        "is_required": {
                            "type": "boolean",
                            "description": "꼭 내야 하면 true, 해당자만 내면 false",
                        },
                    },
                    "required": ["name", "issuer", "how_to", "lead_days"],
                },
            }
        },
        "required": ["documents"],
    },
)


@dataclass(frozen=True)
class GuideDraft:
    name: str
    issuer: str | None
    how_to: str | None
    lead_days: int | None
    effort_minutes: int | None
    is_required: bool = True


class GuideError(Exception):
    """모델 답을 쓸 수 없다(도구를 부르지 않았거나 모양이 틀렸다)."""


def prompt(title: str, organizer: str | None, names: Sequence[str] | None, text: str | None) -> str:
    head = f"공고: {title}" + (f" ({organizer})" if organizer else "")
    if names:
        listed = "\n".join(f"{index}. {name}" for index, name in enumerate(names, 1))
        return f"{head}\n{_NAMES_TASK}\n{listed}"
    return f"{head}\n{_TEXT_TASK}\n---\n{text or ''}\n---"


async def ask_guides(
    llm: LlmClient,
    *,
    model: str,
    title: str,
    organizer: str | None,
    names: Sequence[str] | None = None,
    text: str | None = None,
) -> tuple[list[GuideDraft], LlmReply]:
    """names를 주면 그 서류만(모델이 빼먹은 이름은 빠진다), text를 주면 글에서 고른 서류를 돌려준다.

    TIMEOUT_SECONDS를 넘기면 TimeoutError다(부르는 쪽에서 LLM_TIMEOUT).
    """
    async with asyncio.timeout(TIMEOUT_SECONDS):
        reply = await llm.generate(
            model=model,
            system=SYSTEM,
            turns=[UserTurn(prompt(title, organizer, names, text))],
            tools=[TOOL],
            force_tool=TOOL_NAME,
        )
    calls = [call for call in reply.turn.tool_calls if call.name == TOOL_NAME]
    raw = calls[0].args.get("documents") if calls else None
    if not isinstance(raw, list):
        raise GuideError("서류 안내 도구를 부르지 않았어요.")
    drafts = _drafts(raw)
    if names:  # 물어본 이름만 남긴다(이름을 조금 바꿔 답해도 같은 서류면 받는다)
        wanted = {normalize(name): name for name in names}
        drafts = [
            replace(draft, name=wanted[normalize(draft.name)])
            for draft in drafts
            if normalize(draft.name) in wanted
        ]
    return _unique(drafts)[:MAX_DOCUMENTS], reply


def _drafts(items: list[Any]) -> list[GuideDraft]:
    drafts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = _short(item.get("name"), _NAME_LIMIT)
        if name is None:
            continue
        drafts.append(
            GuideDraft(
                name=name,
                issuer=_short(item.get("issuer"), _ISSUER_LIMIT),
                how_to=_short(item.get("how_to"), _HOW_LIMIT),
                lead_days=_whole(item.get("lead_days"), _LEAD_MAX),
                effort_minutes=_whole(item.get("effort_minutes"), _EFFORT_MAX) or None,
                is_required=item.get("is_required") is not False,
            )
        )
    return drafts


def _unique(drafts: list[GuideDraft]) -> list[GuideDraft]:
    seen: set[str] = set()
    unique = []
    for draft in drafts:
        if (key := normalize(draft.name)) and key not in seen:
            seen.add(key)
            unique.append(draft)
    return unique


def _short(value: Any, limit: int) -> str | None:
    """공백을 한 칸으로 줄인 한 줄. 비었으면 None, 길면 자른다."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text[:limit].rstrip() or None


def _whole(value: Any, limit: int) -> int | None:
    """0–limit 정수. 숫자가 아니면 None, 넘치면 limit."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return max(0, min(limit, int(value)))
