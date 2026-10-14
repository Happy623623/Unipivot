from uuid import UUID

from fastapi import APIRouter

from app.auth import CurrentUserDep
from app.errors import ApiError
from app.repositories.runs import RunRepoDep
from app.schemas.prepare import RunView

router = APIRouter(prefix="/runs", tags=["실행"])


@router.get("/{run_id}", response_model=RunView)
async def read_run(run_id: UUID, user: CurrentUserDep, repo: RunRepoDep) -> RunView:
    """실행 진행·결과(API 명세 11장). 본인 실행만 본다. 배치 실행은 403, 남의 실행·없는 실행은 404다.

    steps는 처리 과정(F-42)이고, 끝나면 result(준비하기는 계획·서류·할 일)나 error(코드·문구)가 붙는다.
    """
    run = await repo.run(str(run_id))
    if run is not None and run.user_id is None:
        raise ApiError(403, "FORBIDDEN", "이 실행은 볼 수 없어요.")
    if run is None or run.user_id != user.id:
        raise ApiError(404, "NOT_FOUND", "실행을 찾을 수 없어요.")
    result = None
    if run.status == "succeeded" and run.trigger_type == "prepare":
        result = await repo.prepare_result(user.id, run.id)
    return RunView(
        id=run.id,
        trigger_type=run.trigger_type,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        latency_ms=run.latency_ms,
        steps=await repo.steps(run.id),
        result=result,
        error=run.error(),
    )
