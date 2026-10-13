"""온통청년 정책 시험 자료. 10/13에 받은 실제 정책(조달청 "해외조달시장 전문인력 양성과정")의 칸 모양을
본떠 만든다. 테스트마다 바꿀 칸만 넘긴다. FakeClient는 온통청년 클라이언트 대신 쓴다."""

from typing import Any

import pytest

from app.youth.client import FetchResult, YouthApiError
from app.youth.regions import region_table

# 전국: 지금 있는 끝 지역(구가 있는 시는 구) 전부. 온통청년의 전국 정책도 이 256곳이다
NATIONWIDE = ",".join(sorted(region_table().leaves))
INCHEON_BEFORE_JULY = "28125,28177,28185,28200,28237,28245,28290,28710,28720"  # 527건이 이 모양

BASE: dict[str, Any] = {
    "plcyNo": "20261008005400113930",
    "plcyAprvSttsCd": "0044002",
    "plcyNm": "해외조달시장 전문인력 양성과정",
    "plcyKywdNm": None,
    "plcyExplnCn": "청년을 대상으로 해외조달시장 진출 직무 (해외 B2G) 교육 프로그램 제공",
    "lclsfNm": "일자리",
    "mclsfNm": "취업",
    "plcySprtCn": "1. 해외 B2G 관련 이론 및 실무 강의, 실습\n2. 기업 현장 견학",
    "sprvsnInstCd": "1230000",
    "sprvsnInstCdNm": "조달청",
    "rgtrInstCdNm": "조달청",
    "aplyPrdSeCd": "0057002",
    "aplyYmd": "",
    "bizPrdSeCd": "0056002",
    "bizPrdBgngYmd": "",
    "bizPrdEndYmd": "",
    "plcyAplyMthdCn": "",
    "srngMthdCn": "",
    "aplyUrlAddr": "",
    "sbmsnDcmntCn": "",
    "etcMttrCn": "",
    "refUrlAddr1": "https://www.jobkorea.co.kr/Recruit/GI_Read/49098517",
    "refUrlAddr2": "",
    "sprtTrgtMinAge": "0",
    "sprtTrgtMaxAge": "0",
    "sprtTrgtAgeLmtYn": "N",
    "mrgSttsCd": "0055003",
    "earnCndSeCd": "0043001",
    "earnMinAmt": "0",
    "earnMaxAmt": "0",
    "earnEtcCn": "",
    "addAplyQlfcCndCn": "",
    "ptcpPrpTrgtCn": "",
    "inqCnt": "47",
    "zipCd": NATIONWIDE,
    "plcyMajorCd": "0011009",
    "jobCd": "0013010",
    "schoolCd": "0049010",
    "sbizCd": "0014010",
    "frstRegDt": "2026-10-08 16:52:36",
    "lastMdfcnDt": "2026-10-08 17:06:23",
}


def policy(**values: Any) -> dict[str, Any]:
    """BASE에 값을 덮어쓴 정책 하나. 조건 없는 전국·상시 정책이 기본이다."""
    return {**BASE, **values}


class FakeClient:
    """정해 둔 정책을 돌려주는 온통청년 클라이언트. skipped는 읽지 못한 순번, error는 온통청년 오류다."""

    def __init__(
        self,
        items: list[dict[str, Any]],
        *,
        skipped: tuple[int, ...] = (),
        stopped: str | None = None,
        error: str | None = None,
    ) -> None:
        self.items = items
        self.skipped = skipped
        self.stopped = stopped
        self.error = error
        self.closed = False

    async def fetch_all(self) -> FetchResult:
        if self.error:
            raise YouthApiError(self.error)
        return FetchResult(
            policies=tuple(self.items),
            total=len(self.items) + len(self.skipped),
            calls=1,
            skipped=self.skipped,
            stopped=self.stopped,
            total_changed=False,
            seconds=0.1,
        )

    async def aclose(self) -> None:
        self.closed = True


async def skip_if_other_youth_policies(conn: Any, prefix: str) -> None:
    """청년정책 공고가 이미 있는 DB면 건너뛴다. 빠짐없이 받은 수집은 목록에 없는 공고를 숨기므로 그 DB의
    공고를 숨기거나(CLI는 autocommit) 숫자가 어긋난다. CI의 빈 DB에서 돈다."""
    cursor = await conn.execute(
        "select count(*) from opportunities where source_type = 'youth_policy'"
        " and external_id not like %s",
        (prefix + "%",),
    )
    row = await cursor.fetchone()
    count = row["count"] if isinstance(row, dict) else row[0]
    if count:
        pytest.skip(f"청년정책 공고가 {count}건 있는 DB라 건너뜀(빈 DB에서 돈다)")
