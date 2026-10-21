"""업로드 파일 검사 (F-13, API 명세 6장).

파일 이름과 브라우저가 보낸 Content-Type은 믿지 않고 앞부분 바이트로 형식을 가린다. 확장자만 .jpg로
바꾼 실행 파일이 저장소에 들어가지 않게 하려는 것이다.

포스터는 JPG·PNG·WEBP 사진과 2쪽 이하 PDF를 받는다. HEIC(아이폰 기본 사진 형식)는 아직 못 읽는다.
아이폰에서 고른 사진은 그대로 HEIC로 올라오기 쉬워서, "형식이 아니에요" 대신 무엇을 하면 되는지
알려 준다.

20MB까지만 메모리로 올린다. FastAPI는 핸들러가 돌기 전에 몸통을 모두 받아 임시 파일에 쓰므로
(1MB가 넘으면 디스크), 여기서 끊는 것은 큰 파일을 통째로 메모리에 올리지 않기 위한 것이다. 아주 큰
몸통 자체를 거절하는 것은 앞단(프록시·ASGI)의 몫이다.
"""

import hashlib
import io
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.eligibility.dates import KST
from app.errors import ApiError

MAX_BYTES = 20 * 1024 * 1024
MAX_MB = MAX_BYTES // (1024 * 1024)
POSTER_MAX_PAGES = 2
SYLLABUS_MAX_PAGES = 10  # 강의계획서는 보통 2~6쪽이다(녹화한 포털 계획서 기준)
# 강의자료(F-15). 요약은 글자 수(토큰 상한)로 막고, 쪽수 상한은 깨진 PDF·아주 긴 파일을 읽느라 서버가 멈추지
# 않게 하는 것이다. 슬라이드 한 학기 묶음도 보통 이 안이다
LECTURE_MAX_PAGES = 300
PDF_TEXT_MAX_CHARS = 60_000  # 뽑은 글자 상한. 계획서 10쪽이면 2만 자 안쪽이다
DAILY_UPLOAD_LIMIT = 20  # 사용자당 KST 하루 (API 명세 14장, 10/15 확정)
_CHUNK_BYTES = 1024 * 1024
_NAME_MAX = 200
_EXTENSION_MAX = 10  # 이름을 줄일 때 남기는 확장자 길이 상한(그보다 길면 확장자가 아니라 본다)


@dataclass(frozen=True)
class FileType:
    mime: str
    extension: str


JPEG = FileType("image/jpeg", "jpg")
PNG = FileType("image/png", "png")
WEBP = FileType("image/webp", "webp")
PDF = FileType("application/pdf", "pdf")
HEIC = FileType("image/heic", "heic")

