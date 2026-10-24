# UNIPIVOT api 이미지 (docs/배포_절차.md). Cloud Run이 `gcloud run deploy --source .`로 이 파일을 빌드한다.
# 로컬 PC에는 Docker가 없어도 된다 — 빌드는 Cloud Build에서 돈다.
FROM python:3.12-slim

# uv는 uv.lock 그대로 설치하는 데만 쓴다(버전 고정)
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

# 바이트코드를 미리 만들어 처음 뜨는 시간을 줄인다. 파이썬은 이미지의 것만 쓴다(내려받지 않음)
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성을 먼저 깔아 두면 코드만 바뀐 빌드는 이 층을 다시 쓴다. --locked: uv.lock이 pyproject와 안 맞으면 멈춘다
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app

# 루트가 아닌 사용자로 돈다. 앱은 디스크에 쓰지 않는다
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin unipivot
USER unipivot

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080

# 워커는 하나다(서버 안 스케줄러, app/scheduler.py). Cloud Run이 PORT를 준다.
# --proxy-headers: 앞단(Cloud Run)이 붙인 https 정보를 믿는다(만드는 주소가 http로 나가지 않게)
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8080}\" --proxy-headers --forwarded-allow-ips '*'"]
