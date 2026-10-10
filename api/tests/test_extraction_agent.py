"""요건 추출 에이전트: 가짜 LLM으로 루프·도구·검증·재시도·상한·기록을 본다(PRD 6장, S08·S09)."""

import json
import zipfile
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from pypdf import PdfReader

from app.attachments import UnreadableAttachment
from app.crawl import FetchError
from app.eligibility import KST, Department
from app.extraction import AttachmentInput, ExtractionAgent, Limits, NoticeInput
from app.extraction.prompt import FETCH_ORIGINAL, FORCED, NUDGE, READ_IMAGE, READ_TEXT, SUBMIT
from app.llm import ModelTurn, ToolResultTurn, UserTurn
from tests import samples
from tests.llm_fakes import MemoryRunLog, ScriptedLlm, call, calls
from tests.samples import hp

pytestmark = pytest.mark.anyio

MODEL = "gemini-3.8-flash"
BODY = """2026학년도 2학기 ○○장학생 선발 안내
1. 지원 자격
가. 본교 재학생(휴학생 제외)
나. 직전 학기 평점평균 3.0 이상(4.5 만점)
2. 제출 서류: 장학금 신청서 1부, 성적증명서 1부
3. 신청 기간: 10. 13.(월) ~ 10. 24.(금)"""
NOTICE = NoticeInput(title="○○장학생 선발 안내", body=BODY, posted_on=date(2026, 10, 8))


def req(
    clause: int,
    field: str,
    operator: str,
    value: Any,
    evidence: str,
    *,
    basis: str | None = None,
    ambiguous: bool = False,
) -> dict[str, Any]:
    item = {
        "clause_no": clause,
        "field": field,
        "operator": operator,
        "value_json": json.dumps(value, ensure_ascii=False),
        "evidence_text": evidence,
        "is_ambiguous": ambiguous,
    }
    return {**item, "basis": basis} if basis else item


def submission(*requirements: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "requirements": list(requirements),
        "documents": [],
        "deadline": "2026-10-24",
        "confidence": 0.9,
        "needs_review": False,
        **extra,
    }


GPA = req(1, "gpa_last_semester", "gte", 3.0, "직전 학기 평점평균 3.0 이상(4.5 만점)")


async def run(
    llm: ScriptedLlm, notice: NoticeInput = NOTICE, **options: Any
) -> tuple[Any, MemoryRunLog]:
    log = MemoryRunLog()
    result = await ExtractionAgent(llm, model=MODEL, **options).run(notice, log)
    return result, log


async def test_body_only_notice_is_submitted_without_reading() -> None:
    llm = ScriptedLlm(
        call(
            SUBMIT,
            **submission(
                req(1, "enrollment_status", "eq", "enrolled", "본교 재학생(휴학생 제외)"),
                {**GPA, "clause_no": 2},
                documents=[
                    {"name": "장학금 신청서", "is_required": True},
                    {"name": "성적증명서", "is_required": True},
                ],
                apply_start="2026-10-13",
                easy_summary="평점 3.0 이상 재학생이 10월 24일까지 신청하는 장학금이에요.",
            ),
        )
    )
    result, log = await run(llm)

    assert result.succeeded and not result.needs_review and result.review_reasons == ()
    assert [
        (r.clause_no, r.field, r.operator, r.value, r.is_ambiguous) for r in result.requirements
    ] == [
        (1, "enrollment_status", "eq", "enrolled", False),
        (2, "gpa_last_semester", "gte", 3.0, False),
    ]
    assert [d.name for d in result.documents] == ["장학금 신청서", "성적증명서"]
    assert result.apply_start_at == datetime(2026, 10, 13, 0, 0, tzinfo=KST)
    assert result.deadline_at == datetime(2026, 10, 24, 23, 59, tzinfo=KST)  # 날짜만 있으면 23:59
    assert result.confidence == Decimal("0.90")
    assert [tool.name for tool in log.tools] == [SUBMIT]
    assert log.llm == [
        {
            "provider": "google",
            "model": MODEL,
            "input_tokens": 1000,
            "output_tokens": 200,
            "latency_ms": 7,
            "tool_call": None,
        }
    ]
    first = llm.requests[0]
    assert first.tools == [READ_TEXT, READ_IMAGE, FETCH_ORIGINAL, SUBMIT]
    assert first.force_tool is None
    assert first.system is not None and "gpa_last_semester(직전학기 평점)" in first.system
    message = first.turns[0]
    assert isinstance(message, UserTurn)
    assert "제목: ○○장학생 선발 안내" in message.text and "게시일: 2026-10-08" in message.text
    assert message.text.endswith("[첨부]\n없음")


