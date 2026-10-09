"""팀이 브라우저로 저장한 한양대 공지를 읽는다(A안). 학교 서버에는 접속하지 않는다.

공지 하나 = 폴더 하나다.

    <공지 폴더>/
      공지사항 - 한양대학교.html      Chrome·Edge·Whale에서 Ctrl+S → "웹페이지, 전체"
      공지사항 - 한양대학교_files/    브라우저가 같이 만든 폴더. 본문 이미지가 여기 있다
      1. 모집 공고문.pdf             페이지의 첨부를 눌러 내려받은 파일

"웹페이지, 단일 파일"(.mhtml)로 저장해도 된다. 본문 이미지가 그 파일 안에 들어 있다.

첨부는 페이지에 보이는 이름과 폴더의 파일 이름으로 짝을 짓는다. 대소문자, macOS의 한글 자모 분리,
운영체제가 바꾸는 글자(: ? 등)는 무시한다. 같은 이름을 또 받아 붙은 " (1)"도 그 이름의 파일로 본다.
이름이 같은 파일들의 내용 가짓수가 그 이름의 첨부 수와 다르면(고친 첨부를 다시 받은 경우 등) 어느 것인지
모르므로 짝짓지 않는다. 비슷하기만 한 이름은 짝짓지 않고 알려만 준다. 틀린 파일로 요건을 뽑느니 멈춘다.
"""

import base64
import difflib
import email
import email.policy
import hashlib
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes, urljoin, urlsplit

from app.crawl.fetch import decode_html
from app.crawl.hanyang import AttachmentLink, NoticePage, NotNoticePage, body_text, parse_notice
from app.extraction.models import AttachmentInput, NoticeInput

PAGE_SUFFIXES = frozenset({".html", ".htm", ".mhtml", ".mht"})
MAX_FILE_BYTES = 50 * 1024 * 1024  # 첨부·본문 이미지 하나
MAX_PAGE_BYTES = 50 * 1024 * 1024  # 저장한 페이지(.mhtml은 이미지까지 들어 있어 크다)
MIN_IMAGE_BYTES = 4 * 1024  # 이보다 작은 본문 이미지는 아이콘·장식으로 보고 뺀다
IMAGE_KINDS = frozenset({"png", "jpeg", "webp"})  # Vision으로 읽는 이미지 형식
_IGNORED = frozenset({".ds_store", "thumbs.db", "desktop.ini"})
_PARTIAL = (".crdownload", ".part", ".partial", ".download", ".tmp")  # 내려받는 중인 파일
_RESOURCES = "_files"  # 브라우저가 페이지와 같이 만드는 자료 폴더의 끝 이름
_LOOSE = re.compile(r"[\s\\/:*?\"<>|_\-~.'`]+")
_COPY = re.compile(r"\s*\((\d+)\)(?=\.[^.]*$|$)")  # "이름 (1).pdf"의 " (1)"
_NOT_SAVED = "저장되지 않았어요(페이지를 '웹페이지, 전체'로 다시 저장하세요)"


class SavedPageError(Exception):
    """공지 폴더를 읽지 못함. 메시지는 사용자에게 그대로 보여도 되는 한 줄이다."""


@dataclass(frozen=True)
class SavedFile:
    seq: int  # 첨부 번호. 페이지의 첨부 → 본문 이미지 순서. 모델과 opportunity_attachments.seq에 쓴다
    name: str  # 페이지에 보이는 첨부 이름. 본문 이미지는 이미지 파일 이름
    data: bytes | None  # None이면 가져오지 못했다(problem에 이유)
    source_url: str | None  # 학교 다운로드 주소. 본문 이미지는 원래 주소를 알 수 없어 None
    body_image: bool = False
    problem: str | None = None
    file_name: str | None = None  # 짝지은 폴더 파일 이름. " (1)"이 붙는 등 name과 다를 수 있다


