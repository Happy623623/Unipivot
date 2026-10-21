"""토큰 암호화 키 교체와 로그 마스킹 (PRD 7장 토큰 보안)."""

import logging
from decimal import Decimal

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
        "sb_secret_" + "Tq7" * 10 + "x",  # Supabase 파일 저장소 키(F-13·F-54)
    )
    text = (
        f"Authorization: Bearer {secrets[0]} google={secrets[1]} refresh={secrets[2]}"
        f" lms={secrets[3]} stored={secrets[4]} access_token={secrets[5]} key={secrets[6]}"
        f" gemini={secrets[7]} apikey: {secrets[8]}"
    )
    cleaned = redact(text)
    assert not [secret for secret in secrets if secret in cleaned]
    assert redact("input_tokens=1200, 장학금 3건") == "input_tokens=1200, 장학금 3건"
    # publishable key는 브라우저에 두는 공개 값이라 가리지 않는다
    assert redact("sb_publishable_Pk4Pk4Pk4Pk4") == "sb_publishable_Pk4Pk4Pk4Pk4"
    # LearningX 토큰은 접두 자릿수와 뒤 길이·글자가 제각각이다(명세 8장 예시는 짧다)
    for token in ("18742~xxxxxxxx", "18742~abc_def-ghi0000", "1234567~" + "a" * 30):
        assert token not in redact(f"lms={token}")
    assert redact("12~short") == "12~short"  # 토큰 모양이 아닌 글자는 그대로 둔다


def test_attachment_keys_in_addresses_are_redacted() -> None:
    """공지 첨부 주소(F-54): verifier와 저장소 서명은 그 자체로 열쇠다. 경로·다른 값은 남긴다."""
    url = (
        "https://lms.test/files/11637886/download?download_frd=1&verifier=Ab12Cd34Ef "
        "→ https://kr.object.test/x.json?X-Amz-Algorithm=AWS4-HMAC-SHA256"
        "&X-Amz-Credential=AKIAEXAMPLE%2F20261019&x-amz-signature=0a1b2c3d&X-Amz-Expires=300"
    )
    cleaned = redact(url)
    for secret in ("Ab12Cd34Ef", "AKIAEXAMPLE", "0a1b2c3d"):
        assert secret not in cleaned
    for kept in ("/files/11637886/download", "download_frd=1", "X-Amz-Expires=300"):
        assert kept in cleaned
    assert redact("unverifier=3") == "unverifier=3"  # 낱말 가운데는 건드리지 않는다


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


def test_a_secret_that_only_shows_in_repr_is_redacted(caplog: pytest.LogCaptureFixture) -> None:
    """예외는 보통 `%r`로 찍는다. `str()`에는 없고 `repr()`에만 나오는 값(요청 주소를 든 예외)도 가린다."""
    install_log_redaction()

    class RequestFailed(Exception):
        def __init__(self, url: str) -> None:
            super().__init__("요청 실패")
            self.url = url

        def __repr__(self) -> str:
            return f"RequestFailed(url={self.url!r})"

    secret = "AKIAEXAMPLE0123"
    error = RequestFailed(
        f"https://s.example/f.pdf?X-Amz-Credential={secret}%2F2026&X-Amz-Expires=300"
    )
    logger = logging.getLogger("unipivot.test")
    with caplog.at_level(logging.INFO, logger="unipivot.test"):
        logger.warning("첨부 글자 추출 실패(%s): %r", "a.pdf", error)
        logger.warning("같은 예외를 %%s로: %s", error)
        logger.warning("이름 붙인 인자로: %(error)r", {"error": error})
    assert secret not in caplog.text
    assert (
        "이름 붙인 인자로: RequestFailed(url='https://s.example/f.pdf?X-Amz-Credential=[REDACTED]"
        in caplog.text
    )
    assert (
        "RequestFailed(url='https://s.example/f.pdf?X-Amz-Credential=[REDACTED]&X-Amz-Expires=300')"
        in caplog.text
    )
    assert "같은 예외를 %s로: 요청 실패" in caplog.text  # str()은 그대로다
    record = caplog.records[0]
    stand_in = record.args[1]
    assert stand_in is not error  # 바꿔 넣은 자리다. str()·repr()·format()을 따로 낸다
    assert str(stand_in) == "요청 실패"
    assert "[REDACTED]" in repr(stand_in) and secret not in repr(stand_in)
    assert f"{stand_in}" == "요청 실패" and format(stand_in, ">6") == " 요청 실패"
    assert f"{stand_in!r}" == repr(stand_in)


def test_an_argument_with_nothing_to_hide_is_passed_through_untouched(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """가릴 것이 없으면 인자 객체를 그대로 둔다(인자를 직접 꺼내 쓰는 포매터를 위해)."""
    install_log_redaction()
    url = httpx.URL("https://www.youthcenter.go.kr/go/ythip/getPlcy?pageNum=1")
    error = ValueError("읽을 수 없는 값")
    logger = logging.getLogger("unipivot.test")
    with caplog.at_level(logging.INFO, logger="unipivot.test"):
        logger.info("HTTP Request: %s %r", url, error)
    assert caplog.records[0].args[0] is url
    assert caplog.records[0].args[1] is error
    assert "ValueError('읽을 수 없는 값')" in caplog.text


def test_a_value_whose_repr_is_broken_is_still_redacted_by_str(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """repr()만 깨진 값은 str()로 찍은 것처럼 본다 — 전처럼 str()의 비밀은 가린다(회귀 방지)."""
    install_log_redaction()

    class BrokenRepr:
        def __str__(self) -> str:
            return f"Authorization: Bearer {JWT_LIKE}"

        def __repr__(self) -> str:
            raise RuntimeError("repr 없음")

    logger = logging.getLogger("unipivot.test")
    with caplog.at_level(logging.INFO, logger="unipivot.test"):
        logger.info("값 %s", BrokenRepr())
        logger.info("값 %r", BrokenRepr())
    assert JWT_LIKE not in caplog.text
    assert caplog.text.count("Authorization: Bearer [REDACTED]") == 2


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


def test_a_sensitive_format_hides_any_kind_of_argument(caplog: pytest.LogCaptureFixture) -> None:
    """서식에 token·secret이 있으면 그 자리의 값은 문자열이 아니어도 가린다(숫자·None은 그대로)."""
    install_log_redaction()

    class Holder:  # 패턴에 안 맞는 토큰을 든 객체(SecretStr·주소 객체 같은 것)
        def __str__(self) -> str:
            return "opaque-value-123"

        def __repr__(self) -> str:
            return "Holder(opaque-value-123)"

    logger = logging.getLogger("unipivot.test.sensitive")
    with caplog.at_level(logging.INFO, logger="unipivot.test.sensitive"):
        logger.info("refresh token=%s", Holder())
        logger.info("refresh token=%r", Holder())
        logger.info("client secret %s", b"opaque-bytes-456")
        logger.info("token count %d, secret %s", 3, None)
        logger.info("token cost %.2f, %d", Decimal("1.5"), True)  # 숫자는 서식이 깨지지 않게 그대로
    for value in ("opaque-value-123", "opaque-bytes-456"):
        assert value not in caplog.text
    assert caplog.text.count("[REDACTED]") == 3
    assert "token count 3, secret None" in caplog.text  # 숫자·None은 가리지 않는다
    assert "token cost 1.50, 1" in caplog.text
