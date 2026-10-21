"""로그인 확인(Supabase 토큰): 시계 차이 허용, 실패 이유 로그(토큰 제외), 공개키 실패는 503."""

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient

from app import auth as auth_module
from app.auth import auth_settings_problem
from app.config import Settings, get_settings
from app.main import create_app
from app.repositories.meta import get_meta_repo
from app.repositories.opportunities import get_opportunity_repo
from app.repositories.profiles import get_profile_repo
from tests.conftest import USER_ID, make_token
from tests.fakes import FakeMetaRepository, FakeOpportunityRepository, FakeProfileRepository

PROJECT_URL = "https://abcdefghijklmnopqrst.supabase.co"
JWKS_URL = f"{PROJECT_URL}/auth/v1/.well-known/jwks.json"
KEY = ec.generate_private_key(ec.SECP256R1())
JWKS = {"keys": [{**json.loads(jwt.algorithms.ECAlgorithm.to_jwk(KEY.public_key())), "kid": "k1"}]}
NETWORK_HINT = "api/.env의 SUPABASE_URL과 네트워크를 확인하세요"


def es256_token(kid: str = "k1", **claims: Any) -> str:
    now = int(time.time())
    payload = {"sub": USER_ID, "aud": "authenticated", "iat": now, "exp": now + 3600, **claims}
    return jwt.encode(payload, KEY, algorithm="ES256", headers={"kid": kid})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class StaticJwks(jwt.PyJWKClient):
    """네트워크 없이 정해 둔 응답(또는 예외)을 차례로 돌려주는 공개키 클라이언트.

    라이브러리의 fetch_data처럼 성공한 시각을 남겨서, 모르는 키로 다시 받기를 30초에 한 번만 한다
    (cooldown 0이면 매번 다시 받는다)."""

    def __init__(self, *responses: Any, cooldown: float = 30, lifespan: float = 300) -> None:
        super().__init__(JWKS_URL, cache_keys=True, cooldown_duration=cooldown, lifespan=lifespan)
        self.responses = list(responses)
        self.fetches = 0

    def fetch_data(self) -> Any:
        self.fetches += 1
        response = self.responses[min(self.fetches, len(self.responses)) - 1]
        if isinstance(response, Exception):
            raise response
        self._last_successful_fetch = time.monotonic()
        return response


def jwks_app(
    monkeypatch: pytest.MonkeyPatch, jwks: StaticJwks | None, **overrides: Any
) -> TestClient:
    """공개키(JWKS)로 검증하는 설정(비밀키 없음)의 앱. 저장소는 가짜다."""
    values: dict[str, Any] = {
        "database_url": "",
        "supabase_url": PROJECT_URL,
        "supabase_jwt_secret": "",
        "token_encryption_key": Fernet.generate_key().decode(),
    }
    settings = Settings(**{**values, **overrides})
    if jwks is not None:
        monkeypatch.setattr(auth_module, "_jwks_client", lambda url: jwks)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_profile_repo] = FakeProfileRepository
    app.dependency_overrides[get_meta_repo] = FakeMetaRepository
    app.dependency_overrides[get_opportunity_repo] = FakeOpportunityRepository
    return TestClient(app)