@dataclass(frozen=True)
class SavedNotice:
    folder: Path
    page_file: Path
    page: NoticePage
    # 본문 글자. 본문 이미지 자리에는 "[이미지: 첨부 3번 포스터.jpg]"처럼 첨부 번호를 적었다
    text: str
    files: tuple[SavedFile, ...]
    skipped_images: tuple[str, ...]  # 아이콘 크기라 뺀 본문 이미지
    extra_files: tuple[str, ...]  # 폴더에 있지만 페이지 첨부가 아닌 파일(쓰지 않는다)
    duplicate_files: tuple[str, ...]  # 같은 첨부를 두 번 받은 파일(내용이 같아 쓰지 않는다)
    same_name_links: tuple[str, ...] = ()  # 이름이 같은 첨부가 여럿이라 내려받은 순서로 짝지은 이름
    identical: tuple[
        tuple[int, ...], ...
    ] = ()  # 파일 내용이 같은 첨부 번호들(같은 첨부를 두 번 받았을 수 있다)
    nested_folders: tuple[str, ...] = ()  # 안에 페이지가 있는 아래 폴더(예전 저장 등). 쓰지 않는다

    @property
    def missing(self) -> tuple[SavedFile, ...]:
        return tuple(file for file in self.files if file.data is None)

    @property
    def renamed(self) -> tuple[SavedFile, ...]:
        """폴더 파일 이름이 페이지 이름과 달라 보이는 첨부. 맞게 짝지었는지 사람이 볼 수 있게 알려 준다."""
        return tuple(
            file
            for file in self.files
            if file.file_name and not file.body_image and _nfc(file.file_name) != _nfc(file.name)
        )

    def body(self) -> str:
        """모델에 보낼 본문: 게시판 정보 몇 줄 + 본문 글자. opportunities.raw_text에도 이 글을 넣는다."""
        page = self.page
        lines = ["[게시판 정보]"]
        head = [
            f"분류: {page.category}" if page.category else "",
            f"캠퍼스: {page.campus or '표시 없음'}",
        ]
        lines.append(" · ".join(part for part in head if part))
        if page.notice_period:
            lines.append(
                f"공지 게시 기간: {_period(page.notice_period)}"
                " (게시판에 올려 두는 기간이라 신청 기간과 다를 수 있다)"
            )
        if page.event_period:
            lines.append(f"행사 기간: {_period(page.event_period)}")
        if page.external_url:
            lines.append(f"원문 URL: {page.external_url}")
        if self.missing:
            names = ", ".join(f"첨부 {file.seq}번 {file.name}" for file in self.missing)
            lines.append(f"가져오지 못해 읽을 수 없는 첨부: {names}")
        return "\n".join(lines) + "\n\n" + (self.text or "(본문 글자 없음)")

    def notice_input(self) -> NoticeInput:
        return NoticeInput(
            title=self.page.title,
            body=self.body(),
            posted_on=self.page.posted_on,
            organizer=self.page.department,
            # A안에서는 원문 다시 읽기(학교 서버 접속)를 쓰지 않는다. 저장한 페이지에 본문이 다 있다
            original_url=None,
            attachments=tuple(
                AttachmentInput(file.seq, file.name, file.data, file.source_url)
                for file in self.files
                if file.data is not None
            ),
        )


def notice_folders(paths: Iterable[Path]) -> list[Path]:
    """경로마다 공지 폴더를 찾는다. 페이지 파일이 바로 들어 있으면 그 폴더가 공지 하나다.
    바로 있는 페이지가 공지 상세가 아니고(목록 페이지 등) 아래 폴더에 페이지가 있으면 아래 폴더들이 공지들이다.
    공지 폴더 안에 예전에 저장한 폴더가 있어도 바깥 페이지를 쓴다(안쪽은 알려만 준다)."""
    folders: list[Path] = []
    for path in paths:
        if path.is_file():
            folders.append(path.parent)
            continue
        if not path.is_dir():
            raise SavedPageError(f"폴더가 없어요: {path}")
        try:
            if _is_notice_folder(path):
                folders.append(path)
            else:
                folders += sorted(sub for sub in _subfolders(path) if _page_files(sub))
        except OSError as exc:
            raise SavedPageError(f"폴더를 읽지 못했어요({type(exc).__name__}): {path}") from exc
    return list(dict.fromkeys(folders))