async def test_requirements_only_in_attachment_are_read_and_logged() -> None:
    """S09: 본문이 첨부를 가리키면 모델이 첨부를 골라 읽고, 고른 이유가 기록에 남는다."""
    guide = samples.pdf(
        [
            "2026-2 ○○장학 선발 요강",
            "1. 지원 자격: 직전 학기 12학점 이상 이수자\n(단, 4학년은 9학점 이상)",
        ]
    )
    notice = NoticeInput(
        title="○○장학 선발",
        body="자세한 내용은 첨부 파일을 참조하세요.",
        posted_on=date(2026, 10, 8),
        attachments=(
            AttachmentInput(1, "선발요강.pdf", guide, "https://example.ac.kr/f/1", id="att-1"),
            AttachmentInput(
                2, "신청서.hwpx", samples.hwpx(hp("장학금 신청서")), "https://example.ac.kr/f/2"
            ),
        ),
    )
    reason = "본문이 첨부를 가리켜서 선발요강을 읽음"
    llm = ScriptedLlm(
        call(READ_TEXT, attachment_no=1, reason=reason),
        call(
            SUBMIT,
            **submission(
                req(1, "grade", "eq", 4, "(단, 4학년은 9학점 이상)"),
                req(1, "credits_last_semester", "gte", 12, "직전 학기 12학점 이상 이수자"),
                req(2, "grade", "neq", 4, "(단, 4학년은 9학점 이상)"),
                req(2, "credits_last_semester", "gte", 9, "4학년은 9학점 이상"),
                documents=[{"name": "장학금 신청서", "is_required": True, "form_attachment_no": 2}],
            ),
        ),
    )
    result, log = await run(llm, notice)

    assert result.succeeded and not result.needs_review
    assert [r.clause_no for r in result.requirements] == [1, 1, 2, 2]
    assert result.documents[0].form_url == "https://example.ac.kr/f/2"
    listing = llm.requests[0].turns[0].text  # type: ignore[union-attr]
    assert "1. 선발요강.pdf — PDF 2쪽, 글자" in listing and f"→ {READ_TEXT}" in listing
    assert "2. 신청서.hwpx — HWPX, 글자 7자" in listing

    tool_turn = llm.requests[1].turns[-1]
    assert isinstance(tool_turn, ToolResultTurn)
    output = tool_turn.results[0].content["output"]
    assert "12학점 이상 이수자" in output["text"] and output["chars"] == len(output["text"])
    assert [(tool.name, (tool.input or {}).get("reason")) for tool in log.tools] == [
        (READ_TEXT, reason),
        (SUBMIT, None),
    ]
    assert "text" not in log.tools[0].output and log.tools[0].output["sent_chars"] > 0
    assert log.tools[1].output == {"accepted": True, "problems": []}

    first, second = result.attachments
    assert (first.id, first.method, first.mime_type) == ("att-1", "pdf_text", "application/pdf")
    assert first.text is not None and "12학점 이상" in first.text
    assert (second.method, second.text, second.error) == (None, None, None)  # 읽지 않은 첨부


async def test_evidence_not_in_source_is_retried_once() -> None:
    paraphrase = req(1, "gpa_last_semester", "gte", 3.0, "평점 3.0 이상인 학생")
    llm = ScriptedLlm(call(SUBMIT, **submission(paraphrase)), call(SUBMIT, **submission(GPA)))
    result, log = await run(llm)

    rejected = llm.requests[1].turns[-1]
    assert isinstance(rejected, ToolResultTurn)
    assert "근거 문장이 읽은 원문에 없다" in rejected.results[0].content["problems"][0]
    assert result.succeeded and not result.needs_review
    assert not result.requirements[0].is_ambiguous
    assert [tool.output["accepted"] for tool in log.tools] == [False, True]


