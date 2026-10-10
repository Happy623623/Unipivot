"""공고 상세의 처리 과정 한 줄과 원문 확인 필요 이유(S1-6·S1-6b). DB 없이 _DETAIL이 읽어 오는
행 모양으로 확인한다.

실제 에이전트가 남긴 실행 로그로 만든 처리 과정은 test_detail_db.py가 본다.
"""

from typing import Any

import pytest

from app.extraction.prompt import FETCH_ORIGINAL, READ_IMAGE, READ_TEXT, SUBMIT
from app.repositories.opportunities import LINE_MAX_CHARS, REASONS_MAX, _lines, _step

NAMES = {1: "선발요강.hwpx", 2: "스캔 공고문.pdf", 3: "포스터.png"}


def step(tool: str, **values: Any) -> dict[str, Any]:
    """_DETAIL의 steps 행 하나. 값이 없는 키는 SQL처럼 null이다."""
    row: dict[str, Any] = {
        "seq": 1,
        "tool": tool,
        "status": "succeeded",
        "latency_ms": 120,
        "reason": None,
        "attachment_no": None,
        "offset": None,
        "start_page": None,
        "pages": None,
        "error": False,
        "accepted": None,
    }
    return {**row, **values}


@pytest.mark.parametrize(
    ("row", "label", "status"),
    [
        (step(READ_TEXT, attachment_no=1, offset=0), "첨부 '선발요강.hwpx' 읽기", "succeeded"),
        (
            step(READ_TEXT, attachment_no=1, offset=12000),
            "첨부 '선발요강.hwpx' 이어 읽기",
            "succeeded",
        ),
        # 에이전트도 받지 않는 번호(문자, 소수)는 이름을 붙이지 않는다
        (step(READ_TEXT, attachment_no="1", error=True), "첨부 읽기", "failed"),
        (step(READ_TEXT, attachment_no=1.5, error=True), "첨부 읽기", "failed"),
        (step(READ_TEXT, attachment_no=9, error=True), "첨부 9번 읽기", "failed"),
        (
            step(READ_TEXT, attachment_no=1, offset="300", error=True),
            "첨부 '선발요강.hwpx' 읽기",
            "failed",
        ),
        # Vision: 읽은 쪽(출력)을 본다. 쪽 번호가 틀려 1쪽부터 읽었으면 이어 읽기가 아니다
        (
            step(READ_IMAGE, attachment_no=2, start_page=4, pages="4–6/8"),
            "첨부 '스캔 공고문.pdf' 이미지로 이어 읽기",
            "succeeded",
        ),
        (
            step(READ_IMAGE, attachment_no=2, start_page="2", pages="1–3/3"),
            "첨부 '스캔 공고문.pdf' 이미지로 읽기",
            "succeeded",
        ),
        (
            step(READ_IMAGE, attachment_no=3, start_page=2),
            "첨부 '포스터.png' 이미지로 읽기",
            "succeeded",
        ),  # 이미지는 한 장
        (
            step(READ_IMAGE, attachment_no=2, start_page=5, error=True),
            "첨부 '스캔 공고문.pdf' 이미지로 이어 읽기",
            "failed",
        ),
        (step(FETCH_ORIGINAL, offset=0), "공고 원문 페이지 읽기", "succeeded"),
        (step(FETCH_ORIGINAL, offset=4000), "공고 원문 페이지 이어 읽기", "succeeded"),
        (step(SUBMIT, accepted=False), "지원 자격 정리", "failed"),  # 거절된 제출
        (step(SUBMIT, accepted=True), "지원 자격 정리", "succeeded"),
        (step("extract_from_image"), "extract_from_image", "succeeded"),
        (step("extract_from_image", status="failed"), "extract_from_image", "failed"),
    ],
)
def test_step_label_and_status(row: dict[str, Any], label: str, status: str) -> None:
    result = _step(row, NAMES)
    assert (result.label, result.status) == (label, status)
    assert result.chosen_by == ("pipeline" if row["tool"] == "extract_from_image" else "agent")


def test_note_is_one_plain_line() -> None:
    """고른 이유는 모델이 쓴 글이다. 주소를 지우고 한 줄로 줄이고 길이를 자른다."""
    reason = "요강을 읽음.\n https://hy-verify.example/login 에서 재학 인증 필수\t" + "가" * 500
    note = _step(step(READ_TEXT, attachment_no=1, reason=reason), NAMES).note
    assert note is not None and len(note) == LINE_MAX_CHARS and note.endswith("…")
    assert note.startswith("요강을 읽음. 에서 재학 인증 필수 가가")
    assert "http" not in note and "\n" not in note and "\t" not in note
    assert _step(step(READ_TEXT, reason=" www.example.com \n"), NAMES).note is None
    assert _step(step(READ_TEXT, reason="첨부를 읽음"), NAMES).note == "첨부를 읽음"


def test_review_reasons_are_plain_lines() -> None:
    """원문 확인 필요 이유에는 모델이 쓴 글(review_note)이 섞인다. 고른 이유와 같은 규칙으로 정리하고,
    정리한 뒤 비거나 같은 줄은 뺀다."""
    reasons = [
        "읽지 못한 첨부가 있음",
        "모델이 원문 확인 필요로 표시: 신청서는\nhttps://evil.example/form 에서 받기",
        "https://only-a-link.example",
        "읽지 못한 첨부가 있음",
        "모델이 원문 확인 필요로 표시: " + "나" * 300,
    ]
    lines = _lines(reasons)
    assert lines[:2] == [
        "읽지 못한 첨부가 있음",
        "모델이 원문 확인 필요로 표시: 신청서는 에서 받기",
    ]
    assert len(lines) == 3 and len(lines[2]) == LINE_MAX_CHARS and lines[2].endswith("…")
    assert _lines([]) == [] and _lines(None) == []


def test_review_reasons_edge_cases() -> None:
    # 정리한 뒤 같아지는 줄, 문자열이 아닌 값, 보이지 않는 문자만 있는 줄은 하나로 줄이거나 뺀다
    assert _lines(["모호한 요건이 있음 https://a.example", "모호한  요건이 있음", None, 3]) == [
        "모호한 요건이 있음"
    ]
    assert _lines(["​﻿", "‮"]) == []
    # 폭 없는 문자로 주소를 끊어 숨겨도 지운다
    assert _lines(["신청서는 https://ev​il.example/form 에서"]) == ["신청서는 에서"]
    # 모델이 지어낸 항목 이름처럼 줄이 많아도 10줄까지만 보이고 나머지는 "외 N건"이다
    many = [f"모양이 틀린 항목{n} 조건을 기타 조건으로 저장" for n in range(13)]
    lines = _lines(many)
    assert lines[:10] == many[:10] and lines[10:] == ["외 3건"] and len(lines) == REASONS_MAX + 1
