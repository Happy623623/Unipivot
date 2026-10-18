"""푸시 발송기 의존 (F-33). 설정에 VAPID 키가 없으면 아무것도 보내지 않는 발송기다.

앱마다 하나를 만들어 둔다(httpx 연결을 다시 쓰려고). 테스트·시나리오는 이 의존을 가짜로 바꾼다.
"""

from typing import Annotated, Any

from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.push.keys import load_keys
from app.push.send import PushSender


def push_sender_for(state: Any, settings: Settings) -> PushSender:
    """앱의 발송기. 요청 밖(스케줄러)에서도 같은 것을 쓰려고 `app.state`를 직접 받는다."""
    if getattr(state, "push_sender", None) is None:
        state.push_sender = PushSender(
            load_keys(private_key=settings.vapid_private_key, subject=settings.vapid_subject)
        )
    sender: PushSender = state.push_sender
    return sender


def get_push_sender(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> PushSender:
    return push_sender_for(request.app.state, settings)


PushSenderDep = Annotated[PushSender, Depends(get_push_sender)]
