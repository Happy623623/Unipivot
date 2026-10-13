"""온통청년 지역 코드(zipCd) → 판정 엔진의 거주지역 조건 (판정엔진_규칙.md 11장).

zipCd는 법정동 코드 앞 5자리(시군구) 목록이다. 코드표는 region_codes.py다.
- 끝 지역: 지금 있는 시군구 중 아래에 구를 두지 않은 곳(구가 있는 시는 그 구). 시 코드(안산시)는 그 아래 구를
  모두 고른 것으로 본다.
- 끝 지역을 모두 고른 정책은 전국이라 거주지역 조건을 만들지 않는다.
- 시도의 끝 지역을 모두 고르면 시도 이름("경기도"), 일부면 시군구 이름("경기도 안산시 단원구")이다.
  한 시의 구를 모두 고르면 시 이름으로 줄인다("경기도 안산시").
- 판정할 수 없는 곳은 같은 묶음의 기타 조건(원문 확인)으로 둔다. 그곳에 사는 학생은 지원 어려움이 아니라
  원문 확인 필요가 된다.
  - 판정 엔진이 모르는 시도(2026-07 출범한 전남광주통합특별시). 네 곳 이상이면 "전남광주통합특별시(광양시
    빼고)", "전남광주통합특별시 중 12곳"처럼 줄여 쓴다
  - 없어진 코드(2026-07 개편 전 인천 중구·동구·서구 등)와 코드표에 없는 코드
  - 시도의 끝 지역을 5곳 이상 고르고 한두 곳만 빠뜨린 경우의 빠진 곳(정책 등록 때 코드가 덜 옮겨진 경우가 많다)
- 2026-07-01 인천 개편 보정: 7월 전에 등록한 정책 중 옛 중구·서구를 제물포구·검단구로만 옮긴 정책이 많다
  (10/13 받은 3234건 중 527건). 7월 전 정책이 제물포구(검단구)를 고르고 영종구(서해구)를 빠뜨렸으면, 인천의
  나머지를 모두 골랐을 때는 영종구(서해구)도 고른 것으로 보고, 아니면 원문 확인으로 둔다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from functools import cache

from app.eligibility.regions import normalize_sido
from app.youth.region_codes import ROWS

CAPITAL = ("11", "28", "41")  # 서울·인천·경기(코드 앞 2자리)
_SPLIT_DATE = date(2026, 7, 1)
_SPLITS = {"28125": "28155", "28290": "28275"}  # 제물포구 → 영종구, 검단구 → 서해구
_NEAR_MISSING = 2  # 빠진 끝 지역이 이만큼 이하이고
_NEAR_COVERED = 5  # 고른 끝 지역이 이만큼 이상이면 빠진 곳은 원문 확인
_FEW = 3  # 모르는 시도에서 고른 곳(빠진 곳)이 이만큼 이하면 이름을 쓰고, 많으면 줄여 쓴다


@dataclass(frozen=True)
class RegionCondition:
    values: tuple[str, ...]  # 거주지역 in 값(판정할 수 있는 이름)
    uncertain: tuple[str, ...]  # 판정할 수 없는 곳. 기타 조건(원문 확인)이 된다


class RegionTable:
    def __init__(self, rows: Iterable[tuple[str, str, bool]]) -> None:
        self.names: dict[str, str] = {}
        self.current: set[str] = set()
        for code, name, exists in rows:
            self.names[code] = name
            if exists:
                self.current.add(code)
        self.children: dict[str, frozenset[str]] = {}
        for parent in self.current:
            prefix = self.names[parent] + " "
            kids = frozenset(code for code in self.current if self.names[code].startswith(prefix))
            if kids:
                self.children[parent] = kids
        self.leaves = frozenset(code for code in self.current if code not in self.children)
        by_sido: dict[str, set[str]] = {}
        for code in self.leaves:
            by_sido.setdefault(code[:2], set()).add(code)
        self.by_sido = {sido: frozenset(codes) for sido, codes in sorted(by_sido.items())}

    def covers_capital(self, codes: Iterable[str]) -> bool:
        """서울·인천·경기를 한 곳이라도 고른 정책(전국 포함). 없어진 코드도 센다."""
        return any(code.startswith(CAPITAL) for code in codes)

    def condition(
        self, codes: Iterable[str], registered_on: date | None = None
    ) -> RegionCondition | None:
        """거주지역 조건. 전국이거나 코드가 없으면 None이다."""
        given = sorted({code.strip() for code in codes if code and code.strip()})
        if not given:
            return None
        covered: set[str] = set()
        for code in given:
            covered |= self._leaves_under(code)
        maybe: set[str] = set()
        if registered_on is not None and registered_on < _SPLIT_DATE:
            for source, split in _SPLITS.items():
                if source in covered and split not in covered and split in self.leaves:
                    maybe.add(split)
        if self.leaves <= covered | maybe:
            return None
        values: list[str] = []
        uncertain: list[str] = []
        stale = [code for code in given if code in self.names and code not in self.current]
        for leaves in self.by_sido.values():
            hit = covered & leaves
            near = maybe & leaves
            if not hit and not near:
                continue
            sido_name = self.names[min(leaves)].split()[0]
            if not normalize_sido(sido_name):
                uncertain.append(self._unknown_sido(sido_name, hit | near, leaves))
                continue
            if hit | near == leaves:
                values.append(sido_name)
                continue
            values.extend(self._collapsed(hit))
            uncertain.extend(self.names[code] for code in sorted(near))
            missing = leaves - hit - near
            if len(missing) <= _NEAR_MISSING and len(hit) >= _NEAR_COVERED:
                uncertain.extend(self.names[code] for code in sorted(missing))
        uncertain.extend(f"{self.names[code]}(없어진 지역)" for code in stale)
        uncertain.extend(f"지역 코드 {code}" for code in given if code not in self.names)
        return RegionCondition(tuple(dict.fromkeys(values)), tuple(dict.fromkeys(uncertain)))

    def _unknown_sido(self, sido_name: str, chosen: set[str], leaves: frozenset[str]) -> str:
        """판정 엔진이 모르는 시도에서 고른 곳(원문 확인). 여러 곳이면 이름을 다 늘어놓지 않고 줄인다."""
        if chosen == leaves:
            return sido_name
        names = self._collapsed(chosen)
        if len(names) <= _FEW:
            return ", ".join(names)
        missing = sorted(leaves - chosen)
        if len(missing) <= _FEW:
            short = ", ".join(self.names[code].removeprefix(sido_name + " ") for code in missing)
            return f"{sido_name}({short} 빼고)"
        return f"{sido_name} 중 {len(chosen)}곳"

    def _leaves_under(self, code: str) -> set[str]:
        if code in self.leaves:
            return {code}
        return set(self.children.get(code, frozenset()) & self.leaves)

    def _collapsed(self, hit: set[str]) -> list[str]:
        """고른 끝 지역의 이름. 한 시의 구를 모두 골랐으면 시 이름 하나로 줄인다."""
        named: dict[str, str] = {}
        done: set[str] = set()
        for parent, kids in self.children.items():
            leaves = kids & self.leaves
            if leaves and leaves <= hit:
                named[parent] = self.names[parent]
                done |= leaves
        named.update({code: self.names[code] for code in hit - done})
        return [named[code] for code in sorted(named)]


def parse_rows(text: str) -> list[tuple[str, str, bool]]:
    rows = []
    for line in text.splitlines():
        if line.strip():
            code, name, exists = line.split("|")
            rows.append((code, name, exists == "1"))
    return rows


@cache
def region_table() -> RegionTable:
    return RegionTable(parse_rows(ROWS))
