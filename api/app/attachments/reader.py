"""첨부 읽기 입구: 형식을 알아내고 글자를 뽑는다.

처리 순서(10/8 확정): 본문 → PDF 글자 → HWPX → HWP → 글자 없는 PDF·이미지는 Vision.
여기 없는 형식(DOCX·XLSX·ZIP·HWP 3.0 등)은 UnreadableAttachment로 끝나고 공고는 '원문 확인 필요'가 된다.
형식은 파일 이름보다 내용 앞부분(매직 바이트)을 믿는다. 게시판 첨부는 확장자가 틀린 경우가 있다.
"""

import logging
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO

import olefile

from app.attachments.hwp import SIGNATURE as HWP_SIGNATURE
from app.attachments.hwp import HwpError, hwp_text
from app.attachments.hwpx import HwpxError, hwpx_text
from app.attachments.pdf import PdfError, pdf_page_count, pdf_slice, pdf_text

IMAGE_MIME = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
MIME_TYPES = {
    **IMAGE_MIME,
    "pdf": "application/pdf",
    "hwp": "application/x-hwp",
    "hwpx": "application/hwp+zip",
    "gif": "image/gif",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "zip": "application/zip",
}
MAX_VISION_BYTES = 15 * 1024 * 1024
KIND_LABELS = {
    "pdf": "PDF",
    "hwpx": "HWPX",
    "hwp": "HWP",
    "png": "이미지(PNG)",
    "jpeg": "이미지(JPG)",
    "webp": "이미지(WEBP)",
}
_UNSUPPORTED = {
    "hwp3": "HWP 3.0 이전 문서는 못 읽어요",
    "ole": "HWP가 아닌 옛 오피스 문서(DOC·XLS·PPT)는 못 읽어요",
    "docx": "DOCX는 아직 못 읽어요",
    "xlsx": "XLSX는 아직 못 읽어요",
    "pptx": "PPTX는 아직 못 읽어요",
    "zip": "압축 파일은 못 읽어요",
    "gif": "GIF 이미지는 못 읽어요",
    "image": "이 이미지 형식은 못 읽어요",
}
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# 탭·줄 바꿈을 뺀 제어 문자. NUL은 Postgres text·jsonb에 들어가지 않아 저장이 통째로 실패한다
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BROKEN = "파일을 읽다가 오류가 났어요(깨진 파일일 수 있어요)"
logger = logging.getLogger(__name__)


class UnreadableAttachment(Exception):
    """읽을 수 없는 첨부. str(예외)는 extract_error로 저장하고 모델에도 그대로 돌려준다."""


@dataclass(frozen=True)
class AttachmentText:
    kind: str  # detect_format 결과
    method: str | None  # extract_method 값(pdf_text·hwpx_text·hwp_text). 글자가 없으면 None
    text: str
    page_count: int | None = None  # PDF만
    image_pages: tuple[int, ...] = ()  # PDF에서 글자가 거의 없어 Vision으로 볼 후보인 쪽(1부터)

    @property
    def needs_vision(self) -> bool:
        """이미지이거나 글자가 하나도 없는 PDF."""
        return self.method is None


@dataclass(frozen=True)
class VisionPayload:
    data: bytes
    mime_type: str
    first_page: int | None = None  # PDF일 때 보낸 쪽 범위
    last_page: int | None = None
    page_count: int | None = None


def clean_text(text: str) -> str:
    """DB·JSON에 넣을 수 없는 제어 문자를 지운다. 추출한 글자와 모델이 보낸 글자에 쓴다."""
    return _CONTROL.sub("", text)


def detect_format(data: bytes, file_name: str | None = None) -> str:
    """형식 이름. 깨진 파일이어도 예외를 내지 않는다."""
    try:
        return _detect(data, file_name)
    except Exception:
        return "unknown"


def _detect(data: bytes, file_name: str | None) -> str:
    head = data[:1024]
    if b"%PDF-" in head:
        return "pdf"
    if data.startswith(b"HWP Document File V"):
        return "hwp3"
    if data.startswith(_OLE_MAGIC):
        return "hwp" if _is_hwp(data) else "ole"
    if data.startswith(b"PK\x03\x04"):
        return _zip_kind(data)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] in (b"II*\x00", b"MM\x00*") or data[4:12] in (b"ftypheic", b"ftypheix"):
        return "image"
    name = (file_name or "").lower()
    if name.endswith((".bmp", ".tif", ".tiff", ".heic")):
        return "image"
    return "unknown"


