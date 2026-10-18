"""웹 푸시 (F-33). 구독 저장은 `repositories/push.py`, 발송은 이 폴더다.

- `keys.py`: VAPID 키 읽기·만들기(`python -m app.push.keys`로 키 한 쌍을 찍는다)
- `vapid.py`: 푸시 서비스에 보낼 `Authorization: vapid` 머리값(ES256 JWT)
- `payload.py`: 서비스 워커에 보낼 JSON(명세 10장)과 누르면 갈 주소
- `send.py`: 페이로드를 암호화해 구독 주소로 보낸다(RFC 8291 aes128gcm)
"""

from app.push.keys import VapidKeys, generate_keys, load_keys
from app.push.payload import PushPayload, payload_for, url_for
from app.push.send import PushResult, PushSender, PushTarget, Subscription

__all__ = [
    "PushPayload",
    "PushResult",
    "PushSender",
    "PushTarget",
    "Subscription",
    "VapidKeys",
    "generate_keys",
    "load_keys",
    "payload_for",
    "url_for",
]
