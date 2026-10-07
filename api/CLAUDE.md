# api — FastAPI

기준 문서는 `docs/API_명세_v0.4.md`(계약), `docs/ERD_v0.9.md`(DB), `docs/PRD_v0.9.md`(기능·우선순위), `docs/판정엔진_규칙.md`(판정 규칙)다.

## 구조

- `app/main.py` 앱·CORS·라우터 등록, `app/config.py` `.env` 설정
- `app/errors.py` API 명세 13장 에러 형식, `app/auth.py` Supabase JWT 검증(`CurrentUserDep`)
- `app/db.py` psycopg 풀 2개(요청용 트랜잭션 풀, 실행 로그용 autocommit 풀)
- `app/crypto.py` 토큰 암호화, `app/agent_log.py` 에이전트 실행 로깅
- `app/schemas/` 요청·응답 모델, `app/repositories/` SQL, `app/routers/` 엔드포인트
- `app/services/` 판정 엔진·수집·요건 추출 같은 에이전트 로직(추가 예정)

## 규칙

- 경로는 `/api/v1` 아래, 필드 이름은 API 명세 그대로(snake_case). 응답 모델 이름은 `web/src/types/api.ts`와 같게 한다.
- 에러는 `ApiError(status, code, message, details)`만 던진다. `code`는 명세 13장 표에 있는 것만 쓰고, 새 코드는 명세에 먼저 추가한다. 메시지는 해요체로, 사용자가 무엇을 하면 되는지 쓴다.
- 사용자 API는 모두 `CurrentUserDep`으로 인증한다. 서버는 서비스 권한으로 DB에 붙어 RLS가 막아주지 않으므로, SQL에는 항상 `user_id` 조건을 건다.
- SQL은 `repositories/`에만 쓴다. 값은 항상 파라미터로 넘기고, 동적 컬럼 이름은 `psycopg.sql.Identifier`로 만든다.
- LLM·외부 도구 호출은 `agent_run` → `run.tool` → `run.record_llm` 안에서만 한다. 로그용 autocommit 연결(`get_log_conn`)을 넘겨야 실패한 실행도 남는다.
- 토큰은 `crypto.encrypt`로 암호화해 저장하고, 로그·응답·`tool_calls.input`에 넣지 않는다(`scrub`가 키 이름으로 한 번 더 지운다).
- 오래 걸리는 작업(포스터 추출, 준비하기 등)은 202와 `run_id`로 응답하고, 진행은 `GET /runs/{id}`로 보여준다(명세 2장).
- 시간은 `timestamptz`(UTC)로 저장한다. 날짜 계산(D-day, 만 나이)은 KST 기준이다.
- 자격 판정은 코드로 한다. LLM은 요건 추출까지만 쓴다. 판정 규칙은 `docs/판정엔진_규칙.md`를 따르고, 프로필 값은 LLM 프롬프트와 `tool_calls.input`에 넣지 않는다.

## 테스트

- 단위 테스트는 DB·네트워크 없이 돈다. 저장소는 `tests/fakes.py`의 가짜로 바꿔 끼우고, LLM은 가짜 응답으로 대체한다.
- `@pytest.mark.db` 테스트는 `DATABASE_URL`이 있을 때만 돈다. CI는 Postgres 컨테이너에 마이그레이션을 적용해서 돌린다. 실제 Supabase DB로는 돌리지 않는다.
- 새 엔드포인트마다 성공, 인증 실패, 대표 에러를 하나 이상 테스트한다.
- Supabase 트랜잭션 풀러(6543)에서도 동작하도록 `prepare_threshold=None`을 유지한다.

## DB 변경

- 테이블·컬럼 변경은 `supabase/migrations/`에 새 파일로만 한다. 이미 적용한 파일은 고치지 않는다.
- 적용 순서는 v07 → v08 → v09 → seed다. 같은 PR에서 `docs/ERD_v0.9.md`와 CI의 DB 테스트를 함께 고친다.
