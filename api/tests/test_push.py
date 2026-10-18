"""웹 푸시 (F-33): VAPID 키·머리값, 페이로드 주소, 암호화, 발송, 구독 API.

DB도 실제 푸시 서비스도 쓰지 않는다. 구독 SQL은 test_push_db.py, 발송 작업 전체는
test_notifications_db.py가 본다.
"""

import json
import time
from typing import Any

import http_ece
import httpx
import jwt
import pytest
import respx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient
from http_ece import ECEException

from app.config import Settings, get_settings
from app.main import create_app
from app.push.keys import b64u, generate_keys, load_keys, unb64u
from app.push.payload import PushPayload, url_for
from app.push.send import GONE, PushSender, PushTarget, Subscription, encrypt
from app.push.vapid import EXPIRY_SECONDS, authorization, origin_of
from app.repositories.push import get_push_repo
from tests.conftest import USER_ID, make_token

SUBJECT = "mailto:capstone@hanyang.ac.kr"
ENDPOINT = "https://push.example.com/fcm/send/abc123"


def keys() -> Any:
    private, _ = generate_keys()
    found = load_keys(private_key=private, subject=SUBJECT)
    assert found is not None
    return found


def browser_subscription() -> tuple[Subscription, ec.EllipticCurvePrivateKey, bytes]:
    """브라우저가 만드는 구독 하나. 비밀 키는 시험이 들고 있다가 풀어 본다."""
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    return (
        Subscription(id="q-1", endpoint=ENDPOINT, p256dh=b64u(public), auth=b64u(auth)),
        private,
        auth,
    )


def payload() -> PushPayload:
    return PushPayload(
        type="new_material",
        title="기계학습 8주차 자료가 올라왔어요",
        body="08 - Ensemble Methods",
        url="/academics/course-1?tab=materials",
        notification_id="n-1",
    )


# ── 키 ──────────────────────────────────────────────────────────────────────


def test_a_generated_key_loads_back() -> None:
    private, public = generate_keys()
    found = load_keys(private_key=private, subject=SUBJECT)
    assert found is not None
    # 공개 키는 비밀 키에서 다시 만든다(설정에 둘을 따로 두지 않는다)
    assert found.public_b64 == public
    assert len(unb64u(found.public_b64)) == 65  # 비압축 P-256 점
    assert found.subject == SUBJECT


def test_a_missing_or_broken_key_means_no_push() -> None:
    assert load_keys(private_key="", subject=SUBJECT) is None
    assert load_keys(private_key=generate_keys()[0], subject="") is None
    assert load_keys(private_key="not-a-key", subject=SUBJECT) is None
    short = b64u(b"\x01" * 16)  # 32바이트가 아니다
    assert load_keys(private_key=short, subject=SUBJECT) is None


# ── VAPID 머리값 ────────────────────────────────────────────────────────────


def test_the_header_is_a_token_the_push_service_can_check() -> None:
    found = keys()
    issued = time.time()
    header = authorization(found, ENDPOINT, now=issued)
    assert header.startswith("vapid t=")
    token = header.removeprefix("vapid t=").split(", k=")[0]
    assert header.endswith(f", k={found.public_b64}")
    # 푸시 서비스는 머리값의 공개 키로 토큰을 검사한다. 그대로 해 본다
    claims = jwt.decode(
        token,
        found.private_key.public_key(),
        algorithms=["ES256"],
        audience="https://push.example.com",
    )
    assert claims["sub"] == SUBJECT
    assert claims["exp"] == int(issued) + EXPIRY_SECONDS


def test_the_audience_is_the_push_services_origin() -> None:
    assert origin_of("https://fcm.googleapis.com/fcm/send/x?y=1") == "https://fcm.googleapis.com"
    with pytest.raises(ValueError, match="푸시 주소"):
        origin_of("fcm/send/x")


# ── 누르면 갈 주소 ──────────────────────────────────────────────────────────


