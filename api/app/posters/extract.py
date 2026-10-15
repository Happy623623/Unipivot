"""포스터 한 장 → 공고 초안 (F-16).

Vision 모델을 **한 번만** 부른다. 포스터는 사진 한 장이라 더 읽을 첨부가 없어서, 글자를 옮기는 일과
요건을 뽑는 일을 한 호출에서 함께 받는다(submit_poster의 poster_text + 나머지 항목).

검증은 공지 추출과 같은 코드(app/extraction/validate.check_submission)를 쓴다. 근거 문장은 모델이
옮겨 적은 poster_text에 있는지 본다 — 포스터에는 대조할 다른 원문이 없다.

한 번만 부르므로 final=True로 검증한다. 문제가 있으면 모델에 다시 묻지 않고 코드가 고쳐서 받고,
고친 항목은 확인 화면에서 강조할 low_confidence_fields에 넣는다.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.eligibility import Department, Requirement, condition_text
from app.extraction.models import DocumentDraft, RequirementDraft
from app.extraction.validate import Context, Evidence, Submission, check_submission
from app.llm import Blob, LlmClient, LlmReply, UserTurn
from app.posters.prompt import (
    CATEGORIES,
    NO_TEXT,
    SUBMIT,
    SUBMIT_POSTER,
    first_message,
    system_prompt,
)
from app.prepare.documents import lookup
from app.schemas.posters import (
    LOW_CONFIDENCE_FIELDS,
    PosterDocumentDraft,
    PosterDraft,
    PosterRequirementDraft,
)

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 50.0  # 웹이 실행을 확인하는 60초 안에 실패를 알려 준다
MAX_OUTPUT_TOKENS = 16_000  # 옮긴 글자 + 요건. 넘치면 제출이 잘려 읽지 못한 것으로 본다
LOW_CONFIDENCE = 0.6  # 이보다 낮으면 제목·마감일을 확인하게 한다
_DEFAULT_CATEGORY = "etc"


class PosterError(Exception):
    """포스터에서 공고를 읽지 못했다. 학생에게 그대로 보여 줄 문구다."""


@dataclass(frozen=True)
class Extracted:
    draft: PosterDraft
    poster_text: str  # 등록(F-16 2차)에서 공고 원문으로 쓴다
    reply: LlmReply


async def extract(
    llm: LlmClient,
    *,
    model: str,
    blob: Blob,
    departments: Sequence[Department],
    today: date,
) -> Extracted:
    """Vision 한 번 호출. 읽지 못하면 PosterError다."""
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            reply = await llm.generate(
                model=model,
                system=system_prompt(departments),
                turns=[UserTurn(text=first_message(today), blobs=(blob,))],
                tools=(SUBMIT_POSTER,),
                force_tool=SUBMIT,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )
    except TimeoutError as exc:
        raise TimeoutError("포스터를 읽는 데 너무 오래 걸렸어요.") from exc
    call = next((c for c in reply.turn.tool_calls if c.name == SUBMIT), None)
    if call is None:
        raise PosterError(f"포스터에서 글자를 읽지 못했어요({reply.finish_reason or '이유 없음'}).")
    args = call.args
    poster_text = args.get("poster_text")
    if (
        not isinstance(poster_text, str)
        or not poster_text.strip()
        or poster_text.strip() == NO_TEXT
    ):
        raise PosterError("포스터에서 글자를 읽지 못했어요.")

    evidence = Evidence()
    evidence.add(poster_text)
    # 포스터에는 게시일이 없다. 연도 없는 날짜("10. 24.까지")는 사진을 올린 날 뒤로 읽는다
    context = Context(evidence, {}, departments, today)
    submission, problems = check_submission(args, context, final=True)
    if submission is None:
        logger.info("포스터 제출을 받지 못했어요: %s", "; ".join(problems[:3]))
        raise PosterError("포스터에서 지원 조건을 정리하지 못했어요.")

    title = _text(args.get("title"))
    if title is None:
        raise PosterError("포스터에서 공고 이름을 찾지 못했어요.")
    draft = PosterDraft(
        title=title[:200],
        organizer=_cut(_text(args.get("organizer")), 100),
        category=_category(args.get("category")),
        apply_start_at=submission.apply_start_at,
        deadline_at=submission.deadline_at,
        easy_summary=submission.easy_summary,
        requirements=[_requirement(req) for req in submission.requirements],
        documents=[_document(doc) for doc in submission.documents],
        extraction_confidence=float(submission.confidence),
        low_confidence_fields=_low_confidence(
            args.get("low_confidence_fields"), submission, title, _text(args.get("category"))
        ),
    )
    return Extracted(draft, poster_text, reply)


def _requirement(req: RequirementDraft) -> PosterRequirementDraft:
    """조건 문장은 공고 상세와 같은 방법으로 만든다(app/eligibility/describe)."""
    shown = Requirement(
        id="",
        clause_no=req.clause_no,
        field=req.field,
        operator=req.operator,
        value=req.value,
        basis=req.basis,
        is_ambiguous=req.is_ambiguous,
        evidence_text=req.evidence_text,
    )
    return PosterRequirementDraft(
        clause_no=req.clause_no,
        field=req.field,
        operator=req.operator,
        value=req.value,
        basis=req.basis,
        condition_text=condition_text(shown),
        evidence_text=req.evidence_text,
        is_ambiguous=req.is_ambiguous,
    )


def _document(doc: DocumentDraft) -> PosterDocumentDraft:
    """발급처·소요 일수·작성 시간은 서류 사전에서 채운다(준비하기와 같은 사전)."""
    guide = lookup(doc.name)
    return PosterDocumentDraft(
        name=doc.name,
        issuer=guide.issuer if guide else None,
        lead_days=guide.lead_days if guide else None,
        effort_minutes=guide.effort_minutes if guide else None,
        form_url=doc.form_url,
    )


def _low_confidence(
    raw: object, submission: Submission, title: str, category: str | None
) -> list[str]:
    """모델이 고른 항목 + 코드가 보기에 확인이 필요한 항목. 확인 화면에서 강조한다."""
    # 모델이 아무 값이나 줄 수 있다(글이 아닌 것도). 아는 항목만 남기는 것은 마지막 한 줄에서 한다
    found = {name for name in raw if isinstance(name, str)} if isinstance(raw, list) else set()
    if submission.deadline_at is None:
        found.add("deadline_at")  # 마감일을 못 읽으면 학생이 넣어야 한다
    if submission.confidence < LOW_CONFIDENCE:
        found.update(("title", "deadline_at"))
    if any(req.is_ambiguous for req in submission.requirements):
        found.add("requirements")
    if submission.fixes:  # 코드가 고쳐서 받은 것이 있다(날짜 뒤바뀜, 근거 없는 조건 등)
        found.add("requirements")
    if len(title) < 4:  # "장학금"처럼 너무 짧은 제목은 큰 글씨만 읽은 것일 수 있다
        found.add("title")
    if category not in CATEGORIES:  # 모르는 종류는 '그 밖'으로 두므로 학생이 골라야 한다
        found.add("category")
    return [name for name in LOW_CONFIDENCE_FIELDS if name in found]


def _category(raw: object) -> str:
    return raw if isinstance(raw, str) and raw in CATEGORIES else _DEFAULT_CATEGORY


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _cut(value: str | None, limit: int) -> str | None:
    return value[:limit] if value else None