async def test_second_failure_is_stored_as_ambiguous() -> None:
    """끝까지 근거가 없는 조건은 모호, 모양이 틀린 조건은 기타+모호로 저장한다."""
    bad = submission(
        req(1, "gpa_last_semester", "gte", 3.0, "평점 3.0 이상인 학생"),
        req(2, "region", "in", ["안산시"], "본교 재학생(휴학생 제외)", basis="unspecified"),
    )
    llm = ScriptedLlm(call(SUBMIT, **bad), call(SUBMIT, **bad))
    result, _ = await run(llm)

    gpa, region = result.requirements
    assert (gpa.field, gpa.value, gpa.is_ambiguous) == ("gpa_last_semester", 3.0, True)
    assert (region.field, region.operator, region.basis, region.is_ambiguous) == (
        "other",
        "eq",
        None,
        True,
    )
    assert region.value == {"text": "본교 재학생(휴학생 제외)"}
    assert result.succeeded and result.needs_review
    assert result.confidence == Decimal("0.50")  # 코드가 고쳐 넣은 제출
    assert "근거 문장을 원문에서 찾지 못한 조건을 모호한 조건으로 저장" in result.review_reasons
    assert "모양이 틀린 거주지역 조건을 기타 조건으로 저장" in result.review_reasons


async def test_read_cap_forces_submission_and_needs_review() -> None:
    limits = Limits(max_reads=2)
    attachment = AttachmentInput(1, "요강.hwpx", samples.hwpx(hp("직전 학기 평점평균 3.0 이상")))
    notice = NoticeInput(title="장학", body=BODY, attachments=(attachment,))
    llm = ScriptedLlm(
        call(READ_TEXT, attachment_no=1, reason="요강 확인"),
        call(READ_TEXT, attachment_no=1, reason="다시 확인"),
        call(READ_TEXT, attachment_no=1, reason="또 확인"),
        call(SUBMIT, **submission(GPA)),
    )
    result, log = await run(llm, notice, limits=limits)

    capped = llm.requests[3]
    assert (capped.force_tool, capped.tools) == (SUBMIT, [SUBMIT])
    cap_turn = capped.turns[-1]
    assert isinstance(cap_turn, ToolResultTurn) and cap_turn.results[0].content == {"error": FORCED}
    assert [tool.name for tool in log.tools] == [
        READ_TEXT,
        READ_TEXT,
        SUBMIT,
    ]  # 막힌 호출은 실행하지 않는다
    assert result.succeeded and result.needs_review
    assert "읽기 도구 상한(2번)에 닿음" in result.review_reasons


async def test_token_cap_forces_submission() -> None:
    attachment = AttachmentInput(1, "요강.hwpx", samples.hwpx(hp("직전 학기 평점평균 3.0 이상")))
    notice = NoticeInput(title="장학", body=BODY, attachments=(attachment,))
    llm = ScriptedLlm(
        call(READ_TEXT, attachment_no=1, reason="요강 확인"), call(SUBMIT, **submission(GPA))
    )
    result, _ = await run(llm, notice, limits=Limits(max_tokens=1000))

    assert llm.requests[1].force_tool == SUBMIT
    note = llm.requests[1].turns[-1].results[0].content["note"]  # type: ignore[union-attr]
    assert note == FORCED
    assert "토큰 상한(1,000)에 닿음" in result.review_reasons


async def test_no_submission_is_a_failed_extraction() -> None:
    llm = ScriptedLlm("요건은 평점 3.0 이상입니다.", "다시 말하면 평점 3.0 이상이에요.")
    result, log = await run(llm)

    assert llm.requests[1].turns[-1] == UserTurn(NUDGE)  # 한 번은 제출하라고 다시 말한다
    assert not result.succeeded and result.needs_review
    assert result.requirements == () and "제출을 받지 못함" in result.review_reasons
    assert log.tools == []