def test_the_url_matches_the_web_routes() -> None:
    """`web/src/lib/routes.ts`와 같은 꼴이어야 한다(명세 10장)."""
    assert (
        url_for(kind="new_eligible", link_type="opportunity", link_id="o-1", course_id=None)
        == "/opportunities/o-1"
    )
    assert (
        url_for(kind="profile_needed", link_type="opportunity", link_id="o-1", course_id=None)
        == "/opportunities/o-1?focus=profile_input"
    )
    assert url_for(kind="task_due", link_type="planner_task", link_id="t-1", course_id=None) == (
        "/planner"
    )
    assert (
        url_for(kind="new_material", link_type="lms_module_item", link_id="i-1", course_id="c-1")
        == "/academics/c-1?tab=materials"
    )
    assert (
        url_for(
            kind="schedule_change", link_type="lms_announcement", link_id="a-1", course_id="c-1"
        )
        == "/academics/c-1?tab=announcements"
    )
    assert (
        url_for(kind="new_assignment", link_type="lms_assignment", link_id="a-1", course_id="c-1")
        == "/academics/c-1?tab=assignments"
    )


def test_a_notification_without_a_target_goes_home() -> None:
    assert url_for(kind="new_eligible", link_type=None, link_id=None, course_id=None) == "/"
    # 수강을 뺀 과목이면 과목 번호가 없다. 학업 화면까지만 보낸다
    assert (
        url_for(kind="new_material", link_type="lms_module_item", link_id="i-1", course_id=None)
        == "/academics"
    )


# ── 암호화 ──────────────────────────────────────────────────────────────────


def test_the_browser_can_decrypt_what_we_send() -> None:
    """RFC 8291 그대로여야 브라우저가 푼다. 구독 비밀 키로 풀어서 본다."""
    subscription, private, auth = browser_subscription()
    body = encrypt(payload(), subscription)

    plain = http_ece.decrypt(body, private_key=private, auth_secret=auth, version="aes128gcm")

    assert json.loads(plain) == {
        "type": "new_material",
        "title": "기계학습 8주차 자료가 올라왔어요",
        "body": "08 - Ensemble Methods",
        "url": "/academics/course-1?tab=materials",
        "notification_id": "n-1",
    }


def test_every_message_gets_a_new_ephemeral_key() -> None:
    """RFC 8291 3.1: 메시지마다 새 임시 키다. 같은 키를 다시 쓰면 안전하지 않다.

    aes128gcm 본문 머리는 `salt(16) | rs(4) | 키 길이(1) | 임시 공개 키(65)`다(RFC 8188).
    같은 내용을 두 번 암호화해 그 자리가 달라지는지 본다.
    """
    subscription, _, _ = browser_subscription()

    first, second = encrypt(payload(), subscription), encrypt(payload(), subscription)

    assert first[:16] != second[:16]  # salt
    assert first[20] == 65  # 임시 공개 키 길이
    assert first[21:86] != second[21:86]  # 임시 공개 키


def test_another_browsers_key_cannot_decrypt_it() -> None:
    subscription, _, auth = browser_subscription()
    body = encrypt(payload(), subscription)
    other = ec.generate_private_key(ec.SECP256R1())

    with pytest.raises((InvalidTag, ECEException)):  # 다른 키로는 풀리지 않는다
        http_ece.decrypt(body, private_key=other, auth_secret=auth, version="aes128gcm")


# ── 발송 ────────────────────────────────────────────────────────────────────


async def _send(status: int, *, subscriptions: int = 1) -> Any:
    subscription, _, _ = browser_subscription()
    targets = [
        PushTarget(
            payload=payload(),
            subscriptions=tuple(
                Subscription(
                    id=f"q-{index}",
                    endpoint=f"{ENDPOINT}/{index}",
                    p256dh=subscription.p256dh,
                    auth=subscription.auth,
                )
                for index in range(subscriptions)
            ),
        )
    ]
    with respx.mock(assert_all_called=False) as router:
        route = router.post(url__startswith=ENDPOINT).mock(return_value=httpx.Response(status))
        async with httpx.AsyncClient() as client:
            result = await PushSender(keys(), client=client).send(targets)
        return result, route


