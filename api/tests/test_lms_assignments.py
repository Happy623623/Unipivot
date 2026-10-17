"""Canvas 과제 응답 읽기(F-51). DB·네트워크 없이 돈다.

녹화(과제 17건)에서 확정한 규칙만 본다: 마감은 `due_at ?? lock_at`, 제출은 `submission.workflow_state`,
아직 열지 않은 과제는 건너뛴다.
"""

from datetime import UTC, datetime
from typing import Any

from app.lms.assignments import NO_TITLE, assignment, assignments, moment
from tests.lms_samples import DB_ASSIGNMENTS, DRAFT_ASSIGNMENT, HOMEWORK, LAB_REPORT, QUIZ


def test_it_reads_a_homework_with_a_due_date() -> None:
    one = assignment(HOMEWORK)
    assert one is not None
    assert one.canvas_assignment_id == 2811242
    assert one.title == "실습 2주차 결과 제출"
    assert one.due_at == datetime(2026, 10, 20, 14, 59, 59, tzinfo=UTC)  # 20일 23:59:59 KST
    assert one.html_url == "https://lms.test/courses/214023/assignments/2811242"
    assert one.submission_state == "unsubmitted"
    assert one.submitted_at is None
    assert not one.submitted


def test_the_deadline_falls_back_to_lock_at() -> None:
    """녹화 17건 중 5건은 due_at이 null이고 lock_at만 있었다(명세 9장)."""
    one = assignment(LAB_REPORT)
    assert one is not None
    assert LAB_REPORT["due_at"] is None
    assert one.due_at == datetime(2026, 10, 18, 14, 59, 59, tzinfo=UTC)


def test_a_submitted_assignment_keeps_the_time_it_was_submitted() -> None:
    one = assignment(LAB_REPORT)
    assert one is not None
    assert one.submission_state == "submitted"
    assert one.submitted_at == datetime(2026, 10, 15, 23, 2, 17, tzinfo=UTC)
    assert one.submitted


def test_a_quiz_comes_back_already_graded() -> None:
    """퀴즈는 자동 채점돼 graded로 온다. 그래도 '제출한 과제'다."""
    one = assignment(QUIZ)
    assert one is not None
    assert one.submission_state == "graded"
    assert one.submitted


def test_it_skips_an_assignment_that_is_not_published_yet() -> None:
    assert assignment(DRAFT_ASSIGNMENT) is None
    titles = [one.title for one in assignments(DB_ASSIGNMENTS)]
    assert titles == ["실습 2주차 결과 제출", "실습 3주차 결과 제출"]


def test_it_does_not_use_the_course_wide_submitted_flag() -> None:
    """has_submitted_submissions는 과목 전체 기준이라 내가 내지 않은 과제에도 true다(명세 9장)."""
    assert HOMEWORK["has_submitted_submissions"] is True
    one = assignment(HOMEWORK)
    assert one is not None and not one.submitted


def test_an_unknown_submission_state_is_treated_as_not_submitted() -> None:
    """DB enum에 없는 값을 그대로 넣으면 저장이 터진다. 모르는 값은 unsubmitted로 둔다."""
    raw: dict[str, Any] = {**HOMEWORK, "submission": {"workflow_state": "pending_upload"}}
    one = assignment(raw)
    assert one is not None
    assert one.submission_state == "unsubmitted"
    assert one.submitted_at is None


def test_a_submission_can_be_missing_altogether() -> None:
    raw = {key: value for key, value in HOMEWORK.items() if key != "submission"}
    one = assignment(raw)
    assert one is not None
    assert one.submission_state == "unsubmitted"


def test_pending_review_counts_as_submitted() -> None:
    """녹화에서는 못 봤지만 DB enum에 있는 값이다. 냈고 손 채점만 남은 상태라 제출로 센다 —
    제출로 보지 않으면 할 일이 끝나지 않고 알림도 멈추지 않는다."""
    raw: dict[str, Any] = {
        **HOMEWORK,
        "submission": {"workflow_state": "pending_review", "submitted_at": "2026-10-19T05:00:00Z"},
    }
    one = assignment(raw)
    assert one is not None
    assert one.submission_state == "pending_review"
    assert one.submitted
    assert one.submitted_at == datetime(2026, 10, 19, 5, 0, tzinfo=UTC)


def test_it_skips_items_without_a_usable_number() -> None:
    assert assignment({"name": "번호 없음"}) is None
    assert assignment({**HOMEWORK, "id": True}) is None  # bool은 int이지만 번호가 아니다
    assert assignment({**HOMEWORK, "id": 2**63}) is None  # bigint를 넘는 번호
    assert assignment("과제가 아니다") is None


def test_an_assignment_without_a_name_is_kept_with_a_placeholder() -> None:
    """이름이 빈 과제도 할 일이라 버리지 않는다. 화면에 (제목 없음)으로 보인다."""
    one = assignment({**HOMEWORK, "name": "   "})
    assert one is not None
    assert one.title == NO_TITLE


def test_it_reads_times_without_a_zone_as_utc() -> None:
    assert moment("2026-10-20T14:59:59Z") == datetime(2026, 10, 20, 14, 59, 59, tzinfo=UTC)
    assert moment("2026-10-20T14:59:59") == datetime(2026, 10, 20, 14, 59, 59, tzinfo=UTC)
    assert moment("2026-10-20T23:59:59+09:00") == datetime(2026, 10, 20, 14, 59, 59, tzinfo=UTC)


def test_a_broken_time_is_left_empty_instead_of_failing() -> None:
    assert moment("어제") is None
    assert moment("") is None
    assert moment(None) is None
    assert moment(1760000000) is None
    one = assignment({**HOMEWORK, "due_at": "곧", "lock_at": None})
    assert one is not None and one.due_at is None
