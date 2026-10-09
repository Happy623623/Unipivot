"""테스트용 첨부 파일을 코드로 만든다. 실제 파일 대조는 docs/요건추출_구현.md의 '실제 파일 확인'에 있다."""

import struct
import zipfile
import zlib
from io import BytesIO

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from app.attachments.hwp import SIGNATURE, _rand

KOREAN_FONT = "HYSMyeongJo-Medium"  # reportlab 내장 CID 글꼴. 글꼴 파일 없이 한글 PDF를 만든다
pdfmetrics.registerFont(UnicodeCIDFont(KOREAN_FONT))


# ---------- PDF ----------


def pdf(pages: list[str | None], *, user_password: str | None = None) -> bytes:
    """쪽마다 글자를 쓴다. None인 쪽은 사각형만 그려 스캔본처럼 글자가 없다."""
    buffer = BytesIO()
    page_canvas = canvas.Canvas(buffer, encrypt=user_password)
    for text in pages:
        if text is None:
            page_canvas.rect(100, 300, 300, 300, fill=1)
        else:
            page_canvas.setFont(KOREAN_FONT, 11)
            for no, line in enumerate(text.splitlines()):
                page_canvas.drawString(60, 780 - 16 * no, line)
        page_canvas.showPage()
    page_canvas.save()
    return buffer.getvalue()


# ---------- HWPX ----------

_HWPX_NS = (
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
)


def hwpx(*sections: str, encrypted: bool = False) -> bytes:
    """sections는 <hs:sec> 안쪽 XML이다. 순서대로 section0.xml, section1.xml …이 된다."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        manifest = "<odf:encryption-data/>" if encrypted else ""
        archive.writestr(
            "META-INF/manifest.xml",
            '<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
            f"{manifest}</odf:manifest>",
        )
        for no, body in enumerate(sections):
            archive.writestr(
                f"Contents/section{no}.xml",
                f'<?xml version="1.0" encoding="UTF-8"?><hs:sec {_HWPX_NS}>{body}</hs:sec>',
            )
    return buffer.getvalue()


def hp(text: str) -> str:
    return f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"


def hp_cell(row: int, col: int, text: str, row_span: int = 1) -> str:
    return (
        f"<hp:tc><hp:subList>{hp(text)}</hp:subList>"
        f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
        f'<hp:cellSpan colSpan="1" rowSpan="{row_span}"/></hp:tc>'
    )


# ---------- HWP 5.0 ----------

PARA_HEADER, PARA_TEXT, CTRL_HEADER, LIST_HEADER, TABLE = 66, 67, 71, 72, 77


def record(tag: int, level: int, payload: bytes) -> bytes:
    if len(payload) >= 0xFFF:
        return struct.pack("<II", tag | level << 10 | 0xFFF << 20, len(payload)) + payload
    return struct.pack("<I", tag | level << 10 | len(payload) << 20) + payload


def para(level: int, text: str) -> bytes:
    """문단 하나(PARA_HEADER + PARA_TEXT). 끝의 13은 문단 끝 문자다."""
    return record(PARA_HEADER, level, b"\x00" * 22) + record(
        PARA_TEXT, level + 1, text.encode("utf-16-le") + struct.pack("<H", 13)
    )


def table(
    level: int, cells: list[tuple[int, int, int, str]], *, caption: str | None = None
) -> bytes:
    """level 문단 안의 표. cells는 (행, 열, 행 병합, 글자). 캡션은 TABLE 레코드 앞에 온다."""
    control = struct.pack("<8H", 11, 0x6C74, 0x2062, 0, 0, 0, 0, 11)  # 표 확장 제어 문자
    out = record(PARA_HEADER, level, b"\x00" * 22)
    out += record(PARA_TEXT, level + 1, control + struct.pack("<H", 13))
    out += record(CTRL_HEADER, level + 1, int.from_bytes(b"tbl ", "big").to_bytes(4, "little"))
    if caption is not None:  # 캡션 리스트 헤더: 셀 헤더와 같은 수준이라 셀로 오인하기 쉽다
        out += record(LIST_HEADER, level + 2, struct.pack("<iI", 1, 0) + b"\x07\x00" * 8)
        out += para(level + 2, caption)
    out += record(TABLE, level + 2, b"\x00" * 18)
    for row, col, row_span, text in cells:
        header = struct.pack("<iIHHHH", 1, 0, col, row, 1, row_span) + b"\x00" * 18
        out += record(LIST_HEADER, level + 2, header) + para(level + 2, text)
    return out


class FakeOle:
    """olefile.OleFileIO 대역. 테스트에서는 OLE 파일을 새로 만들 수 없어 스트림 사전으로 흉내 낸다."""

    def __init__(self, streams: dict[str, bytes]) -> None:
        self.streams = streams

    def exists(self, name: str) -> bool:
        return name in self.streams

    def listdir(self) -> list[list[str]]:
        return [name.split("/") for name in self.streams]

    def openstream(self, name: str) -> BytesIO:
        return BytesIO(self.streams[name])


def hwp_ole(
    *sections: bytes, compressed: bool = True, distribution: bool = False, version: int = 0x05000300
) -> FakeOle:
    props = int(compressed) | int(distribution) << 2
    streams = {"FileHeader": SIGNATURE.ljust(32, b"\x00") + struct.pack("<II", version, props)}
    storage = "ViewText" if distribution else "BodyText"
    for no, section in enumerate(sections):
        if compressed:
            deflater = zlib.compressobj(wbits=-15)
            section = deflater.compress(section) + deflater.flush()
        if distribution:
            section = _encrypt_distribution(section)
        streams[f"{storage}/Section{no}"] = section
    return FakeOle(streams)


def _encrypt_distribution(body: bytes) -> bytes:
    """배포용 문서 만들기: 256바이트 머리에 AES 키를 숨기고 본문을 AES-128-ECB로 잠근다."""
    key = bytes(range(16))
    head = bytearray(256)
    head[:4] = (0x2A2A2A2A).to_bytes(4, "little")
    offset = 4 + (head[0] & 0xF)
    head[offset : offset + 16] = key
    _xor_keystream(head)  # 같은 씨앗의 XOR이라 한 번 더 하면 원래대로 돌아온다
    padder = padding.PKCS7(128).padder()
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    sealed = encryptor.update(padder.update(body) + padder.finalize()) + encryptor.finalize()
    return struct.pack("<I", 28 | 256 << 20) + bytes(head) + sealed


def _xor_keystream(data: bytearray) -> None:
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


# ---------- 이미지 ----------

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
