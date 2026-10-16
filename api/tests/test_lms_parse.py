"""과목명 파싱과 포털 계획서 링크(F-14·F-50). 녹화한 8과목의 꼴을 그대로 쓴다."""

import pytest

from app.lms.parse import PORTAL_SYLLABUS_URL, course_name


@pytest.mark.parametrize(
    ("name", "short", "year", "term", "no"),
    [
        ("202620HY23525_데이터베이스", "데이터베이스", 2026, 20, "23525"),
        ("202620HY20165_사회봉사", "사회봉사", 2026, 20, "20165"),
        ("202620HY23530_글로벌SW창업디자인2", "글로벌SW창업디자인2", 2026, 20, "23530"),
        ("202620HY25123_AI+X공학융합프로젝트", "AI+X공학융합프로젝트", 2026, 20, "25123"),
        ("202510HY12345_선형대수", "선형대수", 2025, 10, "12345"),
    ],
)
def test_it_splits_the_course_name(name: str, short: str, year: int, term: int, no: str) -> None:
    parsed = course_name(name)
    assert parsed.short_name == short
    assert (parsed.portal_year, parsed.portal_term, parsed.portal_course_no) == (year, term, no)


def test_it_builds_the_portal_syllabus_link() -> None:
    parsed = course_name("202620HY23525_데이터베이스")
    assert parsed.syllabus_url == PORTAL_SYLLABUS_URL.format(year=2026, term=20, course_no="23525")
    assert "year=2026" in (parsed.syllabus_url or "")
    assert "suup=23525" in (parsed.syllabus_url or "")


def test_a_name_in_another_shape_keeps_the_whole_name_and_has_no_link() -> None:
    parsed = course_name("대학원 세미나(비정규)")
    assert parsed.short_name == "대학원 세미나(비정규)"
    assert parsed.syllabus_url is None
    assert parsed.portal_course_no is None


def test_the_term_label_comes_from_the_code_and_falls_back_to_learningx() -> None:
    assert course_name("202620HY23525_데이터베이스").term("2026년 2학기") == "2026-2"
    assert course_name("202510HY12345_선형대수").term(None) == "2025-1"
    assert course_name("202621HY12345_겨울특강").term(None) == "2026-겨울"
    # 꼴이 다르면 LearningX가 준 학기 이름을 그대로 쓴다
    assert course_name("세미나").term("2026년 2학기") == "2026년 2학기"
    assert course_name("세미나").term(None) is None
