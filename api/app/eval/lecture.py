"""시나리오가 올리는 강의자료 PDF(S19). 글자만 있는 영어 강의 노트를 **코드로** 만든다.

LMS 강의자료는 영어인 것이 흔해서 영어로 쓴다 — 그래서 PDF 표준 글꼴(Helvetica)만으로 되고 글꼴을 담지
않는다. 쪽마다 줄을 그대로 적고 내용은 zlib으로 줄인다(PDF FlateDecode). 같은 인자면 늘 같은 바이트다 — 몇 번을
돌려도 같은 파일이다.

- `short_notes()`: 3쪽짜리 9주차 노트. 상한(3만 토큰) 안이라 전체를 한 번에 요약한다
- `long_notes()`: 48쪽짜리 한 학기 노트. 쪽 수는 올릴 수 있는 300쪽 안이지만 글자가 상한을 넘어 요약하지 않고
  나눠 올리라고 안내한다(413 MATERIAL_TOO_LONG)
"""

import zlib
from collections.abc import Sequence

COURSE = "Database Systems"
SHORT_TITLE = f"{COURSE} - Week 9: Transactions and Concurrency Control"
# 짧은 노트의 첫 줄과 마지막 줄. 모델에 간 글에 둘 다 있으면 문서 전체를 보낸 것이다
FIRST_LINE = SHORT_TITLE
LAST_LINE = "End of Week 9 notes. Next week: recovery and logging."
SHORT_PAGES: tuple[tuple[str, ...], ...] = (
    (
        SHORT_TITLE,
        "1. What is a transaction",
        "A transaction is a sequence of reads and writes that forms one logical unit of work.",
        "It either commits as a whole or aborts and leaves no effect on the database.",
        "2. ACID properties",
        "Atomicity: all or nothing. Consistency: constraints hold before and after.",
        "Isolation: concurrent transactions do not see each other's partial results.",
        "Durability: once committed, changes survive crashes.",
    ),
    (
        "3. Schedules and serializability",
        "A schedule interleaves the operations of several transactions.",
        "A schedule is conflict serializable if its precedence graph has no cycle.",
        "Conflicting operations: two operations on the same item, at least one is a write.",
        "4. Two-phase locking (2PL)",
        "Growing phase: a transaction acquires locks and releases none.",
        "Shrinking phase: it releases locks and acquires no new lock.",
        "Strict 2PL holds exclusive locks until commit, which avoids cascading aborts.",
    ),
    (
        "5. Deadlocks",
        "A deadlock is a cycle in the waits-for graph.",
        "Prevention: wait-die and wound-wait use transaction timestamps.",
        "Detection: build the waits-for graph periodically and abort a victim.",
        "6. Isolation levels in SQL",
        "READ UNCOMMITTED, READ COMMITTED, REPEATABLE READ and SERIALIZABLE.",
        "Weaker levels allow dirty reads, non-repeatable reads or phantoms.",
        LAST_LINE,
    ),
)
LONG_PAGE_COUNT = 48
_LONG_LINES = (
    "Relational model: a relation is a set of tuples with the same attributes.",
    "Keys: a candidate key is a minimal set of attributes that identifies a tuple.",
    "Relational algebra: selection, projection, join, union, difference and rename.",
    "SQL joins: inner, left outer, right outer and full outer joins with ON conditions.",
    "Normalization: 1NF, 2NF, 3NF and BCNF remove redundancy caused by dependencies.",
    "Indexing: B+ trees keep keys sorted and support range scans in logarithmic time.",
    "Hash indexes answer equality lookups but cannot serve range predicates.",
    "Query processing: the optimizer compares plans using cardinality estimates.",
    "Transactions: atomicity, consistency, isolation and durability (ACID).",
    "Recovery: write-ahead logging records changes before they reach the disk.",
)
_LINES_PER_LONG_PAGE = 44
_PAGE_WIDTH, _PAGE_HEIGHT = 595, 842  # A4(pt)


def short_notes() -> bytes:
    """3쪽짜리 9주차 노트(상한 안)."""
    return notes_pdf(SHORT_PAGES)


def long_notes() -> bytes:
    """48쪽짜리 한 학기 노트(쪽 수는 받지만 글자가 상한을 넘는다)."""
    pages = []
    for page in range(1, LONG_PAGE_COUNT + 1):
        week = (page - 1) // 3 + 1  # 한 주에 3쪽, 16주
        lines = [f"{COURSE} - Lecture notes, week {week}, page {page}"]
        lines += [
            f"Slide {page}.{no}: {_LONG_LINES[(page + no) % len(_LONG_LINES)]}"
            for no in range(1, _LINES_PER_LONG_PAGE)
        ]
        pages.append(tuple(lines))
    return notes_pdf(pages)


def notes_pdf(pages: Sequence[Sequence[str]]) -> bytes:
    """쪽마다 줄을 위에서부터 적은 PDF. 글자는 ASCII만 받는다(표준 글꼴 Helvetica, 글꼴을 담지 않는다)."""
    font_no = 3 + 2 * len(pages)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids ["
        + b" ".join(f"{3 + 2 * index} 0 R".encode() for index in range(len(pages)))
        + f"] /Count {len(pages)} >>".encode(),
    ]
    for index, lines in enumerate(pages):
        content = zlib.compress(_page_content(lines), 9)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PAGE_WIDTH} {_PAGE_HEIGHT}]"
            f" /Resources << /Font << /F1 {font_no} 0 R >> >> /Contents {4 + 2 * index} 0 R >>".encode()
        )
        objects.append(
            f"<< /Length {len(content)} /Filter /FlateDecode >>\nstream\n".encode()
            + content
            + b"\nendstream"
        )
    # WinAnsiEncoding: 기본(StandardEncoding)이면 '가 ’(quoteright)로 읽힌다
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    out += f"startxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _page_content(lines: Sequence[str]) -> bytes:
    commands = []
    for no, line in enumerate(lines):
        if not line.isascii():
            raise ValueError(f"강의 노트 PDF는 ASCII 글자만 쓴다: {line!r}")
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"BT /F1 10 Tf 50 {_PAGE_HEIGHT - 50 - 16 * no} Td ({escaped}) Tj ET")
    return "\n".join(commands).encode("ascii")
