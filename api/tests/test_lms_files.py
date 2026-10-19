"""공지 첨부를 학생 문서함에 저장한다(F-54): `app/lms/files.py`.

DB·네트워크 없이 돈다. LearningX·저장소·파일 표는 가짜다. 실제 받기는 test_lms_attachments_client.py,
SQL은 test_lms_db.py가 본다.
"""

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.agent_log import agent_run, using
from app.lms.announcements import CanvasAnnouncement, announcement
from app.lms.client import AttachmentUnavailable, DownloadedFile, LearningXClient
from app.lms.files import MAX_PER_SYNC, TOOL, AttachmentSaver, storage_path
from app.repositories.lms import CourseRow
from app.uploads import MAX_BYTES
from app.uploads.storage import StorageError, SupabaseStorage
from tests.fakes import FakeLogConnection
from tests.lms_samples import GUIDE_FILE_ID, POSTER_ATTACHMENT, POSTER_FILE_ID, attachment

pytestmark = pytest.mark.anyio

USER = "00000000-0000-4000-8000-000000000001"
COURSE = CourseRow(id="course-db", canvas_course_id=214023, short_name="데이터베이스")
NOW = datetime(2026, 10, 19, 3, 0, tzinfo=UTC)
GUIDE = b'{"projects": []}'
POSTER = b"\x89PNG\r\n\x1a\nposter"


class FakeLms(LearningXClient):
    """주소 → 바이트. 없는 주소는 받지 못한 것(로그인 화면으로 간 것)으로 본다."""

    def __init__(self, files: dict[int, bytes]) -> None:
        super().__init__(api_base="https://lms.test")
        self.files = files
        self.asked: list[tuple[str, int, bool]] = []

    async def attachment(
        self, url: str, *, max_bytes: int, html_ok: bool = False
    ) -> DownloadedFile:
        self.asked.append((url, max_bytes, html_ok))
        number = int(url.split("/files/")[1].split("/")[0])
        if number not in self.files:
            raise AttachmentUnavailable("LearningX가 첨부 대신 로그인 화면으로 보냈어요.")
        return DownloadedFile(self.files[number], "application/octet-stream")


class FakeStorage(SupabaseStorage):
    def __init__(self, *, broken: bool = False) -> None:
        super().__init__(base_url="https://storage.test", bucket="uploads", service_key="k")
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.removed: list[str] = []
        self.broken = broken

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        if self.broken:
            raise StorageError("파일 저장소가 요청을 거절했어요(503).")
        self.objects[path] = (data, content_type)

    async def remove(self, path: str) -> None:
        self.objects.pop(path, None)
        self.removed.append(path)


@dataclass
class FakeFiles:
    """files 표 흉내: (user_id, external_ref) 유니크."""

    rows: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    asked: list[list[str]] = field(default_factory=list)
    fail: bool = False
    race: bool = False  # 넣으려는 순간 다른 쪽이 같은 첨부를 넣었다

    async def lms_attachment_refs(self, user_id: str, refs: list[str]) -> set[str]:
        self.asked.append(refs)
        return {ref for (uid, ref) in self.rows if uid == user_id and ref in refs}

    async def add_lms_attachment(self, user_id: str, **values: Any) -> str | None:
        if self.fail:
            raise RuntimeError("DB가 멈췄다")
        key = (user_id, values["ref"])
        if self.race or key in self.rows:
            return None
        self.rows[key] = values
        return values["file_id"]


def notice(
    topic_id: int,
    attachments: list[dict[str, Any]],
    *,
    days_ago: float = 0,
    section_specific: bool = False,
) -> CanvasAnnouncement:
    posted = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    parsed = announcement(
        {
            "id": topic_id,
            "title": f"공지 {topic_id}",
            "message": "<p>본문</p>",
            "posted_at": posted,
            "attachments": attachments,
            "is_section_specific": section_specific,
        }
    )
    assert parsed is not None
    return parsed


@pytest.fixture
def files() -> FakeFiles:
    return FakeFiles()


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def lms() -> FakeLms:
    return FakeLms({GUIDE_FILE_ID: GUIDE, POSTER_FILE_ID: POSTER})


@pytest.fixture
def log() -> FakeLogConnection:
    return FakeLogConnection()


