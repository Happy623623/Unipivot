"""엔진 등록부와 원문 확인 이유 코드(오케스트레이션 명세 v1 2장·3.1·3.3, O2).

엔진 하나 = 계약(입출력 타입·도구·상한)과 버전이 고정된 모듈 하나다. 실행 기록(agent_runs.engine·
engine_version·model·review_codes)과 엔진별 지표·평가가 등록부의 id로 묶인다.
"""

from app.engines.registry import ENGINES, EngineSpec, RetryPolicy, get_engine, model_name
from app.engines.review import ReviewCode, ReviewReason, review_codes, review_texts

__all__ = [
    "ENGINES",
    "EngineSpec",
    "RetryPolicy",
    "ReviewCode",
    "ReviewReason",
    "get_engine",
    "model_name",
    "review_codes",
    "review_texts",
]
