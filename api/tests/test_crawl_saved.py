"""저장한 공지 폴더 읽기(A안): 첨부 짝짓기, 본문 이미지, MHTML, 폴더 찾기."""

import base64
import quopri
import unicodedata
from pathlib import Path

import pytest

from app.crawl import saved as saved_module
from app.crawl.saved import SavedPageError, load_folder, notice_folders
from tests import hanyang_pages, samples
from tests.hanyang_pages import FILES, POSTER, save_notice
from tests.samples import hp


def test_pairs_attachments_and_body_images(tmp_path: Path) -> None:
    guide = samples.hwpx(hp("직전 학기 평점평균 3.0 이상"))
    form = samples.pdf(["장학금 신청서 양식입니다. 학번과 이름을 적는다."])
    html = hanyang_pages.detail(
        files=("1. 선발요강.hwpx", "2. 신청서: 양식?.pdf", "3. 개인정보 동의서.hwp"),
        body=(
            "<p>자격은 첨부 1을 보세요.</p>"
            f'<p><img alt="포스터" src="./{FILES}/poster.jpg"></p>'
            f'<p><img src="./{FILES}/poster%20copy.jpg"></p>'  # 같은 그림을 또 넣은 경우
            f'<p><img src="./{FILES}/dot.png"></p>'  # 아이콘 크기
            f'<p><img src="./{FILES}/anim.gif"></p>'
        ),
    )
    folder = save_notice(
        tmp_path / "장학",
        html,
        {
            unicodedata.normalize("NFD", "1. 선발요강.hwpx"): guide,  # macOS가 쓰는 이름
            "2. 신청서_ 양식_.pdf": form,  # Windows가 : ? 를 _로 바꾼 이름
            "3. 개인정보 동의서 (1).hwp": b"not really hwp",  # 두 번 받아 (1)이 붙은 이름
            "메모.txt": b"x",
            "4. 다른 공지 첨부.pdf.crdownload": b"",  # 내려받는 중
            ".DS_Store": b"",
        },
        {
            "poster.jpg": POSTER,
            "poster copy.jpg": POSTER,
            "dot.png": samples.PNG,
            "anim.gif": b"GIF89a" + b"\x00" * 5000,
        },
    )
    saved = load_folder(folder)
    assert [(f.seq, f.name, f.body_image, f.data is not None) for f in saved.files] == [
        (1, "1. 선발요강.hwpx", False, True),
        (2, "2. 신청서: 양식?.pdf", False, True),
        (3, "3. 개인정보 동의서.hwp", False, True),
        (4, "poster.jpg", True, True),
        (5, "anim.gif", True, True),  # 못 읽는 형식도 첨부로 둔다(원문 확인 필요가 된다)
    ]
    assert saved.files[0].data == guide and saved.files[1].data == form
    assert saved.files[0].source_url.startswith("https://www.hanyang.ac.kr/documents/")
    assert saved.files[3].source_url is None  # 본문 이미지는 원래 주소를 모른다
    assert saved.missing == ()
    # 이름이 달라 보이는 짝은 사람이 볼 수 있게 알려 준다(자모 분리만 다른 1번은 같은 이름)
    assert [(f.seq, f.file_name) for f in saved.renamed] == [
        (2, "2. 신청서_ 양식_.pdf"),
        (3, "3. 개인정보 동의서 (1).hwp"),
    ]
    assert saved.skipped_images == ("dot.png(아이콘 크기)",)
    assert saved.extra_files == ("메모.txt",)
    assert saved.text.splitlines() == [
        "자격은 첨부 1을 보세요.",
        "[이미지: 첨부 4번 poster.jpg]",
        "[이미지: 첨부 4번 poster.jpg]",
        "[이미지: 첨부 5번 anim.gif]",
    ]
    body = saved.body()
    assert body.startswith(
        "[게시판 정보]\n분류: 장학/등록 · 캠퍼스: ERICA\n"
        "공지 게시 기간: 2026-09-30 ~ 2026-10-24 (게시판에 올려 두는 기간이라 신청 기간과 다를 수 있다)\n\n"
    )
    notice = saved.notice_input()
    assert (notice.title, notice.posted_on.isoformat(), notice.organizer) == (
        "2026학년도 2학기 ○○장학생 선발 안내",
        "2026-09-30",
        "학생지원팀",
    )
    assert notice.original_url is None  # 학교 서버를 다시 읽지 않는다
    assert [a.seq for a in notice.attachments] == [1, 2, 3, 4, 5]
    assert notice.body == body


