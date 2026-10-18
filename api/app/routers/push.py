"""웹 푸시 구독 (F-33, API 명세 10장). 브라우저가 구독을 만들면 여기에 올린다.

구독을 저장만 하고 어떤 값도 돌려주지 않는다 — 키는 브라우저가 이미 갖고 있고, 서버가 되돌려 줄
이유가 없다. 해제는 주소로 한다(`DELETE`). **내 구독만** 지울 수 있다.
"""

from fastapi import APIRouter, Response

from app.auth import CurrentUserDep
from app.repositories.push import PushRepoDep
from app.schemas.push import PushSubscribed, PushSubscriptionRequest, PushUnsubscribeRequest

router = APIRouter(prefix="/push", tags=["알림"])


@router.post("/subscriptions", status_code=201, response_model=PushSubscribed)
async def subscribe(
    body: PushSubscriptionRequest, user: CurrentUserDep, repo: PushRepoDep
) -> PushSubscribed:
    """구독을 저장한다. 같은 주소를 다시 보내면 키만 갱신한다(201은 그대로다)."""
    await repo.save(
        user.id,
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        user_agent=body.user_agent,
    )
    return PushSubscribed()


@router.delete("/subscriptions", status_code=204, response_class=Response)
async def unsubscribe(
    body: PushUnsubscribeRequest, user: CurrentUserDep, repo: PushRepoDep
) -> Response:
    """구독을 지운다. 없는 주소여도 204다(브라우저가 이미 지웠을 수 있다)."""
    await repo.remove(user.id, body.endpoint)
    return Response(status_code=204)
