"""운영체제 차이를 맞춘다. 명령줄 도구(app.crawl.cli·app.extraction.cli)와 테스트 설정이 쓴다."""

import asyncio
import io
import sys
from collections.abc import Callable


def event_loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    """asyncio.run에 넘길 이벤트 루프. Windows가 아니면 기본값(None)이다.

    Windows 기본 루프(Proactor)에서는 psycopg 비동기 연결이 InterfaceError로 멈춘다.
    그래서 Windows에서는 Selector 루프를 쓴다. Selector 루프는 하위 프로세스를 못 띄우지만 쓰지 않는다.
    """
    return asyncio.SelectorEventLoop if sys.platform == "win32" else None


def utf8_output() -> None:
    """콘솔이 아닌 곳(파이프·파일·Claude Code)으로 나가는 출력을 UTF-8로 쓴다.

    Windows는 이때 시스템 인코딩(한국어 Windows는 cp949)으로 써서, 공지 제목의 —·이모지처럼 cp949에
    없는 글자에서 멈추고 UTF-8로 읽는 도구에서는 한글이 깨진다. 콘솔에 바로 쓸 때는 그대로 둔다.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