def test_missing_files_and_unsaved_images(tmp_path: Path) -> None:
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(POSTER)
    html = hanyang_pages.detail(
        files=("1. 공고문.pdf", "2. 신청서.hwp"),
        body=(
            '<p><img src="https://www.hanyang.ac.kr/documents/20122/0/poster.jpg"></p>'  # HTML만 저장
            '<p><img src="../outside.jpg"></p>'  # 폴더 밖 파일은 읽지 않는다
        ),
    )
    folder = save_notice(tmp_path / "공지", html, {"1. 공고문.pdf": samples.pdf(["공고"])}, {})
    saved = load_folder(folder)
    assert [(f.seq, f.name, f.problem) for f in saved.missing] == [
        (2, "2. 신청서.hwp", "폴더에 없어요"),
        (3, "poster.jpg", saved_module._NOT_SAVED),
        (4, "outside.jpg", saved_module._NOT_SAVED),
    ]
    assert "[이미지: 첨부 3번 poster.jpg(저장 안 됨)]" in saved.text
    assert (
        "가져오지 못해 읽을 수 없는 첨부: 첨부 2번 2. 신청서.hwp, 첨부 3번 poster.jpg"
        in saved.body()
    )
    assert [a.seq for a in saved.notice_input().attachments] == [1]


def test_pairing_rules(tmp_path: Path) -> None:
    def pair(name: str, links: tuple[str, ...], files: dict[str, bytes]) -> list[tuple]:
        saved = load_folder(save_notice(tmp_path / name, hanyang_pages.detail(files=links), files))
        return [(f.seq, f.file_name, f.problem) for f in saved.files] + [
            ("같은 파일", saved.duplicate_files),
            ("남는 파일", saved.extra_files),
        ]

    # 앞 링크의 " (1)" 짝 찾기가 뒤 링크의 제 이름 파일을 뺏지 않는다
    assert pair(
        "영문",
        ("2026 신청서(영문).pdf", "2026 신청서.pdf"),
        {"2026 신청서.pdf": b"ko"},
    ) == [
        (1, None, "폴더에 없어요"),
        (2, "2026 신청서.pdf", None),
        ("같은 파일", ()),
        ("남는 파일", ()),
    ]
    # 비슷하기만 한 이름은 짝짓지 않는다(첨부가 "(수정)"본으로 바뀌었는데 옛 파일이 남은 경우)
    assert pair(
        "수정본",
        ("2026학년도 장학생 선발 공고문(수정).pdf",),
        {"2026학년도 장학생 선발 공고문.pdf": b"old"},
    ) == [
        (
            1,
            None,
            "폴더에 없어요(비슷한 이름: 2026학년도 장학생 선발 공고문.pdf. 같은 파일이면 이름을"
            " 페이지와 같게 바꾸고, 고친 첨부면 새로 내려받으세요)",
        ),
        ("같은 파일", ()),
        ("남는 파일", ("2026학년도 장학생 선발 공고문.pdf",)),
    ]
    # 페이지에 "신청서.hwp"와 "신청서 (1).hwp"가 다 있으면 각자 제 이름 파일
    assert pair(
        "두 신청서",
        ("신청서.hwp", "신청서 (1).hwp"),
        {"신청서.hwp": b"a", "신청서 (1).hwp": b"b"},
    )[:2] == [(1, "신청서.hwp", None), (2, "신청서 (1).hwp", None)]
    # 고친 첨부를 같은 이름으로 다시 받아 " (1)"이 붙었다: 어느 것이 맞는지 모르니 멈춘다
    assert pair(
        "다시 받음",
        ("1. 선발요강.hwpx",),
        {"1. 선발요강.hwpx": b"old", "1. 선발요강 (1).hwpx": b"new"},
    )[0] == (
        1,
        None,
        "같은 첨부로 보이는 파일이 2개예요(1. 선발요강.hwpx, 1. 선발요강 (1).hwpx)."
        " 맞는 파일 하나만 남기세요",
    )
    # 같은 파일을 두 번 받은 것뿐이면 하나를 쓰고 알려 준다
    assert pair(
        "두 번 받음",
        ("1. 선발요강.hwpx",),
        {"1. 선발요강.hwpx": b"same", "1. 선발요강 (1).hwpx": b"same"},
    ) == [
        (1, "1. 선발요강.hwpx", None),
        ("같은 파일", ("1. 선발요강 (1).hwpx",)),
        ("남는 파일", ()),
    ]
    # 이름이 같은 첨부 둘(학부용·대학원용): 내용 가짓수가 첨부 수와 같으면 내려받은 순서대로 짝짓는다
    links = ("신청서.hwp", "신청서.hwp")
    folder = save_notice(
        tmp_path / "같은 이름",
        hanyang_pages.detail(files=links),
        {"신청서.hwp": b"undergrad", "신청서 (1).hwp": b"undergrad", "신청서 (2).hwp": b"grad"},
    )
    saved = load_folder(folder)
    assert [(f.file_name, f.data) for f in saved.files] == [
        ("신청서.hwp", b"undergrad"),
        ("신청서 (2).hwp", b"grad"),
    ]
    assert (saved.same_name_links, saved.duplicate_files) == (("신청서.hwp",), ("신청서 (1).hwp",))
    # 학교가 같은 파일을 두 번 올렸으면(내용이 같으면) 그대로 짝짓는다
    identical = load_folder(
        save_notice(
            tmp_path / "같은 파일 두 번",
            hanyang_pages.detail(files=links),
            {"신청서.hwp": b"same", "신청서 (1).hwp": b"same"},
        )
    )
    assert [(f.file_name, f.problem) for f in identical.files] == [
        ("신청서.hwp", None),
        ("신청서 (1).hwp", None),
    ]
    # 첨부 1을 두 번 받고 2를 안 받은 것일 수도 있어 알려 준다
    assert (identical.same_name_links, identical.identical) == (("신청서.hwp",), ((1, 2),))
    # 페이지에 "신청서 (1).hwp"라는 첨부가 따로 있어도, 내용이 첨부 1과 같으면 알려 준다
    twice = load_folder(
        save_notice(
            tmp_path / "한 번 더 받음",
            hanyang_pages.detail(files=("신청서.hwp", "신청서 (1).hwp")),
            {"신청서.hwp": b"x", "신청서 (1).hwp": b"x"},
        )
    )
    assert [f.file_name for f in twice.files] == ["신청서.hwp", "신청서 (1).hwp"]
    assert (twice.same_name_links, twice.identical) == ((), ((1, 2),))
    # 하나만 받았으면 어느 첨부인지 모르므로 둘 다 멈춘다
    assert [f.problem for f in load_folder(
        save_notice(tmp_path / "하나만", hanyang_pages.detail(files=links), {"신청서.hwp": b"a"})
    ).files] == [
        "이름이 같은 첨부가 2개인데 폴더의 파일은 1가지예요(신청서.hwp). 첨부마다 한 번씩만 내려받아 주세요"
    ] * 2  # fmt: skip
    # " (2)"만 있으면 그 파일이 짝이다
    assert pair("복사본", ("신청서.hwp",), {"신청서 (2).hwp": b"x"})[0] == (
        1,
        "신청서 (2).hwp",
        None,
    )


