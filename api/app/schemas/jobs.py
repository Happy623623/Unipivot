"""정기 작업 예약표를 부르는 응답(API 명세 12장 `POST /internal/jobs/tick`)."""

from pydantic import BaseModel


class TickResult(BaseModel):
    """이번 tick에 집어 뒤에서 띄운 작업(예약표 줄 이름, 이른 차례부터). 비었으면 때가 된 작업이 없거나 남이
    이미 집었다. 작업 결과는 로그와 예약표(`job_schedule`)에 남는다."""

    started: list[str]