@pytest.mark.anyio
async def test_a_push_the_service_accepts_counts_as_sent() -> None:
    result, route = await _send(201, subscriptions=2)

    assert (result.notifications, result.sent, result.failed) == (1, 2, 0)
    assert result.gone == []
    request = route.calls[0].request
    assert request.headers["content-encoding"] == "aes128gcm"
    assert request.headers["authorization"].startswith("vapid t=")
    assert request.headers["ttl"] == "86400"
    assert request.headers["content-type"] == "application/octet-stream"


@pytest.mark.anyio
@pytest.mark.parametrize("status", GONE)
async def test_a_gone_subscription_is_reported_for_deletion(status: int) -> None:
    result, _ = await _send(status)

    assert (result.sent, result.failed) == (0, 0)
    assert result.gone == [f"{ENDPOINT}/0"]


@pytest.mark.anyio
async def test_a_failing_push_service_is_only_counted() -> None:
    result, _ = await _send(500)

    assert (result.sent, result.failed, result.gone) == (0, 1, [])


@pytest.mark.anyio
async def test_without_keys_nothing_is_sent() -> None:
    subscription, _, _ = browser_subscription()
    targets = [PushTarget(payload=payload(), subscriptions=(subscription,))]

    with respx.mock(assert_all_called=False) as router:
        route = router.post(url__startswith=ENDPOINT).mock(return_value=httpx.Response(201))
        result = await PushSender(None).send(targets)

    assert (result.notifications, result.sent) == (0, 0)
    assert not route.called  # 설정이 비면 푸시 서비스를 부르지 않는다


# ── 구독 API ────────────────────────────────────────────────────────────────


class FakePushRepo:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str, str, str | None]] = []
        self.removed: list[tuple[str, str]] = []

    async def save(
        self, user_id: str, *, endpoint: str, p256dh: str, auth: str, user_agent: str | None
    ) -> bool:
        self.saved.append((user_id, endpoint, p256dh, auth, user_agent))
        return True

    async def remove(self, user_id: str, endpoint: str) -> int:
        self.removed.append((user_id, endpoint))
        return 1


@pytest.fixture
def push_repo() -> FakePushRepo:
    return FakePushRepo()


@pytest.fixture
def client(settings: Settings, push_repo: FakePushRepo) -> Any:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_push_repo] = lambda: push_repo
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {make_token()}"
        yield test_client


SUBSCRIPTION = {
    "endpoint": ENDPOINT,
    "keys": {"p256dh": "BPublicKeyValue", "auth": "AuthSecretValue"},
    "user_agent": "Chrome 129 / Android",
}


def test_subscribing_saves_the_browser_keys(client: Any, push_repo: FakePushRepo) -> None:
    response = client.post("/api/v1/push/subscriptions", json=SUBSCRIPTION)

    assert response.status_code == 201
    assert response.json() == {"subscribed": True}
    assert push_repo.saved == [
        (USER_ID, ENDPOINT, "BPublicKeyValue", "AuthSecretValue", "Chrome 129 / Android")
    ]


def test_an_insecure_endpoint_is_refused(client: Any, push_repo: FakePushRepo) -> None:
    """http 주소면 암호화한 본문이 평문 길로 나간다."""
    response = client.post(
        "/api/v1/push/subscriptions", json={**SUBSCRIPTION, "endpoint": "http://push.example/x"}
    )

    assert response.status_code == 422
    assert push_repo.saved == []


def test_a_subscription_without_keys_is_refused(client: Any) -> None:
    response = client.post("/api/v1/push/subscriptions", json={"endpoint": ENDPOINT})
    assert response.status_code == 422


def test_unsubscribing_removes_my_endpoint(client: Any, push_repo: FakePushRepo) -> None:
    response = client.request("DELETE", "/api/v1/push/subscriptions", json={"endpoint": ENDPOINT})

    assert response.status_code == 204
    assert push_repo.removed == [(USER_ID, ENDPOINT)]


def test_subscribing_needs_a_login(settings: Settings, push_repo: FakePushRepo) -> None:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_push_repo] = lambda: push_repo
    with TestClient(app) as anonymous:
        response = anonymous.post("/api/v1/push/subscriptions", json=SUBSCRIPTION)
    assert response.status_code == 401
