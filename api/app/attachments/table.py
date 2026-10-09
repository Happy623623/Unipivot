"""표 → 줄. HWP·HWPX가 같이 쓴다.

행마다 "셀 | 셀" 한 줄이다. 여러 행에 걸친 짧은 셀(구분 칸 등)은 걸친 행마다 되풀이해,
"성적우수 | 평점 3.5 이상 | 100만원"처럼 행 하나만 봐도 뜻이 통하게 한다.
칸이 하나뿐인 표(공고문 전체를 상자로 두른 표 등)는 표가 아니라 글로 보고 줄을 살린다.
"""

from dataclasses import dataclass, field

_FILL_MAX_CHARS = 40  # 이보다 긴 병합 셀은 내용 칸으로 보고 되풀이하지 않는다
_FILL_MAX_ROWS = 50


@dataclass
class Cell:
    row: int
    col: int
    row_span: int = 1
    lines: list[str] = field(default_factory=list)


def table_lines(cells: list[Cell]) -> list[str]:
    if all(cell.col == 0 for cell in cells):
        return [line for cell in sorted(cells, key=lambda c: c.row) for line in cell.lines]
    rows: dict[int, dict[int, str]] = {}
    for cell in cells:
        text = " ".join(cell.lines)
        rows.setdefault(cell.row, {})[cell.col] = text
        if text and len(text) <= _FILL_MAX_CHARS:
            for row in range(cell.row + 1, cell.row + min(cell.row_span, _FILL_MAX_ROWS)):
                rows.setdefault(row, {}).setdefault(cell.col, text)
    lines = [
        " | ".join(text for _, text in sorted(cols.items())) for _, cols in sorted(rows.items())
    ]
    return [line for line in lines if line.replace("|", "").strip()]
