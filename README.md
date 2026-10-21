# UNIPIVOT — 학내 정보 에이전트

대학생이 장학금·청년정책·공모전 공고에 **지원할 수 있는지 판정**받고, **준비 일정**을 만들고, **LMS 과제·자료**를
챙기는 웹 서비스다. SW창업캡스톤(AOP) 과제로, LLM Tool Calling 기반 에이전트 MVP · 최종 데모 · 테스트 시나리오
측정(성공률·응답시간·비용)이 산출물이다.

- 공고는 세 길로 들어온다 — 저장한 학교 공지(명령), 온통청년 청년정책(매일 자동), 학생이 올린 포스터(화면)
- LLM은 **공고 원문에서 요건을 구조화**하는 데까지만 쓰고, **자격 판정은 코드**가 한다(`docs/판정엔진_규칙.md`)
- 모든 LLM·외부 호출은 실행 로그(`agent_runs`·`tool_calls`·`llm_calls`)에 남고, 그 로그로 지표를 센다

## 구조

| 폴더 | 내용 | 기준 |
| --- | --- | --- |
| `web/` | Next.js 16 + Tailwind 4 화면 | `docs/API_명세_v0.4.md` |
| `api/` | FastAPI(Python 3.12, uv) API·에이전트·정기 작업 | `docs/API_명세_v0.4.md` |
| `supabase/migrations/` | DB 스키마(파일 이름 순으로 적용) | `docs/ERD_v0.9.md` |
| `docs/` | 기준 문서 | 아래 순서 |

기준 문서는 충돌하면 위가 이긴다: `docs/API_명세_v0.4.md`(계약) → `docs/ERD_v0.9.md`(DB) → `docs/PRD_v0.9.md`(기능·우선순위)
→ `docs/판정엔진_규칙.md`.

## 시작하기

필요한 것: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 22, Supabase 프로젝트(Postgres + Google 로그인),
[Supabase CLI](https://supabase.com/docs/guides/cli).

    # 1. DB — Supabase 프로젝트에 마이그레이션을 적용한다
    npx supabase link --project-ref <ref>
    npx supabase db push

    # 2. API
    cd api
    cp .env.example .env            # 값을 채운다(아래 "설정")
    uv sync
    uv run uvicorn app.main:app --reload     # http://localhost:8000, 문서는 /docs

    # 3. 화면
    cd web
    cp .env.local.example .env.local
    npm ci
    npm run dev                     # http://localhost:3000

`NEXT_PUBLIC_USE_MOCKS=true`면 화면이 API 없이 목데이터로 뜬다(상태 미리보기 패널 포함). 실제 API를 붙이면 `false`.

### 설정 (`api/.env`)

| 값 | 쓰는 곳 |
| --- | --- |
| `DATABASE_URL` · `SUPABASE_URL` · `SUPABASE_JWT_SECRET` | DB, 로그인 토큰 검증 |
| `TOKEN_ENCRYPTION_KEY` | Google·LMS 토큰 암호화 |
| `GOOGLE_CLOUD_PROJECT` | Gemini(요건 추출·공지 분류). 없으면 모델이 필요한 일만 실패한다 |
| `GOOGLE_OAUTH_CLIENT_ID` · `GOOGLE_OAUTH_CLIENT_SECRET` | Google 캘린더(증분 승인) |
| `SUPABASE_SECRET_KEY` · 버킷 | 포스터·공지 첨부 파일 저장. 값은 API Keys의 Secret keys(`sb_secret_…`). 예전 이름 `SUPABASE_SERVICE_ROLE_KEY`도 읽는다 |
| `YOUTH_API_KEY` | 온통청년 수집 |
| `VAPID_PRIVATE_KEY` · `VAPID_SUBJECT` | 웹 푸시(`uv run python -m app.push.keys`로 만든다) |
| `INTERNAL_API_KEY` | `/internal/*` 서비스 키 |
| `SCHEDULER_ENABLED` | 서버 안 정기 작업(아래) |

키·`.env`·`.env.local`은 레포에 넣지 않는다. 예시는 `.env.example`에만 적는다.

## 정기 작업

`SCHEDULER_ENABLED=true`면 서버가 직접 돈다(`api/app/scheduler.py`). 같은 일을 `POST /internal/jobs/*`로 손으로
부를 수도 있다(둘은 같은 함수다). 워커는 하나로 둔다.

| 작업 | 주기 |
| --- | --- |
| 알림 발송(알림함 → 웹 푸시) | 5분 |
| LMS 동기화(과목·과제·자료·공지) | 30분 |
| 공고 알림 예약(새 적격·마감 임박·정보 필요) | 매일 KST 08:30 |
| 온통청년 정책 수집 | 매일 KST 04:00 |

## 명령 (`api` 폴더에서)

    uv run python -m app.youth.cli fetch              # 온통청년 정책 수집(정기 작업과 같은 함수)
    uv run python -m app.crawl.cli import <공지 폴더>   # 저장한 학교 공지 넣기 + 요건 추출
    uv run python -m app.eval.cli                      # 테스트 시나리오 전부 실행(시험용 DB에서만)
    uv run python -m app.eval.cli --out eval_baseline.json   # 베이스라인 저장(결과 JSON은 레포에 넣지 않는다)
    uv run python -m app.push.keys                     # 웹 푸시 VAPID 키 만들기

## 검사

| 위치 | 명령 |
| --- | --- |
| api | `uv run ruff check . && uv run ruff format --check . && uv run pytest` |
| web | `npm run typecheck && npm run build` |

`@pytest.mark.db` 테스트는 `DATABASE_URL`이 있을 때만 돈다. CI는 Postgres 컨테이너에 마이그레이션을 적용해서
돌리고, 실제 Supabase DB로는 돌리지 않는다. 테스트 시나리오(지금 18개)는 `python -m app.eval.cli`로 돌리며
모델·Google·파일 저장소·LMS는 녹화한 응답을 쓴다. 측정 결과는 `docs/베이스라인.md`에 절을 더해 비교한다.

## 작업 방식

작업 하나 = 브랜치 하나 = PR 하나. 문서에 없는 엔드포인트·필드·컬럼을 만들지 않고, 필요하면 기준 문서를 같은
PR에서 고친다.
