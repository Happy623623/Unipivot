# UNIPIVOT(가칭) — 학내 정보 에이전트

대학생이 장학금·청년정책·공모전 공고에 지원할 수 있는지 판정받고, 준비 일정을 만들고, LMS 과제·자료를 챙기는 웹 서비스다. SW창업캡스톤(AOP) 과제라 LLM API와 Tool Calling 기반 에이전트 MVP, 최종 데모, 테스트 시나리오 측정(성공률·응답시간·비용)이 필수 산출물이다.

## 구조

- `web/` Next.js 16 + Tailwind 4 화면. 규칙은 `web/CLAUDE.md`
- `api/` FastAPI(Python 3.12, uv) API와 에이전트. 규칙은 `api/CLAUDE.md`
- `supabase/migrations/` DB 마이그레이션. `docs/ERD_v0.8.md` 7장의 v0.7 DDL → v0.8 마이그레이션 순서
- `docs/` 기준 문서

## 기준 문서 (충돌하면 위가 이긴다)

1. API 계약: `docs/API_명세_v0.3.md`
2. DB: `docs/ERD_v0.8.md`
3. 기능·우선순위: `docs/PRD_v0.8.md` (기능 ID F-xx)
4. 구현 기록: `docs/Nextjs_이식_가이드.md`, `docs/온보딩_구현.md`, `docs/API_뼈대_구현.md`

v0.7·v0.2 원본과 변경분 문서는 `docs/archive/`에 있다. 이력 확인용이고 기준이 아니다.

문서에 없는 엔드포인트·필드·컬럼을 만들지 않는다. 꼭 필요하면 먼저 기준 문서를 고치고 같은 PR에서 코드와 함께 올린다.

## 명령

| 위치 | 명령 |
| --- | --- |
| web | `npm run dev` · `npm run typecheck` · `npm run build` |
| api | `uv run uvicorn app.main:app --reload` · `uv run pytest` · `uv run ruff check .` · `uv run ruff format .` |
| DB | 새 변경은 `supabase/migrations/`에 새 파일로. 이미 적용한 파일은 고치지 않는다 |

## 작업 방식

- 작업 하나 = 브랜치 하나 = PR 하나. 브랜치는 `feat/F-xx-짧은설명`, 커밋과 PR 제목에 기능 ID를 붙인다.
- 계획을 먼저 세우고 범위를 확인받은 뒤 수정한다. 기본 크기는 "API 하나 + 목 함수 하나 교체 + 테스트"다.
- 끝내기 전에 바꾼 쪽의 검사를 통과시킨다(web: typecheck·build, api: ruff·pytest). 통과하지 못하면 커밋하지 않고 원인을 보고한다.
- 반복 절차는 스킬을 쓴다. 새 엔드포인트는 `api-endpoint`, 목 함수를 실제 API로 바꿀 때는 `mock-to-api`.

## 지켜야 할 것

- `.env`·`.env.local`은 읽거나 커밋하지 않는다. 예시는 `.env.example`에만 적는다.
- Google·LMS 토큰은 암호화해 저장하고, 응답·로그·`tool_calls.input`에 남기지 않는다.
- 자격 판정은 코드로 한다. LLM은 공고 원문에서 요건을 구조화하는 데까지만 쓴다.
- LLM과 외부 도구 호출은 모두 `api/app/agent_log.py`의 실행 로깅을 거친다. AOP 지표가 여기서 나온다.
- 시간은 DB에 UTC로 저장하고 화면에는 KST로 보여준다.
- 탈퇴하면 사용자 데이터를 지운다. 공유 포스터 공고의 업로더는 가려서(김\*지) 보여준다.