@pytest.fixture
def logs(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    with caplog.at_level(logging.WARNING, logger="app"):
        yield caplog


def test_clock_leeway(client: TestClient) -> None:
    """서버와 시계가 1분까지 달라도 받는다. 그보다 오래 지난 토큰은 만료다."""
    now = int(time.time())
    for token in (make_token(iat=now + 30), make_token(expires_in=-30)):
        assert client.get("/api/v1/me", headers=bearer(token)).status_code == 200
    for token in (make_token(iat=now + 120), make_token(expires_in=-120)):
        assert client.get("/api/v1/me", headers=bearer(token)).status_code == 401


def test_rejection_reason_is_logged_without_the_token(
    client: TestClient, logs: pytest.LogCaptureFixture
) -> None:
    expired = make_token(expires_in=-120)
    forged = make_token(secret="forged-secret-forged-secret-forged")
    future = make_token(iat=int(time.time()) + 600)
    for token in (expired, forged, future):
        res = client.get("/api/v1/me", headers=bearer(token))
        assert (res.status_code, res.json()["error"]["code"]) == (401, "UNAUTHORIZED")
    logged = logs.text
    assert "로그인 확인 실패(401): ExpiredSignatureError: Signature has expired" in logged
    assert "InvalidSignatureError" in logged
    assert "SUPABASE_JWT_SECRET이 이 프로젝트의 값인지 확인하세요" in logged
    assert "ImmatureSignatureError" in logged and "시간 동기화를 켜세요" in logged
    assert not [token for token in (expired, forged, future) if token in logged]
    assert "eyJ" not in logged


def test_new_project_token_on_the_secret_path(
    client: TestClient, logs: pytest.LogCaptureFixture
) -> None:
    """비밀키(HS256)를 채운 서버에 새 프로젝트 토큰(ES256)이 오면 비밀키를 비우라고 알린다."""
    assert client.get("/api/v1/me", headers=bearer(es256_token())).status_code == 401
    assert "InvalidAlgorithmError" in logs.text
    assert "SUPABASE_JWT_SECRET을 비우세요" in logs.text


def test_jwks_verifies_and_rejects_other_projects(
    monkeypatch: pytest.MonkeyPatch, logs: pytest.LogCaptureFixture
) -> None:
    jwks = StaticJwks(JWKS)
    with jwks_app(monkeypatch, jwks) as client:
        assert client.get("/api/v1/me", headers=bearer(es256_token())).status_code == 200
        # 다른 프로젝트의 토큰(모르는 키)과 레거시 토큰(HS256, 키 없음): 401과 고칠 곳
        for token in (es256_token(kid="other"), make_token()):
            res = client.get("/api/v1/me", headers=bearer(token))
            assert (res.status_code, res.json()["error"]["code"]) == (401, "UNAUTHORIZED")
    assert "PyJWKClientError" in logs.text
    assert "같은 Supabase 프로젝트 주소를 쓰는지 확인하세요" in logs.text
    assert "레거시(HS256) 토큰이에요" in logs.text
    assert jwks.fetches == 1  # 받은 지 30초 안에는 모르는 키로 다시 받지 않는다(라이브러리 규칙)


def test_a_known_key_keeps_working_when_the_endpoint_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """한 번 찾은 키는 기억한다. 공개키 목록이 만료된 뒤 주소가 안 돼도 아는 키의 토큰은 검증한다."""
    jwks = StaticJwks(JWKS, jwt.PyJWKClientConnectionError("down"), lifespan=0.01)
    with jwks_app(monkeypatch, jwks) as client:
        assert client.get("/api/v1/me", headers=bearer(es256_token())).status_code == 200
        time.sleep(0.05)
        assert client.get("/api/v1/me", headers=bearer(es256_token())).status_code == 200
    assert jwks.fetches == 1


@pytest.mark.parametrize(
    ("response", "logged"),
    [
        (
            jwt.PyJWKClientConnectionError('Fail to fetch data from the url, err: "getaddrinfo"'),
            ("PyJWKClientConnectionError", NETWORK_HINT),
        ),
        (["not", "an", "object"], ("did not return a JSON object", NETWORK_HINT)),
        (
            {"keys": []},
            ("PyJWKSetError", "레거시 프로젝트면 api/.env의 SUPABASE_JWT_SECRET을 채우세요"),
        ),
        (json.JSONDecodeError("Expecting value", "<html>", 0), ("JSONDecodeError", NETWORK_HINT)),
        (ConnectionResetError("reset while reading"), ("ConnectionResetError", NETWORK_HINT)),
        # 라이브러리가 예상하지 못한 모양(키 값의 타입이 틀림, 너무 깊은 JSON)도 500이 아니라 503이다
        ({"keys": [{"kty": "EC", "alg": ["x"]}]}, ("TypeError", NETWORK_HINT)),
        (RecursionError("maximum recursion depth exceeded"), ("RecursionError", NETWORK_HINT)),
    ],
    ids=["connection", "not-object", "no-keys", "not-json", "reset", "odd-alg", "nested"],
)
def test_jwks_failure_is_503_not_401(
    monkeypatch: pytest.MonkeyPatch,
    logs: pytest.LogCaptureFixture,
    response: Any,
    logged: tuple[str, str],
) -> None:
    """공개키를 받지 못하면 서버 문제다. 401을 주면 웹이 로그인 화면으로 보내 같은 곳을 맴돈다."""
    with jwks_app(monkeypatch, StaticJwks(response)) as client:
        res = client.get("/api/v1/me", headers=bearer(es256_token()))
    assert res.status_code == 503
    assert res.json()["error"] == {
        "code": "AUTH_UNAVAILABLE",
        "message": "로그인을 확인하지 못했어요. 잠시 후 다시 시도해 주세요.",
        "details": {},
    }
    assert f"로그인 확인 실패(503): 공개키를 받지 못했어요({JWKS_URL})" in logs.text
    assert all(text in logs.text for text in logged), logs.text


@pytest.mark.parametrize(
    "refetch",
    [
        jwt.PyJWKClientConnectionError("timed out"),
        json.JSONDecodeError("Expecting value", "<html>", 0),
        {"keys": []},
    ],
    ids=["connection", "not-json", "no-keys"],
)
def test_refetch_failure_is_503(
    monkeypatch: pytest.MonkeyPatch, logs: pytest.LogCaptureFixture, refetch: Any
) -> None:
    """모르는 키라 공개키를 다시 받다가 실패해도 서버 문제(503)다."""
    jwks = StaticJwks(JWKS, refetch, cooldown=0)
    with jwks_app(monkeypatch, jwks) as client:
        res = client.get("/api/v1/me", headers=bearer(es256_token(kid="rotated")))
    assert (res.status_code, res.json()["error"]["code"]) == (503, "AUTH_UNAVAILABLE")
    assert jwks.fetches == 2
    assert "로그인 확인 실패(503): 공개키를 받지 못했어요" in logs.text


def test_attacker_controlled_text_stays_on_one_short_line(
    monkeypatch: pytest.MonkeyPatch, logs: pytest.LogCaptureFixture
) -> None:
    """토큰 머리(kid)는 요청이 정한다. 줄바꿈·제어 문자로 가짜 로그 줄을 만들거나 로그를 키우지 못한다."""
    kid = "evil\nINFO:     forged \x1b[2K\x1b[1Gline\x00‮ " + "x" * 5000
    with jwks_app(monkeypatch, StaticJwks(JWKS)) as client:
        assert client.get("/api/v1/me", headers=bearer(es256_token(kid=kid))).status_code == 401
    record = next(r for r in logs.records if "로그인 확인 실패(401)" in r.getMessage())
    message = record.getMessage()
    assert message.isprintable() and len(message) < 500
    # 줄바꿈·이어진 공백은 공백 하나로, 제어 문자는 \x1b처럼 보인다
    assert '"evil INFO: forged \\x1b[2K\\x1b[1Gline\\x00\\u202e x' in message


def test_algorithm_that_does_not_match_the_key_is_401(
    monkeypatch: pytest.MonkeyPatch, logs: pytest.LogCaptureFixture
) -> None:
    """토큰의 alg가 kid가 가리키는 키의 알고리즘과 다르면 토큰 문제(401)다. 500이 되지 않는다."""
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_jwk = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(rsa_key.public_key())), "kid": "r1"}
    now = int(time.time())
    claims = {"sub": USER_ID, "aud": "authenticated", "iat": now, "exp": now + 3600}
    with jwks_app(monkeypatch, StaticJwks({"keys": [*JWKS["keys"], rsa_jwk]})) as client:
        for token in (
            jwt.encode(claims, rsa_key, algorithm="RS256", headers={"kid": "k1"}),  # EC 키의 kid
            es256_token(kid="r1"),  # RSA 키의 kid
        ):
            res = client.get("/api/v1/me", headers=bearer(token))
            assert (res.status_code, res.json()["error"]["code"]) == (401, "UNAUTHORIZED")
    assert logs.text.count("로그인 확인 실패(401): InvalidAlgorithmError") == 2


