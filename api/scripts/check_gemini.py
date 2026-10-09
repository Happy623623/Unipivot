"""Gemini 플랫폼(구 Vertex AI) 연결 확인. api 폴더에서 실행한다.

    uv run --no-project --with google-genai python scripts/check_gemini.py <프로젝트 ID>

먼저 gcloud auth application-default login 으로 로그인해 둔다. 크레딧에서 1원도 안 되는 금액이 빠진다.
"""

import sys

from google import genai
from google.genai import types

client = genai.Client(enterprise=True, project=sys.argv[1], location="global")
response = client.models.generate_content(
    model="gemini-3.8-flash",
    contents="연결 확인이야. '연결됨' 한 단어로만 답해.",
    config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
    ),
)
usage = response.usage_metadata
print(response.text)
print(
    f"입력 {usage.prompt_token_count} · 출력 {usage.candidates_token_count}"
    f" · 생각 {usage.thoughts_token_count or 0} 토큰"
)
