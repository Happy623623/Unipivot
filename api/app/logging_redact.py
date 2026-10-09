"""로그에서 토큰을 가린다 (PRD 7장 토큰 보안). 앱을 만들 때 install_log_redaction()을 한 번 부른다.

가리는 것: Authorization 헤더, Bearer 토큰, token=… 값, JWT, Google access·refresh token,
LearningX(Canvas) 개인 액세스 토큰, Fernet 암호문, Anthropic·Google API 키.
"""

import logging
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
    (re.compile(r"\b\d{2,6}~[A-Za-z0-9]{20,}"), _REDACTED),
    (re.compile(r"gAAAAA[A-Za-z0-9_=-]{20,}"), _REDACTED),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), _REDACTED),
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), _REDACTED),
)
# 이런 말이 든 서식 문자열이면 인자(문자열)를 통째로 가린다: logger.info("Authorization: %s", value)
_SENSITIVE_FORMAT = re.compile(r"(?i)authorization|bearer|token|secret|password|api[_-]?key")


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


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
                if not isinstance(item, str):
                    return item
                return _REDACTED if mask_all else redact(item)

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
