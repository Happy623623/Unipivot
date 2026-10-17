"""강의계획서 일정 추출 (F-14).

학생이 포털 계획서를 PDF로 저장해 올리면, 글자를 뽑아 **중간·기말·발표·과제** 일정만 골라낸다.
일반 강의 주차는 넣지 않는다 — 플래너가 수업 일정으로 가득 차면 쓸모가 없다.
"""

from app.syllabi.extract import (
    DEFAULT_TIME,
    DraftItem,
    Extracted,
    SyllabusError,
    extract,
    extracted_items,
    semester_range,
)
from app.syllabi.prompt import EXTRACT_SPEC, system_prompt

__all__ = [
    "DEFAULT_TIME",
    "EXTRACT_SPEC",
    "DraftItem",
    "Extracted",
    "SyllabusError",
    "extract",
    "extracted_items",
    "semester_range",
    "system_prompt",
]
