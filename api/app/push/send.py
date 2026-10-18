"""푸시 발송 (F-33, RFC 8291). 페이로드를 구독 키로 암호화해 푸시 서비스에 보낸다.

한 알림을 그 사용자의 **구독마다** 한 번씩 보낸다(브라우저·기기별로 구독이 따로다). 발송 결과는
세 갈래다.

- 보냈다(201·200·202): 셀 뿐이다. 알림함 행은 이미 `succeeded`다
- 구독이 사라졌다(404·410): 그 구독을 지운다. 브라우저를 지웠거나 알림을 껐다
- 그 밖(5xx·시간 초과): 로그만 남기고 둔다. 알림은 이미 보낸 것으로 닫혀 **다시 보내지 않는다**
  — 같은 알림을 두 번 보내는 쪽이 한 번 빠뜨리는 쪽보다 나쁘다(명세 10장: 같은 알림은 한 번만)

암호화는 `http_ece`(aes128gcm)에 맡긴다. 직접 구현하면 우리 시험은 통과하면서 실제 브라우저에서는
풀리지 않는 일이 생긴다 — 이 부분은 검증된 구현을 쓴다.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

import http_ece
import httpx
from cryptography.hazmat.primitives.asymmetric import ec

from app.push.keys import VapidKeys, unb64u
from app.push.payload import PushPayload
from app.push.vapid import authorization, origin_of

logger = logging.getLogger(__name__)

TTL_SECONDS = 24 * 60 * 60  # 푸시 서비스가 기기를 못 깨우면 이만큼 들고 있는다
TIMEOUT_SECONDS = 10.0
GONE = (404, 410)  # 구독이 사라졌다는 뜻(RFC 8030)
_OK = (200, 201, 202)
_RECORD_SIZE = 4096


@dataclass(frozen=True)
class Subscription:
    """브라우저 구독 하나. 키는 base64url 그대로 담는다."""

    id: str
    endpoint: str
    p256dh: str
    auth: str


@dataclass(frozen=True)
class PushTarget:
    """알림 하나와 그 사용자의 구독들."""

    payload: PushPayload
    subscriptions: tuple[Subscription, ...]


@dataclass
class PushResult:
    """발송 한 묶음의 결과."""

    notifications: int = 0  # 푸시를 보낸 알림 수(구독이 여러 개면 한 알림에 여러 번 보낸다)
    sent: int = 0  # 보낸 구독 수
    gone: list[str] = field(default_factory=list)  # 지워야 하는 구독 주소
    failed: int = 0


def encrypt(payload: PushPayload, subscription: Subscription) -> bytes:
    """RFC 8291 aes128gcm 본문. 구독의 공개 키·비밀 값으로만 풀 수 있다.

    **메시지마다 새 임시 키**를 만든다(RFC 8291 3.1). 같은 키를 다시 쓰면 두 메시지의 암호가
    같은 비밀에서 나와 안전하지 않다. 임시 공개 키는 본문 머리에 함께 들어가므로 따로 보내지 않는다.
    """
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    return http_ece.encrypt(
        payload.to_json(),
        private_key=ephemeral,
        dh=unb64u(subscription.p256dh),
        auth_secret=unb64u(subscription.auth),
        version="aes128gcm",
        rs=_RECORD_SIZE,
    )


class PushSender:
    """푸시 서비스에 보내는 쪽. 키가 없으면 아무것도 보내지 않는다(설정이 비었다)."""

    def __init__(self, keys: VapidKeys | None, *, client: httpx.AsyncClient | None = None) -> None:
        self.keys = keys
        self.client = client

    async def send(self, targets: Sequence[PushTarget]) -> PushResult:
        """알림마다 그 사용자의 구독 전체에 보낸다. 사라진 구독 주소를 함께 돌려준다."""
        result = PushResult()
        if self.keys is None or not targets:
            return result
        client = self.client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        own = self.client is None
        try:
            for target in targets:
                result.notifications += 1
                for subscription in target.subscriptions:
                    await self._one(client, target.payload, subscription, result)
        finally:
            if own:
                await client.aclose()
        return result

    async def _one(
        self,
        client: httpx.AsyncClient,
        payload: PushPayload,
        subscription: Subscription,
        result: PushResult,
    ) -> None:
        assert self.keys is not None
        try:
            body = encrypt(payload, subscription)
            headers = {
                "Authorization": authorization(self.keys, subscription.endpoint),
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(TTL_SECONDS),
                "Urgency": "normal",
            }
            response = await client.post(subscription.endpoint, content=body, headers=headers)
        except Exception as exc:  # 주소가 이상하거나 네트워크가 막혔다
            logger.warning("푸시를 보내지 못했어요: %r", exc)
            result.failed += 1
            return
        if response.status_code in _OK:
            result.sent += 1
            return
        if response.status_code in GONE:
            # 브라우저를 지웠거나 알림을 껐다. 다음 발송에서 또 시도하지 않게 구독을 지운다
            logger.info("사라진 푸시 구독을 지워요: %s", origin_of(subscription.endpoint))
            result.gone.append(subscription.endpoint)
            return
        logger.warning("푸시 서비스가 거절했어요: %s %s", response.status_code, response.text[:120])
        result.failed += 1
