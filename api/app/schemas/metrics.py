"""내부 지표 집계 (API 명세 v0.4 12장 `GET /internal/metrics`, PRD 8장 성공 지표).

세 묶음을 돌려준다.
- scenarios: 기간 안의 시나리오 실행(agent_runs.trigger_type = 'eval') 성공률·응답시간·호출비용
- eligibility: 가장 최근 시나리오 실행 묶음의 판정 3×3 혼동행렬
- product: 제품 지표 5개

비용은 scenario_code로 묶은 `llm_calls`를 더한다. 시나리오 실행 행의 cost_usd는 0이다(제 손으로
모델을 부르지 않는다). agent_runs.cost_usd를 또 더하면 같은 비용을 두 번 센다.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.opportunities import ELIGIBILITY_STATUSES, EligibilityStatus

# 시나리오 실행이 남기는 확인 줄(app/eval/world.py의 check). 혼동행렬은 kind가 아래 값인 줄만 읽는다
CHECK_TOOL = "check"
ELIGIBILITY_CHECK = "eligibility"
STATUSES: tuple[str, ...] = ELIGIBILITY_STATUSES


class Latency(BaseModel):
    p50_ms: int
    p95_ms: int


class ScenarioMetric(BaseModel):
    """시나리오 번호별 집계. 같은 번호를 여러 번 돌렸으면 다 더한다."""

    code: str
    runs: int
    passed: int
    success_rate: float
    latency: Latency
    cost_usd: float
    llm_calls: int


class ScenarioMetrics(BaseModel):
    runs: int
    passed: int
    success_rate: float  # E2E 성공률(PRD 8장)
    latency: Latency
    cost_usd: float
    llm_calls: int
    by_scenario: list[ScenarioMetric]


class MatrixRow(BaseModel):
    """정답 상태 한 줄. counts의 키는 엔진이 낸 상태다."""

    expected: EligibilityStatus
    counts: dict[str, int]
    total: int


class EligibilityMatrix(BaseModel):
    """판정 정확도 3×3(PRD 8장). 가장 최근 시나리오 실행 묶음 기준이다."""

    run_started_at: datetime | None  # 그 묶음의 첫 실행 시각. 확인 줄이 없으면 null
    checks: int
    correct: int
    accuracy: float
    rows: list[MatrixRow]
    eligible_to_ineligible: int  # 핵심 목표: 0건
    ineligible_to_eligible: int  # 따로 추적한다


class Ratio(BaseModel):
    """나눈 값 하나. 분모가 0이면 rate는 null이다(0.0과 구분한다)."""

    numerator: int
    denominator: int
    rate: float | None


class MissingField(BaseModel):
    field: str
    count: int


class UndeterminedRate(Ratio):
    """판정 불가 비율. 지금 저장된 (사용자 × 활성 공고) 판정 기준이다(기간이 아니라 현재 상태)."""

    top_missing_fields: list[MissingField]  # 원인 항목 상위 3개


class ProductMetrics(BaseModel):
    """제품 지표 5개(PRD 8장). 목표치는 W6 베이스라인을 잰 뒤 정한다."""

    undetermined: UndeterminedRate
    profile_prompt: Ratio  # 즉석 입력 응답률: 입력창 노출 → 입력 완료
    prepare_conversion: Ratio  # 준비하기 전환율: 상세 조회 → 준비하기
    lms_connect: Ratio  # LMS 연결 완료율: 토큰 가이드 진입 → 검증 성공
    weekly_return: Ratio  # 주간 재방문율: 가입 다음 주에 1회 이상 접속


class Metrics(BaseModel):
    """응답 키는 from·to다(파이선에서 from은 예약어라 필드 이름만 다르다)."""

    model_config = ConfigDict(populate_by_name=True)

    from_date: date = Field(alias="from")  # 집계 기간(KST 날짜, 양 끝 포함)
    to_date: date = Field(alias="to")
    scenarios: ScenarioMetrics
    eligibility: EligibilityMatrix
    product: ProductMetrics


# POST /internal/eval/run


class EvalRunRequest(BaseModel):
    scenario_codes: list[str] | None = None  # 없으면 전부
    now: datetime | None = None  # 시계 고정. 없으면 기본값
    fixtures: Literal["recorded"] = "recorded"  # 지금은 녹화한 응답만


class EvalCheck(BaseModel):
    what: str
    expected: object
    actual: object
    ok: bool
    kind: str | None = None


class EvalScenarioResult(BaseModel):
    code: str
    title: str
    ok: bool
    latency_ms: int
    api_ms: float
    run_id: str | None
    cost_usd: float
    llm_calls: int
    checks: list[EvalCheck]
    error: str | None


class EvalRunResult(BaseModel):
    now: datetime
    priced_on: date | None  # 단가를 고른 날. 이 날짜가 다르면 비용끼리 비교하지 않는다
    scenarios: int
    passed: int
    success_rate: float
    latency: Latency
    cost_usd: float
    llm_calls: int
    results: list[EvalScenarioResult]