def test_empty_or_wrong_project_url_is_503_without_showing_secrets(
    monkeypatch: pytest.MonkeyPatch, logs: pytest.LogCaptureFixture
) -> None:
    for url, logged in (
        ("", "로그인 확인 실패(503): SUPABASE_URL이 비어 있어요(api/.env)"),
        (
            "postgresql://postgres.abcd:pw-1234@pooler.example.com:5432/postgres",
            "로그인 확인 실패(503): SUPABASE_URL에 계정 정보(@)가 들어 있어요",
        ),
        (PROJECT_URL + "/rest/v1", "로그인 확인 실패(503): SUPABASE_URL에 경로가 붙어 있어요"),
    ):
        jwks = StaticJwks(JWKS)
        with jwks_app(monkeypatch, jwks, supabase_url=url) as client:
            res = client.get("/api/v1/me", headers=bearer(es256_token()))
        assert (res.status_code, res.json()["error"]["code"]) == (503, "AUTH_UNAVAILABLE")
        assert logged in logs.text
        assert jwks.fetches == 0  # 틀린 주소로는 공개키를 받으러 가지 않는다
    assert "pw-1234" not in logs.text


@pytest.mark.parametrize(
    ("url", "secret", "problem", "shown"),
    [
        (PROJECT_URL, "", None, True),
        (PROJECT_URL + "/", "", None, True),  # 끝의 /는 검증할 때 뗀다
        ("http://localhost:54321", "", None, True),  # 로컬 Supabase
        ("", "legacy-secret-legacy-secret-legacy-secret", None, True),  # 비밀키면 주소를 안 쓴다
        ("", "", "SUPABASE_URL이 비어 있어요", True),
        ("https://<project-ref>.supabase.co", "", "예시 값이 남아 있어요", True),
        ("abcdefghijklmnopqrst.supabase.co", "", "https://로 시작하지 않아요", False),
        ("sb_secret_pasted-by-mistake", "", "https://로 시작하지 않아요", False),
        ("postgresql://postgres:pw-1234@db.example.com:5432/postgres", "", "계정 정보(@)", False),
        ("https://user:pw-1234@abcdefghijklmnopqrst.supabase.co", "", "계정 정보(@)", False),
        (
            PROJECT_URL + "/rest/v1",
            "",
            "경로가 붙어 있어요",
            False,
        ),  # 대시보드 API 주소를 그대로 복사
        (PROJECT_URL + "/auth/v1/", "", "경로가 붙어 있어요", False),
        (PROJECT_URL + "?x=1", "", "경로가 붙어 있어요", False),
        (PROJECT_URL + "?", "", "경로가 붙어 있어요", False),  # 빈 ?도 공개키 주소를 틀어 놓는다
        ("https://example.com/supabase", "", None, True),  # 앞단 경로가 붙은 자체 호스팅은 그대로
        ("https://example.com/supabase/rest/v1", "", "경로가 붙어 있어요", False),
        ("http://", "", "https://로 시작하지 않아요", False),  # 주소가 없다
        ("http://[", "", "주소 모양이 아니에요", False),  # urlsplit이 ValueError를 낸다
        (
            PROJECT_URL + "/rest/v1",
            "legacy-secret-legacy-secret-legacy-secret",
            None,
            True,
        ),  # 비밀키면 안 쓴다
    ],
)
def test_auth_settings_problem(url: str, secret: str, problem: str | None, shown: bool) -> None:
    found = auth_settings_problem(Settings(supabase_url=url, supabase_jwt_secret=secret))
    if problem is None:
        assert found is None
        return
    assert found is not None and problem in found
    assert (url in found) == shown  # 주소처럼 보이는 값만 보여 준다


def test_startup_warns_about_a_placeholder_url(
    monkeypatch: pytest.MonkeyPatch, logs: pytest.LogCaptureFixture
) -> None:
    with jwks_app(monkeypatch, None, supabase_url="https://<project-ref>.supabase.co"):
        pass  # 시작(lifespan)만 한다
    assert "로그인 설정 확인: SUPABASE_URL에 예시 값이 남아 있어요" in logs.text
