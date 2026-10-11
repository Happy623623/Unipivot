"""요건 추출 에이전트 (PRD 6장). 모델이 읽을 자료를 고르고, 코드가 제출을 검증한다.

    agent = ExtractionAgent(llm, model="gemini-3.8-flash", departments=departments)
    async with agent_run(log_conn, trigger="batch_crawl") as run:
        result = await agent.run(notice, run)

루프: 모델 호출 → 도구 실행 → 결과 돌려주기를 제출을 받을 때까지 되풀이한다.
읽기 도구는 공고당 max_reads번, 제출은 max_submits번(재시도 1번)까지다. 읽기 상한이나
토큰 상한에 닿으면 제출만 부를 수 있게 하고(force_tool), 결과는 원문 확인 필요로 둔다.
그렇게 시킨 제출은 실행 로그(tool_calls.output)에 forced로 남아 처리 과정에서 정해진 단계로 보인다.
LLM 호출 오류는 잡지 않는다. 실행이 실패로 기록되고 저장하지 않으므로 다음 수집 때 다시 돈다.

원문 확인 필요 이유(review_reasons)는 공고 상세에서 학생에게 그대로 보이므로 쉬운 말로 쓴다.
"""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from app.attachments import clean_text
from app.eligibility import Department
from app.extraction.models import ExtractionResult, Limits, NoticeInput
from app.extraction.prompt import (
    FETCH_ORIGINAL,
    FORCED,
    NUDGE,
    READ_TEXT,
    READ_TOOLS,
    SUBMIT,
    SUBMIT_SPEC,
    VISION_PROMPT,
    notice_message,
    system_prompt,
    tool_specs,
)
from app.extraction.sources import Library, PageFetcher, ToolError
from app.extraction.validate import LOW_CONFIDENCE, Context, Submission, check_submission
from app.llm import (
    Blob,
    LlmClient,
    LlmReply,
    ToolCall,
    ToolResult,
    ToolResultTurn,
    Turn,
    UserTurn,
)

# 원문 확인 필요 이유. 상한·도구 이름 같은 내부 말 대신 학생이 알아들을 말로 쓴다
_READ_CAP = "읽기 횟수 한도에 닿아 그때까지 읽은 내용으로 조건을 정리함"
_TOKEN_CAP = "처리 분량 한도에 닿아 그때까지 읽은 내용으로 조건을 정리함"
_UNREADABLE = "읽지 못한 첨부가 있음"  # 상세 첨부 목록에도 실패로 보인다
_NO_SUBMISSION = "자격 요건을 정리하지 못함"
_MODEL_FLAG = "AI가 원문 확인이 필요하다고 표시함"  # 모델이 이유(review_note)를 쓰지 않았을 때
# 모델이 모호하다고 한 조건과 코드가 모호로 바꾼 조건(근거 없음, 모양이 틀림, 목록에 없는 학과) 모두다
_AMBIGUOUS = "자동으로 판정할 수 없는 조건이 있음"
_NOT_READ = "첨부를 읽지 않고 자격 제한이 없다고 봄"


class RunLog(Protocol):
    """app.agent_log.AgentRun과 같은 모양. 테스트는 메모리에 남기는 가짜를 쓴다."""

    def tool(
        self, name: str, input: dict[str, Any] | None = None
    ) -> AbstractAsyncContextManager[Any]: ...

    async def record_llm(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        tool_call: Any = None,
    ) -> None: ...


@dataclass
class _State:
    reads: int = 0
    submits: int = 0
    tokens: int = 0
    nudged: bool = False
    forcing: bool = False
    accepted: Submission | None = None
    reasons: list[str] = field(default_factory=list)

    def force(self, reason: str) -> None:
        self.forcing = True
        self.reasons.append(reason)


