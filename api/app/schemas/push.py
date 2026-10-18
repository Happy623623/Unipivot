"""웹 푸시 구독 (F-33, API 명세 10장). 브라우저 `PushManager.subscribe()` 결과를 그대로 받는다."""

from pydantic import BaseModel, Field, field_validator

ENDPOINT_MAX = 1000  # 푸시 주소(FCM은 200자 안쪽이지만 넉넉히 둔다)
KEY_MAX = 200
AGENT_MAX = 200


class SubscriptionKeys(BaseModel):
    """브라우저가 주는 두 값. base64url(패딩 없음)이다."""

    p256dh: str = Field(min_length=1, max_length=KEY_MAX)
    auth: str = Field(min_length=1, max_length=KEY_MAX)


class PushSubscriptionRequest(BaseModel):
    endpoint: str = Field(min_length=1, max_length=ENDPOINT_MAX)
    keys: SubscriptionKeys
    user_agent: str | None = Field(default=None, max_length=AGENT_MAX)

    @field_validator("endpoint")
    @classmethod
    def _https(cls, value: str) -> str:
        """https 주소만 받는다. http면 암호화한 본문이 평문 길로 나간다."""
        if not value.startswith("https://"):
            raise ValueError("https 주소만 받아요.")
        return value


class PushSubscribed(BaseModel):
    subscribed: bool = True


class PushUnsubscribeRequest(BaseModel):
    endpoint: str = Field(min_length=1, max_length=ENDPOINT_MAX)
