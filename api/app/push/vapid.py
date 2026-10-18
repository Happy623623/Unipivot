"""VAPID 머리값 (F-33, RFC 8292). 푸시 서비스에 "이 서버가 보냈다"고 밝힌다.

푸시 주소의 **출처(origin)마다** 토큰을 하나 만들어 쓴다(`aud`). 토큰은 ES256으로 서명하고
만료는 12시간 뒤다(RFC 권고 상한 24시간). 같은 발송에서 같은 출처면 토큰을 다시 쓴다.

aes128gcm 인코딩에서는 머리값 하나에 토큰과 공개 키를 함께 담는다:

    Authorization: vapid t=<JWT>, k=<base64url 공개 키>
"""

import time
from urllib.parse import urlsplit

import jwt

from app.push.keys import VapidKeys

EXPIRY_SECONDS = 12 * 60 * 60  # 토큰 수명. 푸시 서비스는 24시간을 넘기면 거절한다


def origin_of(endpoint: str) -> str:
    """구독 주소의 출처(스킴 + 호스트). VAPID 토큰의 `aud`다."""
    parts = urlsplit(endpoint)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"푸시 주소가 아니에요: {endpoint[:40]}")
    return f"{parts.scheme}://{parts.netloc}"


def authorization(keys: VapidKeys, endpoint: str, *, now: float | None = None) -> str:
    """그 주소에 보낼 `Authorization` 머리값."""
    issued = int(now if now is not None else time.time())
    token = jwt.encode(
        {"aud": origin_of(endpoint), "exp": issued + EXPIRY_SECONDS, "sub": keys.subject},
        keys.private_key,
        algorithm="ES256",
    )
    return f"vapid t={token}, k={keys.public_b64}"