class ExtractionAgent:
    def __init__(
        self,
        llm: LlmClient,
        *,
        model: str,
        vision_model: str | None = None,
        departments: Sequence[Department] = (),
        limits: Limits | None = None,
        fetch_page: PageFetcher | None = None,
        thinking: str | None = "low",
    ) -> None:
        self.llm = llm
        self.model = model
        self.vision_model = vision_model or model
        self.departments = tuple(departments)
        self.limits = limits or Limits()
        self.fetch_page = fetch_page
        self.thinking = thinking

    async def run(self, notice: NoticeInput, log: RunLog) -> ExtractionResult:
        library = Library(notice, self.limits)
        context = Context(
            evidence=library.evidence,
            attachments={attachment.seq: attachment for attachment in notice.attachments},
            departments=self.departments,
            posted_on=notice.posted_on,
        )
        state = _State()
        system = system_prompt(self.departments, self.limits)
        tools = tool_specs(self.limits)
        message = notice_message(notice, library.body, library.body_truncated, library.listing())
        turns: list[Turn] = [UserTurn(message)]

        for _ in range(self.limits.max_reads + self.limits.max_submits + 3):
            # 상한에 닿은 뒤의 요청은 제출만 부를 수 있다. 그 답의 제출은 모델이 고른 것이 아니다.
            # 같은 답에서 상한에 닿은 읽기 뒤에 모델이 스스로 낸 제출은 강제가 아니다
            forced = state.forcing
            reply = await self.llm.generate(
                model=self.model,
                system=system,
                turns=turns,
                tools=(SUBMIT_SPEC,) if forced else tools,
                thinking=self.thinking,
                force_tool=SUBMIT if forced else None,
            )
            await self._record(log, reply, self.model, state)
            if not reply.turn.tool_calls:
                if state.nudged:
                    break
                state.nudged = True
                if reply.turn.text:  # 글로 답했다: 제출하라고 한 번 더 말한다
                    turns += [reply.turn, UserTurn(NUDGE)]
                # 빈 답(차단·잘못된 함수 호출)은 대화에 넣지 않고 같은 요청을 한 번 더 보낸다.
                # 빈 model 턴을 보내면 다음 요청이 거절된다
                continue
            turns.append(reply.turn)
            results = [
                await self._call(call, library, context, state, log, forced=forced)
                for call in reply.turn.tool_calls
            ]
            if state.accepted is not None:
                break
            if state.tokens >= self.limits.max_tokens and not state.forcing:
                state.force(_TOKEN_CAP)
                results = [ToolResult(r.call, {**r.content, "note": FORCED}) for r in results]
            turns.append(ToolResultTurn(tuple(results)))
        return self._result(state, library)

    async def _record(
        self, log: RunLog, reply: LlmReply, model: str, state: _State, call: Any = None
    ) -> None:
        state.tokens += reply.usage.input_tokens + reply.usage.output_tokens
        await log.record_llm(
            provider=self.llm.provider,
            model=model,
            input_tokens=reply.usage.input_tokens,
            output_tokens=reply.usage.output_tokens,
            latency_ms=reply.latency_ms,
            tool_call=call,
        )

    async def _call(
        self,
        call: ToolCall,
        library: Library,
        context: Context,
        state: _State,
        log: RunLog,
        *,
        forced: bool = False,
    ) -> ToolResult:
        if state.accepted is not None:
            return ToolResult(call, {"error": "이미 제출을 받았어요"})
        if call.name == SUBMIT:
            return await self._submit(call, context, state, log, forced=forced)
        if call.name not in READ_TOOLS:
            return ToolResult(call, {"error": f"없는 도구예요: {call.name}"})
        if state.reads >= self.limits.max_reads:
            if not state.forcing:
                state.force(_READ_CAP)
            return ToolResult(call, {"error": FORCED})
        state.reads += 1
        args = _clean(call.args)
        async with log.tool(call.name, args) as logged:
            try:
                content: dict[str, Any] = {
                    "output": await self._read(call.name, args, library, state, log, logged)
                }
            except ToolError as exc:
                content = {"error": str(exc)}
            logged.output = _summary(content)
        return ToolResult(call, content)

    async def _read(
        self,
        name: str,
        args: dict[str, Any],
        library: Library,
        state: _State,
        log: RunLog,
        logged: Any,
    ) -> dict[str, Any]:
        if name == READ_TEXT:
            return library.read_text(args.get("attachment_no"), args.get("offset", 0))
        if name == FETCH_ORIGINAL:
            return await library.read_original(self.fetch_page, args.get("offset", 0))
        # READ_IMAGE: Vision 모델이 글자로 옮기고, 그 글자를 근거 대조에 쓴다
        item, payload = library.vision_input(args.get("attachment_no"), args.get("start_page", 1))
        reply = await self.llm.generate(
            model=self.vision_model,
            system=None,
            turns=[UserTurn(VISION_PROMPT, blobs=(Blob(payload.data, payload.mime_type),))],
            thinking=self.thinking,
        )
        await self._record(log, reply, self.vision_model, state, logged)
        text = (reply.turn.text or "").strip()
        if not text:
            reason = f"Vision이 글자를 돌려주지 않았어요({reply.finish_reason or '이유 없음'})"
            library.vision_failed(item, reason)
            raise ToolError(reason)
        return library.record_vision(item, payload, text)

    async def _submit(
        self, call: ToolCall, context: Context, state: _State, log: RunLog, *, forced: bool
    ) -> ToolResult:
        state.submits += 1
        final = state.submits >= self.limits.max_submits
        args = _clean(call.args)
        async with log.tool(SUBMIT, args) as logged:
            submission, problems = check_submission(args, context, final=final)
            output: dict[str, Any] = {"accepted": submission is not None, "problems": problems[:20]}
            if forced:  # 상한에 닿아 코드가 시킨 제출. 처리 과정에서 정해진 단계(pipeline)로 보인다
                output["forced"] = True
            logged.output = output
        if submission is None:
            return ToolResult(
                call,
                {
                    "error": "제출을 받지 않았어요. 아래 문제를 고쳐 한 번 더 제출하세요.",
                    "problems": problems[:20],
                },
            )
        state.accepted = submission
        return ToolResult(call, {"output": "받았어요"})

    def _result(self, state: _State, library: Library) -> ExtractionResult:
        attachments = library.outcomes()
        reasons = list(state.reasons)
        if any(attachment.error for attachment in attachments):
            reasons.append(_UNREADABLE)
        reasons += library.partial_reads()
        submission = state.accepted
        if submission is None:
            reasons.append(_NO_SUBMISSION)
            return ExtractionResult(
                succeeded=False,
                needs_review=True,
                review_reasons=tuple(dict.fromkeys(reasons)),
                attachments=attachments,
            )
        reasons += submission.fixes
        if submission.needs_review:
            # 모델이 쓴 이유는 AI가 쓴 글임을 밝혀 보인다(프롬프트가 쉬운 말 한 문장을 시킨다).
            # 공고 속 지시문이 끼어들 수 있는 글이라 상세가 주소를 지우고 한 줄로 정리한다
            note = submission.review_note
            reasons.append(f"AI 메모: {note}" if note else _MODEL_FLAG)
        if any(requirement.is_ambiguous for requirement in submission.requirements):
            reasons.append(_AMBIGUOUS)
        if submission.confidence < Decimal(str(self.limits.low_confidence)):
            reasons.append(LOW_CONFIDENCE)
        if not submission.requirements and library.unread():
            reasons.append(_NOT_READ)
        confidence = submission.confidence
        if submission.fixes:
            confidence = min(confidence, Decimal("0.50"))  # 코드가 고쳐 넣은 제출
        return ExtractionResult(
            succeeded=True,
            requirements=submission.requirements,
            documents=submission.documents,
            apply_start_at=submission.apply_start_at,
            deadline_at=submission.deadline_at,
            eligibility_basis_date=submission.eligibility_basis_date,
            easy_summary=submission.easy_summary,
            confidence=confidence,
            needs_review=bool(reasons),
            review_reasons=tuple(dict.fromkeys(reasons)),
            attachments=attachments,
        )


def _clean(value: Any) -> Any:
    """모델이 보낸 값에서 DB(text·jsonb)가 받지 못하는 제어 문자를 지운다."""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def _summary(content: dict[str, Any]) -> dict[str, Any]:
    """tool_calls.output에 남길 요약. 읽은 글자 자체는 남기지 않는다(첨부 행에 저장된다)."""
    if "error" in content:
        return {"error": content["error"]}
    output = content["output"]
    summary = {key: value for key, value in output.items() if key != "text"}
    summary["sent_chars"] = len(output.get("text", ""))
    return summary
