"""저장한 한양대 공지를 확인하고(check) DB에 넣는다(import). api 폴더에서 실행한다.

    uv run python -m app.crawl.cli check ~/공지/1009            # DB·LLM 없이: 캠퍼스, 첨부 짝, 첨부 형식 집계
    uv run python -m app.crawl.cli import ~/공지/1009           # DB에 넣고 새 글·수정된 글만 요건 추출
    uv run python -m app.crawl.cli list ~/공지/목록.html --db    # 저장한 목록에서 ERICA·공통 글, 아직 안 가져온 글

폴더 구조는 app/crawl/saved.py 설명을 본다. 학교 서버에는 접속하지 않는다.
import와 list --db는 DATABASE_URL, import는 GOOGLE_CLOUD_PROJECT도 필요하다(api/.env).
"""

import argparse
import asyncio
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.attachments import KIND_LABELS, AttachmentText
from app.config import Settings
from app.crawl.fetch import decode_html
from app.crawl.hanyang import BOARD_URL, ListRow, NotNoticePage, parse_list
from app.crawl.importer import (
    SOURCE_TYPE,
    ImportOptions,
    ImportResult,
    ensure_source,
    import_notice,
    mark_collected,
)
from app.crawl.saved import (
    IMAGE_KINDS,
    SavedNotice,
    SavedPageError,
    entry_ids,
    load_folder,
    notice_folders,
)
from app.eligibility import KST
from app.extraction.agent import ExtractionAgent
from app.extraction.models import Limits
from app.extraction.setup import build_agent
from app.extraction.sources import Library
from app.extraction.store import load_departments
from app.runtime import event_loop_factory, utf8_output

AgentFactory = Callable[..., ExtractionAgent]
_SCOPE = {"erica": "가져올 대상", "seoul": "건너뜀(서울)", "unmarked": "건너뜀(캠퍼스 표시 없음)"}
_FIX = "고칠 것"


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.crawl.cli", description="저장한 한양대 공지를 확인하고 DB에 넣는다"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    check_parser = commands.add_parser("check", help="DB·LLM 없이 저장한 폴더를 확인한다")
    check_parser.add_argument(
        "paths", nargs="+", type=Path, help="공지 폴더, 또는 공지 폴더들이 든 폴더"
    )

    load = commands.add_parser("import", help="DB에 넣고 새 글·수정된 글만 요건을 추출한다")
    load.add_argument("paths", nargs="+", type=Path, help="공지 폴더, 또는 공지 폴더들이 든 폴더")
    load.add_argument(
        "--include-unmarked",
        action="store_true",
        help="캠퍼스 게시가 '안함'인 공지도 가져온다(ERICA 학생 공지가 맞을 때)",
    )
    load.add_argument(
        "--allow-missing",
        action="store_true",
        help="가져오지 못한 첨부·본문 이미지가 있어도 가져온다(원문 확인 필요가 된다)",
    )
    load.add_argument("--force", action="store_true", help="내용이 같아도 다시 추출한다")
    load.add_argument("--model", help="추출 모델(기본: EXTRACTION_MODEL)")
    load.add_argument("--scenario", help="agent_runs.scenario_code(시나리오 실행 때, 예: S10)")

    listing = commands.add_parser("list", help="저장한 목록 페이지에서 ERICA·공통 글을 보여 준다")
    listing.add_argument("pages", nargs="+", type=Path, help="목록 페이지 .html")
    listing.add_argument("--db", action="store_true", help="이미 가져온 글인지 DB에서 본다")
    return parser.parse_args(argv)


async def main(argv: Sequence[str], *, make_agent: AgentFactory = build_agent) -> int:
    args = parse_args(argv)
    if args.command == "check":
        return check(args.paths)
    if args.command == "list":
        return await list_rows(args.pages, use_db=args.db)
    options = ImportOptions(
        include_unmarked=args.include_unmarked,
        allow_missing=args.allow_missing,
        force=args.force,
        scenario=args.scenario,
    )
    return await import_folders(args.paths, options, model=args.model, make_agent=make_agent)


# ---------- check ----------


