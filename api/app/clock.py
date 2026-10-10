"""현재 시각. 날짜에 따라 결과가 바뀌는 코드는 이 값을 인자로 받는다(API 명세 1장, 테스트에서 고정)."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends


def current_time() -> datetime:
    return datetime.now(UTC)


NowDep = Annotated[datetime, Depends(current_time)]