async def test_scanned_pdf_is_read_with_vision() -> None:
    scanned = samples.pdf([None, None])
    notice = NoticeInput(
        title="지역 장학",
        body="첨부 공고문을 확인하세요.",
        attachments=(AttachmentInput(1, "공고문(스캔).pdf", scanned),),
    )
    transcription = "1. 지원 자격 | 경기도 안산시에 주민등록을 둔 자\n2. 마감: 2026. 10. 24."
    llm = ScriptedLlm(
        call(READ_IMAGE, attachment_no=1, reason="스캔본이라 Vision으로 읽음"),
        transcription,
        call(
            SUBMIT,
            **submission(
                req(
                    1,
                    "region",
                    "in",
                    ["경기도 안산시"],
                    "경기도 안산시에 주민등록을 둔 자",
                    basis="resident_registration",
                )
            ),
        ),
    )
    result, log = await run(llm, notice, vision_model="gemini-3.5-flash-lite")

    assert "글자 없음(스캔본) → read_attachment_image" in llm.requests[0].turns[0].text  # type: ignore[union-attr]
    vision = llm.requests[1]
    assert (vision.model, vision.system, vision.tools) == ("gemini-3.5-flash-lite", None, [])
    (blob,) = vision.blobs
    assert blob.mime_type == "application/pdf" and len(PdfReader(BytesIO(blob.data)).pages) == 2
    assert [entry["tool_call"] for entry in log.llm] == [None, log.tools[0].id, None]
    assert log.tools[0].output["pages"] == "1–2/2"

    assert result.succeeded and not result.needs_review
    (attachment,) = result.attachments
    assert attachment.method == "vision" and attachment.text == transcription


async def test_partly_read_scan_needs_review() -> None:
    """스캔본을 앞 몇 쪽만 읽으면 남은 쪽에 요건이 있을 수 있다. 이유에는 파일 이름을 쓴다."""
    notice = NoticeInput(
        title="지역 장학",
        body="첨부 공고문을 확인하세요.",
        attachments=(AttachmentInput(1, "공고문(스캔).pdf", samples.pdf([None, None, None])),),
    )
    evidence = "경기도 안산시에 주민등록을 둔 자"
    llm = ScriptedLlm(
        call(READ_IMAGE, attachment_no=1, reason="스캔본이라 Vision으로 읽음"),
        f"1. 지원 자격 | {evidence}",
        call(
            SUBMIT,
            **submission(
                req(1, "region", "in", ["경기도 안산시"], evidence, basis="resident_registration")
            ),
        ),
    )
    result, log = await run(llm, notice, limits=Limits(vision_max_pages=2))

    assert log.tools[0].output["pages"] == "1–2/3"
    assert result.succeeded and result.needs_review
    assert "첨부 '공고문(스캔).pdf' 2/3쪽만 읽음" in result.review_reasons


async def test_unreadable_attachment_marks_review() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    notice = NoticeInput(
        title="장학", body=BODY, attachments=(AttachmentInput(1, "요강.docx", buffer.getvalue()),)
    )
    llm = ScriptedLlm(call(SUBMIT, **submission(GPA)))
    result, _ = await run(llm, notice)

    assert "1. 요강.docx — 못 읽음: DOCX는 아직 못 읽어요" in llm.requests[0].turns[0].text  # type: ignore[union-attr]
    assert result.attachments[0].error == "DOCX는 아직 못 읽어요"
    assert result.needs_review and "읽지 못한 첨부가 있음" in result.review_reasons


async def test_fetch_original_reads_the_page() -> None:
    page = "지원 자격: 외국인 유학생은 제외"

    async def fetch(url: str) -> str:
        assert url == "https://example.ac.kr/notice/1"
        return page

    notice = NoticeInput(title="장학", body="", original_url="https://example.ac.kr/notice/1")
    llm = ScriptedLlm(
        call(FETCH_ORIGINAL, reason="본문이 비어 원문을 다시 읽음"),
        call(SUBMIT, **submission(req(1, "is_international", "eq", False, "외국인 유학생은 제외"))),
    )
    result, log = await run(llm, notice, fetch_page=fetch)

    assert result.succeeded and not result.needs_review
    assert log.tools[0].output == {"chars": len(page), "offset": 0, "sent_chars": len(page)}
    assert "원문 링크: 있음" in llm.requests[0].turns[0].text  # type: ignore[union-attr]


