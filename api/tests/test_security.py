"""토큰 암호화 키 교체와 로그 마스킹 (PRD 7장 토큰 보안)."""

import logging

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
