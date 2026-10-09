"""추출 CLI: 파일을 읽어 에이전트를 돌리고, 도구 호출·토큰·비용과 결과 JSON을 찍는다(가짜 LLM)."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.extraction import ExtractionAgent
from app.extraction.cli import main
from app.extraction.prompt import READ_TEXT, SUBMIT
from tests import samples
from tests.llm_fakes import ScriptedLlm, call
from tests.samples import hp

pytestmark = pytest.mark.anyio


async def test_cli_prints_steps_cost_and_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = tmp_path / "본문.html"
    body.write_text("<p>자세한 자격은 <b>첨부</b>를 보세요.</p>", encoding="utf-8")
    guide = tmp_path / "요강.hwpx"
    guide.write_bytes(samples.hwpx(hp("직전 학기 평점평균 3.0 이상")))
    llm = ScriptedLlm(
        call(READ_TEXT, attachment_no=1, reason="요강에 자격이 있어서 읽음"),
        call(
            SUBMIT,
            requirements=[
                {
                    "clause_no": 1,
                    "field": "gpa_last_semester",
                    "operator": "gte",
                    "value_json": "3.0",
                    "evidence_text": "직전 학기 평점평균 3.0 이상",
                    "is_ambiguous": False,
                }
            ],
            documents=[],
            deadline="2026-10-24",
            confidence=0.9,
            needs_review=False,
        ),
    )
    made: dict[str, Any] = {}

    def make_agent(settings: Any, **options: Any) -> ExtractionAgent:
        made.update(options)
        return ExtractionAgent(llm, model="gemini-3.8-flash")

    argv = [
        "--title",
        "○○장학",
        "--body",
        str(body),
        "--attach",
        str(guide),
        "--posted",
        "2026-10-08",
    ]
    assert await main(argv, make_agent=make_agent) == 0

    out = capsys.readouterr().out
    assert "[1] read_attachment_text — 요강에 자격이 있어서 읽음" in out
    assert "LLM gemini-3.8-flash: 입력 1,000 · 출력 200 토큰" in out
    assert "합계: LLM 2번 · 입력 2,000 · 출력 400 토큰" in out
    result = json.loads(out[out.index("\n{\n") :])  # 마지막에 찍는 결과 JSON
    assert result["succeeded"] is True and result["deadline_at"] == "2026-10-24T23:59:00+09:00"
    assert result["attachments"][0]["method"] == "hwpx_text"
    assert result["attachments"][0]["text_chars"] > 0 and "text" not in result["attachments"][0]
    first = llm.requests[0].turns[0].text  # type: ignore[union-attr]
    assert "자세한 자격은 첨부를 보세요." in first and "1. 요강.hwpx — HWPX" in first
    assert made == {"fetch_page": None, "model": None}
