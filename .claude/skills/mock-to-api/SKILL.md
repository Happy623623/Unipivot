---
name: mock-to-api
description: web/src/api/client.ts의 목 함수를 실제 FastAPI 호출로 바꿀 때 쓴다. 화면 코드는 그대로 두고 함수 안쪽만 apiFetch로 바꾸며, 목 모드도 계속 동작하게 남긴다.
---

# 목 함수를 실제 API로 바꾸기

1. **대상 확인.** `docs/Nextjs_이식_가이드.md`의 "목 함수 → 실제 API" 표에서 함수와 엔드포인트를 찾는다. `api/`에 그 엔드포인트가 있고 테스트가 통과하는지 먼저 확인한다. 없으면 `api-endpoint` 스킬부터 한다.
2. **목 구현 옮기기(처음 한 번).** `src/api/mockClient.ts`가 없으면 만들고, 바꿀 함수의 기존 목 구현을 같은 이름으로 옮긴다.
3. **교체.** `client.ts`의 함수는 이름·인자·반환 타입을 그대로 두고 `NEXT_PUBLIC_USE_MOCKS === "true"`면 `mockClient`를, 아니면 `apiFetch`를 부른다.
4. **비동기 작업.** 202와 `run_id`를 받는 API는 `waitForRun`으로 결과를 기다리고, 진행 단계는 화면이 쓰던 형태로 넘긴다.
5. **에러.** `ApiError.code`로 분기한다(API 명세 13장 "프론트 처리" 열). 문구는 `web/CLAUDE.md`의 문구 규칙을 따른다.
6. **검사.** `npm run typecheck`, `NEXT_PUBLIC_USE_MOCKS=true npm run build`가 통과하고, `NEXT_PUBLIC_USE_MOCKS=false`로 실제 API를 붙여 그 화면 흐름을 한 번 눌러 본다.
7. **표 갱신.** 이식 가이드 표에서 해당 줄 비고에 "실제 API 연결"을 적는다.