def check(paths: Sequence[Path]) -> int:
    """폴더마다 읽은 값과 첨부 짝을 찍고, 끝에 첨부 형식을 센다. 고칠 것이 있으면 1을 돌려준다."""
    folders = _folders(paths)
    if folders is None:
        return 1
    problems = _duplicates(folders)
    formats: Counter[str] = Counter()
    plan: Counter[str] = Counter()
    for no, folder in enumerate(folders, 1):
        print(f"[{no}/{len(folders)}] {folder.name}")
        saved = _load(folder, problems)
        if isinstance(saved, str):
            print(f"    {_FIX}: {saved}")
            plan[_FIX] += 1
            continue
        page = saved.page
        print(f"    {page.title}")
        print(
            f"    글 {page.entry_id} · {page.posted_on or '등록일 모름'}"
            f" · {page.category or '분류 없음'}({page.opportunity_category})"
            f" · 캠퍼스 {page.campus or '없음'} → {_SCOPE[page.scope]}"
        )
        for line, label in _attachment_lines(saved):
            print(f"    {line}")
            formats[label] += 1
        for note in _notes(saved):
            print(f"    {note}")
        if page.scope == "erica" and saved.missing:
            print(
                f"    {_FIX}: 가져오지 못한 파일을 고친다(없이 가져오려면 import --allow-missing)"
            )
            plan[_FIX] += 1
        else:
            plan[_SCOPE[page.scope]] += 1
    print()
    print("공지 " + " · ".join(f"{name} {count}" for name, count in plan.items()))
    if formats:
        print(f"첨부 형식(본문 이미지 포함 {sum(formats.values())}개)")
        for label, count in formats.most_common():
            print(f"    {label}: {count}")
    return 1 if plan[_FIX] else 0


def _attachment_lines(saved: SavedNotice) -> list[tuple[str, str]]:
    """(첨부 한 줄, 형식 집계 이름). 한 줄은 모델이 첫 메시지에서 보는 첨부 목록과 같다."""
    library = Library(saved.notice_input(), Limits())
    listing = dict(zip(library.items, library.listing(), strict=True))
    lines = []
    for file in saved.files:
        prefix = "본문 이미지 " if file.body_image else "첨부 "
        if file.data is None:
            lines.append((f"{prefix}{file.seq}. {file.name} — {file.problem}", "가져오지 못함"))
            continue
        item = library.items[file.seq]
        label = _format_label(item.kind, item.scanned, item.error)
        lines.append((prefix + listing[file.seq], label))
    return lines


def _format_label(kind: str, scanned: AttachmentText | None, error: str | None) -> str:
    name = KIND_LABELS.get(kind, kind.upper())
    if error is not None or scanned is None:
        return f"못 읽음({name})"
    if kind == "pdf":
        return "PDF 스캔본(Vision)" if scanned.needs_vision else "PDF 글자"
    if kind in IMAGE_KINDS:
        return "이미지(Vision)"
    return name


def _notes(saved: SavedNotice) -> list[str]:
    """사람이 한 번 볼 것: 이름이 달라 짝지은 첨부, 안 쓰는 파일, 뺀 본문 이미지."""
    notes = [
        f"파일 이름이 달라 짝지음: {file.file_name} → 첨부 {file.seq}. {file.name}"
        for file in saved.renamed
    ]
    notes += [
        f"이름이 같은 첨부가 여럿이라 내려받은 순서대로 짝지음: {name}. 맞는지 확인하세요"
        for name in saved.same_name_links
    ]
    notes += [
        f"첨부 {', '.join(map(str, seqs))}의 파일 내용이 같아요."
        " 같은 첨부를 두 번 받은 건 아닌지 확인하세요"
        for seqs in saved.identical
    ]
    if saved.duplicate_files:
        notes.append(f"같은 파일을 또 받은 것(안 씀): {', '.join(saved.duplicate_files)}")
    if saved.extra_files:
        notes.append(f"폴더에만 있는 파일(안 씀): {', '.join(saved.extra_files)}")
    notes += [f"본문 이미지 뺌: {name}" for name in saved.skipped_images]
    if saved.nested_folders:
        notes.append(f"안쪽 폴더의 페이지는 쓰지 않음: {', '.join(saved.nested_folders)}")
    return notes


# ---------- import ----------