async def test_tool_errors_are_returned_to_the_model() -> None:
    async def broken(url: str) -> str:
        raise FetchError("HTTP 404")

    notice = NoticeInput(title="장학", body=BODY, original_url="https://example.ac.kr/notice/1")
    llm = ScriptedLlm(
        calls(
            (FETCH_ORIGINAL, {"reason": "확인"}),
            (READ_TEXT, {"attachment_no": 9, "reason": "확인"}),
            ("delete_everything", {}),
        ),
        call(SUBMIT, **submission(GPA)),
    )
    result, log = await run(llm, notice, fetch_page=broken)

    errors = [r.content["error"] for r in llm.requests[1].turns[-1].results]  # type: ignore[union-attr]
    assert errors == [
        "원문을 가져오지 못했어요: HTTP 404",
        "첨부 번호가 없어요. [첨부] 목록의 번호를 쓰세요: 9",
        "없는 도구예요: delete_everything",
    ]
    assert [tool.name for tool in log.tools] == [FETCH_ORIGINAL, READ_TEXT, SUBMIT]
    assert result.succeeded


async def test_department_names_outside_the_list_are_ambiguous() -> None:
    departments = [Department("소프트웨어학부", "소프트웨어융합대학", "공학계열")]
    body = "지원 자격: 소프트웨어융합대학 또는 공과대학 소속 학생"
    llm = ScriptedLlm(
        call(
            SUBMIT,
            **submission(
                req(
                    1,
                    "department",
                    "in",
                    ["소프트웨어융합대학"],
                    "소프트웨어융합대학",
                    basis="college",
                ),
                req(1, "department", "in", ["공과대학"], "공과대학 소속 학생", basis="college"),
            ),
        )
    )
    result, _ = await run(llm, NoticeInput(title="장학", body=body), departments=departments)

    assert [r.is_ambiguous for r in result.requirements] == [False, True]
    assert "- 단과대학: 소프트웨어융합대학" in llm.requests[0].system  # type: ignore[operator]


async def test_no_requirements_with_unread_attachment_needs_review() -> None:
    attachment = AttachmentInput(1, "요강.hwpx", samples.hwpx(hp("직전 학기 평점평균 3.0 이상")))
    notice = NoticeInput(title="장학", body="첨부 참조", attachments=(attachment,))
    result, _ = await run(ScriptedLlm(call(SUBMIT, **submission())), notice)

    assert result.succeeded and result.requirements == ()
    assert result.review_reasons == ("첨부를 읽지 않고 요건 없음으로 판단",)


async def test_calls_after_an_accepted_submission_are_skipped() -> None:
    attachment = AttachmentInput(1, "요강.hwpx", samples.hwpx(hp("직전 학기 평점평균 3.0 이상")))
    notice = NoticeInput(title="장학", body=BODY, attachments=(attachment,))
    llm = ScriptedLlm(
        calls((SUBMIT, submission(GPA)), (READ_TEXT, {"attachment_no": 1, "reason": "x"}))
    )
    result, log = await run(llm, notice)

    assert [tool.name for tool in log.tools] == [SUBMIT] and len(llm.requests) == 1
    assert result.succeeded


GUIDE_GPA = {**GPA, "evidence_text": "직전 학기 평점평균 3.0 이상"}


def _long_guide(lines: int = 40) -> bytes:
    return samples.hwpx(
        *[hp(f"{no}. 안내 문단입니다. 직전 학기 평점평균 3.0 이상") for no in range(lines)]
    )