def saver(lms: FakeLms, storage: FakeStorage, files: FakeFiles) -> AttachmentSaver:
    @asynccontextmanager
    async def transaction() -> AsyncIterator[Any]:
        yield None  # 가짜 저장소는 연결을 쓰지 않는다

    return AttachmentSaver(
        transaction=transaction,
        client=lms,
        storage=storage,
        files=lambda conn: files,  # type: ignore[arg-type,return-value]
    )


async def save(
    lms: FakeLms,
    storage: FakeStorage,
    files: FakeFiles,
    log: FakeLogConnection,
    notices: list[CanvasAnnouncement],
) -> Any:
    async with agent_run(using(log), trigger="lms_sync", user_id=USER) as run:  # type: ignore[arg-type]
        return await saver(lms, storage, files).run(run, USER, [(COURSE, notices)])


async def test_each_attachment_lands_in_my_files_once(
    lms: FakeLms, storage: FakeStorage, files: FakeFiles, log: FakeLogConnection
) -> None:
    """받아서 올리고 기록한다. 저장소 경로에는 원래 이름이 아니라 파일 번호가 들어간다."""
    made = await save(lms, storage, files, log, [notice(1, [attachment(), POSTER_ATTACHMENT])])
    assert (made.saved, made.failed) == (2, 0)
    guide = files.rows[(USER, str(GUIDE_FILE_ID))]
    assert guide["course_id"] == COURSE.id
    assert guide["original_name"] == "ERICA-projects-guide-v2.json"
    assert guide["mime_type"] == "application/json"  # 첨부 목록의 형식을 쓴다
    assert guide["size_bytes"] == len(GUIDE)
    assert guide["sha256"] == hashlib.sha256(GUIDE).hexdigest()
    assert guide["path"] == f"{USER}/lecture_material/{guide['file_id']}.json"
    assert storage.objects[guide["path"]] == (GUIDE, "application/json")
    poster = files.rows[(USER, str(POSTER_FILE_ID))]
    assert poster["path"].endswith(".png") and "포스터" not in poster["path"]
    assert all(max_bytes == MAX_BYTES and not html for _, max_bytes, html in lms.asked)

    # 다음 동기화: 이미 저장한 첨부는 받지 않는다(같은 첨부는 한 번만 — PRD F-54)
    lms.asked.clear()
    again = await save(lms, storage, files, log, [notice(1, [attachment(), POSTER_ATTACHMENT])])
    assert (again.saved, again.failed) == (0, 0) and lms.asked == []
    assert len(storage.objects) == 2


async def test_the_run_records_counts_but_never_the_address(
    lms: FakeLms, storage: FakeStorage, files: FakeFiles, log: FakeLogConnection
) -> None:
    lms.files.pop(POSTER_FILE_ID)  # 하나는 받지 못한다
    await save(lms, storage, files, log, [notice(1, [attachment(), POSTER_ATTACHMENT])])
    assert TOOL in log.tools()
    assert log.outputs()[TOOL] == {"saved": 1, "failed": 1}
    written = repr(log.statements)
    assert "verifier" not in written and "lms.test/files" not in written


async def test_nothing_to_fetch_leaves_no_record(
    lms: FakeLms, storage: FakeStorage, files: FakeFiles, log: FakeLogConnection
) -> None:
    """첨부가 없거나 다 받았으면 도구 기록도 없다(30분마다 빈 기록이 쌓이지 않게)."""
    await save(lms, storage, files, log, [notice(1, [])])
    assert TOOL not in log.tools() and files.asked == []
    await save(lms, storage, files, log, [notice(1, [attachment()])])
    log.statements.clear()
    await save(lms, storage, files, log, [notice(1, [attachment()])])
    assert TOOL not in log.tools()


async def test_too_large_section_only_and_addressless_files_are_not_fetched(
    lms: FakeLms, storage: FakeStorage, files: FakeFiles, log: FakeLogConnection
) -> None:
    big = attachment(901, display_name="녹화본.mp4", size=MAX_BYTES + 1)
    edge = attachment(902, display_name="딱 20MB.pdf", size=MAX_BYTES)
    no_url = {**attachment(903, display_name="주소 없음.pdf"), "url": None}
    lms.files[902] = b"%PDF-"
    await save(
        lms,
        storage,
        files,
        log,
        [
            notice(1, [big, edge, no_url]),
            notice(2, [POSTER_ATTACHMENT], section_specific=True),  # 화면에 안 보이는 공지
        ],
    )
    assert [url.split("/files/")[1].split("/")[0] for url, _, _ in lms.asked] == ["902"]
    assert set(ref for _, ref in files.rows) == {"902"}