def entry_ids(folder: Path) -> set[str]:
    """폴더에 바로 있는 페이지들의 글 번호(읽히는 것만). 같은 글을 두 폴더에 저장했는지 볼 때 쓴다.
    페이지가 여럿이라 읽기에 실패하는 폴더의 글 번호도 모은다."""
    try:
        pages = _page_files(folder)
    except OSError:
        return set()
    found = (_entry_id(page_file) for page_file in pages)
    return {entry_id for entry_id in found if entry_id}


def load_folder(folder: Path) -> SavedNotice:
    folder = folder.resolve()
    page_file, page, page_url, resources = _open_page(folder)
    try:
        candidates = _candidates(folder, page_file)
    except OSError as exc:
        raise SavedPageError(f"폴더를 읽지 못했어요({type(exc).__name__})") from exc

    files: list[SavedFile] = []
    pairs, duplicates, extra, same_name = _pair(page.attachments, candidates)
    for seq, (link, (path, problem)) in enumerate(zip(page.attachments, pairs, strict=True), 1):
        data = None
        if path is not None:
            data, problem = _read(path, MAX_FILE_BYTES)
        files.append(
            SavedFile(
                seq,
                link.name,
                data,
                link.url,
                problem=problem,
                file_name=path.name if path is not None else None,
            )
        )

    labels: dict[int, str] = {}
    skipped: list[str] = []
    seen: dict[str, str] = {}
    for index, src in enumerate(page.image_sources):
        if not src:
            continue
        name, data, problem = _image(src, page_file, folder, page_url, resources)
        if data is None:
            files.append(SavedFile(len(files) + 1, name, None, None, True, problem))
            labels[index] = f"첨부 {len(files)}번 {name}(저장 안 됨)"
            continue
        if len(data) < MIN_IMAGE_BYTES:
            skipped.append(f"{name}(아이콘 크기)")
            continue
        # GIF처럼 못 읽는 형식도 첨부로 둔다. 못 읽은 첨부라 원문 확인 필요가 된다(포스터일 수 있다)
        digest = hashlib.sha256(data).hexdigest()
        if digest not in seen:  # 같은 이미지가 본문에 두 번 나오면 첨부는 하나
            files.append(
                SavedFile(len(files) + 1, name, data, None, body_image=True, file_name=name)
            )
            seen[digest] = f"첨부 {len(files)}번 {name}"
        labels[index] = seen[digest]

    return SavedNotice(
        folder=folder,
        page_file=page_file,
        page=page,
        text=body_text(page, labels),
        files=tuple(files),
        skipped_images=tuple(skipped),
        extra_files=tuple(path.name for path in extra),
        duplicate_files=tuple(path.name for path in duplicates),
        same_name_links=tuple(same_name),
        identical=_identical(files),
        nested_folders=tuple(_nested(folder)),
    )


def _identical(files: list[SavedFile]) -> tuple[tuple[int, ...], ...]:
    by_content: dict[str, list[int]] = {}
    for file in files:
        if file.data is not None and not file.body_image:
            by_content.setdefault(hashlib.sha256(file.data).hexdigest(), []).append(file.seq)
    return tuple(tuple(seqs) for seqs in by_content.values() if len(seqs) > 1)


def _open_page(
    folder: Path,
) -> tuple[Path, NoticePage, str | None, dict[str, bytes] | None]:
    """(페이지 파일, 읽은 페이지, 페이지 주소, MHTML 자료)."""
    try:
        pages = _page_files(folder)
    except OSError as exc:
        raise SavedPageError(f"폴더를 읽지 못했어요({type(exc).__name__})") from exc
    if not pages:
        raise SavedPageError("저장한 공지 페이지(.html·.mhtml)가 없어요")
    if len(pages) > 1:
        names = ", ".join(page.name for page in pages)
        raise SavedPageError(
            f"페이지 파일이 {len(pages)}개예요({names}). 공지마다 폴더를 나눠 주세요"
        )
    page_file = pages[0]
    page, page_url, resources = _parse_page(page_file)
    return page_file, page, page_url, resources