async def test_partly_read_attachment_needs_review() -> None:
    """뒷부분을 읽지 않으면 거기 있는 요건을 놓칠 수 있다(특히 '단, …'처럼 자격을 넓히는 문구)."""
    notice = NoticeInput(
        title="장학",
        body="첨부 참조",
        attachments=(AttachmentInput(1, "요강.hwpx", _long_guide()),),
    )
    llm = ScriptedLlm(
        call(READ_TEXT, attachment_no=1, reason="요강 확인"), call(SUBMIT, **submission(GUIDE_GPA))
    )
    result, _ = await run(llm, notice, limits=Limits(max_read_chars=500))

    output = llm.requests[1].turns[-1].results[0].content["output"]  # type: ignore[union-attr]
    # 학생에게 보이는 이유라 첨부는 파일 이름으로 쓴다
    expected = f"첨부 '요강.hwpx' {output['next_offset']:,}/{output['chars']:,}자만 읽음"
    assert expected in result.review_reasons and result.needs_review


async def test_reading_to_the_end_is_not_partial() -> None:
    notice = NoticeInput(
        title="장학",
        body="첨부 참조",
        attachments=(AttachmentInput(1, "요강.hwpx", _long_guide(8)),),
    )

    def next_chunk(request: Any) -> Any:
        output = request.turns[-1].results[0].content["output"]
        return call(READ_TEXT, attachment_no=1, offset=output["next_offset"], reason="이어 읽기")

    llm = ScriptedLlm(
        call(READ_TEXT, attachment_no=1, reason="요강 확인"),
        next_chunk,
        call(SUBMIT, **submission(GUIDE_GPA)),
    )
    result, _ = await run(llm, notice, limits=Limits(max_read_chars=200))
    assert "next_offset" not in llm.requests[2].turns[-1].results[0].content["output"]  # type: ignore[union-attr]
    assert result.review_reasons == ()


async def test_long_body_is_cut_and_flagged() -> None:
    body = BODY + "\n" + "참고 문구입니다. " * 50
    result, _ = await run(
        ScriptedLlm(call(SUBMIT, **submission(GPA))),
        NoticeInput(title="장학", body=body),
        limits=Limits(max_body_chars=300),
    )
    assert "본문이 길어 앞 300자만 읽음" in result.review_reasons


async def test_empty_model_reply_is_retried_without_an_empty_turn() -> None:
    """차단·잘못된 함수 호출로 빈 답이 오면 빈 model 턴을 보내지 않고 같은 요청을 다시 보낸다."""
    llm = ScriptedLlm(ModelTurn(text=None), call(SUBMIT, **submission(GPA)))
    result, _ = await run(llm)
    assert llm.requests[1].turns == llm.requests[0].turns
    assert result.succeeded


async def test_control_characters_from_the_model_are_removed() -> None:
    nul = {**GPA, "evidence_text": "직전 학기\x00 평점평균 3.0 이상(4.5 만점)"}
    result, log = await run(ScriptedLlm(call(SUBMIT, **submission(nul))))
    assert result.requirements[0].evidence_text == "직전 학기 평점평균 3.0 이상(4.5 만점)"
    assert not result.requirements[0].is_ambiguous  # 지운 뒤에는 원문과 맞는다
    assert "\x00" not in json.dumps(log.tools[0].input, ensure_ascii=False)


async def test_broken_scan_is_reported_and_the_run_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise UnreadableAttachment("PDF 쪽을 잘라 낼 수 없어요(파일이 깨졌을 수 있어요)")

    monkeypatch.setattr("app.extraction.sources.vision_payload", broken)
    notice = NoticeInput(
        title="장학", body=BODY, attachments=(AttachmentInput(1, "스캔.pdf", samples.pdf([None])),)
    )
    llm = ScriptedLlm(
        call(READ_IMAGE, attachment_no=1, reason="스캔본"), call(SUBMIT, **submission(GPA))
    )
    result, log = await run(llm, notice)

    assert llm.requests[1].turns[-1].results[0].content == {  # type: ignore[union-attr]
        "error": "PDF 쪽을 잘라 낼 수 없어요(파일이 깨졌을 수 있어요)"
    }
    assert result.attachments[0].error == "PDF 쪽을 잘라 낼 수 없어요(파일이 깨졌을 수 있어요)"
    assert result.succeeded and "읽지 못한 첨부가 있음" in result.review_reasons
    assert len(log.llm) == 2  # Vision 호출 전에 막혔다