async def test_newest_announcements_go_first_and_at_most_ten_per_sync(
    lms: FakeLms, storage: FakeStorage, files: FakeFiles, log: FakeLogConnection
) -> None:
    many = [notice(100 + index, [attachment(1000 + index)], days_ago=index) for index in range(12)]
    for index in range(12):
        lms.files[1000 + index] = b"x"
    first = await save(lms, storage, files, log, many)
    assert first.saved == MAX_PER_SYNC == 10
    got = sorted(int(ref) for _, ref in files.rows)
    assert got == list(range(1000, 1010))  # 최근 공지(0~9일 전)부터
    second = await save(lms, storage, files, log, many)
    assert second.saved == 2  # 남은 둘은 다음 동기화가 받는다


async def test_the_same_attachment_on_two_notices_is_fetched_once(
    lms: FakeLms, storage: FakeStorage, files: FakeFiles, log: FakeLogConnection
) -> None:
    made = await save(
        lms, storage, files, log, [notice(1, [attachment()]), notice(2, [attachment()], days_ago=3)]
    )
    assert made.saved == 1 and len(lms.asked) == 1


async def test_one_failure_does_not_stop_the_rest(
    lms: FakeLms, storage: FakeStorage, files: FakeFiles, log: FakeLogConnection
) -> None:
    """못 받은 첨부는 기록하지 않는다 — "저장 전"으로 남아 다음 동기화가 다시 받는다."""
    lms.files.pop(GUIDE_FILE_ID)
    made = await save(
        lms,
        storage,
        files,
        log,
        [notice(1, [attachment()]), notice(2, [POSTER_ATTACHMENT], days_ago=1)],
    )
    assert (made.saved, made.failed) == (1, 1)
    assert set(ref for _, ref in files.rows) == {str(POSTER_FILE_ID)}


async def test_a_storage_failure_records_nothing(
    lms: FakeLms, files: FakeFiles, log: FakeLogConnection
) -> None:
    broken = FakeStorage(broken=True)
    made = await save(lms, broken, files, log, [notice(1, [attachment()])])
    assert (made.saved, made.failed) == (0, 1) and files.rows == {}


async def test_an_upload_without_a_record_is_taken_back(
    lms: FakeLms, storage: FakeStorage, files: FakeFiles, log: FakeLogConnection
) -> None:
    """기록을 남기지 못하면(DB가 멈춤·그새 같은 첨부가 들어옴) 올린 파일을 지운다 — 주인 없는 파일이 남지 않게."""
    files.fail = True
    made = await save(lms, storage, files, log, [notice(1, [attachment()])])
    assert (made.saved, made.failed) == (0, 1)
    assert storage.objects == {} and len(storage.removed) == 1
    files.fail, files.race = False, True
    made = await save(lms, storage, files, log, [notice(1, [attachment()])])
    assert (made.saved, made.failed) == (0, 0)  # 이미 들어온 것이라 실패로 세지 않는다
    assert storage.objects == {} and len(storage.removed) == 2


async def test_an_html_attachment_may_be_html(
    lms: FakeLms, storage: FakeStorage, files: FakeFiles, log: FakeLogConnection
) -> None:
    """첨부 자체가 HTML이면 HTML 응답을 받아들인다(아니면 로그인 화면이 온 것이다)."""
    page = attachment(904, display_name="안내.html", content_type="text/html")
    lms.files[904] = b"<html></html>"
    await save(lms, storage, files, log, [notice(1, [page, attachment()])])
    assert sorted(html for _, _, html in lms.asked) == [False, True]


def test_the_storage_path_keeps_only_a_plain_extension() -> None:
    assert storage_path(USER, "f1", "보고서.HWP") == f"{USER}/lecture_material/f1.hwp"
    assert storage_path(USER, "f1", "이름 없음") == f"{USER}/lecture_material/f1.bin"
    assert storage_path(USER, "f1", "a.tar.gz") == f"{USER}/lecture_material/f1.gz"
    assert storage_path(USER, "f1", "x.한글") == f"{USER}/lecture_material/f1.bin"
    assert storage_path(USER, "f1", "../../etc.passwd/") == f"{USER}/lecture_material/f1.bin"
