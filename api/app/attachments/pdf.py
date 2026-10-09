"""PDF 글자 추출(pypdf). 글자 층이 없거나 깨진 쪽은 스캔본으로 보고 Vision으로 넘긴다."""

import logging
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader, PdfWriter

# pypdf는 고칠 수 없는 글꼴 경고를 쪽마다 남긴다. 실패는 예외로 받으므로 경고는 끈다
logging.getLogger("pypdf").setLevel(logging.ERROR)

MAX_PAGES = 100  # 이보다 긴 PDF는 앞쪽만 읽는다. 공지 첨부는 대부분 30쪽 안이다
_MIN_CHARS = 20  # 공백을 뺀 글자가 이보다 적으면(쪽 번호·머리글뿐) 글자 없는 쪽으로 본다
# 글꼴의 글자 대응표가 깨졌을 때 나오는 문자: 사용자 정의 영역(U+E000–F8FF)과 대체 문자(U+FFFD)
_GARBLED = frozenset(range(0xE000, 0xF900)) | {0xFFFD}


class PdfError(Exception):
    """읽을 수 없는 PDF. 메시지는 첨부 실패 사유(extract_error)로 그대로 저장한다."""


@dataclass(frozen=True)
class PdfText:
    pages: tuple[str, ...]  # 읽은 쪽의 글자. 1쪽이 0번
    page_count: int  # 전체 쪽 수. MAX_PAGES보다 크면 pages가 더 짧다

    @property
    def image_pages(self) -> tuple[int, ...]:
        """글자가 거의 없거나 깨진 쪽(1부터). Vision으로 볼 후보이고, 스캔본이면 전부다."""
        return tuple(no for no, text in enumerate(self.pages, 1) if not has_text(text))

    @property
    def text(self) -> str:
        """깨지지 않은 쪽의 글자. 표지처럼 글자가 적은 쪽도 넣는다."""
        return "\n".join(page.strip() for page in self.pages if _readable(page)[1])

    @property
    def scanned(self) -> bool:
        """글자 있는 쪽이 하나도 없다. 통째로 Vision으로 본다."""
        return not any(has_text(page) for page in self.pages)


def pdf_text(data: bytes) -> PdfText:
    reader = _open(data)
    page_count = len(reader.pages)
    pages: list[str] = []
    for index in range(min(page_count, MAX_PAGES)):
        try:
            pages.append(reader.pages[index].extract_text() or "")
        except Exception:  # 쪽 하나가 깨져도 나머지는 읽는다. 그 쪽은 글자 없는 쪽이 된다
            pages.append("")
    return PdfText(pages=tuple(pages), page_count=page_count)


def pdf_page_count(data: bytes) -> int:
    return len(_open(data).pages)


def pdf_slice(data: bytes, first: int, count: int) -> bytes:
    """first쪽(1부터)부터 count쪽만 담은 PDF. Vision에 필요한 쪽만 보내 토큰을 아낀다."""
    reader = _open(data)
    try:
        writer = PdfWriter()
        for page in reader.pages[first - 1 : first - 1 + count]:
            writer.add_page(page)
        buffer = BytesIO()
        writer.write(buffer)
    except Exception as exc:  # 열리기는 해도 쪽 내용이 깨진 PDF
        raise PdfError("PDF 쪽을 잘라 낼 수 없어요(파일이 깨졌을 수 있어요)") from exc
    return buffer.getvalue()


def has_text(text: str) -> bool:
    """읽을 만한 글자가 충분한지. 쪽 번호·머리글만 있는 스캔 쪽과 글꼴 정보가 깨진 쪽을 걸러 낸다."""
    count, clean = _readable(text)
    return clean and count >= _MIN_CHARS


def _readable(text: str) -> tuple[int, bool]:
    """(읽을 수 있는 글자 수, 깨지지 않았는지). 70% 넘게 _GARBLED 문자가 아니면 깨지지 않은 쪽이다."""
    visible = [ch for ch in text if not ch.isspace()]
    count = sum(1 for ch in visible if ch.isprintable() and ord(ch) not in _GARBLED)
    return count, count > 0 and count >= len(visible) * 0.7


def _open(data: bytes) -> PdfReader:
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise PdfError("암호가 걸린 PDF예요")
        if len(reader.pages) == 0:
            raise PdfError("쪽이 없는 PDF예요")
        return reader
    except PdfError:
        raise
    except Exception as exc:  # pypdf는 깨진 파일에서 여러 종류의 예외를 낸다
        raise PdfError("PDF를 열 수 없어요(파일이 깨졌을 수 있어요)") from exc
