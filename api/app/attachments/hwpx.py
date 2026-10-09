"""HWPX(한글 2010 이후 기본 형식, OWPML) 본문 글자 추출. zip 안의 Contents/sectionN.xml을 읽는다.

표는 셀 주소로 행을 맞춰 "셀 | 셀" 한 줄로 만든다(table.py). 글상자·각주 안 글자도 읽는다.
XML은 표준 라이브러리로 읽는다. expat 2.4 이상은 엔티티 폭탄을 막고, 외부 엔티티는 풀지 않는다.
"""

import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree

from app.attachments.table import Cell, table_lines

_SECTION = re.compile(r"Contents/section(\d+)\.xml")
_MAX_XML_BYTES = (
    50 * 1024 * 1024
)  # 압축 폭탄 방지: 본문 XML 합계 상한(zip에 적힌 크기를 zipfile이 지킨다)
_MAX_MANIFEST_BYTES = 1024 * 1024
_INLINE = {"tab": "\t", "lineBreak": "\n", "nbSpace": " ", "fwSpace": " ", "hyphen": "-"}


class HwpxError(Exception):
    """읽을 수 없는 HWPX. 메시지는 첨부 실패 사유(extract_error)로 그대로 저장한다."""


def hwpx_text(data: bytes) -> str:
    try:
        return _read(data)
    except HwpxError:
        raise
    except Exception as exc:  # 깨진 zip·XML, 지원하지 않는 압축 방식 등
        raise HwpxError("HWPX를 읽을 수 없어요(파일이 깨졌을 수 있어요)") from exc


def _read(data: bytes) -> str:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        names = set(archive.namelist())
        if "META-INF/manifest.xml" in names:
            with archive.open("META-INF/manifest.xml") as member:
                manifest = member.read(_MAX_MANIFEST_BYTES)  # 압축 폭탄이어도 앞부분만 푼다
            if b"encryption-data" in manifest:
                raise HwpxError("암호가 걸렸거나 배포용으로 잠긴 HWPX예요")
        sections = sorted(
            (int(match.group(1)), name) for name in names if (match := _SECTION.fullmatch(name))
        )
        if not sections:
            raise HwpxError("본문(Contents/section)이 없어요")
        if sum(archive.getinfo(name).file_size for _, name in sections) > _MAX_XML_BYTES:
            raise HwpxError("본문이 너무 커요")
        lines: list[str] = []
        for _, name in sections:
            try:
                root = ElementTree.fromstring(archive.read(name))
            except ElementTree.ParseError as exc:
                raise HwpxError(f"{name}을 읽을 수 없어요") from exc
            lines.extend(_block(root))
    return "\n".join(lines)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(node: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in node if _local(child.tag) == name]


def _block(node: ElementTree.Element) -> list[str]:
    """문단(p)을 담은 그릇(sec, subList) → 줄 목록."""
    return [line for p in _children(node, "p") for line in _paragraph(p)]


def _paragraph(p: ElementTree.Element) -> list[str]:
    out: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        text = "".join(buffer).strip()
        buffer.clear()
        if text:
            out.append(text)

    def visit(node: ElementTree.Element) -> None:
        name = _local(node.tag)
        if name == "t":
            buffer.append(_t(node))
        elif name == "tbl":
            flush()
            out.extend(_table(node))
        elif name == "subList":  # 글상자·각주·머리말 안 문단
            flush()
            out.extend(_block(node))
        else:
            for child in node:
                visit(child)

    for child in p:
        visit(child)
    flush()
    return out


def _t(node: ElementTree.Element) -> str:
    parts = [node.text or ""]
    for child in node:
        parts.append(_INLINE.get(_local(child.tag), ""))
        parts.append(child.tail or "")
    return "".join(parts)


def _table(tbl: ElementTree.Element) -> list[str]:
    cells: list[Cell] = []
    for row_no, tr in enumerate(_children(tbl, "tr")):
        for col_no, tc in enumerate(_children(tr, "tc")):
            address = _attrs(tc, "cellAddr")
            cells.append(
                Cell(
                    row=_int(address.get("rowAddr"), row_no),
                    col=_int(address.get("colAddr"), col_no),
                    row_span=_int(_attrs(tc, "cellSpan").get("rowSpan"), 1),
                    lines=[line for sub in _children(tc, "subList") for line in _block(sub)],
                )
            )
    return table_lines(cells)


def _attrs(node: ElementTree.Element, name: str) -> dict[str, str]:
    found = _children(node, name)
    return dict(found[0].attrib) if found else {}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default
