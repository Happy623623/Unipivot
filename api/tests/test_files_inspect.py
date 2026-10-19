"""업로드 파일 검사(F-13). 바이트로 형식을 가리고, 크기·쪽수·이름·하루 경계를 본다."""

from datetime import UTC, datetime

import pytest

from app.errors import ApiError
from app.uploads import (
    HEIC,
    JPEG,
    MAX_BYTES,
    PDF,
    PNG,
    WEBP,
    clean_name,
    day_reset,
    day_start,
    inspect_poster,
    inspect_syllabus,
    read_upload,
    sniff,
    storage_path,
)
from tests import samples

pytestmark = pytest.mark.anyio


class Source:
    """UploadFile처럼 조금씩 읽히는 것."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.at = 0
        self.read_bytes = 0

    async def read(self, size: int = -1, /) -> bytes:
        end = len(self.data) if size < 0 else min(self.at + size, len(self.data))
        chunk = self.data[self.at : end]
        self.at = end
        self.read_bytes += len(chunk)
        return chunk


def test_sniff_reads_the_first_bytes_not_the_file_name() -> None:
    assert sniff(samples.JPEG) is JPEG
    assert sniff(samples.PNG) is PNG
    assert sniff(samples.WEBP) is WEBP
    assert sniff(samples.HEIC) is HEIC
    assert sniff(samples.pdf(["포스터"])) is PDF
    assert sniff(b"<html>poster.jpg</html>") is None
    assert sniff(b"") is None


def test_riff_that_is_not_webp_is_not_an_image() -> None:
    assert sniff(b"RIFF" + b"\x00" * 4 + b"WAVEfmt ") is None


async def test_an_oversized_file_stops_before_it_is_all_read() -> None:
    source = Source(b"\xff\xd8\xff" + b"\x00" * (MAX_BYTES + 1024 * 1024))
    with pytest.raises(ApiError) as caught:
        await read_upload(source)
    assert caught.value.status == 413
    assert caught.value.code == "FILE_TOO_LARGE"
    assert "20MB" in caught.value.message
    assert source.read_bytes < len(source.data)  # 남은 바이트는 받지 않는다


async def test_a_file_at_the_limit_is_read_whole() -> None:
    source = Source(b"\xff\xd8\xff" + b"\x00" * (MAX_BYTES - 3))
    assert len(await read_upload(source)) == MAX_BYTES


def test_a_photo_gets_its_type_and_hash() -> None:
    found = inspect_poster(samples.PNG)
    assert found.type is PNG
    assert found.page_count is None
    assert len(found.sha256) == 64
    assert inspect_poster(samples.PNG).sha256 == found.sha256
    assert inspect_poster(samples.JPEG).sha256 != found.sha256


def test_a_two_page_pdf_is_allowed_and_a_three_page_one_is_not() -> None:
    assert inspect_poster(samples.pdf(["1쪽", "2쪽"])).page_count == 2
    with pytest.raises(ApiError) as caught:
        inspect_poster(samples.pdf(["1쪽", "2쪽", "3쪽"]))
    assert caught.value.status == 413
    assert caught.value.code == "PAGE_LIMIT_EXCEEDED"


def test_an_iphone_photo_says_what_to_do_instead() -> None:
    with pytest.raises(ApiError) as caught:
        inspect_poster(samples.HEIC)
    assert caught.value.status == 400
    assert caught.value.code == "UNSUPPORTED_FILE_TYPE"
    assert "JPG" in caught.value.message


def test_an_unknown_format_is_turned_away() -> None:
    for data in (b"", b"<html>\xff\xd8\xff</html>", samples.hwpx("<hs:sec/>")):
        with pytest.raises(ApiError) as caught:
            inspect_poster(data)
        assert caught.value.code == "UNSUPPORTED_FILE_TYPE"


def test_a_broken_pdf_is_turned_away_rather_than_counted_as_one_page() -> None:
    with pytest.raises(ApiError) as caught:
        inspect_poster(b"%PDF-1.7\n" + "여기부터 깨졌다".encode())
    assert caught.value.status == 400
    assert caught.value.code == "UNSUPPORTED_FILE_TYPE"
    assert "사진으로 찍어서" in caught.value.message  # 포스터는 사진으로 다시 찍으면 된다


def test_a_broken_syllabus_pdf_is_not_told_to_take_a_photo() -> None:
    """계획서는 사진을 받지 않는다. 깨진 PDF에 "사진으로 찍어서"라고 하면 막힌 길을 알려 주는 셈이다."""
    with pytest.raises(ApiError) as caught:
        inspect_syllabus(b"%PDF-1.7\n" + "여기부터 깨졌다".encode())
    assert (caught.value.status, caught.value.code) == (400, "UNSUPPORTED_FILE_TYPE")
    assert "PDF로 저장" in caught.value.message
    assert "사진" not in caught.value.message


def test_the_stored_name_drops_the_folder_and_the_control_characters() -> None:
    assert clean_name("C:\\Users\\학생\\Desktop\\포스터.jpg") == "포스터.jpg"
    assert clean_name("/tmp/../poster.png") == "poster.png"
    assert clean_name("이름\n줄바꿈.jpg") == "이름줄바꿈.jpg"
    assert clean_name("가" * 400) == "가" * 200
    # 줄여도 확장자는 남긴다(내려받은 파일이 .pdf 없이 저장되지 않게). 확장자가 너무 길면 확장자로 보지 않는다
    assert clean_name("가" * 300 + ".pdf") == "가" * 196 + ".pdf"
    assert clean_name("가" * 300 + "." + "x" * 11) == ("가" * 300 + "." + "x" * 11)[:200]
    assert clean_name(None) is None
    assert clean_name("   ") is None


def test_the_storage_path_starts_with_the_user_folder() -> None:
    path = storage_path("user-1", "poster", "file-1", "jpg")
    assert path == "user-1/poster/file-1.jpg"


def test_the_daily_window_is_kst_not_utc() -> None:
    # 2026-10-15 23:00 UTC는 KST로 10/16 08:00이다. 그날의 기준은 10/16 0시 KST다
    now = datetime(2026, 10, 15, 23, 0, tzinfo=UTC)
    assert day_start(now).isoformat() == "2026-10-16T00:00:00+09:00"
    assert day_reset(now).isoformat() == "2026-10-17T00:00:00+09:00"
    # 같은 날 KST 0시 직후도 같은 기준이다(10/15 15:00 UTC = 10/16 0시 KST)
    assert day_start(datetime(2026, 10, 15, 15, 0, tzinfo=UTC)) == day_start(now)
    assert day_start(datetime(2026, 10, 15, 14, 59, tzinfo=UTC)) != day_start(now)