def read_attachment_text(data: bytes, file_name: str | None = None) -> AttachmentText:
    """글자 추출. 실패는 모두 UnreadableAttachment(사유 한 줄)로 바꿔서 실행 전체가 멈추지 않게 한다."""
    kind = detect_format(data, file_name)
    try:
        if kind == "pdf":
            pdf = pdf_text(data)
            if pdf.scanned:
                all_pages = tuple(range(1, pdf.page_count + 1))
                return AttachmentText(kind, None, "", pdf.page_count, all_pages)
            text = clean_text(pdf.text)
            return AttachmentText(kind, "pdf_text", text, pdf.page_count, pdf.image_pages)
        if kind in IMAGE_MIME:
            return AttachmentText(kind, None, "")
        if kind == "hwpx":
            text, method = hwpx_text(data), "hwpx_text"
        elif kind == "hwp":
            text, method = hwp_text(data), "hwp_text"
        else:
            raise UnreadableAttachment(_UNSUPPORTED.get(kind, "알 수 없는 형식이라 못 읽어요"))
    except UnreadableAttachment:
        raise
    except (PdfError, HwpxError, HwpError) as exc:
        raise UnreadableAttachment(str(exc)) from exc
    except Exception as exc:  # 추출기가 예상하지 못한 파일. 로그만 남기고 못 읽은 첨부로 둔다
        logger.warning("첨부 글자 추출 실패(%s): %r", file_name, exc)
        raise UnreadableAttachment(_BROKEN) from exc
    text = clean_text(text)
    if not text.strip():
        raise UnreadableAttachment("글자가 없는 문서예요(그림만 있을 수 있어요)")
    return AttachmentText(kind, method, text)


def vision_payload(
    data: bytes, kind: str, *, start_page: int = 1, max_pages: int = 4
) -> VisionPayload:
    """Vision 모델에 보낼 파일. PDF는 start_page부터 max_pages쪽만 잘라 보낸다."""
    if kind == "pdf":
        try:
            page_count = pdf_page_count(data)
            if not 1 <= start_page <= page_count:
                raise UnreadableAttachment(f"{page_count}쪽까지만 있어요")
            last = min(page_count, start_page + max_pages - 1)
            payload = VisionPayload(
                pdf_slice(data, start_page, last - start_page + 1),
                "application/pdf",
                start_page,
                last,
                page_count,
            )
        except UnreadableAttachment:
            raise
        except PdfError as exc:
            raise UnreadableAttachment(str(exc)) from exc
        except Exception as exc:  # 열리기는 하지만 쪽을 자를 수 없는 깨진 PDF
            raise UnreadableAttachment(_BROKEN) from exc
    elif kind in IMAGE_MIME:
        payload = VisionPayload(data, IMAGE_MIME[kind])
    else:
        raise UnreadableAttachment("이미지나 PDF가 아니라 Vision으로 볼 수 없어요")
    if len(payload.data) > MAX_VISION_BYTES:
        raise UnreadableAttachment("파일이 너무 커서(15MB 넘음) Vision으로 못 보내요")
    return payload


def _is_hwp(data: bytes) -> bool:
    try:
        with olefile.OleFileIO(data) as ole:
            return (
                ole.exists("FileHeader")
                and ole.openstream("FileHeader").read(len(HWP_SIGNATURE)) == HWP_SIGNATURE
            )
    except Exception:  # 깨진 OLE
        return False


def _zip_kind(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
            mimetype = b""
            if "mimetype" in names:
                with archive.open("mimetype") as member:
                    mimetype = member.read(64)  # 압축 폭탄이어도 앞 64바이트만 푼다
    except Exception:  # 깨진 zip, 암호 걸린 항목, 잘못된 파일 이름 인코딩
        return "zip"
    if mimetype.startswith(b"application/hwp+zip") or "Contents/section0.xml" in names:
        return "hwpx"
    if "word/document.xml" in names:
        return "docx"
    if "xl/workbook.xml" in names:
        return "xlsx"
    if "ppt/presentation.xml" in names:
        return "pptx"
    return "zip"
