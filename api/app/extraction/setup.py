"""설정(api/.env)으로 요건 추출 에이전트를 만든다. 배치 작업·학교 공지 링크·과목 공지·시나리오가 모두 여기서 만든다.

- `make_extractor`: 이미 있는 LLM 클라이언트로 만든다. 캐스케이드(EXTRACTION_CASCADE, O4)를 켰으면
  `CascadeAgent`(EXTRACTION_LITE_MODEL → EXTRACTION_MODEL), 아니면 `ExtractionAgent`(EXTRACTION_MODEL) 하나다.
  모델을 직접 주면(비교 실험·CLI의 --model) 캐스케이드를 쓰지 않고 그 모델 하나로 돈다.
- `build_agent`: 설정으로 Gemini 클라이언트까지 만든다(CLI·비교 실험).
"""

from collections.abc import Sequence

from app.config import Settings
from app.eligibility import Department
from app.engines import get_engine
from app.extraction.agent import ExtractionAgent, Extractor
from app.extraction.cascade import CascadeAgent
from app.extraction.models import Limits
from app.extraction.sources import PageFetcher
from app.llm import LlmClient
from app.llm.gemini import GeminiClient

ENGINE = "extract.requirements"


def make_extractor(
    llm: LlmClient,
    settings: Settings,
    departments: Sequence[Department] = (),
    *,
    fetch_page: PageFetcher | None = None,
    model: str | None = None,
    budget_s: float | None = None,
) -> Extractor:
    """요건 추출 에이전트. budget_s는 캐스케이드가 두 모델에 쓸 수 있는 초다(학생이 기다리는 링크 가져오기)."""
    limits = Limits(
        max_reads=settings.extraction_max_reads, max_tokens=settings.extraction_max_tokens
    )

    def agent(name: str) -> ExtractionAgent:
        return ExtractionAgent(
            llm,
            model=name,
            vision_model=settings.vision_model,
            departments=departments,
            limits=limits,
            fetch_page=fetch_page,
        )

    cascade = get_engine(ENGINE).cascade
    if model is not None or cascade is None or not getattr(settings, cascade.switch):
        return agent(model or settings.extraction_model)
    return CascadeAgent(
        agent(getattr(settings, cascade.first_model_setting)),
        agent(settings.extraction_model),
        on=cascade.on,
        budget_s=budget_s,
    )


def build_agent(
    settings: Settings,
    *,
    departments: Sequence[Department] = (),
    fetch_page: PageFetcher | None = None,
    model: str | None = None,
) -> Extractor:
    llm = GeminiClient(
        project=settings.google_cloud_project, location=settings.google_cloud_location
    )
    return make_extractor(llm, settings, departments, fetch_page=fetch_page, model=model)
