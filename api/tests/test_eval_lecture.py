"""S19가 올리는 강의자료 PDF(app/eval/lecture.py). DB 없이 본다.

PDF는 코드로 만든 가장 작은 모양이다. 올리기 검사(app/uploads)와 요약 서비스(app/materials)가 쓰는 같은 글자
뽑기로 읽어서, 짧은 노트는 상한 안·긴 노트는 **글자 어림으로** 상한 밖인지 본다(글자 상한에서 잘려 넘는 것이
아니다). pypdf가 올라가 글자가 달라지면 여기서 먼저 걸린다.
"""

import pytest

from app.config import Settings
from app.eval.lecture import (
    FIRST_LINE,
    LAST_LINE,
    LONG_PAGE_COUNT,
    SHORT_PAGES,
    long_notes,
    notes_pdf,
    short_notes,
)
from app.materials.summarize import TEXT_MAX_CHARS, estimate_tokens
from app.uploads import LECTURE_MAX_PAGES, inspect_lecture_material, pdf_text

LIMIT = Settings.model_fields["material_max_tokens"].default


def test_the_short_notes_read_back_line_by_line_within_the_limit() -> None:
    data = short_notes()
    assert inspect_lecture_material(data).page_count == len(SHORT_PAGES) == 3
    text = pdf_text(data, max_chars=TEXT_MAX_CHARS)
    assert text.splitlines() == [line for page in SHORT_PAGES for line in page]
    assert text.startswith(FIRST_LINE) and text.rstrip().endswith(LAST_LINE)
    assert estimate_tokens(text) < LIMIT


def test_the_long_notes_can_be_uploaded_but_are_over_the_token_limit() -> None:
    data = long_notes()
    assert inspect_lecture_material(data).page_count == LONG_PAGE_COUNT < LECTURE_MAX_PAGES
    text = pdf_text(data, max_chars=TEXT_MAX_CHARS)
    # 글자 상한(잘림)이 아니라 토큰 어림으로 넘는다 — 서비스가 413에 적는 text_tokens가 어림값이다
    assert len(text) < TEXT_MAX_CHARS
    assert estimate_tokens(text) > LIMIT
    assert text.splitlines()[0] == "Database Systems - Lecture notes, week 1, page 1"
    assert text.splitlines()[-1].startswith(f"Slide {LONG_PAGE_COUNT}.")


def test_the_same_notes_are_the_same_bytes() -> None:
    """실행마다 같은 파일이다(저장소의 sha256이 같다)."""
    assert short_notes() == short_notes() and long_notes() == long_notes()
    assert short_notes() != long_notes()


def test_brackets_survive_and_only_ascii_is_written() -> None:
    data = notes_pdf([["f(x) = a \\ b (note)"]])
    assert pdf_text(data).strip() == "f(x) = a \\ b (note)"
    with pytest.raises(ValueError, match="ASCII"):
        notes_pdf([["강의 노트"]])
