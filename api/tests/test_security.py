"""토큰 암호화 키 교체와 로그 마스킹 (PRD 7장 토큰 보안)."""

import logging

import httpx
import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.crypto import decrypt, encrypt, rotate
from app.logging_redact import install_log_redaction, redact

JWT_LIKE = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXZhbHVlLWhlcmU"
LMS_TOKEN = "1234~AbCdEfGhIjKlMnOpQrStUvWx"


def test_key_rotation() -> None:
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    stored = encrypt("1//refresh", old)
    both = f"{new},{old}"
    assert decrypt(stored, both) == "1//refresh"  # 키를 바꾼 뒤에도 옛 값을 읽는다
    rotated = rotate(stored, both)
    assert decrypt(rotated, new) == "1//refresh"  # 다시 암호화하면 새 키만으로 읽는다
    with pytest.raises(InvalidToken):
        decrypt(stored, new)


def test_redact_patterns() -> None:
    secrets = (
        JWT_LIKE,
        "ya29.a0AfH6SMBx",
        "1//0gAbCdEfGhIjKl",
        LMS_TOKEN,
        "gAAAAABlZ0123456789abcdefghij",
        "secret123",
        "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv",
        "AIza" + "B" * 35,
    )
    text = (
        f"Authorization: Bearer {secrets[0]} google={secrets[1]} refresh={secrets[2]}"
        f" lms={secrets[3]} stored={secrets[4]} access_token={secrets[5]} key={secrets[6]}"
        f" gemini={secrets[7]}"
    )
    cleaned = redact(text)
    assert not [secret for secret in secrets if secret in cleaned]
    assert redact("input_tokens=1200, 장학금 3건") == "input_tokens=1200, 장학금 3건"


def test_log_records_are_redacted(caplog: pytest.LogCaptureFixture) -> None:
    install_log_redaction()
    logger = logging.getLogger("unipivot.test")
    with caplog.at_level(logging.INFO, logger="unipivot.test"):
        logger.info("LMS 호출 Authorization: Bearer %s", LMS_TOKEN)
        logger.info(f"세션 토큰 확인 {JWT_LIKE}")
        logger.info(  # uvicorn 접근 로그와 같은 모양
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:5000",
            "GET",
            "/auth/callback?access_token=ya29.zzzzzz",
            "1.1",
            200,
        )
        try:
            raise RuntimeError("refresh failed for 1//0gAbCdEfGhIjKl")
        except RuntimeError:
            logger.exception("Google 토큰 갱신 실패")
    for secret in (LMS_TOKEN, JWT_LIKE, "ya29.zzzzzz", "1//0gAbCdEfGhIjKl"):
        assert secret not in caplog.text
    access = caplog.records[2]
    assert len(access.args) == 5 and access.args[4] == 200  # 인자 개수와 타입은 그대로


def test_api_key_in_request_url_is_redacted(caplog: pytest.LogCaptureFixture) -> None:
    """httpx는 요청 주소를 URL 객체로 넘겨 로그를 남긴다. 주소에 붙은 온통청년 키도 가린다."""
    install_log_redaction()
    key = "youthcenter-key-0123456789"
    url = httpx.URL(f"https://www.youthcenter.go.kr/go/ythip/getPlcy?apiKeyNm={key}&pageNum=1")
    logger = logging.getLogger("unipivot.test")
    with caplog.at_level(logging.INFO, logger="unipivot.test"):
        logger.info('HTTP Request: %s %s "%s %d %s"', "GET", url, "HTTP/1.1", 200, "OK")
    assert key not in caplog.text
    assert "apiKeyNm=[REDACTED]&pageNum=1" in caplog.text
    assert caplog.records[0].args[3] == 200  # 숫자 인자는 그대로
    assert redact("https://x.example/?serviceKey=abc&rows=10") == (
        "https://x.example/?serviceKey=[REDACTED]&rows=10"
    )
    assert redact("x_api_key=abc&n=1") == "x_api_key=[REDACTED]&n=1"
    assert redact("rapikey=abc") == "rapikey=abc"  # 다른 낱말 속의 apikey는 아니다


def test_log_argument_that_cannot_be_stringified_does_not_break_the_caller() -> None:
    """가릴 것을 찾으려고 인자를 문자열로 바꾸다 실패해도 로그를 부른 곳(요청 처리)은 멈추지 않는다."""
    install_log_redaction()

    class Unprintable:
        def __str__(self) -> str:
            raise RuntimeError("문자열로 바꿀 수 없음")

    logger = logging.getLogger("unipivot.test.unprintable")
    logger.setLevel(logging.INFO)  # 레코드를 만든다(가리기는 여기서 돈다)
    logger.propagate = False  # 처리기가 없어 서식은 만들지 않는다
    logger.info("값 %s", Unprintable())