def _parse_page(page_file: Path) -> tuple[NoticePage, str | None, dict[str, bytes] | None]:
    raw, problem = _read(page_file, MAX_PAGE_BYTES)
    if raw is None:
        raise SavedPageError(f"페이지 파일을 읽지 못했어요: {problem}")
    resources: dict[str, bytes] | None = None
    page_url = None
    if page_file.suffix.lower() in (".mhtml", ".mht"):
        html, page_url, resources = _read_mhtml(raw)
    else:
        html = decode_html(raw)
    try:
        page = parse_notice(html, page_url=page_url)
    except NotNoticePage as exc:
        raise SavedPageError(str(exc)) from exc
    return page, page_url, resources


def _entry_id(page_file: Path) -> str | None:
    """페이지 파일 하나의 글 번호. 공지 상세 페이지가 아니거나 읽지 못하면 None."""
    try:
        return _parse_page(page_file)[0].entry_id
    except Exception:  # 깨진 페이지·MHTML. 폴더를 읽을 때 이유를 알린다
        return None


def _is_notice_folder(folder: Path) -> bool:
    pages = _page_files(folder)
    if not pages:
        return False
    if not any(_page_files(sub) for sub in _subfolders(folder)):
        return True  # 아래에 페이지가 없으면 공지 폴더다(페이지가 틀렸으면 읽을 때 알린다)
    return any(_entry_id(page_file) for page_file in pages)


def _nested(folder: Path) -> list[str]:
    try:
        return sorted(sub.name for sub in _subfolders(folder) if _page_files(sub))
    except OSError:
        return []


def _page_files(folder: Path) -> list[Path]:
    return sorted(
        path for path in folder.iterdir() if path.suffix.lower() in PAGE_SUFFIXES and _usable(path)
    )


def _subfolders(folder: Path) -> list[Path]:
    return [
        path
        for path in folder.iterdir()
        if path.is_dir() and not path.is_symlink() and not path.name.endswith(_RESOURCES)
    ]


def _candidates(folder: Path, page_file: Path) -> list[Path]:
    """첨부 후보: 폴더 바로 아래의 보통 파일. 숨김·내려받는 중·시스템 파일은 뺀다."""
    return sorted(
        path
        for path in folder.iterdir()
        if path != page_file
        and _usable(path)
        and path.name.lower() not in _IGNORED
        and not path.name.lower().endswith(_PARTIAL)
    )


def _usable(path: Path) -> bool:
    # 바로가기(심볼릭 링크)는 폴더 밖 파일을 가리킬 수 있어 쓰지 않는다
    return path.is_file() and not path.is_symlink() and not path.name.startswith(".")


