---
name: api-endpoint
description: API 명세에 있는 엔드포인트를 api/(FastAPI)에 추가하거나 고칠 때 쓴다. 명세 확인, 스키마, 저장소 SQL, 라우터, 테스트, 문서 대조 순서로 진행한다.
---

# API 엔드포인트 추가

1. **명세 확인.** `docs/API_명세_v0.4.md`에서 요청·응답 예시, 에러 코드, 기능 ID(F-xx)를 찾는다. 명세에 없으면 멈추고 무엇이 비었는지 보고한다.
2. **테이블 확인.** 쓸 테이블·컬럼·enum은 `supabase/migrations/`의 SQL이 기준이다(적용 순서 v07 → v08 → v09 → seed). 설계 의도와 제약 설명은 `docs/ERD_v0.9.md`를 본다. 컬럼이 없으면 새 마이그레이션이 필요하다고 보고하고 멈춘다.
3. **스키마.** `api/app/schemas/`에 요청·응답 모델을 만든다. 필드 이름은 명세, `web/src/types/api.ts`와 같게 한다.
4. **저장소.** `api/app/repositories/`에 SQL을 쓴다. `user_id` 조건을 빼먹지 않고, 값은 파라미터로 넘긴다.
5. **라우터.** `api/app/routers/`에 엔드포인트를 만들고 `app/main.py`에 등록한다. 인증은 `CurrentUserDep`, 에러는 `ApiError`. LLM·외부 호출이 있으면 `agent_run`으로 감싼다.
6. **테스트.** `tests/fakes.py`에 가짜 저장소 메서드를 추가하고 성공·인증 실패·대표 에러를 테스트한다. SQL이 복잡하면 `@pytest.mark.db` 테스트도 쓴다.
7. **검사.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`가 모두 통과해야 끝난다.
8. **보고.** 바꾼 파일, 명세와 다르게 한 점, 남은 `TODO`를 짧게 정리한다.