def test_names_that_differ_only_in_case_keep_their_own_files(tmp_path: Path) -> None:
    probe = tmp_path / "Case"
    probe.write_text("x")
    if (tmp_path / "case").exists():
        pytest.skip(
            "대소문자를 가리지 않는 파일 시스템(macOS·Windows 기본)에서는 두 파일을 함께 둘 수 없다"
        )
    saved = load_folder(
        save_notice(
            tmp_path / "대소문자",
            hanyang_pages.detail(files=("form.pdf", "Form.pdf")),
            {"Form.pdf": b"upper", "form.pdf": b"lower"},
        )
    )
    assert [(f.file_name, f.data) for f in saved.files] == [
        ("form.pdf", b"lower"),
        ("Form.pdf", b"upper"),
    ]
    assert saved.same_name_links == ()  # 이름이 똑같은 파일끼리 짝지어 순서로 고르지 않았다


def test_size_limit_and_unreadable_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    html = hanyang_pages.detail(files=("큰 파일.pdf", "잠긴 파일.hwp", "보통 파일.pdf"))
    folder = save_notice(
        tmp_path / "공지",
        html,
        {"큰 파일.pdf": b"x" * 64, "잠긴 파일.hwp": b"locked", "보통 파일.pdf": b"%PDF-1.4"},
    )
    monkeypatch.setattr(saved_module, "MAX_FILE_BYTES", 32)
    read_bytes = Path.read_bytes

    def locked(path: Path) -> bytes:
        if path.name == "잠긴 파일.hwp":  # 한글에서 열어 둔 파일(Windows)
            raise PermissionError(13, "Permission denied")
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", locked)
    saved = load_folder(folder)
    assert [f.problem for f in saved.files] == [
        "파일이 너무 커요(32바이트 넘음)",
        "파일을 읽지 못했어요(PermissionError). 열려 있으면 닫고 다시 하세요",
        None,
    ]


