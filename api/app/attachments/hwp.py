"""HWP 5.0(바이너리) 본문 글자 추출. 배포용 문서도 읽는다. 공개된 "한글 문서 파일 형식 5.0" 기준.

표는 셀 주소로 행을 맞춰 "셀 | 셀" 한 줄로 만든다(table.py). 그림·수식 등 글자가 아닌 개체는 건너뛴다.
"""

import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from io import BytesIO
from typing import Protocol

import olefile
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.attachments.table import Cell, table_lines

SIGNATURE = b"HWP Document File"
_MAX_TOTAL_BYTES = 64 * 1024 * 1024  # 압축 폭탄 방지: 모든 구역을 풀었을 때 합계 상한
_MAX_SECTIONS = 256
_MAX_RECORDS = (
    2_000_000  # 문서 전체 레코드 수 상한(글자 190만 자 시험 파일이 64만 개). 처리 시간을 묶는다
)
_FIRST_TAG = 16  # HWPTAG_BEGIN. 이보다 작은 태그는 없으므로 나오면 깨진 뒷부분으로 보고 멈춘다
# HWPTAG_BEGIN(16) + 51, 55, 56, 61
_PARA_TEXT, _CTRL_HEADER, _LIST_HEADER, _TABLE_RECORD = 67, 71, 72, 77
_TABLE_ID = "tbl "
# 8글자(16바이트)를 차지하는 제어 문자: 인라인 4–9·19·20, 확장 1–3·11·12·14–18·21–23
_WIDE_CONTROLS = frozenset(
    {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
)


class HwpError(Exception):
    """읽을 수 없는 HWP. 메시지는 첨부 실패 사유(extract_error)로 그대로 저장한다."""


class OleLike(Protocol):
    def exists(self, name: str) -> bool: ...
    def listdir(self) -> list[list[str]]: ...
    def openstream(self, name: str) -> BytesIO: ...


def hwp_text(data: bytes) -> str:
    try:
        if not olefile.isOleFile(data=data):
            raise HwpError("HWP 5.0 파일이 아니에요(OLE 형식이 아님)")
        with olefile.OleFileIO(data) as ole:
            return read_ole(ole)
    except HwpError:
        raise
    except Exception as exc:  # 깨진 OLE·레코드
        raise HwpError("HWP를 읽을 수 없어요(파일이 깨졌을 수 있어요)") from exc


def read_ole(ole: OleLike) -> str:
    if not ole.exists("FileHeader"):
        raise HwpError("FileHeader가 없어요")
    header = ole.openstream("FileHeader").read()
    if not header.startswith(SIGNATURE):
        raise HwpError("HWP 문서 서명이 없어요")
    (version,) = struct.unpack_from("<I", header, 32)
    (props,) = struct.unpack_from("<I", header, 36)
    if version >> 24 != 5:
        raise HwpError(f"지원하지 않는 HWP 버전이에요({version >> 24})")
    if props & 0b10:
        raise HwpError("암호가 걸린 문서예요")
    compressed, distribution = bool(props & 0b1), bool(props & 0b100)
    storage = "ViewText" if distribution else "BodyText"
    sections = sorted(
        (int(path[1][len("Section") :]), "/".join(path))
        for path in ole.listdir()
        if len(path) == 2 and path[0] == storage and path[1][len("Section") :].isdigit()
    )
    if not sections:
        raise HwpError(f"{storage}에 본문이 없어요")
    if len(sections) > _MAX_SECTIONS:
        raise HwpError("구역이 너무 많아요")
    lines: list[str] = []
    budget = _MAX_TOTAL_BYTES
    counter = _Counter(_MAX_RECORDS)
    for _, name in sections:
        raw = ole.openstream(name).read()
        if distribution:
            raw = _decrypt(raw)
        if compressed:
            raw = _inflate(raw, budget)
        budget -= len(raw)
        if budget < 0:
            raise HwpError("본문이 너무 커요")
        lines.extend(section_lines(raw, counter))
    return "\n".join(lines)


def section_lines(data: bytes, counter: "_Counter | None" = None) -> list[str]:
    """압축을 푼 Section 스트림 → 줄 목록. 표는 행마다 한 줄.

    표 컨트롤의 레코드 순서: CTRL_HEADER("tbl ") → [캡션 LIST_HEADER + 문단] → TABLE → 셀 LIST_HEADER들.
    TABLE 레코드 앞의 LIST_HEADER는 캡션이라 셀로 보지 않고, 캡션 글자는 표 밖 글로 둔다.
    """
    out: list[str] = []
    stack: list[_Table] = []
    for tag, level, payload in records(data):
        if counter is not None:
            counter.spend()
        while stack and level <= stack[-1].level:
            _close(stack, out)
        inner = bool(stack) and level == stack[-1].level + 1
        if tag == _CTRL_HEADER and _ctrl_id(payload) == _TABLE_ID:
            stack.append(_Table(level=level))
        elif tag == _TABLE_RECORD and inner:
            stack[-1].started = True
        elif tag == _LIST_HEADER and inner and stack[-1].started and len(payload) >= 16:
            # 셀 문단 리스트 헤더: 문단 수(4) 속성(4) 열(2) 행(2) 열 병합(2) 행 병합(2) …
            col, row, _, row_span = struct.unpack_from("<HHHH", payload, 8)
            stack[-1].cells.append(Cell(row=row, col=col, row_span=row_span))
        elif tag == _PARA_TEXT:
            text = para_text(payload).strip()
            if text:
                _append(stack, out, [text])
    while stack:
        _close(stack, out)
    return out


def records(data: bytes) -> Iterator[tuple[int, int, bytes]]:
    """레코드 헤더(32비트): 태그 10비트, 수준 10비트, 크기 12비트(0xFFF면 다음 4바이트가 크기)."""
    pos, end = 0, len(data)
    while pos + 4 <= end:
        (header,) = struct.unpack_from("<I", data, pos)
        pos += 4
        tag, level, size = header & 0x3FF, (header >> 10) & 0x3FF, header >> 20
        if tag < _FIRST_TAG:
            return
        if size == 0xFFF:
            if pos + 4 > end:
                return
            (size,) = struct.unpack_from("<I", data, pos)
            pos += 4
        yield tag, level, data[pos : pos + size]
        pos += size


def para_text(payload: bytes) -> str:
    units = struct.unpack_from(f"<{len(payload) // 2}H", payload)
    out: list[int] = []
    i = 0
    while i < len(units):
        code = units[i]
        if code >= 32:
            out.append(code)
            i += 1
        elif code in _WIDE_CONTROLS:
            if code == 9:
                out.append(9)  # 탭
            i += 8
        else:
            if code == 10:
                out.append(10)  # 줄 바꿈
            elif code == 24:
                out.append(ord("-"))
            elif code in (30, 31):
                out.append(32)  # 묶음 빈칸, 고정폭 빈칸
            i += 1  # 13(문단 끝)·0 등은 버린다
    return struct.pack(f"<{len(out)}H", *out).decode("utf-16-le", errors="replace")


class _Counter:
    def __init__(self, limit: int) -> None:
        self.left = limit

    def spend(self) -> None:
        self.left -= 1
        if self.left < 0:
            raise HwpError("본문이 너무 커요")


@dataclass
class _Table:
    level: int
    started: bool = False  # TABLE 레코드를 지났다(이후 LIST_HEADER가 셀)
    cells: list[Cell] = field(default_factory=list)


def _append(stack: list[_Table], out: list[str], lines: list[str]) -> None:
    """가장 안쪽의 열린 셀에 넣는다. 열린 셀이 없으면(표 밖·캡션) 본문 줄이다."""
    for table in reversed(stack):
        if table.cells:
            table.cells[-1].lines.extend(lines)
            return
    out.extend(lines)


def _close(stack: list[_Table], out: list[str]) -> None:
    _append(stack, out, table_lines(stack.pop().cells))  # 셀 안의 표는 그 셀 글자로 넣는다


def _ctrl_id(payload: bytes) -> str:
    if len(payload) < 4:
        return ""
    (value,) = struct.unpack_from("<I", payload, 0)
    return value.to_bytes(4, "big").decode("latin-1")


def _inflate(raw: bytes, limit: int) -> bytes:
    inflater = zlib.decompressobj(-15)  # 머리 없는 deflate
    try:
        data = inflater.decompress(raw, max(limit, 1))
    except zlib.error as exc:
        raise HwpError("본문 압축을 풀 수 없어요") from exc
    if inflater.unconsumed_tail:
        raise HwpError("본문이 너무 커요")
    return data


def _decrypt(raw: bytes) -> bytes:
    """배포용 문서: 첫 레코드(4+256바이트)에서 AES 키를 꺼내 나머지를 AES-128-ECB로 푼다."""
    if len(raw) < 260:
        raise HwpError("배포용 문서의 본문이 너무 짧아요")
    data = bytearray(raw[4:260])
    seed = int.from_bytes(data[:4], "little")
    value = count = 0
    for i in range(256):
        if count == 0:
            seed, value = _rand(seed)
            seed, number = _rand(seed)
            value &= 0xFF
            count = (number & 0xF) + 1
        if i >= 4:
            data[i] ^= value
        count -= 1
    offset = 4 + (data[0] & 0xF)
    key = bytes(data[offset : offset + 16])
    body = raw[260:]
    body = body[: len(body) - len(body) % 16]
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    plain = decryptor.update(body) + decryptor.finalize()
    pad = plain[-1] if plain else 0
    if 1 <= pad <= 16 and plain.endswith(bytes([pad]) * pad):
        plain = plain[:-pad]
    return plain


def _rand(seed: int) -> tuple[int, int]:
    seed = (seed * 214013 + 2531011) & 0xFFFFFFFF  # MSVC rand()
    return seed, (seed >> 16) & 0x7FFF
