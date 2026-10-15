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
DAILY_UPLOAD_LIMIT = 20  # 사용자당 KST 하루 (API 명세 14장, 10/15 확정)
_CHUNK_BYTES = 1024 * 1024
_NAME_MAX = 200


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


def _pdf_pages(data: bytes) -> int:
    try:
        return len(PdfReader(io.BytesIO(data)).pages)
    except (PdfReadError, ValueError, OSError) as exc:
        # 앞 5바이트는 %PDF-인데 안이 깨졌다. 쪽수를 모르면 2쪽 제한을 지킬 수 없어 받지 않는다
        raise ApiError(
            400,
            "UNSUPPORTED_FILE_TYPE",
            "PDF를 읽지 못했어요. 사진으로 찍어서 올려 주세요.",
        ) from exc


def clean_name(name: str | None) -> str | None:
    """올린 파일 이름. 경로와 줄바꿈을 떼고 길이를 줄인다(그대로 쓰면 저장소 경로가 흔들린다)."""
    if not name:
        return None
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    return base[:_NAME_MAX] or None


def storage_path(user_id: str, kind: str, file_id: str, extension: str) -> str:
    """버킷 안 경로. ERD 8장대로 사용자 폴더(`<user_id>/…`)로 시작한다."""
    return f"{user_id}/{kind}/{file_id}.{extension}"


def day_start(now: datetime) -> datetime:
    """KST 오늘 0시. 하루 한도를 세는 기준이다."""
    return now.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)


def day_reset(now: datetime) -> datetime:
    """한도가 풀리는 시각(KST 내일 0시). 429의 details.reset_at으로 준다."""
    return day_start(now) + timedelta(days=1)