async def import_folders(
    paths: Sequence[Path],
    options: ImportOptions,
    *,
    model: str | None = None,
    make_agent: AgentFactory = build_agent,
) -> int:
    folders = _folders(paths)
    if folders is None:
        return 1
    settings = Settings()
    if not settings.database_url:
        print("DATABASE_URL이 없어요(api/.env)")
        return 1
    counts: Counter[str] = Counter()
    cost = Decimal(0)
    try:
        conn, log_conn = (
            await _connect(settings.database_url),
            await _connect(settings.database_url),
        )
    except psycopg.OperationalError as exc:
        print(f"DB에 연결하지 못했어요: {exc}")
        return 1
    try:
        departments = await load_departments(conn)
        try:
            agent = make_agent(settings, departments=departments, fetch_page=None, model=model)
        except RuntimeError as exc:  # GOOGLE_CLOUD_PROJECT가 없을 때 등
            print(str(exc))
            return 1
        source_id = await ensure_source(conn)
        print(f"모델 {agent.model} · 학과 {len(departments)}개 · 공지 폴더 {len(folders)}개")
        if not departments:
            print("학과 목록이 비어 있어요. 학과 조건은 모두 원문 확인 필요가 돼요")
        problems = _duplicates(folders)
        for no, folder in enumerate(folders, 1):
            print(f"[{no}/{len(folders)}] {folder.name}")
            saved = _load(folder, problems)
            if isinstance(saved, str):
                print(f"    오류: {saved}")
                counts["error"] += 1
                continue
            print(f"    {saved.page.title} (글 {saved.page.entry_id})")
            for note in _notes(saved):
                print(f"    {note}")
            try:
                result = await import_notice(conn, log_conn, source_id, saved, agent, options)
            except Exception as exc:  # LLM·DB 오류. 공고에는 쓰지 않았고 다음에 다시 돈다
                print(f"    오류: 요건 추출 실패 — {type(exc).__name__}: {str(exc)[:200]}")
                counts["error"] += 1
                continue
            counts[result.status] += 1
            counts["unjudged"] += result.unjudged
            cost += result.cost_usd
            for line in _result_lines(result):
                print(f"    {line}")
        await mark_collected(conn, source_id)
    finally:
        await conn.close()
        await log_conn.close()
    names = {"new": "새 공고", "updated": "다시 추출", "unchanged": "그대로", "skipped": "건너뜀"}
    summary = " · ".join(f"{label} {counts[key]}" for key, label in names.items())
    print(
        f"\n{summary} · 오류 {counts['error']} · 판정 안 됨 {counts['unjudged']}"
        f" · 추정 비용 ${cost:.4f}(목록 단가)"
    )
    return 1 if counts["error"] or counts["unjudged"] else 0


def _result_lines(result: ImportResult) -> list[str]:
    extraction = result.extraction
    if extraction is None:
        word = {"unchanged": "그대로", "skipped": "건너뜀", "error": "오류"}[result.status]
        return [f"{word}: {result.message}"]
    if result.status == "new":
        head = "새 공고"
    else:
        head = f"수정된 글 → 다시 추출(요건 버전 {result.version})"
    if not extraction.succeeded:
        return [
            f"{head} · 추출 실패(제출 없음) → 판정하지 않음 · ${result.cost_usd:.4f}",
            result.message,
        ]
    deadline = (
        extraction.deadline_at.astimezone(KST).strftime("%Y-%m-%d %H:%M")
        if extraction.deadline_at
        else "없음"
    )
    lines = [
        f"{head} · 요건 {len(extraction.requirements)}개 · 서류 {len(extraction.documents)}개"
        f" · 마감 {deadline} · 신뢰도 {extraction.confidence or '-'} · ${result.cost_usd:.4f}"
    ]
    if extraction.needs_review:
        lines.append("원문 확인 필요: " + ("; ".join(extraction.review_reasons) or "모델 판단"))
    return lines


# ---------- list ----------


