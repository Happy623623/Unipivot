"""로그에서 토큰을 가린다 (PRD 7장 토큰 보안). 앱을 만들 때 install_log_redaction()을 한 번 부른다.

가리는 것: Authorization 헤더, Bearer 토큰, token=… 값, JWT, Google access·refresh token,
LearningX(Canvas) 개인 액세스 토큰, Fernet 암호문, Anthropic·Google API 키, Supabase secret key
(`sb_secret_…`), 주소에 붙은 API 키(온통청년 apiKeyNm=… 등), 공지 첨부 주소의 열쇠(Canvas
`verifier=…`, 파일 저장소 서명 `X-Amz-Signature=…`·`X-Amz-Credential=…`). 요청 주소처럼 문자열이
아닌 인자도 `str()`·`repr()`로 바꿔 보고 가릴 것이 있으면 가린다 — 예외를 `%r`로 찍는 로그가 많고,
`repr()`에만 나오는 값(요청 주소·헤더를 든 예외)도 있다. 서식 문자열에 token·secret·password 같은 말이
있으면 그 인자는 숫자·None 말고는 무엇이든 통째로 가린다.
"""

import logging
import numbers
import re
from collections.abc import Mapping
from typing import Any

_REDACTED = "[REDACTED]"
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?(?:bearer\s+)?)[^\s'\",}]+"),
        r"\1" + _REDACTED,
    ),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1" + _REDACTED),
    (
        re.compile(r"(?i)((?:access_|refresh_|provider_)?token['\"]?\s*[:=]\s*['\"]?)[^\s'\",}&]+"),
        r"\1" + _REDACTED,
    ),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), _REDACTED),
    (re.compile(r"ya29\.[A-Za-z0-9._-]+"), _REDACTED),
    (re.compile(r"1//[A-Za-z0-9._-]{10,}"), _REDACTED),
    # LearningX(Canvas) 개인 액세스 토큰: `18742~...`. 접두 자릿수와 뒤 길이·글자가 제각각이다
    (re.compile(r"\b\d{1,8}~[A-Za-z0-9_~-]{8,}"), _REDACTED),
    (re.compile(r"gAAAAA[A-Za-z0-9_=-]{20,}"), _REDACTED),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), _REDACTED),
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), _REDACTED),
    # Supabase secret key(파일 저장소 키, F-13·F-54). publishable key는 공개용이라 두지 않는다
    (re.compile(r"sb_secret_[A-Za-z0-9_-]{8,}"), _REDACTED),
    # 주소에 붙은 키: apiKeyNm=…, api_key=…, x_api_key=…, serviceKey=…
    (
        re.compile(r"(?i)(?<![A-Za-z0-9])((?:apiKeyNm|api_?key|service_?key)=)[^&\s'\"]+"),
        r"\1" + _REDACTED,
    ),
    # 공지 첨부 주소(F-54): verifier만 있으면 로그인 없이 받고, 저장소 서명 주소는 만료 전까지 열린다
    (
        re.compile(
            r"(?i)(?<![A-Za-z0-9])((?:verifier|x-amz-signature|x-amz-credential)=)[^&\s'\"]+"
        ),
        r"\1" + _REDACTED,
    ),
)
# 이런 말이 든 서식 문자열이면 인자를 통째로 가린다(숫자·None 말고는 종류를 가리지 않는다): logger.info("Authorization: %s", value)
_SENSITIVE_FORMAT = re.compile(r"(?i)authorization|bearer|token|secret|password|api[_-]?key")


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class _Redacted:
    """가릴 것이 있던 인자의 자리. `%s`로 찍든 `%r`로 찍든 가린 글이 나온다(원래 값은 들고 있지 않는다).

    예외 인자는 보통 `%r`로 찍는데(`logger.warning("실패: %r", exc)`), 어떤 예외는 `str()`에는 없는
    값이 `repr()`에 나온다(주소·헤더가 든 인자). 그래서 둘을 따로 가려 둔다.
    """

    __slots__ = ("_shown", "_text")

    def __init__(self, text: str, shown: str) -> None:
        self._text = text
        self._shown = shown

    def __str__(self) -> str:
        return self._text

    def __repr__(self) -> str:
        return self._shown

    def __format__(self, spec: str) -> str:
        return format(self._text, spec)


_installed = False


def install_log_redaction() -> None:
    """모든 로그 레코드의 메시지·인자·예외 내용에서 토큰을 가린다. 여러 번 불러도 한 번만 건다.

    인자가 있는 레코드는 서식 문자열을 건드리지 않고 인자만 가린다. 인자 개수와 타입이 그대로라서
    uvicorn 접근 로그처럼 인자를 직접 꺼내 쓰는 포매터도 깨지지 않는다.
    """
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()
    formatter = logging.Formatter()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        if record.args:
            mask_all = isinstance(record.msg, str) and bool(_SENSITIVE_FORMAT.search(record.msg))

            def clean(item: Any) -> Any:
                if isinstance(item, str):
                    return _REDACTED if mask_all else redact(item)
                if item is None or isinstance(item, numbers.Number):
                    return item  # 숫자(bool·Decimal 포함)는 %d·%f 자리라 바꾸면 서식이 깨진다
                if mask_all:
                    # 서식에 token·secret이 들어 있으면 그 자리의 값은 무엇이든 가린다. 문자열만 가리면 bytes·
                    # SecretStr·주소 객체로 넘긴 토큰이 패턴에 안 맞을 때 그대로 찍혔다(숫자·None은 그대로 둔다)
                    return _Redacted(_REDACTED, _REDACTED)
                try:  # httpx 요청 로그의 주소(httpx.URL) 같은 객체, `%r`로 찍는 예외
                    text = str(item)
                except Exception:
                    return item  # 문자열로 못 바꾸는 값은 로그 쪽이 알아서 처리한다(부른 곳을 멈추지 않는다)
                try:
                    shown = repr(item)
                except Exception:
                    shown = text  # repr만 깨진 값은 str로 찍은 것처럼 본다(가릴 것은 가린다)
                cleaned, cleaned_shown = redact(text), redact(shown)
                if cleaned == text and cleaned_shown == shown:
                    return item
                return _Redacted(cleaned, cleaned_shown)

            if isinstance(record.args, Mapping):
                record.args = {key: clean(item) for key, item in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(clean(item) for item in record.args)
        elif isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(formatter.formatException(record.exc_info))
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