def test_mhtml_single_file(tmp_path: Path) -> None:
    """Chrome "웹페이지, 단일 파일"과 같은 모양: HTML은 quoted-printable, 이미지는 base64, 주소로 찾는다."""
    page_url = hanyang_pages.view_url(119702).replace("&amp;", "&")
    image_url = "https://www.hanyang.ac.kr/documents/20122/0/%ED%8F%AC%EC%8A%A4%ED%84%B0.jpg/abc"
    html = hanyang_pages.detail(
        permalink=False,
        class_pk=False,
        current_url=False,
        files=(),
        body=f'<p>포스터를 보세요</p><img alt="포스터" src="{image_url}">',
    )
    folded = image_url[:40] + "\r\n\t" + image_url[40:]  # 긴 헤더 줄은 접힐 수 있다
    boundary = "----MultipartBoundary--abc----"
    mhtml = (
        "From: <Saved by Blink>\r\n"
        f"Snapshot-Content-Location: {page_url}\r\n"
        "MIME-Version: 1.0\r\n"
        f'Content-Type: multipart/related;\r\n\ttype="text/html";\r\n\tboundary="{boundary}"\r\n'
        "\r\n\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/html\r\n"
        "Content-ID: <frame-1@mhtml.blink>\r\n"
        "Content-Transfer-Encoding: quoted-printable\r\n"
        f"Content-Location: {page_url}\r\n\r\n"
    ).encode()
    mhtml += quopri.encodestring(html.encode()) + b"\r\n"
    mhtml += (
        f"--{boundary}\r\n"
        "Content-Type: image/jpeg\r\n"
        "Content-Transfer-Encoding: base64\r\n"
        f"Content-Location: {folded}\r\n\r\n"
    ).encode()
    mhtml += base64.encodebytes(POSTER) + f"\r\n--{boundary}--\r\n".encode()
    folder = tmp_path / "단일 파일"
    folder.mkdir()
    (folder / "공지사항 - 한양대학교.mhtml").write_bytes(mhtml)
    saved = load_folder(folder)
    assert saved.page.entry_id == "119702"  # 페이지 주소(Snapshot-Content-Location)에서
    assert saved.page.title == "2026학년도 2학기 ○○장학생 선발 안내"  # quoted-printable·UTF-8
    assert [(f.name, f.data) for f in saved.files] == [("포스터.jpg", POSTER)]
    assert saved.text.splitlines() == ["포스터를 보세요", "[이미지: 첨부 1번 포스터.jpg]"]


def test_mhtml_with_raw_korean_header(tmp_path: Path) -> None:
    html = hanyang_pages.detail(files=())
    boundary = "b"
    mhtml = (
        (
            "MIME-Version: 1.0\r\n"
            f'Content-Type: multipart/related; type="text/html"; boundary="{boundary}"\r\n\r\n'
            f"--{boundary}\r\n"
            'Content-Type: text/html; name="공지사항.html"\r\n'  # 헤더에 인코딩하지 않은 한글
            "Content-Transfer-Encoding: 8bit\r\n\r\n"
        ).encode()
        + html.encode()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    folder = tmp_path / "한글 헤더"
    folder.mkdir()
    (folder / "공지.mhtml").write_bytes(mhtml)
    assert load_folder(folder).page.entry_id == "119702"


def test_finding_notice_folders(tmp_path: Path) -> None:
    html = hanyang_pages.detail(files=())
    first = save_notice(tmp_path / "모음" / "가", html, {}, {"poster.jpg": POSTER})
    second = save_notice(tmp_path / "모음" / "나", html, {}, {})
    (tmp_path / "모음" / "빈 폴더").mkdir()
    (first / FILES / "saved_resource.html").write_text("<p>iframe</p>")  # 자료 폴더 속 페이지
    assert notice_folders([tmp_path / "모음"]) == [first, second]
    # 목록 페이지를 공지 폴더들 옆에 저장해도 아래 폴더들을 공지로 본다
    (tmp_path / "모음" / "목록.html").write_text(hanyang_pages.listing([]), encoding="utf-8")
    assert notice_folders([tmp_path / "모음"]) == [first, second]
    # 공지 폴더 안에 예전 저장본이나 압축을 푼 폴더가 있어도 바깥 페이지를 쓰고 알려만 준다
    save_notice(second / "이전 저장", html.replace("자세한", "예전"), {})
    (second / "서식 모음").mkdir()
    (second / "서식 모음" / "안내.html").write_text("<p>압축 속 페이지</p>", encoding="utf-8")
    assert notice_folders([second]) == [second]
    saved = load_folder(second)
    assert "예전" not in saved.text
    assert saved.nested_folders == ("서식 모음", "이전 저장")
    assert notice_folders([first, first / "공지사항 - 한양대학교.html"]) == [first]
    with pytest.raises(SavedPageError, match="폴더가 없어요"):
        notice_folders([tmp_path / "없음"])

    (first / "다른 공지.html").write_text(html, encoding="utf-8")
    with pytest.raises(SavedPageError, match="공지마다 폴더를 나눠"):
        load_folder(first)
    with pytest.raises(SavedPageError, match="페이지\\(.html·.mhtml\\)가 없어요"):
        load_folder(tmp_path / "모음" / "빈 폴더")
    (second / "공지사항 - 한양대학교.html").write_text(hanyang_pages.listing([]), encoding="utf-8")
    with pytest.raises(SavedPageError, match="상세 페이지가 아니에요"):
        load_folder(second)
