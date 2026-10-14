"""역산 준비 일정(F-31, PRD 6장 build_prep_plan). 코드로만 만든다.

서류마다 "○○ 준비" 할 일 하나(마감 2일 전 − 소요 일수)와 마지막 "신청 제출" 할 일 하나(마감 1일 전)다.
오늘보다 앞선 날짜는 오늘로 둬서 지난 할 일이 생기지 않게 한다(API 명세 7장). 상시 공고는 학생이 고른
목표일을 마감일처럼 쓴다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

SUBMIT_TITLE = "신청 제출"
DOCUMENT_BUFFER_DAYS = 2  # 서류는 마감 이틀 전까지 갖춘다
SUBMIT_BUFFER_DAYS = 1  # 신청은 마감 하루 전에 낸다
UNKNOWN_LEAD_DAYS = 1  # 소요 일수를 모르는 서류는 하루를 둔다


@dataclass(frozen=True)
class PlanDocument:
    id: str
    name: str
    lead_days: int | None


@dataclass(frozen=True)
class TaskDraft:
    title: str
    due_date: date
    document_id: str | None
    sort_order: int


def build_tasks(documents: Sequence[PlanDocument], deadline: date, today: date) -> list[TaskDraft]:
    """서류 할 일(서류 순서대로)과 신청 제출 할 일. 서류 수와 서류 할 일 수가 같다(PRD F-31)."""

    def due(days_before: int) -> date:
        return max(today, deadline - timedelta(days=days_before))

    tasks = [
        TaskDraft(
            title=f"{document.name} 준비",
            due_date=due(
                DOCUMENT_BUFFER_DAYS
                + (UNKNOWN_LEAD_DAYS if document.lead_days is None else document.lead_days)
            ),
            document_id=document.id,
            sort_order=index,
        )
        for index, document in enumerate(documents)
    ]
    tasks.append(TaskDraft(SUBMIT_TITLE, due(SUBMIT_BUFFER_DAYS), None, len(tasks)))
    return tasks
