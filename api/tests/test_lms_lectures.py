"""주차학습 강의(11/24): 응답에서 강의만 고르기와 화면의 한 단어(다 들음·안 들음·놓침…).

응답 모양은 11/12 한양대 실측(학생 본인 계정, 읽기만)이다 — `tests/lms_samples.py`의 주차학습 샘플.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.lms.lectures import Lecture, lecture_status, lectures
from tests.lms_samples import DB_LECTURE_MODULES, ML_LECTURE_MODULES, lecture_item

NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)  # 2026-10-16 12:00 KST


def test_it_picks_the_lectures_and_skips_everything_else() -> None:
    found = lectures(DB_LECTURE_MODULES)
    # 출석 대상이 아닌 PDF(8569303)·퀴즈(8569304)·공개하지 않은 강의(8570004)는 강의가 아니다
    assert [(one.key, one.kind) for one in found] == [
        ("8569302", "video"),
        ("8570001", "video"),
        ("8570002", "live"),
        ("8570003", "material"),
        ("8570005", "video"),
    ]
    assert [one.module_name for one in found] == ["3주차", "6주차", "6주차", "6주차", "7주차"]
    assert [one.position for one in found] == [0, 1, 2, 3, 4]  # 응답 순서(주차 순)


def test_it_keeps_the_student_state_and_the_deadlines() -> None:
    first, open_one, live = lectures(DB_LECTURE_MODULES)[:3]
    assert (first.completed, first.attendance, first.period) == (True, "attendance", "closed")
    assert first.duration_seconds == 1932  # 초는 반올림한다
    assert first.canvas_item_id == 8569302  # Canvas 주차 항목 번호와 같다('LMS에서 듣기' 주소)
    assert open_one.due_at == datetime(2026, 10, 19, 14, 59, 59, tzinfo=UTC)
    assert open_one.late_at == datetime(2026, 10, 26, 14, 59, 59, tzinfo=UTC)
    assert open_one.unlock_at == datetime(2026, 10, 13, tzinfo=UTC)
    assert (live.completed, live.attendance, live.duration_seconds) == (False, "absent", None)


def test_a_lecture_without_a_canvas_number_is_keyed_by_its_learningx_number() -> None:
    unknown, late = lectures(ML_LECTURE_MODULES)
    assert (unknown.key, unknown.canvas_item_id) == ("lx:71001", None)
    # LearningX가 완료 여부를 알 수 없다고 했으면 믿지 않는다 — "안 들음"으로 세지 않는다
    assert unknown.completed is None
    assert (late.key, late.completed) == ("8631790", False)


def test_the_status_word_follows_the_period_learningx_gives() -> None:
    by_key = {one.key: lecture_status(one, NOW) for one in lectures(DB_LECTURE_MODULES)}
    by_key |= {one.key: lecture_status(one, NOW) for one in lectures(ML_LECTURE_MODULES)}
    assert by_key == {
        "8569302": "done",
        "8570001": "todo",
        "8570002": "missed",
        "8570003": "done",
        "8570005": "upcoming",
        "lx:71001": "unknown",
        "8631790": "late",
    }


def _lecture(**values: Any) -> Lecture:
    base: dict[str, Any] = {
        "key": "1",
        "canvas_item_id": 1,
        "module_name": "1주차",
        "title": "강의",
        "kind": "video",
        "completed": False,
        "attendance": "none",
        "period": None,
        "unlock_at": None,
        "due_at": None,
        "late_at": None,
        "duration_seconds": None,
        "position": 0,
    }
    return Lecture(**{**base, **values})


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"completed": True, "period": "late_after"}, "done"),  # 다 들었으면 기간과 상관없다
        ({"completed": None, "period": "open"}, "unknown"),
        # LearningX가 준 기간을 먼저 믿는다(마감 시각이 지났어도 open이면 아직이다)
        ({"period": "open", "due_at": NOW - timedelta(days=1)}, "todo"),
        ({"period": "not_open"}, "upcoming"),
        ({"period": "late"}, "late"),
        ({"period": "late_after"}, "missed"),
        ({"period": "closed"}, "missed"),
        # 기간이 없으면 시각으로 가늠한다
        ({"unlock_at": NOW + timedelta(hours=1)}, "upcoming"),
        ({"due_at": NOW + timedelta(hours=1)}, "todo"),
        ({"due_at": NOW - timedelta(hours=1), "late_at": NOW + timedelta(days=6)}, "late"),
        ({"due_at": NOW - timedelta(hours=1), "late_at": NOW - timedelta(minutes=1)}, "missed"),
        ({"due_at": NOW - timedelta(hours=1)}, "missed"),
        ({}, "todo"),  # 마감이 없는 강의는 아직 들을 수 있다
    ],
)
def test_the_status_word(values: dict[str, Any], expected: str) -> None:
    assert lecture_status(_lecture(**values), NOW) == expected


def test_odd_responses_are_read_without_falling_over() -> None:
    modules: list[Any] = [
        "not a module",
        # `items` 칸으로 온 모듈
        {"title": None, "items": [lecture_item(501, "주차 이름 없는 강의")]},
        {"title": "2주차", "module_items": "not a list"},
        {
            "title": "3주차",
            "module_items": [
                lecture_item(501, "같은 강의가 또"),  # 같은 번호는 한 번만
                lecture_item(None, "번호가 하나도 없는 강의", item_id=0),
                {**lecture_item(502, "본문 없는 항목"), "content_data": None},
                {
                    **lecture_item(503, ""),
                    "content_data": {**lecture_item(503, "")["content_data"]},
                },
                lecture_item(504, "길이가 참·거짓", duration=True),
                lecture_item(505, "시각이 깨진 강의", due_at="다음 주"),
                lecture_item(506, "완료 칸이 글자", completed="true"),
            ],
        },
    ]
    found = {one.key: one for one in lectures(modules)}
    assert list(found) == ["501", "503", "504", "505", "506"]
    assert found["501"].module_name == "주차 미정"
    assert found["503"].title == "(제목 없음)"
    assert found["504"].duration_seconds is None
    assert found["505"].due_at is None
    assert found["506"].completed is None  # 참·거짓이 아니면 모른다
