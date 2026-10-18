"""API가 쓰는 모델 클라이언트(요청마다 같은 것을 쓴다). 테스트는 get_llm을 가짜로 바꾼다."""

import logging
from typing import Annotated, Any

from fastapi import Depends, Request

from app.llm.gemini import GeminiClient
from app.llm.types import LlmClient

logger = logging.getLogger(__name__)


def llm_for(state: Any) -> LlmClient | None:
    """앱의 모델 클라이언트. 요청 밖(스케줄러)에서도 같은 것을 쓰려고 `app.state`를 직접 받는다.

    GOOGLE_CLOUD_PROJECT가 없거나 클라이언트를 만들지 못하면 None이다. 모델이 필요한 일만 실패한다.
    """
    if getattr(state, "llm", None) is None:
        settings = state.settings
        if not settings.google_cloud_project:
            return None
        try:
            state.llm = GeminiClient(
                project=settings.google_cloud_project, location=settings.google_cloud_location
            )
        except Exception:
            logger.exception("모델 클라이언트를 만들지 못했어요")
            return None
    return state.llm


def get_llm(request: Request) -> LlmClient | None:
    return llm_for(request.app.state)


LlmDep = Annotated[LlmClient | None, Depends(get_llm)]