# ISO 기반 미디어 파일(ftyp 박스)의 HEIF 계열 브랜드. 아이폰 사진은 heic·heix·mif1로 온다
_HEIF_BRANDS = frozenset({b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"})


def sniff(data: bytes) -> FileType | None:
    """앞부분 바이트로 가린 형식. 아는 형식이 아니면 None이다."""
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    if data.startswith(b"%PDF-"):
        return PDF
    if data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        return HEIC
    return None


class Chunked(Protocol):
    """UploadFile처럼 조금씩 읽을 수 있는 것."""

    async def read(self, size: int = -1, /) -> bytes: ...


async def read_upload(source: Chunked) -> bytes:
    """20MB까지만 모은다. 넘으면 나머지를 읽지 않고 413이다."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await source.read(_CHUNK_BYTES):
        total += len(chunk)
        if total > MAX_BYTES:
            raise ApiError(
                413,
                "FILE_TOO_LARGE",
                f"파일이 {MAX_MB}MB를 넘어요. 더 작은 파일을 올려 주세요.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class Inspected:
    type: FileType
    page_count: int | None  # PDF만 센다
    sha256: str


def inspect_poster(data: bytes) -> Inspected:
    """포스터로 받을 수 있는 파일인지 보고 형식·쪽수·해시를 돌려준다."""
    found = sniff(data)
    if found is HEIC:
        raise ApiError(
            400,
            "UNSUPPORTED_FILE_TYPE",
            "아이폰 사진 형식(HEIC)은 아직 올릴 수 없어요. 사진을 JPG로 바꿔서 올려 주세요.",
        )
    if found is None:
        raise ApiError(
            400,
            "UNSUPPORTED_FILE_TYPE",
            "JPG·PNG·WEBP 사진이나 2쪽 이하 PDF만 올릴 수 있어요.",
        )
    pages = _pdf_pages(data) if found is PDF else None
    if pages is not None and pages > POSTER_MAX_PAGES:
        raise ApiError(
            413,
            "PAGE_LIMIT_EXCEEDED",
            f"PDF는 {POSTER_MAX_PAGES}쪽까지만 올릴 수 있어요. 포스터가 있는 쪽만 남겨서 올려 주세요.",
        )
    return Inspected(found, pages, hashlib.sha256(data).hexdigest())


def inspect_syllabus(data: bytes) -> Inspected:
    """강의계획서로 받을 수 있는 파일인지 본다. **텍스트가 있는 PDF만** 받는다(명세 6장).

    포털 계획서를 브라우저에서 "PDF로 저장"해 올리는 길이라 스캔본은 거의 없다. 그래도 사진을
    PDF로 감싼 파일이 올 수 있어서, 글자를 못 뽑으면 여기서 막는다 — 모델에 보내도 읽을 것이 없다.
    """
    found = sniff(data)
    if found is not PDF:
        raise ApiError(
            400,
            "UNSUPPORTED_FILE_TYPE",
            "강의계획서는 PDF만 올릴 수 있어요. 포털 계획서를 "
            f"PDF로 저장해서 올려 주세요({SYLLABUS_MAX_PAGES}쪽까지).",
        )
    pages = _pdf_pages(data, advice="포털 계획서를 브라우저에서 PDF로 저장해 올려 주세요.")
    if pages > SYLLABUS_MAX_PAGES:
        raise ApiError(
            413,
            "PAGE_LIMIT_EXCEEDED",
            f"PDF는 {SYLLABUS_MAX_PAGES}쪽까지만 올릴 수 있어요. 계획서 쪽만 남겨서 올려 주세요.",
        )
    if not pdf_text(data).strip():
        raise ApiError(
            400,
            "UNSUPPORTED_FILE_TYPE",
            "PDF에서 글자를 찾지 못했어요. 사진을 PDF로 만든 파일은 읽을 수 없어요."
            " 포털 계획서를 브라우저에서 PDF로 저장해 올려 주세요.",
        )
    return Inspected(found, pages, hashlib.sha256(data).hexdigest())


def inspect_lecture_material(data: bytes) -> Inspected:
    """강의자료로 받을 수 있는 파일인지 본다. **글자가 있는 PDF만** 받는다(F-15 축소판, 명세 6장).

    스캔한 쪽은 읽지 않는다(Vision은 확장 범위). 글자를 하나도 못 뽑으면 요약할 것이 없어서 여기서 막는다.
    """
    found = sniff(data)
    advice = "LMS에서 받은 PDF를 그대로 올려 주세요."
    if found is not PDF:
        raise ApiError(400, "UNSUPPORTED_FILE_TYPE", f"강의자료는 PDF만 올릴 수 있어요. {advice}")
    pages = _pdf_pages(data, advice=advice)
    if pages > LECTURE_MAX_PAGES:
        raise ApiError(
            413,
            "PAGE_LIMIT_EXCEEDED",
            f"PDF는 {LECTURE_MAX_PAGES}쪽까지만 올릴 수 있어요. 요약할 부분만 나눠서 올려 주세요.",
        )
    if not pdf_text(data, max_chars=1_000).strip():
        raise ApiError(
            400,
            "UNSUPPORTED_FILE_TYPE",
            "PDF에서 글자를 찾지 못했어요. 스캔한 자료는 아직 요약할 수 없어요."
            " 글자를 고를 수 있는 PDF를 올려 주세요.",
        )
    return Inspected(found, pages, hashlib.sha256(data).hexdigest())


def pdf_text(data: bytes, *, max_chars: int = PDF_TEXT_MAX_CHARS) -> str:
    """PDF에서 뽑은 글자(쪽마다 줄바꿈으로 잇는다). 읽지 못하면 빈 글자다.

    상한을 두는 것은 모델 입력을 재는 쪽이 아니라, 깨진 PDF가 메모리를 다 먹지 않게 하려는 것이다.
    """
    try:
        reader = PdfReader(io.BytesIO(data))
    except (PdfReadError, ValueError, OSError):
        return ""
    found: list[str] = []
    total = 0
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:  # pypdf가 쪽 하나에서 터져도 나머지는 읽는다
            continue
        found.append(text)
        total += len(text)
        if total >= max_chars:
            break
    return "\n".join(found)[:max_chars]


def pdf_page_count(data: bytes) -> int | None:
    """PDF 쪽수. 읽지 못하면 None이다(공지 첨부처럼 올릴 때 쪽수를 세지 않은 파일에 쓴다)."""
    try:
        return len(PdfReader(io.BytesIO(data)).pages)
    except (PdfReadError, ValueError, OSError):
        return None


def _pdf_pages(data: bytes, *, advice: str = "사진으로 찍어서 올려 주세요.") -> int:
    try:
        return len(PdfReader(io.BytesIO(data)).pages)
    except (PdfReadError, ValueError, OSError) as exc:
        # 앞 5바이트는 %PDF-인데 안이 깨졌다. 쪽수를 모르면 쪽 제한을 지킬 수 없어 받지 않는다.
        # 무엇을 하면 되는지는 종류마다 다르다 — 계획서는 사진을 받지 않는다
        raise ApiError(400, "UNSUPPORTED_FILE_TYPE", f"PDF를 읽지 못했어요. {advice}") from exc


def clean_name(name: str | None) -> str | None:
    """올린 파일 이름. 경로와 줄바꿈을 떼고 길이를 줄인다(그대로 쓰면 저장소 경로가 흔들린다)."""
    if not name:
        return None
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    stem, dot, extension = base.rpartition(".")
    if len(base) > _NAME_MAX and dot and stem and 0 < len(extension) <= _EXTENSION_MAX:
        # 줄여도 확장자는 남긴다. 내려받은 파일이 `.pdf` 없이 저장되면 열 프로그램을 못 고른다
        return f"{stem[: _NAME_MAX - len(extension) - 1]}.{extension}"
    return base[:_NAME_MAX] or None


def document_name(original: str | None, path: str) -> str:
    """문서함에 보이고 내려받을 때 쓰는 이름(F-44). 원래 이름이 없으면 `파일.<확장자>`다."""
    name = clean_name(original)
    if name:
        return name
    last = path.rsplit("/", 1)[-1]
    return f"파일.{last.rsplit('.', 1)[1]}" if "." in last else "파일"


def storage_path(user_id: str, kind: str, file_id: str, extension: str) -> str:
    """버킷 안 경로. ERD 8장대로 사용자 폴더(`<user_id>/…`)로 시작한다."""
    return f"{user_id}/{kind}/{file_id}.{extension}"


def day_start(now: datetime) -> datetime:
    """KST 오늘 0시. 하루 한도를 세는 기준이다."""
    return now.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)


def day_reset(now: datetime) -> datetime:
    """한도가 풀리는 시각(KST 내일 0시). 429의 details.reset_at으로 준다."""
    return day_start(now) + timedelta(days=1)