def _pair(
    links: tuple[AttachmentLink, ...], candidates: list[Path]
) -> tuple[list[tuple[Path | None, str | None]], list[Path], list[Path], list[str]]:
    """링크마다 (파일, 못 짝지은 이유), 내용이 같아 안 쓰는 파일, 남는 파일, 순서로 짝지은 같은 이름.

    1. 링크를 이름(느슨하게 비교)으로 묶는다. 보통은 이름마다 링크 하나다
    2. 이름마다 그 이름의 파일을 모은다: 이름이 같은 파일 먼저, 그다음 " (1)" " (2)" 순서.
       다른 링크의 제 이름 파일(예: 페이지에 "신청서 (1).hwp"라는 첨부가 따로 있음)은 그 링크 몫이다
    3. 모은 파일의 내용 가짓수가 링크 수와 같으면 순서대로 짝짓고 내용이 같은 나머지는 중복으로 둔다.
       내용이 모두 같고 파일이 링크 수만큼 있으면 그대로 짝짓는다(같은 파일을 여러 번 올린 경우).
       그 밖에는 어느 파일이 어느 첨부인지 모르므로 그 이름의 링크를 모두 짝짓지 않는다
    """
    free = list(candidates)
    groups: dict[str, list[int]] = {}
    for no, link in enumerate(links):
        groups.setdefault(_loose(link.name), []).append(no)
    exact: dict[str, list[Path]] = {}
    for key in groups:
        exact[key] = [path for path in free if _loose(path.name) == key]
        for path in exact[key]:
            free.remove(path)
    copies: dict[str, list[Path]] = {}
    for key in groups:
        copies[key] = sorted((path for path in free if _same_name(path, key)), key=_copy_no)
        for path in copies[key]:
            free.remove(path)

    results: list[tuple[Path | None, str | None]] = [(None, None)] * len(links)
    duplicates: list[Path] = []
    same_name: list[str] = []
    for key, indexes in groups.items():
        # 링크 이름과 똑같은 이름의 파일을 그 링크 자리에 먼저 둔다(대소문자만 다른 이름이 섞여도 제 짝)
        files = sorted(exact[key], key=lambda path: _own_link(path, indexes, links)) + copies[key]
        distinct = _distinct(files)
        name = links[indexes[0]].name
        if not files:
            for no in indexes:
                results[no] = (None, _missing(links[no].name, free))
            continue
        if len(distinct) == len(indexes):
            paired = [(no, path) for no, (path, _) in zip(indexes, distinct, strict=True)]
            duplicates += [path for _, same in distinct for path in same]
        elif len(distinct) == 1 and len(files) >= len(indexes):
            # 학교가 같은 파일을 여러 번 올렸다: 내용이 모두 같으니 어느 쪽에 짝지어도 같다
            paired = list(zip(indexes, files, strict=False))
            duplicates += files[len(indexes) :]
        else:
            paired = []
        for no, path in paired:
            results[no] = (path, None)
        if len(indexes) > 1 and any(_nfc(path.name) != _nfc(links[no].name) for no, path in paired):
            same_name.append(name)  # 이름만으로는 어느 첨부인지 몰라 순서로 짝지었다
        if not paired:
            names = ", ".join(path.name for path in files)
            if len(indexes) == 1:
                problem = f"같은 첨부로 보이는 파일이 {len(files)}개예요({names}). 맞는 파일 하나만 남기세요"
            else:
                problem = (
                    f"이름이 같은 첨부가 {len(indexes)}개인데 폴더의 파일은 {len(distinct)}가지예요"
                    f"({names}). 첨부마다 한 번씩만 내려받아 주세요"
                )
            for no in indexes:
                results[no] = (None, problem)
    return results, duplicates, free, same_name


def _own_link(path: Path, indexes: list[int], links: tuple[AttachmentLink, ...]) -> int:
    """path와 이름이 똑같은 링크의 묶음 안 순서. 없으면 맨 뒤."""
    for order, no in enumerate(indexes):
        if _nfc(path.name) == _nfc(links[no].name):
            return order
    return len(indexes)


def _distinct(files: list[Path]) -> list[tuple[Path, list[Path]]]:
    """내용별로 묶는다: (처음 나온 파일, 내용이 같은 나머지). 순서는 files 순서다."""
    groups: list[tuple[Path, list[Path]]] = []
    for path in files:
        for first, same in groups:
            if _same_content(first, path):
                same.append(path)
                break
        else:
            groups.append((path, []))
    return groups


def _same_name(path: Path, key: str) -> bool:
    """path가 key(느슨한 이름)의 파일이나 그 " (n)" 복사본인가."""
    return _loose(_COPY.sub("", path.name)) == key


def _copy_no(path: Path) -> int:
    match = _COPY.search(path.name)
    return int(match.group(1)) if match else 0


def _missing(link_name: str, free: list[Path]) -> str:
    """못 찾은 첨부의 이유. 확장자가 같고 이름이 비슷한 파일이 남아 있으면 알려 준다(짝짓지는 않는다)."""
    suffix = Path(link_name).suffix.casefold()
    scored = [
        (difflib.SequenceMatcher(None, _loose(link_name), _loose(path.name)).ratio(), path.name)
        for path in free
        if path.suffix.casefold() == suffix
    ]
    best = max(scored, default=None)
    if best is None or best[0] < 0.6:
        return "폴더에 없어요"
    return (
        f"폴더에 없어요(비슷한 이름: {best[1]}. 같은 파일이면 이름을 페이지와 같게 바꾸고,"
        " 고친 첨부면 새로 내려받으세요)"
    )


def _same_content(first: Path, second: Path) -> bool:
    try:
        if first.stat().st_size != second.stat().st_size:
            return False
        if first.stat().st_size > MAX_FILE_BYTES:
            return False
        return first.read_bytes() == second.read_bytes()
    except OSError:
        return False


