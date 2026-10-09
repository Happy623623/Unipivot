"""설정(api/.env)으로 요건 추출 에이전트를 만든다. 배치 작업과 scripts/extract_notice.py가 쓴다."""

from collections.abc import Sequence

from app.config import Settings
from app.eligibility import Department
from app.extraction.agent import ExtractionAgent
from app.extraction.models import Limits
from app.extraction.sources import PageFetcher
from app.llm.gemini import GeminiClient


def build_agent(
    settings: Settings,
    *,
    departments: Sequence[Department] = (),
    fetch_page: PageFetcher | None = None,
    model: str | None = None,
) -> ExtractionAgent:
    llm = GeminiClient(
        project=settings.google_cloud_project, location=settings.google_cloud_location
    )
    limits = Limits(
        max_reads=settings.extraction_max_reads, max_tokens=settings.extraction_max_tokens
    )
    return ExtractionAgent(
        llm,
        model=model or settings.extraction_model,
        vision_model=settings.vision_model,
        departments=departments,
        limits=limits,
        fetch_page=fetch_page,
    )
