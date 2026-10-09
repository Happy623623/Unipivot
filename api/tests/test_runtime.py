"""운영체제 차이 맞추기(app/runtime.py). Windows 동작은 sys.platform과 출력 스트림을 바꿔 확인한다."""

import asyncio
import io
import sys

import pytest

from app.runtime import event_loop_factory, utf8_output


def test_windows_uses_selector_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert event_loop_factory() is asyncio.SelectorEventLoop  # psycopg 비동기 연결이 되는 루프
    monkeypatch.setattr(sys, "platform", "linux")
    assert event_loop_factory() is None  # 다른 OS는 asyncio 기본값


class _Console(io.BytesIO):
    def isatty(self) -> bool:
        return True


def test_piped_output_becomes_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    # 한국어 Windows에서 파이프·파일로 보낼 때와 콘솔에 바로 쓸 때
    piped = io.TextIOWrapper(io.BytesIO(), encoding="cp949", newline="\n")
    console = io.TextIOWrapper(_Console(), encoding="cp949", newline="\n")
    monkeypatch.setattr(sys, "stdout", piped)
    monkeypatch.setattr(sys, "stderr", console)
    utf8_output()
    print("장학 — 공지 📢")  # cp949였으면 UnicodeEncodeError로 멈춘다
    piped.flush()
    assert piped.buffer.getvalue().decode("utf-8") == "장학 — 공지 📢\n"
    assert console.encoding == "cp949"  # 콘솔에 바로 쓸 때는 그대로 둔다
