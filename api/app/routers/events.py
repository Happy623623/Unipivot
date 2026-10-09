from fastapi import APIRouter, Response

from app.auth import CurrentUserDep
from app.repositories.meta import MetaRepoDep
from app.schemas.meta import EventRequest

router = APIRouter(prefix="/events", tags=["사용 기록"])


@router.post("", status_code=204, response_class=Response)
async def record_event(body: EventRequest, user: CurrentUserDep, meta: MetaRepoDep) -> Response:
    """화면에서만 알 수 있는 사용 이벤트 (제품 지표, PRD 8장). 화면은 응답을 기다리지 않는다."""
    await meta.record_event(user.id, body.event, body.opportunity_id)
    return Response(status_code=204)