async def list_rows(pages: Sequence[Path], *, use_db: bool) -> int:
    rows: dict[str, ListRow] = {}
    for path in pages:
        try:
            for row in parse_list(decode_html(path.read_bytes())):
                rows.setdefault(row.entry_id, row)
        except (OSError, NotNoticePage) as exc:
            print(f"{path.name}: {exc}")
            return 1
    imported: set[str] = set()
    if use_db:
        settings = Settings()
        if not settings.database_url:
            print("DATABASE_URL이 없어요(api/.env)")
            return 1
        try:
            imported = await _imported_ids(settings.database_url, list(rows))
        except psycopg.OperationalError as exc:
            print(f"DB에 연결하지 못했어요: {exc}")
            return 1
    shown = sorted(
        (row for row in rows.values() if row.scope != "seoul"),
        key=lambda row: int(row.entry_id),
        reverse=True,
    )
    print(f"목록 {len(rows)}건 중 ERICA·공통 {len(shown)}건(서울 {len(rows) - len(shown)}건은 뺌)")
    for row in shown:
        state = ("가져옴" if row.entry_id in imported else "새 글") if use_db else ""
        parts = [row.entry_id, str(row.posted_on or "-"), row.campus or "표시 없음"]
        parts += [row.category or "-", state, row.title]
        print("  ".join(part for part in parts if part))
        if state != "가져옴":
            print(f"        {row.url}")
    return 0


async def _imported_ids(database_url: str, ids: list[str]) -> set[str]:
    """이미 가져온 글 번호. 출처 행이 없으면(처음) 빈 집합이다."""
    conn = await _connect(database_url)
    try:
        found = await (
            await conn.execute(
                "select o.external_id from opportunities o join sources s on s.id = o.source_id"
                " where s.type = %s and s.base_url = %s and o.external_id = any(%s)",
                (SOURCE_TYPE, BOARD_URL, ids),
            )
        ).fetchall()
    finally:
        await conn.close()
    return {row["external_id"] for row in found}


# ---------- 공통 ----------


def _duplicates(folders: Sequence[Path]) -> dict[Path, str]:
    """같은 글을 두 폴더에 저장했으면 둘 다 멈춘다. 그대로 두면 실행마다 번갈아 다시 추출하거나
    옛 저장본으로 되돌린다. 페이지가 여럿이라 읽지 못하는 폴더의 글 번호도 센다."""
    found: dict[str, list[Path]] = {}
    for folder in folders:
        try:
            ids = entry_ids(folder)
        except Exception:  # 폴더를 읽을 때 이유를 다시 알린다
            continue
        for entry_id in ids:
            found.setdefault(entry_id, []).append(folder)
    problems: dict[Path, str] = {}
    for entry_id, group in found.items():
        if len(group) > 1:
            names = ", ".join(folder.name for folder in group)
            for folder in group:
                problems[folder] = (
                    f"같은 글({entry_id})이 폴더 {len(group)}개에 있어요({names})."
                    " 최근에 저장한 폴더 하나만 남기세요"
                )
    return problems


def _load(folder: Path, problems: dict[Path, str]) -> SavedNotice | str:
    """공지 폴더 하나. 못 읽으면 이유 한 줄."""
    if folder in problems:
        return problems[folder]
    try:
        return load_folder(folder)
    except SavedPageError as exc:
        return str(exc)
    except Exception as exc:  # 예상하지 못한 파일. 이 폴더만 건너뛰고 나머지는 계속한다
        return f"폴더를 읽다가 오류가 났어요({type(exc).__name__}: {str(exc)[:200]})"


def _folders(paths: Sequence[Path]) -> list[Path] | None:
    try:
        folders = notice_folders(paths)
    except SavedPageError as exc:
        print(str(exc))
        return None
    if not folders:
        print(
            "공지 폴더가 없어요. 공지마다 폴더를 만들고 저장한 페이지(.html·.mhtml)와 첨부를 넣어 주세요"
        )
        return None
    return folders


async def _connect(database_url: str) -> AsyncConnection:
    """autocommit 연결. 실패한 실행도 로그에 남고, 공지 저장은 공지마다 트랜잭션으로 묶는다."""
    return await AsyncConnection.connect(
        database_url, row_factory=dict_row, autocommit=True, prepare_threshold=None
    )


if __name__ == "__main__":
    utf8_output()  # 출력을 파이프로 보낼 때 cp949에 없는 글자에서 멈추지 않게(Windows)
    sys.exit(asyncio.run(main(sys.argv[1:]), loop_factory=event_loop_factory()))
