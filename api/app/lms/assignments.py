"""Canvas 과제 응답 → 저장할 값 (F-51, API 명세 9장의 10/16 녹화 규칙).

녹화(6과목·과제 17건)에서 확정한 것만 따른다:

- 마감은 `due_at ?? lock_at`이다. 17건 중 5건은 `due_at`이 null이고 `lock_at`만 있었다
- 제출 여부는 `submission.workflow_state`다. 과목 전체 기준인 `has_submitted_submissions`는 쓰지
  않는다(내가 내지 않은 과제에도 true로 온다). 퀴즈는 자동 채점돼 바로 `graded`로 왔다(17건 중 4건)
- `pending_review`(냈고 손 채점만 남음)도 제출로 센다. 녹화에서는 못 봤지만 DB enum에 있는 값이고,
  제출로 보지 않으면 할 일이 끝나지 않고 알림도 멈추지 않는다
- `submission`이 없거나 모르는 상태면 `unsubmitted`로 둔다. 모르는 값을 그대로 넣으면 DB enum이 막는다
- 아직 열지 않은 과제(`published`가 false)는 학생에게 보이지 않으니 건너뛴다(녹화 17건은 모두 true)

시각은 UTC(`timestamptz`)로 저장한다. 화면에서 KST로 바꾼다.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.lms.parse import is_canvas_id

logger = logging.getLogger(__name__)

# DB enum(lms_submission_state)에 있는 값. 그 밖은 unsubmitted로 둔다
STATES = ("unsubmitted", "submitted", "graded", "pending_review")
# 제출로 보는 상태(명세 9장). `pending_review`는 냈고 손 채점만 남은 상태라 제출로 센다
SUBMITTED = ("submitted", "graded", "pending_review")
NO_TITLE = "(제목 없음)"  # 이름이 빈 과제도 할 일이라 버리지 않는다


@dataclass(frozen=True)
class CanvasAssignment:
    """저장 직전의 과제 하나. `lms_assignments` 칸과 같은 이름이다."""

    canvas_assignment_id: int
    title: str
    due_at: datetime | None
    html_url: str | None
    submission_state: str
    submitted_at: datetime | None

    @property
    def submitted(self) -> bool:
        return self.submission_state in SUBMITTED


def assignments(raw: list[Any]) -> list[CanvasAssignment]:
    """과제 목록 응답을 저장할 값으로. 쓸 수 없는 항목은 건너뛴다."""
    items = []
    for one in raw:
        parsed = assignment(one)
        if parsed is not None:
            items.append(parsed)
    return items


def assignment(raw: Any) -> CanvasAssignment | None:
    """과제 하나. 번호가 없거나 아직 열지 않은 과제면 None이다."""
    if not isinstance(raw, dict) or not is_canvas_id(raw.get("id")):
        return None
    if raw.get("published") is False:  # 아직 열지 않은 과제는 학생에게 보이지 않는다
        return None
    submission = raw.get("submission") if isinstance(raw.get("submission"), dict) else {}
    state = _state(submission.get("workflow_state"))
    return CanvasAssignment(
        canvas_assignment_id=raw["id"],
        title=(raw.get("name") or "").strip() or NO_TITLE,
        due_at=moment(raw.get("due_at")) or moment(raw.get("lock_at")),
        html_url=raw.get("html_url") if isinstance(raw.get("html_url"), str) else None,
        submission_state=state,
        submitted_at=moment(submission.get("submitted_at")) if state in SUBMITTED else None,
    )


def _state(value: Any) -> str:
    if value in STATES:
        return str(value)
    if value is not None:
        logger.info("모르는 제출 상태라 unsubmitted로 둬요: %r", value)
    return "unsubmitted"


def moment(value: Any) -> datetime | None:
    """Canvas의 `2026-10-13T14:59:59Z` → UTC 시각. 꼴이 다르면 None이다."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.info("읽을 수 없는 시각이라 비워 둬요: %r", value)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
