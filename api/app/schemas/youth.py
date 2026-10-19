"""청년정책 수집 작업의 응답 (API 명세 12장 `POST /internal/jobs/fetch-policies`)."""

from pydantic import BaseModel


class FetchPoliciesResult(BaseModel):
    """수집 한 번의 결과. 명령 `python -m app.youth.cli fetch`가 찍는 숫자와 같다.

    `fetched`는 받은 정책 수, `total`은 온통청년이 말한 전체 수다. `complete`가 false면 빠짐없이
    받지 못한 것이고, 그때는 목록에서 사라진 정책을 숨기지 않는다. `skipped`는 범위 밖이라 가져오지
    않은 정책 수(마감 지남·수도권 밖 등)이고, `gone_kept`는 한 번에 너무 많이 사라져 숨기지 않고
    둔 정책 수다(온통청년 목록이 덜 왔을 수 있다).
    """

    run_id: str
    fetched: int
    total: int
    complete: bool
    stopped: str | None
    new: int
    updated: int
    unchanged: int
    expired: int
    hidden: int
    skipped: int
    gone_kept: int
