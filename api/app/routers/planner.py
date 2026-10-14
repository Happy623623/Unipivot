"""플래너 할 일 (F-43, API 명세 7장). 기간 조회와 직접 추가·수정·삭제."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.auth import CurrentUserDep
from app.errors import ApiError
from app.repositories.planner import PlannerRepoDep
from app.schemas.planner import (
    PlannerResponse,
    PlannerTask,
    PlannerTaskCreate,
    PlannerTaskPatch,
)

router = APIRouter(prefix="/planner", tags=["플래너"])

MAX_DAYS = 400  # 한 번에 받는 기간 상한. 화면은 한 달이고 앞뒤로 조금 더 받는다
NOT_FOUND = "할 일을 찾을 수 없어요."
# 출처별로 고칠 수 있는 항목(API 명세 7장). 빈 집합이면 아무것도 못 고친다
EDITABLE: dict[str, set[str]] = {
    "manual": {"title", "due_date", "is_done"},
    # 준비 할 일은 날짜만 옮긴다. 제목은 공고의 서류 이름이라 고정이고, 지우려면 준비를 다시 한다
    "prep_plan": {"due_date", "is_done"},
    "syllabus": {"due_date", "is_done"},
    # LMS 과제·공지는 LMS가 기준이라 완료만 바꾼다(F-51)
    "lms_assignment": {"is_done"},
    "lms_announcement": {"is_done"},
}


@router.get("/tasks", response_model=PlannerResponse)
async def read_tasks(
    user: CurrentUserDep,
    repo: PlannerRepoDep,
    from_: str = Query(alias="from", description="YYYY-MM-DD"),
    to: str = Query(description="YYYY-MM-DD"),
    include_done: bool = True,
) -> PlannerResponse:
    """기간 안의 할 일과 마커(준비 중인 공고의 마감일). 날짜는 KST다."""
    start, end = _day(from_, "from"), _day(to, "to")
    if end < start:
        raise _invalid({"to": "끝 날짜는 시작 날짜보다 뒤여야 해요."})
    if (end - start).days + 1 > MAX_DAYS:
        raise _invalid({"to": f"한 번에 {MAX_DAYS}일까지 받을 수 있어요."})
    return await repo.tasks(user.id, start=start, end=end, include_done=include_done)


@router.post("/tasks", status_code=201, response_model=PlannerTask)
async def add_task(
    body: PlannerTaskCreate, user: CurrentUserDep, repo: PlannerRepoDep
) -> PlannerTask:
    """직접 추가(source = manual)."""
    return await repo.add(user.id, body.title, body.due_date)


@router.patch("/tasks/{task_id}", response_model=PlannerTask)
async def change_task(
    task_id: UUID, body: PlannerTaskPatch, user: CurrentUserDep, repo: PlannerRepoDep
) -> PlannerTask:
    """보낸 필드만 바꾼다. 출처가 허락하지 않는 항목이면 400 FIELD_READ_ONLY다."""
    asked = body.fields()
    if not asked:
        raise _invalid({"body": "바꿀 내용을 적어 주세요."})
    task = await repo.task(user.id, str(task_id))
    if task is None:
        raise ApiError(404, "NOT_FOUND", NOT_FOUND)
    locked = sorted(asked - EDITABLE.get(task.source, set()))
    if locked:
        raise ApiError(
            400,
            "FIELD_READ_ONLY",
            _read_only_message(task.source),
            {"fields": locked},
        )
    return await repo.update(user.id, task.id, {name: getattr(body, name) for name in asked})


@router.delete("/tasks/{task_id}", status_code=204, response_class=Response)
async def remove_task(task_id: UUID, user: CurrentUserDep, repo: PlannerRepoDep) -> Response:
    """직접 추가한 할 일만 지운다. 나머지는 400 TASK_NOT_DELETABLE이다."""
    task = await repo.task(user.id, str(task_id))
    if task is None:
        raise ApiError(404, "NOT_FOUND", NOT_FOUND)
    if task.source != "manual":
        raise ApiError(400, "TASK_NOT_DELETABLE", _not_deletable_message(task.source))
    await repo.remove(user.id, task.id)
    return Response(status_code=204)


def _day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _invalid({field: "날짜를 YYYY-MM-DD로 적어 주세요."}) from None


def _invalid(fields: dict[str, str]) -> ApiError:
    return ApiError(422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": fields})


def _read_only_message(source: str) -> str:
    if source == "prep_plan":
        return "준비 일정으로 만든 할 일은 날짜만 옮길 수 있어요."
    if source == "syllabus":
        return "강의계획서에서 온 할 일은 날짜만 옮길 수 있어요."
    return "LMS에서 가져온 할 일은 완료만 바꿀 수 있어요."


def _not_deletable_message(source: str) -> str:
    if source == "prep_plan":
        return "준비 일정으로 만든 할 일은 지울 수 없어요. 공고 상세에서 확인해 주세요."
    return "직접 추가한 할 일만 지울 수 있어요."