def _loose(name: str) -> str:
    return _LOOSE.sub("", _nfc(name)).casefold()


def _nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def _read(path: Path, limit: int) -> tuple[bytes | None, str | None]:
    try:
        if path.stat().st_size > limit:
            size = f"{limit // 1024 // 1024}MB" if limit >= 1024 * 1024 else f"{limit:,}바이트"
            return None, f"파일이 너무 커요({size} 넘음)"
        return path.read_bytes(), None
    except OSError as exc:  # 다른 프로그램(한글 등)이 잠근 파일, 권한 없음
        return None, f"파일을 읽지 못했어요({type(exc).__name__}). 열려 있으면 닫고 다시 하세요"


def _image(
    src: str,
    page_file: Path,
    folder: Path,
    page_url: str | None,
    resources: dict[str, bytes] | None,
) -> tuple[str, bytes | None, str | None]:
    """본문 <img src> → (이름, 데이터, 못 가져온 이유)."""
    if src.startswith("data:"):
        data = _data_uri(src)
        return "본문 이미지", data, None if data else "이미지 데이터를 읽지 못했어요"
    if resources is not None:  # MHTML: 저장할 때의 주소로 찾는다
        url = urljoin(page_url or "", src)
        data = resources.get(url, resources.get(src))
        return _url_name(url), data, None if data is not None else _NOT_SAVED
    parts = urlsplit(src)
    if parts.scheme or src.startswith("//"):
        return _url_name(src), None, _NOT_SAVED  # 서버 주소가 그대로 남았다("HTML만" 저장)
    path = (page_file.parent / unquote(parts.path)).resolve()
    if not path.is_relative_to(folder) or not path.is_file():
        return _url_name(src), None, _NOT_SAVED
    data, problem = _read(path, MAX_FILE_BYTES)
    return path.name, data, problem


def _read_mhtml(raw: bytes) -> tuple[str, str | None, dict[str, bytes]]:
    """MHTML → (페이지 HTML, 페이지 주소, {자료 주소·cid: 데이터})."""
    message = email.message_from_bytes(raw, policy=email.policy.compat32)
    page_url = _header(message.get("Snapshot-Content-Location"))
    html: str | None = None
    resources: dict[str, bytes] = {}
    for part in message.walk():
        if part.is_multipart():
            continue
        payload = part.get_payload(decode=True)
        data = payload if isinstance(payload, bytes) else b""
        location = _header(part.get("Content-Location"))
        if html is None and part.get_content_type() == "text/html":
            html = decode_html(data, str(part.get("Content-Type", "")))
            page_url = page_url or location
            continue
        if location:
            resources.setdefault(location, data)
        content_id = _header(part.get("Content-ID"))
        if content_id:
            resources.setdefault("cid:" + content_id.strip("<>"), data)
    if html is None:
        raise SavedPageError("MHTML 파일에서 페이지를 찾지 못했어요")
    return html, page_url, resources


def _header(value: object) -> str | None:
    """주소 헤더. 긴 줄이 접혀 있을 수 있어 공백을 모두 지운다(주소에는 공백이 없다)."""
    if value is None:
        return None
    return "".join(str(value).split()) or None


def _data_uri(src: str) -> bytes | None:
    head, _, payload = src.partition(",")
    try:
        if head.endswith(";base64"):
            return base64.b64decode(payload, validate=False) or None
        return unquote_to_bytes(payload) or None
    except ValueError:
        return None


def _url_name(url: str) -> str:
    """주소의 파일 이름. 학교 문서 주소는 /documents/…/포스터.jpg/<uuid>라 확장자가 있는 마디를 고른다."""
    parts = [unquote(part) for part in urlsplit(url).path.split("/") if part]
    named = [part for part in parts if re.search(r"\.[A-Za-z0-9]{2,5}$", part)]
    return (named or parts or ["본문 이미지"])[-1]


def _period(period: tuple[date, date]) -> str:
    start, end = period
    return start.isoformat() if start == end else f"{start.isoformat()} ~ {end.isoformat()}"
