# 계정 화면 실제 API 연결 — S1-1·S1-2 웹 (로그인·온보딩·설정·캘린더 연결)

> 📝 기준: PRD v0.9 F-01·F-02·F-04·F-06 · API 명세 v0.4 4·13장 · `온보딩_구현.md` · `Nextjs_이식_가이드.md` W4 · 스킬 `mock-to-api` · 2026-10-11
>
> 함께 보는 파일: `온보딩_구현.md`(Supabase·Google 설정 체크리스트), `Nextjs_이식_가이드.md`. 모두 레포에 들어가 있어야 한다

웹의 계정 화면을 목데이터에서 실제 FastAPI로 바꿨다. 목 모드(`NEXT_PUBLIC_USE_MOCKS=true`)는 전처럼 돈다.
- **온보딩:** 동의, 프로필 4단계, 소득 선택 동의, 학과 목록(48개)을 실제 API로 저장하고 읽는다.
- **설정:** 프로필 수정, 소득 동의 켜기·철회, Google Calendar 연결을 실제로 한다.
- **로그인 세션:** 401이면 로그인 화면으로 보내고, 세션이 만료됐으면 이유를 보여 준다.
- **앱 열기 기록:** 동의를 마친 사용자가 앱을 열면 `app_open`을 남긴다.

실제 모드로 붙여 보다 찾은 문제 4가지도 같이 고쳤다.
1. 서버 500 응답에 CORS 헤더가 없어 브라우저가 "서버에 연결하지 못했어요"로 보였다(API).
2. 캘린더 연결을 Google 화면에서 취소하면 로그인 오류 화면으로 갔다.
3. 연결 뒤 Google refresh token(캘린더 권한)이 브라우저 쿠키에 남았다.
4. Google에서 다른 계정을 고르면 그 계정으로 로그인이 바뀌었다.

공고 피드·상세·플래너·포스터는 아직 목이다. 피드·상세는 다음 PR에서 바꾼다. DB 마이그레이션은 없다.

새 파일 7개, 바꾸는 파일 23개, 지우는 파일 2개다. API는 미들웨어 하나와 테스트 하나를 더했다(레포 전체 Linux `321 passed, 34 skipped`, DB를 붙이면 `355 passed`). 웹은 `tsc`와 `next build`(목 모드, 실제 모드, 환경 변수 없이)를 통과했다. 실제 API·Postgres·가짜 Supabase Auth로 Playwright 99단계(실제 모드)와 18단계(목 모드)를 눌렀다. 콜백의 새 동작 4가지를 하나씩 되돌리면 모두 테스트에 걸렸다. 검토 에이전트 2개가 따로 봤고, 제안을 받아들였다.

## 정한 것

| 항목 | 정한 것 | 이유 |
| --- | --- | --- |
| 파일 나누기 | 계정 함수는 `accountClient.ts`, LMS 함수는 `lmsClient.ts`에 두고 `client.ts`가 다시 내보낸다. 목 구현은 `mockClient.ts` 한 곳에 모은다(`settingsClient.ts`·`notificationClient.ts`를 합침). 실제 호출과 오류 도구는 `http.ts`에 둔다 | `client.ts`가 400줄이 됐다(규칙 300줄). 화면의 import는 그대로 `@/api/client`다. 다음 PR의 피드·상세가 `client.ts`에 들어갈 자리도 남는다 |
| API가 아직 없는 기능(실제 모드) | 목데이터를 보여 주지 않는다. 알림은 빈 목록이다. LMS는 "연결되지 않음"으로 보이고, 연결 창은 준비 중이라고 안내한다. 온보딩 끝의 LMS 단계는 건너뛴다. 탈퇴 창은 준비 중이라고 먼저 알린다. 알림 설정(P1) 구역은 숨긴다 | 실제 사용자에게 가짜 값이 저장되는 것처럼 보이면 안 된다. 기능마다 `…_READY` 상수와 `TODO(api)`를 두어 API가 생기면 지운다 |
| 오류 문구 | 서버가 준 문구(13장)는 그대로 쓴다. 서버 내부 오류(5xx)와 알 수 없는 오류는 화면이 정한 문구를 쓴다(`errorMessage`). 422 항목 오류는 입력란 아래에 보인다(`fieldErrors`). 서버가 준 영어 검사 문구는 "값을 확인해 주세요."로 바꾼다 | API 13장 "프론트 처리" 열, `web/CLAUDE.md` 문구 규칙 |
| 동의가 빠졌을 때(403) | `CONSENT_REQUIRED`의 `details.consent`가 `terms_privacy`면 온보딩 동의 단계로 보낸다. `income_info`면 소득 단계에서는 동의를 다시 묻고, 다른 단계에서는 소득 값을 빼고 다시 저장하게 한다. 설정은 내 정보를 다시 받아 소득 입력란을 닫는다 | 다른 탭에서 동의를 철회한 경우다. 온보딩도 동의 없이는 소득 값을 보내지 않는다(설정과 같다) |
| 프론트 전용 오류 코드 | `NETWORK_ERROR`, `CONFIG_MISSING`, `NOT_READY`, `CALENDAR_CONNECT_FAILED`, `RUN_TIMEOUT`. 응답을 받지 못하면 기기가 오프라인일 때 인터넷을, 아니면 서버를 안내한다 | 서버 코드와 섞이지 않게 `http.ts` 머리말에 적는다 |
| 로그인 만료(401) | 세션이 있었으면 `/login?error=session`("로그인이 만료됐어요. 다시 로그인해 주세요."), 없었으면 그냥 `/login`으로 보낸다. 이동하는 동안 화면은 오류 없이 기다린다 | 처음 온 사람에게 "만료됐어요"를 보이지 않는다 |
| 캘린더 연결(설정) | "연결하기"를 누르면 Google 화면으로 간다(증분 승인). 콜백이 토큰을 저장하고 `/settings?calendar=connected`(또는 `error`)로 돌려보낸다. 결과 안내는 한 번만 보이고 주소의 쿼리를 지운다. 미연결 문구는 "연결되지 않음"이다 | `GET /me`는 연결 여부만 준다. 처음인지 만료인지 알 수 없다 |
| 플래너의 캘린더 줄 | "연결 만료" 문구와 화면 값만 바꾸던 "다시 연결" 버튼을 없앴다. 미연결이면 "설정에서 연결" 버튼으로 설정에 보낸다 | 연결은 결과 안내가 있는 설정 한 곳에서 한다 |
| 콜백: 취소 | 캘린더 연결 중 Google 화면에서 취소하면 로그인을 그대로 두고 원래 화면에 실패 안내를 보인다. 코드 교환이 실패해도 같다 | 로그인한 사람을 로그인 오류 화면으로 보내지 않는다 |
| 콜백: Google 토큰 | 코드 교환 직후 세션에 Google 토큰(`provider_token`·`provider_refresh_token`)이 실려 온다. 콜백은 백엔드에 토큰을 넘긴 뒤 세션을 한 번 새로 받아, Google 토큰이 없는 세션으로 쿠키를 바꾼다. 로그인 콜백도 같다. 새로 받지 못하면 그 기기에서 로그아웃하고 로그인 화면으로 보낸다 | @supabase/ssr은 세션 전체를 자바스크립트가 읽을 수 있는 쿠키(최대 400일)에 둔다. 캘린더 권한이 있는 refresh token을 거기 두면 안 된다(루트 `CLAUDE.md`) |
| 콜백: 다른 계정 | 연결할 때 `login_hint`로 지금 계정을 Google 계정 선택에 미리 고른다. 그래도 다른 계정을 고르면 토큰을 저장하지 않고, 바뀐 세션을 이 기기에서만 지운 뒤 로그인 화면에서 안내한다. 교환 전 사용자 확인은 쿠키를 바꾸지 않는 클라이언트로 한다 | 개인 계정과 학교 계정을 같이 쓰는 학생이 많다. 그대로 두면 새 계정으로 온보딩이 다시 뜬다 |
| 서버 500 | API에 `UnhandledErrorMiddleware`를 더해 처리하지 못한 예외의 500을 CORS 안쪽에서 보낸다. 예외는 다시 던져 로그는 전과 같다 | Starlette는 이런 500을 CORS 밖에서 만들어 헤더가 없다. 브라우저는 응답을 읽지 못하고 연결 실패로 본다 |
| `app_open` | 동의를 마친 사용자가 앱(사이드바가 있는 화면)을 열 때 한 번 보낸다. 서버가 KST 하루 1건만 남긴다 | 동의 전에는 사용 기록을 남기지 않는다. `profile_prompt_shown`은 공고 상세를 붙일 때, `lms_guide_opened`는 LMS 연결 작업 때 붙인다 |
| HY-in 재학생 인증 | 설정에서 숨긴다 | PRD F-06(P2), API 부록 "프론트 반영 목록" |
| 프로필 입력 확인 | 정수 항목(마친 학기 수, 병역 복무 개월 수, 기준 중위소득 %)에 소수를 넣으면 "소수점 없이 입력해 주세요."를 보인다. 시·군·구는 40자까지만 입력된다 | 서버 검사와 같게 한다. 서버 영어 문구가 "값을 확인해 주세요."로만 보이지 않게 |
| 타입 | `ProfileUpdateResponse`(서버 응답 모델과 같은 이름), `ClientEvent`를 더한다. LMS·강의자료 타입은 `types/lms.ts`로 옮기고 `types/api.ts`가 다시 내보낸다 | `types/api.ts`가 300줄을 넘었다. 공고 타입을 v0.4에 맞추는 다음 PR에서 더 늘어난다 |

### 실제 모드에서 화면별로

| 화면 | 실제 API | 아직 목이거나 준비 중 |
| --- | --- | --- |
| 로그인 | 세션 만료·다른 계정 안내 | — |
| 온보딩 | `GET /me`, `GET`·`PATCH /me/profile`, `POST`·`PATCH /me/consents`, `GET /meta/departments` | 마지막 LMS 단계는 건너뛴다 |
| 홈 | 인사말의 이름(`GET /me`) | 공고 목록(다음 PR) |
| 공고 상세 | 캘린더 연결 여부 | 상세·준비하기(다음 PR과 그 뒤) |
| 플래너 | 캘린더 연결 줄 | 할 일 |
| 학업 | — | "연결되지 않음", 연결 창은 준비 중 안내, 과목 상세는 준비 중 오류 |
| 설정 | 입력 개수, 프로필 수정, 소득 동의, 캘린더 연결 | 알림 설정 숨김, 탈퇴 준비 중 |
| 헤더 알림 | — | 빈 목록 |

### 바뀐 문구

| 곳 | 문구 |
| --- | --- |
| 로그인(세션 만료) | 로그인이 만료됐어요. 다시 로그인해 주세요. |
| 로그인(다른 계정) | 캘린더를 연결할 때 다른 Google 계정을 골랐어요. 처음 쓰던 계정으로 다시 로그인한 뒤 연결해 주세요. |
| 응답을 받지 못함 | 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요. (오프라인이면) 인터넷에 연결되어 있지 않아요. 연결을 확인하고 다시 시도해 주세요. |
| 설정 캘린더 | 연결되지 않음. 연결하면 준비 일정을 캘린더에도 넣을 수 있어요. · 버튼 "연결하기"(누르면 "Google로 이동 중") |
| 설정 캘린더 결과 | Google Calendar를 연결했어요. · Google Calendar를 연결하지 못했어요. 연결하기를 다시 눌러 주세요. |
| 플래너 캘린더 줄 | Google Calendar 연결 안 됨 · 설정에서 연결하면 준비 일정과 마감일을 Google Calendar에 넣을 수 있어요. · 버튼 "설정에서 연결" (전: "Google Calendar 연결 만료", "다시 로그인해서 연결해 주세요", "다시 연결") |
| 준비 일정 결과의 캘린더 | 설정에서 Google Calendar를 연결하면 함께 넣을 수 있어요 (전: 캘린더를 다시 연결해야 해요) |
| LMS 연결 창(실제 모드) | LearningX 연결은 아직 준비 중이에요. 준비되면 이 화면에서 과제와 새 강의자료를 바로 볼 수 있어요. |
| 탈퇴 창(실제 모드) | 탈퇴는 아직 준비 중이에요. 준비되면 이 화면에서 바로 탈퇴할 수 있어요. |
| 온보딩(소득 동의가 꺼짐) | 소득·수급 정보 동의가 꺼져 있어요. 소득 정보는 빼고 저장하니 다시 눌러 주세요. |
| 정수 항목 | 소수점 없이 입력해 주세요. |
| 소득 동의 바꾸기 | 동의를 바꾸지 못했어요. 잠시 후 다시 눌러 주세요. · (바꿨는데 화면을 못 불러옴) 동의는 바꿨어요. 화면을 새로 고치면 바뀐 내용이 보여요. |

## 레포에 넣는 법

마이그레이션이 없어서 `supabase db push`는 하지 않는다.

```text
계정 화면 실제 API 연결(S1-1·S1-2 웹)을 넣자. docs/계정API연결_구현.md를 docs/에 넣었어.
1. main을 최신으로 받고 feat/F-02-account-api 브랜치를 만들어. 아래 2번의 바꾸는 파일·지우는 파일 중에 a31345f 뒤로 main에서 바뀐 것이 있으면(git log --oneline a31345f..main -- <파일>) 바꾸기 전에 멈추고 알려줘.
2. 문서 "코드"의 파일 30개를 문서 내용으로 통째로 만들거나 바꾸고, 2개는 지워. 내용은 고치지 마.
   새 파일 7개: web/src/api/http.ts, web/src/api/accountClient.ts, web/src/api/lmsClient.ts, web/src/api/mockClient.ts, web/src/components/ConnectedServices.tsx, web/src/components/NotificationSettings.tsx, web/src/types/lms.ts
   바꾸는 파일 23개: api/app/errors.py, api/app/main.py, api/tests/test_api.py, web/src/api/client.ts, web/src/types/api.ts, web/src/app/(auth)/login/page.tsx, web/src/app/auth/callback/route.ts, web/src/lib/supabase/server.ts, web/src/lib/googleCalendar.ts, web/src/screens/Onboarding.tsx, web/src/lib/profileFields.ts, web/src/components/profile/ProfileFieldInput.tsx, web/src/components/ProfileForm.tsx, web/src/app/(app)/settings/page.tsx, web/src/screens/Settings.tsx, web/src/components/IncomeConsentSetting.tsx, web/src/components/AppFrame.tsx, web/src/components/LmsConnectModal.tsx, web/src/app/(app)/planner/page.tsx, web/src/screens/Planner.tsx, web/src/components/OpportunityPreparation.tsx, web/CLAUDE.md, .claude/skills/mock-to-api/SKILL.md
   지우는 파일 2개(git rm): web/src/api/settingsClient.ts, web/src/api/notificationClient.ts
   .env와 .env.local은 읽거나 고치지 마.
3. 문서 "PRD·ERD·API에 반영하기"의 요청도 이 브랜치에서 해.
4. web에서 npm ci, npm run typecheck, npm run build를 돌려.
5. api에서 uv sync, uv run ruff check ., uv run ruff format --check ., uv run pytest를 돌려. 320 passed, 35 skipped가 나와야 해.
6. 통과하면 커밋하고 PR을 열어. 제목은 "feat(F-02): 계정 화면을 실제 API에 연결 (온보딩·설정·캘린더 연결, S1-1·S1-2 웹)"이고, 설명에 새로 만든·바꾼·지운 파일, 검사 결과, 문서에서 건너뛴 항목을 적어.
7. gh pr checks --watch로 CI를 기다려. web·api 작업이 모두 통과하고 api 로그에 "355 passed"가 있으면 squash로 합치고 브랜치를 지워. 다르면 합치지 말고 무엇이 다른지 알려줘.
```

- [ ] api: Windows·macOS `320 passed, 35 skipped`, Linux `321 passed, 34 skipped`. 테스트 1개를 더했다
- [ ] PR CI의 api 작업은 마이그레이션까지 적용한 DB로 `355 passed`, web 작업은 typecheck·build 통과. 환경 변수 없이 빌드해도 된다(CI와 같은 조건으로 확인함)

## 합친 뒤 실제로 눌러 보기

Google 로그인 설정을 먼저 마친다(`온보딩_구현.md` "Supabase·Google 설정"). 특히 두 가지를 확인한다.
- Supabase Redirect URLs에 `http://localhost:3000/auth/callback**`이 있다. 끝의 `**`가 없으면 캘린더 연결이 Site URL로 떨어진다
- Google OAuth 동의 화면에 `calendar.events` 범위가 있고, 쓸 Google 계정이 테스트 사용자로 들어가 있다

`api/.env`에는 `DATABASE_URL`, `SUPABASE_URL`(새 프로젝트는 JWKS로 검증) 또는 `SUPABASE_JWT_SECRET`(레거시 HS256), `TOKEN_ENCRYPTION_KEY`, `CORS_ORIGINS=["http://localhost:3000"]`를 둔다. `TOKEN_ENCRYPTION_KEY`가 없으면 캘린더 연결이 실패한다. `web/.env.local`에는 `NEXT_PUBLIC_USE_MOCKS=false`, `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1`, Supabase 주소와 anon 키를 둔다. 터미널 두 개에서 `api`는 `uv run uvicorn app.main:app --reload`, `web`은 `npm run dev`를 띄운다.

- [ ] `/login`에서 Google로 시작하기. Google 화면에 캘린더 권한이 없어야 한다. 처음이면 온보딩 동의 단계가 나온다
- [ ] 필수 두 항목만 동의하고 4단계를 저장한다. 학과는 48개다. 소득 단계 앞에서 "소득 정보도 입력할까요?"가 나오고, 끝나면 LMS 단계 없이 홈으로 간다
- [ ] 설정에서 입력 개수가 맞는지, HY-in·알림 구역이 없는지 본다. 캘린더 "연결하기" → Google 화면에 캘린더 권한이 나온다 → 돌아와 "Google Calendar를 연결했어요."가 보인다
- [ ] 레포 루트 PowerShell에서 아래를 돌려 결과를 붙여 준다. 이름·이메일·토큰은 나오지 않는다

```powershell
[Console]::OutputEncoding = [Text.Encoding]::UTF8
npx supabase db query --linked --output-format json "select p.consent_version, p.department is not null as has_department, p.income_info_agreed_at is not null as income_consent, (select count(*) from oauth_tokens t where t.user_id = p.id and t.refresh_token like 'gAAAAA%') as encrypted_calendar_tokens, (select count(*) from usage_events e where e.user_id = p.id and e.event = 'app_open') as app_opens from profiles p order by p.created_at desc limit 1" | Set-Clipboard
```

`encrypted_calendar_tokens`가 1이면 토큰이 암호화돼 저장된 것이다. 로그인한 뒤에도 "로그인이 만료됐어요"가 반복되면 `api/.env`의 토큰 검증 설정(`SUPABASE_URL` 또는 `SUPABASE_JWT_SECRET`)이 프로젝트와 맞지 않는 것이다.

## 구조

```text
api/app/errors.py, main.py              처리하지 못한 예외의 500에도 CORS 헤더(UnhandledErrorMiddleware, CORS 안쪽)
web/src/api/
  http.ts            (새) apiFetch(401 처리, 응답 못 받음), USE_MOCKS·notReady, errorMessage·fieldErrors·consentRequired, waitForRun
  client.ts          화면이 쓰는 함수의 입구. 공고·플래너·포스터(아직 목) + 계정·LMS·오류 도구를 다시 내보냄
  accountClient.ts   (새) 내 정보·프로필·동의·학과·캘린더 연결·사용 기록·알림 설정·알림·탈퇴
  lmsClient.ts       (새) LMS 연결·과목·새 소식·강의자료(실제 모드는 연결 안 됨·준비 중)
  mockClient.ts      (새) 목 구현과 목 응답 도구(settingsClient·notificationClient를 합침)
web/src/types/api.ts, lms.ts            ProfileUpdateResponse·ClientEvent, LMS 타입 분리
web/src/app/auth/callback/route.ts      취소·다른 계정·Google 토큰 빼기·교환 실패 처리
web/src/lib/supabase/server.ts          쿠키를 바꾸지 않는 확인용 클라이언트
web/src/lib/googleCalendar.ts           login_hint
web/src/screens/Onboarding.tsx          서버 오류 표시, 403 동의 처리, 소득 값은 동의했을 때만, LMS 단계 건너뛰기
web/src/screens/Settings.tsx            프로필 저장 오류, 탈퇴 준비 중, HY-in·알림 구역 숨김
web/src/components/
  ConnectedServices.tsx    (새) 설정의 캘린더 연결과 결과 안내, LMS 상태·해제
  NotificationSettings.tsx (새) 설정의 알림 구역(P1, 목 모드에서만)
  ProfileForm.tsx, profile/ProfileFieldInput.tsx, IncomeConsentSetting.tsx  서버 항목 오류, 40자 제한, 동의 오류
  AppFrame.tsx, LmsConnectModal.tsx, OpportunityPreparation.tsx           app_open, LMS 준비 중, 캘린더 문구
web/src/app/(app)/settings/page.tsx     ?calendar= 결과를 한 번 읽고 지움
web/src/app/(app)/planner/page.tsx, screens/Planner.tsx   캘린더 줄 → 설정으로
web/src/lib/profileFields.ts            정수 확인, 시·군·구 40자
```

## 확인한 것

| 검사 | 결과 |
| --- | --- |
| api `ruff check`·`ruff format --check` | 통과 |
| api `pytest` | Linux `321 passed, 34 skipped`. CI처럼 마이그레이션과 스키마 점검을 적용한 Postgres 16으로 `355 passed` |
| web `tsc --noEmit` | 통과 |
| web `next build` | 목 모드, 실제 모드, 환경 변수 없이(CI) 모두 통과. 11개 라우트 |
| 바꾼 파일 줄 수 | 모두 300줄 이하(가장 긴 파일 `types/api.ts` 247줄) |

테스트 1개를 더했다. `test_unexpected_error_keeps_cors`는 처리하지 못한 예외가 13장 형식의 500이고 CORS 헤더가 붙는지, 다른 오류(401)에도 그대로 붙는지 본다.

실제 모드는 샌드박스에서 끝까지 눌러 봤다. 빈 Postgres에 마이그레이션을 모두 적용하고, API는 uvicorn(HS256 검증, 토큰 암호화 키)으로 띄웠다. 웹은 실제 모드로 빌드해 `next start`로 띄웠다. Supabase 로그인은 세션 쿠키로, Supabase Auth는 가짜 서버로 대신했다. 가짜 서버는 authorize·코드 교환·세션 새로 받기·사용자 조회·로그아웃을 흉내 낸다.

| 묶음 | 단계 | 본 것 |
| --- | --- | --- |
| 화면 흐름 | 62 | 로그인 전 → `/login`(만료 문구 없음). 동의 → 4단계(정수 확인, 서버 422 영어·한국어 문구가 입력란 아래, 40자 제한) → 소득 동의 → LMS 단계 없이 홈. `app_open` 하루 1건. 설정의 입력 개수·HY-in·알림 숨김·캘린더 연결 요청 값(범위, offline, consent, 돌아올 곳)·`?calendar=error·connected` 안내와 쿼리 지우기. 프로필 수정 422·403(소득 입력란 닫힘), 소득 동의 켜기·철회, 탈퇴 준비 중, 오프라인 저장, 모바일 390px, 플래너 캘린더 줄, LMS 창, 서버에 닿지 못함, 서버 500(연결 실패로 보지 않음), 세션 만료 → `/login?error=session`, 콘솔 오류 없음 |
| 동의가 빠졌을 때 | 13 | 소득 단계에서 소득 동의 철회 → 동의 다시 묻기 → 값 그대로 저장. 다른 단계에서 철회 → 안내 → 다시 누르면 저장 → 소득 단계는 동의부터. 필수 동의가 빠짐 → 동의 단계로 |
| 콜백 | 24 | 연결 성공(토큰 암호화 저장, `login_hint`, 교환 뒤 세션 새로 받기, 쿠키에 Google 토큰 없음, 같은 사용자). 취소 → 설정에서 안내, 교환 안 함. 다른 계정 → 토큰 저장 안 함, 이 기기만 로그아웃, 안내. 서버에서 끊긴 세션 → 새 로그인처럼 연결. 사용자 확인 오류 → 교환 안 함. 세션 새로 받기 실패 → 쿠키 삭제·로그인 화면. 로그인 콜백 → 홈, 쿠키에 Google 토큰 없음 |
| 목 모드 | 18 | 알림 설정 토글, 캘린더 만료 시나리오 → 연결, LMS 해제, 프로필 저장, 탈퇴 → 온보딩 → LMS 단계 → 토큰 연결, 플래너 → 설정, 학업, 콘솔 오류 없음 |

콜백의 새 동작을 하나씩 되돌려 테스트가 걸리는지도 봤다. 세션 새로 받기를 빼면 쿠키에 `provider_token`·`provider_refresh_token`이 남았고, 취소 처리·다른 계정 막기를 빼거나 확인용 클라이언트를 일반 클라이언트로 바꾸면 각각 해당 단계가 실패했다(4가지 모두 걸림).

검토 에이전트 2개가 따로 봤다. 막을 문제는 없었고 아래를 받아들였다.

| 제안 | 고친 것 |
| --- | --- |
| 500 응답에 CORS 헤더가 없어 모든 서버 오류가 "인터넷 연결을 확인하고"로 보인다 | API 미들웨어, 응답을 못 받았을 때 문구를 오프라인·서버로 나눔 |
| 캘린더 연결을 취소하면 로그인한 사람이 "로그인 정보가 없어요"를 본다. 교환 실패도 같다 | 원래 화면으로 돌려보내 실패 안내 |
| Google refresh token이 자바스크립트로 읽을 수 있는 쿠키에 남는다 | 세션을 새로 받아 뺀다. 못 받으면 이 기기에서 로그아웃 |
| 다른 Google 계정을 고르면 조용히 그 계정으로 바뀐다 | `login_hint`, 콜백에서 막기 |
| 교환 전 사용자 확인이 끊긴 세션을 지우면서 PKCE 값까지 지운다(앞 수정이 만든 문제) | 쿠키를 바꾸지 않는 확인용 클라이언트. Auth 서버 오류면 교환하지 않고 실패 안내 |
| 다른 계정 로그아웃이 그 계정의 모든 기기에서 로그아웃시킨다 | `scope: "local"` |
| 세션 새로 받기 실패를 무시한다 | 실패하면 로그아웃·로그인 화면 |
| 미들웨어가 예외를 삼켜 서버 로그·텔레메트리에 안 남는다 | 500을 보낸 뒤 다시 던진다 |
| 다른 탭에서 소득 동의를 철회하면 온보딩이 소득 동의를 계속 다시 묻는다 | 동의 없으면 소득 값을 보내지 않음, 소득 단계가 아니면 그 자리에서 다시 저장 |
| 실제 모드의 알림 설정 토글이 저장되는 것처럼 보인다. 탈퇴는 "탈퇴"를 입력한 뒤에야 준비 중이라고 한다 | 알림 구역 숨김, 탈퇴 창에서 먼저 안내 |
| 플래너가 처음 쓰는 사람에게 "연결 만료"를 보이고 "다시 연결"은 화면 값만 바꾼다 | 문구를 고치고 설정으로 보냄 |
| 서버 영어 문구는 "값을 확인해 주세요."만 보인다(학기 수 2.5 등) | 정수 확인, 40자 제한 |
| `ProfileUpdateResult`가 서버 모델 이름과 다르다 | `ProfileUpdateResponse` |
| `notificationClient.ts`에 같은 응답 도구가 또 있다 | `mockClient.ts`로 합침 |

그대로 둔 것:
- 프로필 저장은 화면이 가진 프로필 전체를 보낸다. 서버가 프로필 응답에 항목을 더하면 `extra="forbid"` 때문에 422가 난다. 지금 서버는 17개만 주고, 명세의 예시에 있는 `admission_year`·`hyin_verified_at`은 HY-in(P2) 항목이다. HY-in을 넣을 때 보내는 항목을 17개로 고정한다.
- Google 동의 화면에서 캘린더 권한만 끄고 허용하면 지금은 "연결됨"으로 보인다. 받은 범위 확인은 캘린더 일정 API(F-32) 때 서버에서 한다.
- 콜백이 PKCE 흐름 id(`sb_flow_id`)를 읽지 않는다. 라이브러리의 실험 옵션을 켤 때만 붙는 값이라 지금은 쓰지 않는다.

## Windows에서

- 새 코드에 플랫폼별 코드는 없다. API 테스트 수는 대소문자만 다른 파일 이름 테스트 1개가 Windows·macOS에서 건너뛰어서 Linux와 1개 다르다.
- `api` 테스트는 로컬 Postgres로만 돌린다. `DATABASE_URL`에 실제 Supabase 주소를 넣고 `pytest`를 돌리지 않는다.

## 남은 것과 다음 단계

- **다음 PR(S1-5·S1-6 웹):** 홈 피드와 공고 상세를 실제 API에 붙인다. 공고 타입을 v0.4에 맞추고(`reason_text`, `uploaded_by_me`, 조건 묶음·기준일, `review_reasons`, `chosen_by`), "정보 입력" 저장 뒤 다시 불러오고 `profile_prompt_shown`을 보낸다. D-day의 기준인 `MOCK_TODAY`도 실제 모드에서는 오늘(KST)로 바꾼다.
- **API가 생기면 지울 것:** `LMS_CONNECT_READY`(9장 LMS), `DELETE_ACCOUNT_READY`(`DELETE /me`), `NOTIFICATION_SETTINGS_READY`(`/me/settings` P1), 알림 목록의 빈 값(10장).
- **캘린더 연결 해제:** PRD F-06에는 있는데 API 명세에 엔드포인트가 없다. PRD 14장 미결에 올린다(아래 반영하기).
- **다른 계정을 골랐을 때 남는 사용자:** 처음 쓰는 Google 계정이었다면 Supabase 사용자만 생기고 남는다. 정리는 탈퇴(`DELETE /me`) 작업 때 정한다(코드에 `TODO`).
- **Supabase Auth 요청 수:** 콜백이 로그인·연결마다 세션을 한 번 더 받는다. 사용자가 늘면 Supabase Auth 요청 한도(Rate Limits)를 본다.
- 지난 문서에 남은 내 Windows 경로는 아래 반영하기에서 지운다. git 기록에는 남는다. 지우려면 기록을 다시 써야 해서 그대로 둔다.

## PRD·ERD·API에 반영하기

"레포에 넣는 법" 3번에서 같은 브랜치에 적용한다.

```text
docs/계정API연결_구현.md의 결정을 기준 문서에 반영해줘. 문서 파일만 고치고 코드·마이그레이션은 건드리지 마. 아래 자리를 찾지 못하면 지어내지 말고 가장 가까운 자리에 넣은 뒤, 어디에 넣었는지 알려줘. 가까운 자리도 없으면 건너뛰고 알려줘.
1. docs/API_명세_v0.4.md
   - 머리말의 마지막 "v0.4 보강" 줄 아래에 더해: "v0.4 보강(10/11, 계정 화면 실제 연결): 캘린더 연결 콜백의 취소·다른 계정·Google 토큰 처리, 프론트 전용 오류 코드"
   - 4장 POST /auth/google/tokens에서 "콜백에서 받은 provider 토큰을 이 API로 보낸다." 문장 바로 뒤에 목록으로 더해:
     "- 연결을 시작할 때 login_hint로 지금 로그인한 계정을 넘긴다"
     "- Google 화면에서 취소하면 code 없이 돌아온다. 콜백은 로그인을 그대로 두고 next?calendar=error로 보낸다. 코드 교환이 실패해도 같다"
     "- 코드 교환 전 사용자와 교환 뒤 사용자가 다르면(다른 Google 계정을 고름) 토큰을 저장하지 않고, 바뀐 세션을 그 기기에서 지운 뒤 /login?error=other_account로 보낸다"
     "- Google 토큰(provider_token·provider_refresh_token)은 코드 교환 직후 세션에만 실려 온다. 콜백은 이 API를 부른 뒤 세션을 한 번 새로 받아 브라우저 쿠키에 Google 토큰을 남기지 않는다. 새로 받지 못하면 그 기기에서 로그아웃한다. 로그인 콜백도 같다"
   - 13장 에러 코드 표 바로 아래에 더해: "프론트만 쓰는 코드(서버는 주지 않는다, web/src/api/http.ts): NETWORK_ERROR(응답을 받지 못함), CONFIG_MISSING(API 주소 없음), NOT_READY(아직 API가 없는 기능), CALENDAR_CONNECT_FAILED(Google 화면을 열지 못함), RUN_TIMEOUT(실행 확인 시간 초과). 처리하지 못한 예외의 500 INTERNAL_ERROR에도 CORS 헤더가 붙어 브라우저가 문구를 읽을 수 있다."
   - 부록 "프론트 반영 목록" 표 바로 아래에 더해: "> 10/11 반영(docs/계정API연결_구현.md): 설정의 HY-in 숨김과 캘린더 연결."
2. docs/ERD_v0.9.md 7장
   - 마이그레이션 표에서 4행(`supabase/migrations/…_seed_departments.sql`, 학과 목록 seed 자리)을 지우고, 그 아래 행 번호를 4·5·6으로 당겨. 실제 seed 파일(20261010000100_seed_departments.sql) 행은 그대로 둬.
   - "적용 순서는 **v07 → v08 → v09 → seed**다." 문장을 "적용 순서는 파일 이름(시각) 순이다: v07 → v08 → v09 → 판정 엔진 버전 → 원문 확인 이유 → 학과 seed. 새 마이그레이션은 이름 순으로 맨 뒤에 온다."로 바꿔.
3. 루트 CLAUDE.md "구조"의 "적용 순서는 v07 → v08 → v09 → seed다"와 api/CLAUDE.md "DB 변경"의 "적용 순서는 v07 → v08 → v09 → seed다"를 "적용 순서는 파일 이름(시각) 순이다"로 바꿔. 앞뒤 문장과 괄호는 그대로 둬.
4. docs/PRD_v0.9.md 14장 미결 목록 끝에 더해: "- [ ] 설정의 Google 캘린더 연결 해제(F-06) — API 명세에 엔드포인트가 없다. 해제할 때 Google 쪽 토큰 폐기까지 할지 함께 정한다 (10/11)"
5. docs/Nextjs_이식_가이드.md
   - "### 1. 프로젝트 만들기" 명령 블록에서 npm init -y 다음 줄에 "npm pkg delete type   # npm 11의 npm init은 "type": "commonjs"를 넣는다. 레포의 web/package.json처럼 지운다"를 더하고, 명령 블록 바로 아래에 한 줄 더해: "레포에서는 루트 .gitignore가 node_modules/, .next/, .env*(예시 파일 제외), next-env.d.ts, *.tsbuildinfo를 막는다."
   - "## W4: 목데이터를 실제 API로 바꾸기"의 첫 문단 끝에 더해: "계정 함수는 src/api/accountClient.ts, LMS 함수는 src/api/lmsClient.ts에 두고 client.ts가 다시 내보낸다. 목 구현은 src/api/mockClient.ts에 모은다."
   - 그 아래 "#### `src/api/http.ts`" 제목과 코드 블록을 지우고 이 한 줄로 바꿔: "실제 호출 코드는 web/src/api/http.ts에 있다(apiFetch, errorMessage, fieldErrors, consentRequired, waitForRun). 10/11 계정API연결에서 바꾼 레포 파일이 기준이다."
   - 표의 getMe, getProfile · saveProfile, saveConsents 행 비고 끝에 " · 실제 API 연결(10/11)"을 더해.
   - 표의 getSettings · saveSettings 행 비고를 "P1. API 전까지 실제 모드는 설정에서 알림 구역을 숨긴다"로 바꿔.
   - 표의 getLmsConnection · connectLms · disconnectLms 행 비고에 "API 전까지 실제 모드는 '연결되지 않음', 연결 창은 준비 중 안내"를 넣어.
   - 표의 getNotifications · 읽음 처리 행 비고에 "API 전까지 실제 모드는 빈 목록"을 넣어.
   - 표의 reconnectCalendar 행을 "| `reconnectCalendar` | Google 화면으로 이동(증분 승인, `connectGoogleCalendar("/settings")`) → 콜백이 `POST /auth/google/tokens` | 돌아오면 `/settings?calendar=connected`·`error`. 실제 API 연결(10/11) |"로 바꿔.
   - 표의 deleteAccount 행 비고에 "API 전까지 실제 모드는 탈퇴 창에서 준비 중 안내"를 넣어.
   - 표 끝에 세 행을 더해:
     "| `updateIncomeConsent` | `PATCH /me/consents` | 실제 API 연결(10/11) |"
     "| `getDepartments` | `GET /meta/departments` | 응답의 `items`. 실제 API 연결(10/11) |"
     "| `recordEvent` (새로) | `POST /events` | 기다리지 않고 실패도 무시한다. 목 모드는 보내지 않는다. 실제 API 연결(10/11) |"
6. docs/온보딩_구현.md
   - "### `src/api/settingsClient.ts` · `src/api/client.ts`" 제목 바로 아래에 더해: "> 10/11 계정API연결에서 settingsClient.ts는 mockClient.ts로 합쳤고, 실제 호출은 accountClient.ts에 있다."
   - "## 실제 API로 바꿀 때 (S1-1·S1-2)" 제목 바로 아래에 더해: "> 10/11 docs/계정API연결_구현.md에서 이 표대로 바꿨다."
   - "남은 것"의 세 항목 끝에 더해:
     "POST /events의 app_open은…" 항목 → " → 넣었다(동의를 마친 사용자만, docs/계정API연결_구현.md)."
     "캘린더 연결 때 Google 화면에서 다른 계정을 고르면…" 항목 → " → login_hint를 넘기고, 다른 계정이면 콜백이 막는다(docs/계정API연결_구현.md)."
     "HY-in 재학생 인증(F-05)은 P2라 설정에 비활성 버튼만 있다" 항목 → " → 설정에서 숨겼다(PRD F-06)."
7. docs/API_뼈대_구현.md의 "#### `api/app/errors.py`" 제목과 "#### `api/app/main.py`" 제목 바로 아래에 각각 더해: "> 10/11 계정API연결에서 UnhandledErrorMiddleware를 더했다. 최신 코드는 레포 파일이 기준이다."
8. docs/요건추출후속_구현.md "레포에 넣는 법" 체크리스트의 import 명령에서 따옴표 안의 폴더 경로를 "<공지 폴더>"로 바꿔. 문서의 다른 곳에 같은 경로가 있으면 같이 바꿔.
끝나면 바뀐 곳을 알려줘.
```

## 코드

경로는 레포 루트 기준이다. 새 파일과 바뀐 파일 전체를 싣는다. 지우는 파일 2개(`web/src/api/settingsClient.ts`, `web/src/api/notificationClient.ts`)는 싣지 않는다.

### API

#### `api/app/errors.py`

```python
"""API 명세 13장 에러 형식: {"error": {"code", "message", "details"}}."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """라우터·서비스에서 던지는 유일한 에러. code는 명세 13장 표에 있는 것만 쓴다."""

    def __init__(
        self, status: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


_HTTP_CODES = {
    401: ("UNAUTHORIZED", "로그인이 필요해요."),
    403: ("FORBIDDEN", "권한이 없어요."),
    404: ("NOT_FOUND", "대상을 찾을 수 없어요."),
    405: ("METHOD_NOT_ALLOWED", "지원하지 않는 요청이에요."),
    429: ("RATE_LIMITED", "요청이 많아요. 잠시 후 다시 시도해 주세요."),
}


class UnhandledErrorMiddleware:
    """처리하지 못한 예외에 500 INTERNAL_ERROR 응답을 CORSMiddleware 안쪽에서 보낸다.

    Starlette는 이런 예외를 가장 바깥(CORSMiddleware 밖)에서 처리해서 500 응답에 CORS 헤더가 없다.
    그러면 브라우저는 응답을 읽지 못하고 네트워크 오류로 본다. 응답을 보낸 뒤 예외는 그대로 다시 던져서
    바깥 처리(handle_unexpected의 로그, 서버 로그)는 전과 같다. 바깥은 응답이 시작된 것을 보고 다시 보내지 않는다.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_tracking(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking)
        except Exception:
            if not started:  # 이미 응답을 보내기 시작했으면 바꿀 수 없다
                body = error_body("INTERNAL_ERROR", "잠시 후 다시 시도해 주세요.")
                await JSONResponse(status_code=500, content=body)(scope, receive, send)
            raise


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status, content=error_body(exc.code, exc.message, exc.details)
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = {
            ".".join(str(part) for part in error["loc"][1:]) or "body": error["msg"]
            for error in exc.errors()
        }
        body = error_body("VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": fields})
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_CODES.get(exc.status_code, ("HTTP_ERROR", str(exc.detail)))
        return JSONResponse(status_code=exc.status_code, content=error_body(code, message))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("처리하지 못한 예외", exc_info=exc)
        body = error_body("INTERNAL_ERROR", "잠시 후 다시 시도해 주세요.")
        return JSONResponse(status_code=500, content=body)
```

#### `api/app/main.py`

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db import create_pools
from app.errors import UnhandledErrorMiddleware, register_error_handlers
from app.logging_redact import install_log_redaction
from app.routers import auth, events, health, me, meta, opportunities


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    app.state.pool = app.state.log_pool = None
    if settings.database_url:
        app.state.pool, app.state.log_pool = create_pools(settings.database_url)
        await app.state.pool.open()
        await app.state.log_pool.open()
    yield
    for pool in (app.state.pool, app.state.log_pool):
        if pool is not None:
            await pool.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    install_log_redaction()  # 로그에서 토큰을 가린다 (요청 처리 전에 건다)
    settings = settings or get_settings()
    app = FastAPI(title="UNIPIVOT API", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    # 나중에 추가한 미들웨어가 바깥이다. 예외로 생긴 500에도 CORS 헤더가 붙게 CORS를 바깥에 둔다
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(health.router)
    for router in (auth.router, me.router, meta.router, events.router, opportunities.router):
        app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()
```

#### `api/tests/test_api.py`

```python
from uuid import UUID

from fastapi.testclient import TestClient

from app.config import Settings
from app.crypto import decrypt
from app.main import create_app
from tests.conftest import USER_ID, make_token
from tests.fakes import FakeMetaRepository, FakeProfileRepository

CONSENT = {"consent_version": "2026-10-07", "agree_terms": True, "agree_privacy": True}


def consent(client: TestClient, auth: dict[str, str], **extra: bool) -> None:
    res = client.post("/api/v1/me/consents", json={**CONSENT, **extra}, headers=auth)
    assert res.status_code == 200


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_unexpected_error_keeps_cors(settings: Settings) -> None:
    """처리하지 못한 예외도 13장 형식의 500이고, 브라우저가 읽을 수 있게 CORS 헤더가 붙는다."""
    app = create_app(settings)

    @app.get("/api/v1/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    origin = {"Origin": "http://localhost:3000"}
    with TestClient(app, raise_server_exceptions=False) as test_client:
        res = test_client.get("/api/v1/boom", headers=origin)
        assert res.status_code == 500
        assert res.json() == {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "잠시 후 다시 시도해 주세요.",
                "details": {},
            }
        }
        assert res.headers["access-control-allow-origin"] == "http://localhost:3000"
        # 다른 오류 응답도 그대로 CORS 헤더가 붙는다
        res = test_client.get("/api/v1/me", headers=origin)
        assert res.status_code == 401
        assert res.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_me_requires_login(client: TestClient) -> None:
    res = client.get("/api/v1/me")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_expired_or_forged_token_is_rejected(client: TestClient) -> None:
    for token in (
        make_token(expires_in=-10),
        make_token(secret="forged-secret-forged-secret-forged"),
    ):
        res = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_first_me_creates_profile(client: TestClient, auth: dict[str, str]) -> None:
    body = client.get("/api/v1/me", headers=auth).json()
    assert body["user_id"] == USER_ID
    assert body["display_name"] == "테스트 학생"
    assert (body["consented"], body["income_info_consented"], body["calendar_connected"]) == (
        False,
        False,
        False,
    )
    assert body["profile_completion"] == {"filled": 0, "total": 16}


def test_profile_update_needs_consent(client: TestClient, auth: dict[str, str]) -> None:
    client.get("/api/v1/me", headers=auth)
    res = client.patch("/api/v1/me/profile", json={"grade": 3}, headers=auth)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "CONSENT_REQUIRED"
    assert res.json()["error"]["details"] == {"consent": "terms_privacy"}


def test_consent_requires_both(client: TestClient, auth: dict[str, str]) -> None:
    res = client.post("/api/v1/me/consents", json={**CONSENT, "agree_privacy": False}, headers=auth)
    assert res.status_code == 422
    assert res.json()["error"]["details"]["fields"] == {"agree_privacy": "필수 항목이에요."}


def test_onboarding_flow(client: TestClient, auth: dict[str, str]) -> None:
    res = client.post("/api/v1/me/consents", json=CONSENT, headers=auth)
    assert res.status_code == 200
    assert res.json()["consent_version"] == "2026-10-07"
    assert res.json()["income_info_agreed_at"] is None  # 선택 동의는 하지 않음

    patch = {
        "department": "인공지능학과",
        "grade": 3,
        "gpa_last_semester": 3.9,
        "is_international": False,
    }
    res = client.patch("/api/v1/me/profile", json=patch, headers=auth)
    assert res.status_code == 200
    assert (res.json()["profile"]["grade"], res.json()["profile"]["is_international"]) == (3, False)
    assert res.json()["rejudged"] == {
        "changed": 0,
        "eligible": 0,
        "undetermined": 0,
        "ineligible": 0,
    }

    me = client.get("/api/v1/me", headers=auth).json()
    assert me["consented"] is True
    assert me["profile_completion"]["filled"] == 4

    client.patch("/api/v1/me/profile", json={"grade": None}, headers=auth)  # null이면 지운다
    assert client.get("/api/v1/me/profile", headers=auth).json()["grade"] is None


def test_profile_validation(client: TestClient, auth: dict[str, str]) -> None:
    consent(client, auth)
    res = client.patch("/api/v1/me/profile", json={"grade": 9}, headers=auth)
    assert res.status_code == 422
    assert "grade" in res.json()["error"]["details"]["fields"]

    res = client.patch(
        "/api/v1/me/profile", json={"gpa_scale": 4.3, "gpa_total": 4.4}, headers=auth
    )
    assert res.status_code == 422
    assert res.json()["error"]["details"]["fields"] == {
        "gpa_total": "평점 만점(4.3)보다 클 수 없어요."
    }

    res = client.patch("/api/v1/me/profile", json={"nickname": "x"}, headers=auth)
    assert res.status_code == 422  # 명세에 없는 필드는 받지 않는다

    res = client.patch("/api/v1/me/profile", json={"department": "없는학과"}, headers=auth)
    assert res.status_code == 422
    assert res.json()["error"]["details"]["fields"] == {"department": "학과 목록에서 골라 주세요."}

    res = client.patch("/api/v1/me/profile", json={"region_sido": "경기"}, headers=auth)
    assert res.status_code == 422  # 시도는 정식 이름만 (경기도)


def test_department_removed_from_list_is_kept(
    client: TestClient, auth: dict[str, str], meta: FakeMetaRepository
) -> None:
    consent(client, auth)
    res = client.patch("/api/v1/me/profile", json={"department": "경영학부"}, headers=auth)
    assert res.status_code == 200
    meta.departments = [d for d in meta.departments if d.name != "경영학부"]  # 학과가 목록에서 빠짐

    body = {"department": "경영학부", "grade": 2}  # 화면은 프로필 전체를 다시 보낸다
    res = client.patch("/api/v1/me/profile", json=body, headers=auth)
    assert res.status_code == 200
    assert (res.json()["profile"]["department"], res.json()["profile"]["grade"]) == ("경영학부", 2)
    res = client.patch("/api/v1/me/profile", json={"department": "인공지능학과"}, headers=auth)
    assert res.status_code == 200  # 바꿀 때는 목록에 있는 학과로


def test_income_needs_optional_consent(
    client: TestClient, auth: dict[str, str], repo: FakeProfileRepository
) -> None:
    consent(client, auth)
    res = client.patch("/api/v1/me/profile", json={"income_bracket": 6}, headers=auth)
    assert res.status_code == 403
    assert res.json()["error"]["details"] == {"consent": "income_info"}
    res = client.patch("/api/v1/me/profile", json={"income_bracket": None}, headers=auth)
    assert res.status_code == 200  # 지우는 것은 동의 없이도 된다

    res = client.patch("/api/v1/me/consents", json={"agree_income_info": True}, headers=auth)
    assert res.status_code == 200 and res.json()["income_info_agreed_at"] is not None
    res = client.patch(
        "/api/v1/me/profile", json={"income_bracket": 6, "welfare_status": "none"}, headers=auth
    )
    assert res.status_code == 200
    assert client.get("/api/v1/me", headers=auth).json()["income_info_consented"] is True

    res = client.patch("/api/v1/me/consents", json={"agree_income_info": False}, headers=auth)
    assert res.status_code == 200 and res.json()["income_info_agreed_at"] is None
    profile = client.get("/api/v1/me/profile", headers=auth).json()
    assert (profile["income_bracket"], profile["welfare_status"]) == (None, None)  # 철회하면 지운다
    assert client.get("/api/v1/me", headers=auth).json()["income_info_consented"] is False


def test_income_consent_order(client: TestClient, auth: dict[str, str]) -> None:
    client.get("/api/v1/me", headers=auth)
    res = client.patch("/api/v1/me/consents", json={"agree_income_info": True}, headers=auth)
    assert res.status_code == 403  # 필수 동의가 먼저
    assert res.json()["error"]["details"] == {"consent": "terms_privacy"}

    consent(client, auth, agree_income_info=True)  # 온보딩에서 선택 동의까지 한 번에
    assert client.get("/api/v1/me", headers=auth).json()["income_info_consented"] is True
    res = client.patch(
        "/api/v1/me/consents", json={"agree_income_info": True, "extra": 1}, headers=auth
    )
    assert res.status_code == 422


def test_departments(client: TestClient, auth: dict[str, str]) -> None:
    assert client.get("/api/v1/meta/departments").status_code == 401
    res = client.get("/api/v1/meta/departments", headers=auth)
    assert res.status_code == 200
    assert res.json()["items"][0] == {
        "name": "인공지능학과",
        "college": "소프트웨어융합대학",
        "field_group": "공학계열",
    }


def test_events(client: TestClient, auth: dict[str, str], meta: FakeMetaRepository) -> None:
    res = client.post("/api/v1/events", json={"event": "app_open"}, headers=auth)
    assert (res.status_code, res.content) == (204, b"")
    assert meta.events == [(USER_ID, "app_open", None)]

    res = client.post("/api/v1/events", json={"event": "lms_connected"}, headers=auth)
    assert res.status_code == 422  # 서버가 직접 기록하는 이벤트
    res = client.post(
        "/api/v1/events",
        json={"event": "profile_prompt_shown", "opportunity_id": "not-a-uuid"},
        headers=auth,
    )
    assert res.status_code == 422

    opportunity_id = "00000000-0000-4000-8000-0000000000aa"
    body = {"event": "profile_prompt_shown", "opportunity_id": opportunity_id}
    assert client.post("/api/v1/events", json=body, headers=auth).status_code == 204
    assert meta.events[-1] == (USER_ID, "profile_prompt_shown", UUID(opportunity_id))


def test_google_tokens(
    client: TestClient, auth: dict[str, str], repo: FakeProfileRepository, settings: Settings
) -> None:
    res = client.post("/api/v1/auth/google/tokens", json={"provider_token": "ya29.a"}, headers=auth)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "GOOGLE_REFRESH_TOKEN_MISSING"

    body = {"provider_token": "ya29.a", "provider_refresh_token": "1//refresh"}
    res = client.post("/api/v1/auth/google/tokens", json=body, headers=auth)
    assert res.status_code == 200
    assert res.json() == {"calendar_connected": True, "scope": "calendar.events"}

    stored = repo.tokens[USER_ID]["refresh_token"]
    assert stored != "1//refresh"  # 암호화해서 저장한다
    assert decrypt(stored, settings.token_encryption_key) == "1//refresh"
    assert client.get("/api/v1/me", headers=auth).json()["calendar_connected"] is True
```

### 웹: 데이터 함수와 타입

#### `web/src/api/http.ts` (새 파일)

```ts
import { createBrowserSupabase } from "@/lib/supabase/client";
import type { Run } from "@/types/api";

// 실제 FastAPI 호출 (API 명세 1·2·13장). 화면은 이 파일을 직접 쓰지 않고 client.ts 함수만 쓴다.
// code는 서버가 준 13장 코드를 그대로 쓴다. 서버에 닿지 못한 경우만 프론트 코드를 쓴다:
// NETWORK_ERROR(서버 연결 실패), CONFIG_MISSING(API 주소 없음), NOT_READY(아직 API가 없는 기능),
// CALENDAR_CONNECT_FAILED(Google 화면을 열지 못함), RUN_TIMEOUT(실행 확인 시간 초과)
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details?: Record<string, unknown>,
  ) {
    super(message);
  }
}

// 목 모드면 목데이터, 아니면 FastAPI (web/CLAUDE.md, 스킬 mock-to-api)
export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "true";

// 실제 모드에서 아직 API가 없는 기능은 목데이터 대신 빈 값이나 이 오류를 준다
export function notReady(message: string): Promise<never> {
  return Promise.reject(new ApiError("NOT_READY", message, 0));
}

const FALLBACK_MESSAGE = "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.";

// 응답을 받지 못했다. 기기가 오프라인이면 인터넷을, 아니면 서버(꺼짐·주소·CORS 설정)를 탓한다
function networkMessage(): string {
  return typeof navigator !== "undefined" && !navigator.onLine
    ? "인터넷에 연결되어 있지 않아요. 연결을 확인하고 다시 시도해 주세요."
    : "서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.";
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!base) {
    throw new ApiError("CONFIG_MISSING", "API 주소(NEXT_PUBLIC_API_BASE_URL)가 설정되지 않았어요.", 0);
  }
  const { data } = await createBrowserSupabase().auth.getSession();
  const token = data.session?.access_token;
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError("NETWORK_ERROR", networkMessage(), 0);
  }
  // 로그인 전이면 로그인 화면으로, 세션이 만료됐으면 이유와 함께 보낸다.
  // 페이지가 바뀌므로 화면에 오류를 넘기지 않고 기다리게 둔다
  if (response.status === 401 && typeof window !== "undefined") {
    window.location.assign(token ? "/login?error=session" : "/login");
    return new Promise<T>(() => {});
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      body?.error?.code ?? "UNKNOWN",
      body?.error?.message ?? FALLBACK_MESSAGE,
      response.status,
      body?.error?.details,
    );
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

// 화면에 띄울 오류 문구. 서버(13장)와 프론트 코드가 준 문구는 그대로 쓰고,
// 서버 내부 오류(5xx)·알 수 없는 오류·목 모드 오류는 화면이 준 문구를 쓴다
export function errorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError) || error.status >= 500 || error.code === "UNKNOWN") return fallback;
  return error.message;
}

const HANGUL = /[가-힣]/;

// 422 VALIDATION_FAILED의 details.fields를 항목별 문구로. 서버가 준 한국어 문구는 그대로 쓰고,
// 요청 형식 검사에서 온 영어 문구는 "값을 확인해 주세요."로 바꾼다
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.code !== "VALIDATION_FAILED") return {};
  const fields = error.details?.fields;
  if (!fields || typeof fields !== "object") return {};
  return Object.fromEntries(
    Object.entries(fields as Record<string, unknown>).map(([key, message]) => [
      key,
      typeof message === "string" && HANGUL.test(message) ? message : "값을 확인해 주세요.",
    ]),
  );
}

// 403 CONSENT_REQUIRED의 details.consent: terms_privacy(필수 동의 전) · income_info(소득 선택 동의 전)
export function consentRequired(error: unknown): "terms_privacy" | "income_info" | null {
  if (!(error instanceof ApiError) || error.code !== "CONSENT_REQUIRED") return null;
  const consent = error.details?.consent;
  return consent === "terms_privacy" || consent === "income_info" ? consent : null;
}

// 202로 받은 run_id를 1.5초 간격으로 최대 60초까지 확인한다 (API 2장)
export async function waitForRun<R>(runId: string, onProgress?: (run: Run<R>) => void): Promise<Run<R>> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < 60_000) {
    const run = await apiFetch<Run<R>>(`/runs/${runId}`);
    onProgress?.(run);
    if (run.status === "succeeded" || run.status === "failed") return run;
    await new Promise((resolve) => setTimeout(resolve, 1_500));
  }
  throw new ApiError("RUN_TIMEOUT", "백그라운드에서 계속 처리하고 있어요. 끝나면 알림으로 알려드릴게요.", 0);
}
```

#### `web/src/api/client.ts`

```ts
import { MockApiError, rejectAfter, respond } from "@/api/mockClient";
import { getDevScenario } from "@/dev/scenarios";
import {
  mockNow,
  mockToday,
  opportunities,
  opportunityDetails,
  duplicatePosterExtractResult,
  posterExtractResult,
} from "@/mocks";
import {
  getStoredOpportunity,
  getStoredPlanner,
  addStoredManualTask,
  deleteStoredManualTask,
  prepareStoredOpportunity,
  registerStoredPoster,
  setStoredPlannerTaskDone,
  setStoredDocumentDone,
  updateStoredManualTask,
} from "@/mocks/store";
import type {
  Category,
  DisplayStatus,
  FeedCounts,
  FeedResponse,
  OpportunityDetail,
  PlannerResponse,
  PlannerTask,
  PosterExtractResult,
  PrepareResult,
  ReportReason,
} from "@/types/api";

// 화면이 쓰는 데이터 함수는 모두 이 파일에서 가져간다 (web/CLAUDE.md, 스킬 mock-to-api).
// 계정·LMS 함수는 accountClient.ts·lmsClient.ts에 두고 여기서 다시 내보낸다. 아래 공고·플래너·포스터 함수는 아직 목이다
export * from "@/api/accountClient";
export * from "@/api/lmsClient";
export { ApiError, consentRequired, errorMessage, fieldErrors } from "@/api/http";
export { MockApiError };

export interface FeedParams {
  eligibility?: DisplayStatus | "all";
  category?: Category | "all";
  sort?: "deadline" | "recent";
}

export const MOCK_TODAY = mockToday;
export const MOCK_NOW = mockNow;

export type PosterPreviewState =
  | { status: "idle"; result: null }
  | { status: "failure"; result: null }
  | { status: "limit"; result: null }
  | { status: "duplicate"; result: PosterExtractResult };

function getCounts(items: FeedResponse["items"]): FeedCounts {
  return {
    eligible: items.filter((item) => item.eligibility.status === "eligible").length,
    new_eligible: items.filter((item) => item.eligibility.status === "eligible" && item.is_new).length,
    undetermined: items.filter((item) => item.eligibility.status === "undetermined").length,
    missing_info: items.filter((item) => item.eligibility.display_status === "missing_info").length,
    needs_review: items.filter((item) => item.eligibility.display_status === "needs_review").length,
    ineligible: items.filter((item) => item.eligibility.status === "ineligible").length,
    deadline_soon: items.filter((item) => item.eligibility.status !== "ineligible" && item.d_day !== null && item.d_day >= 0 && item.d_day <= 3).length,
  };
}

export function getFeed(params: FeedParams = {}): Promise<FeedResponse> {
  if (getDevScenario() === "empty_feed") {
    return respond({ items: [], next_cursor: null, counts: getCounts([]) });
  }

  let items = [...opportunities];
  if (params.eligibility && params.eligibility !== "all") {
    items = items.filter((item) => item.eligibility.display_status === params.eligibility);
  }
  if (params.category && params.category !== "all") {
    items =
      params.category === "etc"
        ? items.filter((item) => ["research", "exam", "etc"].includes(item.category))
        : items.filter((item) => item.category === params.category);
  }

  items.sort((a, b) => {
    if (params.sort !== "recent") {
      return (a.d_day ?? Number.MAX_SAFE_INTEGER) - (b.d_day ?? Number.MAX_SAFE_INTEGER);
    }
    // 실제 API는 sort=recent를 받아 서버가 등록순으로 정렬한다. 목업은 새 공고를 앞으로만 보낸다.
    return Number(b.is_new) - Number(a.is_new);
  });

  return respond({ items, next_cursor: null, counts: getCounts(items) });
}

export function getOpportunity(id: string): Promise<OpportunityDetail> {
  const detail = getStoredOpportunity(id) ?? opportunityDetails[id];
  if (!detail) return Promise.reject(new Error("공고를 찾을 수 없어요."));
  return respond(detail);
}

export function getPlanner(from: string, to: string): Promise<PlannerResponse> {
  const storedPlanner = getStoredPlanner();
  return respond({
    items: storedPlanner.items.filter((item) => item.due_date >= from && item.due_date <= to),
    markers: storedPlanner.markers.filter((marker) => marker.date >= from && marker.date <= to),
  });
}

export function setPlannerTaskDone(id: string, isDone: boolean): Promise<PlannerTask> {
  return respond(setStoredPlannerTaskDone(id, isDone));
}

export function addManualPlannerTask(title: string, dueDate: string): Promise<PlannerTask> {
  return respond(addStoredManualTask(title, dueDate));
}

export function updateManualPlannerTask(id: string, title: string, dueDate: string): Promise<PlannerTask> {
  return respond(updateStoredManualTask(id, title, dueDate));
}

export function deleteManualPlannerTask(id: string): Promise<void> {
  deleteStoredManualTask(id);
  return respond(undefined);
}

// TODO(api): 실제 준비하기 API가 확정되면 전용 엔드포인트 호출로 교체한다.
export function prepareOpportunity(
  id: string,
  includeCalendar: boolean,
  targetDate?: string,
): Promise<PrepareResult> {
  return respond(prepareStoredOpportunity(id, includeCalendar, targetDate));
}

// TODO(api): 실제 서류 완료 API가 확정되면 planner task 수정 엔드포인트로 교체한다.
export function setDocumentDone(
  opportunityId: string,
  documentId: string,
  isDone: boolean,
): Promise<OpportunityDetail> {
  return respond(setStoredDocumentDone(opportunityId, documentId, isDone));
}

// TODO(api): POST /opportunities/{id}/reports { reason, detail } — 서로 다른 3명째 신고에서 hidden: true
export function reportOpportunity(
  _id: string,
  _reason: ReportReason,
  _detail: string,
): Promise<{ reported: boolean; hidden: boolean }> {
  return respond({ reported: true, hidden: false });
}

export function getPosterPreviewState(): Promise<PosterPreviewState> {
  const scenario = getDevScenario();
  if (scenario === "poster_failure") return respond({ status: "failure", result: null });
  if (scenario === "upload_limit") return respond({ status: "limit", result: null });
  if (scenario === "poster_duplicate") {
    return respond({ status: "duplicate", result: duplicatePosterExtractResult });
  }
  return respond({ status: "idle", result: null });
}

// TODO(api): 포스터 추출 run 생성 API와 연결되면 File 대신 업로드된 file_id를 전달한다.
export function extractPoster(_file: File): Promise<PosterExtractResult> {
  const scenario = getDevScenario();
  if (scenario === "poster_failure") {
    return rejectAfter(
      new MockApiError("poster_read_failed", "포스터에서 글자를 읽지 못했어요."),
    );
  }
  if (scenario === "upload_limit") {
    return rejectAfter(
      new MockApiError("upload_limit", "오늘 업로드 한도를 초과했어요."),
    );
  }
  return respond(
    scenario === "poster_duplicate"
      ? duplicatePosterExtractResult
      : posterExtractResult,
  );
}

// TODO(api): 실제 공고 등록 API가 확정되면 draft 등록 요청으로 교체한다.
export function registerPosterOpportunity(
  draft: PosterExtractResult["draft"],
): Promise<OpportunityDetail> {
  return respond(registerStoredPoster(draft));
}
```

#### `web/src/api/accountClient.ts` (새 파일)

```ts
import { ApiError, apiFetch, notReady, USE_MOCKS } from "@/api/http";
import * as mock from "@/api/mockClient";
import { connectGoogleCalendar } from "@/lib/googleCalendar";
import type {
  AppNotification,
  ClientEvent,
  ConsentResult,
  Department,
  IncomeConsentResult,
  Me,
  Profile,
  ProfileUpdateResponse,
  Settings,
} from "@/types/api";

// 내 정보·프로필·동의·학과·캘린더 연결·사용 기록·설정·알림·탈퇴 (API 명세 4·10장).
// 화면은 client.ts를 거쳐 쓴다. 목 모드면 mockClient.ts, 아니면 FastAPI를 부른다

// GET /me
export function getMe(): Promise<Me> {
  return USE_MOCKS ? mock.getMe() : apiFetch<Me>("/me");
}

// GET /me/profile
export function getProfile(): Promise<Profile> {
  return USE_MOCKS ? mock.getProfile() : apiFetch<Profile>("/me/profile");
}

// PATCH /me/profile. 화면은 프로필 전체를 보낸다. 서버는 바뀐 항목만 저장하고 공고를 다시 판정한다
export async function saveProfile(profile: Profile): Promise<Profile> {
  if (USE_MOCKS) return mock.saveProfile(profile);
  const result = await apiFetch<ProfileUpdateResponse>("/me/profile", {
    method: "PATCH",
    body: JSON.stringify(profile),
  });
  return result.profile;
}

// POST /me/consents (온보딩 동의 단계). 필수 두 항목은 화면이 체크해야 부른다
export function saveConsents(version: string, agreeIncomeInfo: boolean): Promise<ConsentResult> {
  if (USE_MOCKS) return mock.saveConsents(version, agreeIncomeInfo);
  return apiFetch<ConsentResult>("/me/consents", {
    method: "POST",
    body: JSON.stringify({
      consent_version: version,
      agree_terms: true,
      agree_privacy: true,
      agree_income_info: agreeIncomeInfo,
    }),
  });
}

// PATCH /me/consents. 끄면 서버가 소득 3항목을 지우고 다시 판정한다
export function updateIncomeConsent(agree: boolean): Promise<IncomeConsentResult> {
  if (USE_MOCKS) return mock.updateIncomeConsent(agree);
  return apiFetch<IncomeConsentResult>("/me/consents", {
    method: "PATCH",
    body: JSON.stringify({ agree_income_info: agree }),
  });
}

// GET /meta/departments의 items
export async function getDepartments(): Promise<Department[]> {
  if (USE_MOCKS) return mock.getDepartments();
  const { items } = await apiFetch<{ items: Department[] }>("/meta/departments");
  return items;
}

// 설정의 캘린더 연결. 실제 모드는 API를 부르지 않고 Google 화면으로 떠난다(증분 승인, API 4장).
// 콜백이 토큰을 저장한 뒤 /settings?calendar=connected(또는 error)로 돌아온다
export async function reconnectCalendar(): Promise<Me> {
  if (USE_MOCKS) return mock.reconnectCalendar();
  const error = await connectGoogleCalendar("/settings");
  if (error) throw new ApiError("CALENDAR_CONNECT_FAILED", error, 0);
  return new Promise<Me>(() => {}); // 페이지가 Google로 넘어가므로 끝나지 않는다
}

// POST /events. 기록용이라 기다리지 않고, 실패해도 화면은 그대로 둔다 (API 4장)
export function recordEvent(event: ClientEvent, opportunityId?: string): void {
  if (USE_MOCKS) return;
  apiFetch<void>("/events", {
    method: "POST",
    body: JSON.stringify(opportunityId ? { event, opportunity_id: opportunityId } : { event }),
  }).catch(() => undefined);
}

// 알림 설정(P1)을 보여 줄지. TODO(api): GET·PATCH /me/settings가 생기면 아래 두 함수를 바꾸고 지운다.
// 그 전까지 실제 모드는 설정 화면에서 알림 구역을 숨긴다(목 값이 저장되는 것처럼 보이지 않게)
export const NOTIFICATION_SETTINGS_READY = USE_MOCKS;

export function getSettings(): Promise<Settings> {
  return mock.getSettings();
}

export function saveSettings(settings: Settings): Promise<Settings> {
  return mock.saveSettings(settings);
}

// TODO(api): GET /notifications · POST /notifications/read(10장). 그 전까지 실제 모드는 알림이 없다
export function getNotifications(): Promise<AppNotification[]> {
  return USE_MOCKS ? mock.getNotifications() : Promise.resolve([]);
}

export function markNotificationRead(id: string): Promise<AppNotification[]> {
  return USE_MOCKS ? mock.markNotificationRead(id) : Promise.resolve([]);
}

export function markAllNotificationsRead(): Promise<AppNotification[]> {
  return USE_MOCKS ? mock.markAllNotificationsRead() : Promise.resolve([]);
}

// 탈퇴를 받을지. TODO(api): DELETE /me(4장)가 생기면 deleteAccount를 바꾸고 지운다.
// 그 전까지 실제 모드는 탈퇴 창에서 준비 중이라고 먼저 알린다
export const DELETE_ACCOUNT_READY = USE_MOCKS;

export function deleteAccount(): Promise<void> {
  if (USE_MOCKS) return mock.deleteAccount();
  return notReady("탈퇴는 아직 준비 중이에요. 준비되면 이 화면에서 바로 탈퇴할 수 있어요.");
}
```

#### `web/src/api/lmsClient.ts` (새 파일)

```ts
import { notReady, USE_MOCKS } from "@/api/http";
import * as mock from "@/api/mockClient";
import type { Course, CourseDetail, LmsConnection, LmsUpdate, MaterialDetail } from "@/types/api";

// LMS 연결·과목·새 소식·강의자료 (API 명세 8·9장). 화면은 client.ts를 거쳐 쓴다.
// TODO(api): LMS API(9장)가 생기면 안쪽을 apiFetch로 바꾸고 LMS_CONNECT_READY를 지운다.
// 그 전까지 실제 모드는 "연결 안 됨"으로 보이고, 연결·과목 상세·강의자료는 준비 중 오류를 준다

// LMS 연결을 권할지. false면 온보딩 끝의 LMS 단계를 건너뛰고, 연결 창은 준비 중 안내만 보여 준다
export const LMS_CONNECT_READY = USE_MOCKS;

const LMS_NOT_READY = "LMS 연결은 아직 준비 중이에요.";

export function getLmsConnection(): Promise<LmsConnection> {
  if (USE_MOCKS) return mock.getLmsConnection();
  return Promise.resolve({ status: "disconnected", token_last4: "", last_synced_at: null, last_error: null });
}

// 실제 API는 토큰을 서버로만 보내고 클라이언트에는 저장하지 않는다
export function connectLms(token: string): Promise<LmsConnection> {
  return USE_MOCKS ? mock.connectLms(token) : notReady(LMS_NOT_READY);
}

export function disconnectLms(): Promise<LmsConnection> {
  return USE_MOCKS ? mock.disconnectLms() : notReady(LMS_NOT_READY);
}

export function getCourses(): Promise<Course[]> {
  return USE_MOCKS ? mock.getCourses() : Promise.resolve([]);
}

export function getCourse(id: string): Promise<CourseDetail> {
  return USE_MOCKS ? mock.getCourse(id) : notReady(LMS_NOT_READY);
}

export function getLmsUpdates(): Promise<LmsUpdate[]> {
  return USE_MOCKS ? mock.getLmsUpdates() : Promise.resolve([]);
}

export function getMaterial(fileId: string): Promise<MaterialDetail> {
  return USE_MOCKS ? mock.getMaterial(fileId) : notReady("강의자료 요약은 아직 준비 중이에요.");
}
```

#### `web/src/api/mockClient.ts` (새 파일)

```ts
import { getDevScenario } from "@/dev/scenarios";
import { courseDetails, courses, lmsUpdates, materials } from "@/mocks";
import { mockDepartments, mockNow } from "@/mocks/account";
import {
  getStoredNotifications,
  readAllStoredNotifications,
  readStoredNotification,
} from "@/mocks/notificationStore";
import {
  connectStoredLms,
  deleteStoredAccount,
  disconnectStoredLms,
  getStoredLmsConnection,
  getStoredMe,
  getStoredProfile,
  getStoredSettings,
  hasStoredConsent,
  reconnectStoredCalendar,
  storeConsent,
  storeIncomeConsent,
  updateStoredProfile,
  updateStoredSettings,
} from "@/mocks/accountStore";
import type {
  AppNotification,
  ConsentResult,
  Course,
  CourseDetail,
  Department,
  IncomeConsentResult,
  LmsConnection,
  LmsUpdate,
  MaterialDetail,
  Me,
  Profile,
  Settings,
} from "@/types/api";

// 목 모드(NEXT_PUBLIC_USE_MOCKS=true)에서 쓰는 구현 (스킬 mock-to-api).
// 실제 모드 분기가 있는 함수의 목 구현과, 목 함수들이 같이 쓰는 응답 도구를 둔다
const WAIT_MS = 300;

export class MockApiError extends Error {
  constructor(
    public code: "poster_read_failed" | "upload_limit" | "lms_invalid",
    message: string,
  ) {
    super(message);
  }
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function respond<T>(value: T): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(clone(value)), WAIT_MS);
  });
}

export function rejectAfter(error: Error): Promise<never> {
  return new Promise((_, reject) => {
    setTimeout(() => reject(error), WAIT_MS);
  });
}

// 내 정보·프로필·동의·학과·캘린더·설정·알림·탈퇴 (accountClient.ts)

export function getMe(): Promise<Me> {
  const scenario = getDevScenario();
  const result = clone(getStoredMe());

  if (scenario === "first_visit" && !hasStoredConsent()) {
    result.consented = false;
    result.income_info_consented = false;
  }
  if (scenario === "lms_disconnected") {
    result.lms = { status: "disconnected", last_synced_at: null };
  }
  if (scenario === "lms_error" && result.lms) result.lms.status = "error";
  if (scenario === "calendar_expired") result.calendar_connected = false;

  return respond(result);
}

export function getProfile(): Promise<Profile> {
  return respond(getStoredProfile());
}

export function saveProfile(profile: Profile): Promise<Profile> {
  return respond(updateStoredProfile(profile));
}

export function saveConsents(version: string, agreeIncomeInfo: boolean): Promise<ConsentResult> {
  return respond(storeConsent(version, mockNow, agreeIncomeInfo));
}

export function updateIncomeConsent(agree: boolean): Promise<IncomeConsentResult> {
  return respond(storeIncomeConsent(agree, mockNow));
}

export function getDepartments(): Promise<Department[]> {
  return respond([...mockDepartments]);
}

export function reconnectCalendar(): Promise<Me> {
  return respond(reconnectStoredCalendar());
}

export function getSettings(): Promise<Settings> {
  return respond(getStoredSettings());
}

export function saveSettings(settings: Settings): Promise<Settings> {
  return respond(updateStoredSettings(settings));
}

export function deleteAccount(): Promise<void> {
  deleteStoredAccount();
  return new Promise((resolve) => setTimeout(resolve, WAIT_MS));
}

export function getNotifications(): Promise<AppNotification[]> {
  return respond(getStoredNotifications());
}

export function markNotificationRead(id: string): Promise<AppNotification[]> {
  return respond(readStoredNotification(id, mockNow));
}

export function markAllNotificationsRead(): Promise<AppNotification[]> {
  return respond(readAllStoredNotifications(mockNow));
}

// LMS (lmsClient.ts)

export function getLmsConnection(): Promise<LmsConnection> {
  const scenario = getDevScenario();
  const result = clone(getStoredLmsConnection());
  if (scenario === "lms_disconnected") {
    result.status = "disconnected";
    result.last_synced_at = null;
  }
  if (scenario === "lms_error") {
    result.status = "error";
    result.last_error = "LearningX 인증 정보가 만료됐어요. 다시 연결해 주세요.";
  }
  return respond(result);
}

export function connectLms(token: string): Promise<LmsConnection> {
  const normalized = token.trim();
  if (token !== normalized || normalized.length < 8) {
    return rejectAfter(new MockApiError("lms_invalid", "LearningX 토큰을 확인할 수 없어요."));
  }
  return respond(connectStoredLms(normalized.slice(-4)));
}

export function disconnectLms(): Promise<LmsConnection> {
  return respond(disconnectStoredLms());
}

export function getCourses(): Promise<Course[]> {
  return respond(courses);
}

export function getCourse(id: string): Promise<CourseDetail> {
  const course = courseDetails[id];
  if (!course) return Promise.reject(new Error("과목을 찾을 수 없어요."));
  return respond(course);
}

export function getLmsUpdates(): Promise<LmsUpdate[]> {
  return respond(lmsUpdates);
}

export function getMaterial(fileId: string): Promise<MaterialDetail> {
  const material = materials[fileId];
  if (!material) return Promise.reject(new Error("강의자료를 찾을 수 없어요."));
  return respond(material);
}
```

#### `web/src/types/api.ts`

```ts
// API 명세와 1:1로 맞춘 타입. 필드 이름을 바꾸지 않는다. LMS·강의자료 타입은 lms.ts에 두고 여기서 다시 내보낸다.
// 내 정보·프로필·동의·학과·사용 기록은 v0.4에 맞췄다. 공고 피드·상세는 아직 v0.3 모양이다
// (TODO(api): 공고 화면을 실제 API에 붙일 때 명세 부록 "프론트 반영 목록"대로 맞춘다)
// 일시는 ISO 8601 문자열(+09:00), 날짜만은 "YYYY-MM-DD".

export * from "@/types/lms";

export type Category = "scholarship" | "school_program" | "youth_policy" | "contest" | "activity" | "research" | "exam" | "etc";
export type SourceType = "school_notice" | "youth_policy" | "contest" | "poster" | "lms_announcement";
export type EligibilityStatus = "eligible" | "undetermined" | "ineligible";
export type DisplayStatus = "eligible" | "missing_info" | "needs_review" | "ineligible";
export type RunStatus = "pending" | "running" | "succeeded" | "failed";
export type NotificationType =
  | "new_eligible" | "new_assignment" | "new_material" | "schedule_change"
  | "task_due" | "deadline_soon" | "profile_needed";
export type ReportReason = "wrong_info" | "duplicate" | "expired" | "inappropriate";

// GET /me
export interface Me {
  user_id: string;
  display_name: string;
  hyin_verified: boolean;
  calendar_connected: boolean;
  lms: { status: "active" | "error" | "disconnected"; last_synced_at: string | null } | null;
  profile_completion: { filled: number; total: number };
  consented: boolean;
  income_info_consented: boolean;
  unread_notifications: number;
}

// GET /me/profile (모든 값 null 가능)
export interface Profile {
  department: string | null;
  grade: number | null;
  enrollment_status: "enrolled" | "on_leave" | "deferred_graduation" | "graduated" | null;
  semesters_completed: number | null;
  credits_total: number | null;
  credits_last_semester: number | null;
  gpa_total: number | null;
  gpa_last_semester: number | null;      // 직전학기 장학용 평점(F 포함)
  gpa_scale: number;                     // 기본 4.5
  birth_date: string | null;
  military_service_months: number | null;
  region_sido: string | null;
  region_sigungu: string | null;
  income_bracket: number | null;         // 학자금 지원구간
  median_income_pct: number | null;      // 기준 중위소득 %
  welfare_status: "none" | "near_poverty" | "basic_livelihood" | null;
  is_international: boolean | null;
}

// PATCH /me/profile: 저장한 프로필과 다시 판정한 결과 수 (counts와 같은 기준)
export interface ProfileUpdateResponse {
  profile: Profile;
  rejudged: { changed: number; eligible: number; undetermined: number; ineligible: number };
}

// POST /me/consents
export interface ConsentResult {
  terms_agreed_at: string;
  privacy_agreed_at: string;
  income_info_agreed_at: string | null;
  consent_version: string;
}

// PATCH /me/consents
export interface IncomeConsentResult {
  income_info_agreed_at: string | null;
}

// GET /meta/departments의 items
export interface Department {
  name: string;
  college: string;
  field_group: string;
}

// POST /events: 화면에서만 알 수 있는 사용 기록 (나머지 이벤트는 서버가 기록한다)
export type ClientEvent = "app_open" | "profile_prompt_shown" | "lms_guide_opened";

// GET /me/settings
export interface Settings {
  push_enabled: boolean;
  muted_notification_types: NotificationType[];
  calendar_auto_lms: boolean;
}

// GET /opportunities
export interface FeedEligibility {
  status: EligibilityStatus;
  display_status: DisplayStatus;
  summary: string;                       // 카드의 상태 사유 한 줄
  missing_fields: string[];
}
export interface OpportunityItem {
  id: string;
  title: string;
  organizer: string | null;
  category: Category;
  source_type: SourceType;
  deadline_at: string | null;
  d_day: number | null;
  easy_summary: string | null;
  eligibility: FeedEligibility;
  recommend_reason: string | null;       // P1
  needs_review: boolean;
  uploader_masked: string | null;        // 포스터 공고만, 예: "김*지"
  course_name: string | null;            // 과목 공지에서 온 공고만
  prepared: boolean;
  is_new: boolean;
}
export interface FeedCounts {
  eligible: number; new_eligible: number;
  undetermined: number; missing_info: number; needs_review: number;
  ineligible: number; deadline_soon: number;
}
export interface FeedResponse { items: OpportunityItem[]; next_cursor: string | null; counts: FeedCounts; }

// GET /opportunities/{id}
export interface Condition {
  requirement_id: string;
  field: string;
  label: string;                         // "직전학기 취득학점"
  operator: string;
  value: unknown;
  user_value: unknown;
  condition_text: string;                // "직전학기 12학점 이상"
  user_value_text: string | null;        // "18학점", 미입력이면 null
  outcome: "pass" | "fail" | "unknown";
  evidence_text: string | null;          // 근거 원문 문장
  is_ambiguous: boolean;
}
export interface DocumentItem {
  id: string;
  name: string;
  issuer: string | null;
  how_to: string | null;
  lead_days: number | null;              // 0이면 즉시 발급
  effort_minutes: number | null;         // 작성 예상 시간
  form_url: string | null;               // 첨부 양식
  is_required: boolean;
  task_id: string | null;                // 준비하기 전에는 null
  is_done: boolean | null;
}
export interface ProcessStep { seq: number; label: string; status: RunStatus; latency_ms: number | null; }
export interface OpportunityDetail {
  id: string;
  title: string;
  organizer: string | null;
  category: Category;
  source_type: SourceType;
  original_url: string | null;
  poster_url: string | null;             // 포스터 공고의 원본 이미지
  easy_summary: string | null;
  apply_start_at: string | null;
  deadline_at: string | null;
  needs_review: boolean;
  extraction_confidence: number | null;
  uploader_masked: string | null;
  course_name: string | null;
  eligibility: {
    status: EligibilityStatus;
    display_status: DisplayStatus;
    summary: string;                     // 상태 사유 한 줄 (API v0.3 보완)
    reason_text: string | null;          // 탈락 사유
    missing_fields: string[];
    conditions: Condition[];
    evaluated_at: string;
  };
  documents: DocumentItem[];
  prep: {
    prepared: boolean;
    prep_plan_id: string | null;
    tasks_total: number;
    tasks_done: number;
    calendar_events: { id: string; provider: "google" | "ics" }[];
  };
  process: { extraction: ProcessStep[]; evaluated_at: string; prepare_run_id: string | null };
  reported_by_me: boolean;
}

// GET /runs/{id}: 포스터 추출·준비하기 진행 표시
export interface Run<R = unknown> {
  id: string;
  status: RunStatus;
  steps: { seq: number; tool: string; label: string; status: RunStatus; latency_ms: number | null }[];
  result: R | null;
  error: { code: string; message: string } | null;
}
export interface PosterExtractResult {
  kind: "poster_extract";
  draft: {
    title: string;
    organizer: string | null;
    category: Category;
    apply_start_at: string | null;
    deadline_at: string | null;
    easy_summary: string | null;
    requirements: { field: string; operator: string; value: unknown; condition_text: string; evidence_text: string | null; is_ambiguous: boolean }[];
    documents: { name: string; issuer: string | null; lead_days: number | null; effort_minutes: number | null; form_url: string | null }[];
    extraction_confidence: number;
    low_confidence_fields: string[];
  };
  duplicate_candidate: { opportunity_id: string; title: string } | null;
}
export interface PrepareResult {
  kind: "prepare";
  prep_plan_id: string;
  documents: DocumentItem[];
  tasks: { id: string; title: string; due_date: string; document_id: string | null }[];
  calendar_event: { id: string; provider: "google" | "ics"; starts_at: string } | null;
}

// GET /planner/tasks
export interface PlannerTask {
  id: string;
  title: string;
  due_date: string;
  is_done: boolean;
  source: "prep_plan" | "syllabus" | "lms_assignment" | "lms_announcement" | "manual";
  link: {
    type: "opportunity" | "syllabus_item" | "lms_assignment" | "lms_announcement" | null;
    id: string | null;
    title: string | null;                // 공고 제목 또는 과목명
    category: Category | null;           // 공고에서 온 할 일만
    html_url?: string;
  };
  auto_completed?: boolean;              // LMS 제출로 자동 완료
}
export interface PlannerMarker { kind: "deadline"; date: string; title: string; opportunity_id: string; category: Category; }
export interface PlannerResponse { items: PlannerTask[]; markers: PlannerMarker[]; }

// GET /notifications
export interface AppNotification {
  id: string;
  type: NotificationType;
  title: string;
  body: string | null;
  scheduled_at: string;
  read_at: string | null;
  link: {
    type: "opportunity" | "planner_task" | "lms_assignment" | "lms_module_item" | "lms_announcement";
    id: string;
    course_id?: string;                  // lms_* 링크의 과목 ID (API v0.3 보완)
    focus?: "profile_input";
  };
}
```

#### `web/src/types/lms.ts` (새 파일)

```ts
// LMS·강의자료 타입 (API 명세 8·9장). 화면은 @/types/api에서 가져간다
import type { RunStatus } from "@/types/api";

// GET /lms/connection
export interface LmsConnection {
  status: "active" | "error" | "disconnected";
  token_last4: string;
  last_synced_at: string | null;
  last_error: string | null;
}

// GET /lms/courses
export interface Course {
  id: string;
  canvas_course_id: number;
  name: string;
  short_name: string;
  has_syllabus: boolean;
  portal_syllabus_url: string;
  open_assignments: number;
  new_materials: number;
  next_due: { kind: "assignment" | "syllabus"; title: string; due_at: string } | null;
}

// GET /lms/courses/{id}
export type SubmissionState = "unsubmitted" | "submitted" | "graded" | "pending_review";
export type AnnouncementCategory = "schedule_change" | "material" | "opportunity" | "general";
export interface CourseDetail {
  course: { id: string; short_name: string; html_url: string; has_syllabus: boolean; portal_syllabus_url: string }; // html_url: 과목 홈 (API v0.3 보완)
  assignments: { id: string; title: string; due_at: string | null; submission_state: SubmissionState; html_url: string }[];
  module_items: { id: string; module_name: string; title: string; html_url: string; is_new: boolean; uploaded_file_id: string | null }[];
  announcements: { id: string; title: string; summary: string | null; category: AnnouncementCategory | null; posted_at: string; opportunity_id: string | null }[];
  syllabus_items: { id: string; item_type: "midterm" | "final" | "presentation" | "assignment" | "etc"; title: string; starts_at: string | null; is_confirmed: boolean }[];
  materials: { file_id: string; original_name: string | null; status: RunStatus }[];
}

// GET /materials/{file_id}: 강의자료 요약·구간 번역 (TODO(api): API 명세 8장 응답과 필드 이름 대조)
export interface MaterialDetail {
  file_id: string;
  original_name: string | null;
  total_pages: number;
  page_start: number;
  page_end: number;
  over_limit: boolean;
  overall_summary: string | null;
  status: RunStatus;
  sections: {
    id: string;
    seq: number;
    title: string;
    page_start: number;
    page_end: number;
    summary: string | null;
    translation_status: RunStatus | null; // null이면 번역 요청 전
    translation_url: string | null;
  }[];
}

// GET /lms/updates
export type LmsUpdate =
  | { type: "module_item"; id: string; course: { id: string; short_name: string }; module_name: string; title: string; html_url: string; first_seen_at: string; uploaded_file_id: string | null }
  | { type: "announcement"; id: string; course: { id: string; short_name: string }; title: string; summary: string | null; posted_at: string; category: AnnouncementCategory | null; attachment_count: number; opportunity_id: string | null; planner_task_id: string | null }
  | { type: "assignment"; id: string; course: { id: string; short_name: string }; title: string; due_at: string; submission_state: SubmissionState };
```

### 웹: 로그인과 콜백

#### `web/src/app/(auth)/login/page.tsx`

```tsx
"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createBrowserSupabase } from "@/lib/supabase/client";

const useMocks = process.env.NEXT_PUBLIC_USE_MOCKS === "true";

const errorMessages: Record<string, string> = {
  auth: "로그인을 마치지 못했어요. 다시 시도해 주세요.",
  missing_code: "로그인 정보가 없어요. 처음부터 다시 시도해 주세요.",
  session: "로그인이 만료됐어요. 다시 로그인해 주세요.",
  other_account: "캘린더를 연결할 때 다른 Google 계정을 골랐어요. 처음 쓰던 계정으로 다시 로그인한 뒤 연결해 주세요.",
};

function GoogleMark() {
  return (
    <svg aria-hidden="true" width="18" height="18" viewBox="0 0 48 48">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

function LoginCard() {
  const router = useRouter();
  const errorCode = useSearchParams().get("error");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(
    errorCode ? (errorMessages[errorCode] ?? errorMessages.auth) : null,
  );

  const signIn = async () => {
    setPending(true);
    setError(null);
    if (useMocks) {
      router.push("/onboarding");
      return;
    }
    // 로그인은 기본 범위(이메일·프로필)만 받는다. 캘린더 권한은 처음 등록할 때 따로 받는다 (증분 승인)
    const { error: signInError } = await createBrowserSupabase().auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });
    if (signInError) {
      setError("Google 로그인을 시작하지 못했어요. 잠시 후 다시 시도해 주세요.");
      setPending(false);
    }
  };

  return (
    <section className="mx-auto w-full max-w-[440px] rounded-[18px] border border-[#e5e7eb] bg-white p-8 text-center max-[760px]:p-6">
      <p className="text-[32px] font-bold text-[#4f6ef7]">UNIPIVOT</p>
      <h1 className="mt-4 text-[20px] font-bold leading-[1.45]">
        지원할 수 있는 장학금·정책·공모전을 찾아 준비 일정까지 만들어요
      </h1>
      <button
        type="button"
        onClick={signIn}
        disabled={pending}
        className="mt-8 flex h-[48px] w-full items-center justify-center gap-3 rounded-[10px] border border-[#e5e7eb] bg-white text-[15px] font-semibold text-[#181a20] transition hover:bg-[#f7f8fa] disabled:cursor-not-allowed disabled:opacity-50"
      >
        <GoogleMark />
        {pending ? "Google로 이동 중" : "Google로 시작하기"}
      </button>
      <p className="mt-3 text-[12px] leading-5 text-[#667085]">
        Google 계정으로 로그인해요. 캘린더는 마감일을 처음 등록할 때 따로 연결해요.
      </p>
      {error && (
        <p role="alert" className="mt-4 rounded-[10px] bg-[#fef2f2] p-3 text-[13px] text-[#c53030]">
          {error}
        </p>
      )}
    </section>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginCard />
    </Suspense>
  );
}
```

#### `web/src/app/auth/callback/route.ts`

```ts
import { isAuthApiError, isAuthSessionMissingError, type SupabaseClient } from "@supabase/supabase-js";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { safeNextPath, withQuery } from "@/lib/redirectPath";
import { createReadOnlyServerSupabase, createServerSupabase } from "@/lib/supabase/server";

// 로그인과 캘린더 연결이 함께 쓰는 콜백 (API 4장, 증분 승인)
// - 로그인: 세션만 만든다. 동의 전이면 홈의 AppFrame이 /onboarding으로 보낸다
// - 캘린더 연결(connect=calendar): Google 토큰을 백엔드에 한 번 넘겨 암호화 저장한다
// 어느 쪽이든 Google 토큰(provider_token·provider_refresh_token)은 브라우저 쿠키에 남기지 않는다.
// 코드 교환 직후 세션에만 실려 오므로, 세션을 한 번 새로 받아 Google 토큰이 없는 세션으로 바꾼다
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const next = safeNextPath(searchParams.get("next"));
  const connectCalendar = searchParams.get("connect") === "calendar";
  const toLogin = (reason: string) => NextResponse.redirect(`${origin}/login?error=${reason}`);
  // 캘린더 연결은 실패해도 로그인을 그대로 두고 원래 화면으로 돌려보낸다
  const backWith = (result: string) => NextResponse.redirect(`${origin}${withQuery(next, "calendar", result)}`);
  // Google 화면에서 취소·거절하면 code 없이 돌아온다
  if (!code) return connectCalendar ? backWith("error") : toLogin("missing_code");

  // 캘린더 연결 전에 로그인해 있던 사용자. Google에서 다른 계정을 고르면 세션이 그 계정으로 바뀌므로 비교한다
  const before = connectCalendar ? await signedInUserId() : null;
  if (before === undefined) return backWith("error");

  const supabase = await createServerSupabase();
  const { data, error } = await supabase.auth.exchangeCodeForSession(code);
  if (error || !data.session) return connectCalendar ? backWith("error") : toLogin("auth");
  if (!connectCalendar) {
    return (await dropGoogleTokens(supabase)) ? NextResponse.redirect(`${origin}${next}`) : toLogin("auth");
  }
  if (before && before !== data.session.user.id) {
    // 다른 계정의 토큰은 저장하지 않고, 바뀐 세션도 이 기기에서 지운다. 처음 계정으로 다시 로그인하게 한다
    // TODO: 처음 쓰는 Google 계정이었다면 Supabase 사용자만 생기고 남는다. 정리는 탈퇴(DELETE /me) 작업 때 정한다
    await endSession(supabase);
    return toLogin("other_account");
  }

  const { access_token, provider_token, provider_refresh_token } = data.session;
  let result = "error";
  try {
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/auth/google/tokens`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${access_token}` },
      body: JSON.stringify({ provider_token, provider_refresh_token }),
    });
    if (response.ok) result = "connected";
  } catch {
    // 백엔드에 닿지 못해도 로그인 세션은 그대로 두고, 돌아간 화면에서 다시 연결하게 한다
  }
  // refresh token을 못 받았을 때(422 GOOGLE_REFRESH_TOKEN_MISSING)도 error로 돌아가 다시 연결을 안내한다
  return (await dropGoogleTokens(supabase)) ? backWith(result) : toLogin("auth");
}

// 지금 로그인한 사용자 id. 세션이 없거나 끊겼으면 null(새 로그인처럼 진행), Auth 서버 오류로 확인하지 못하면 undefined.
// 쿠키를 바꾸지 않는 클라이언트로 확인한다(세션이 끊겨 있으면 auth-js가 PKCE 값까지 지워 교환이 실패한다)
async function signedInUserId(): Promise<string | null | undefined> {
  const { data, error } = await (await createReadOnlyServerSupabase()).auth.getUser();
  if (data.user) return data.user.id;
  const gone = isAuthSessionMissingError(error) || (isAuthApiError(error) && error.status < 500 && error.status !== 429);
  return !error || gone ? null : undefined;
}

// 세션을 새로 받아 Google 토큰이 없는 세션으로 바꾼다. 실패하면 Google 토큰이 남지 않게 이 기기에서 로그아웃한다
async function dropGoogleTokens(supabase: SupabaseClient): Promise<boolean> {
  if (!(await supabase.auth.refreshSession()).error) return true;
  await endSession(supabase);
  return false;
}

// 이 기기의 세션을 끝낸다. 로그아웃 요청이 실패해도 세션 쿠키는 지운다
async function endSession(supabase: SupabaseClient): Promise<void> {
  await supabase.auth.signOut({ scope: "local" });
  const cookieStore = await cookies();
  for (const { name } of cookieStore.getAll()) {
    if (name.startsWith("sb-") && name.includes("-auth-token")) cookieStore.delete(name);
  }
}
```

#### `web/src/lib/supabase/server.ts`

```ts
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

// 라우트 핸들러(로그인 콜백)에서 쓰는 Supabase 클라이언트
export async function createServerSupabase() {
  const cookieStore = await cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options));
          } catch {
            // 서버 컴포넌트에서 부르면 쿠키를 쓸 수 없다. 라우트 핸들러에서는 정상 동작한다
          }
        },
      },
    },
  );
}

// 쿠키를 읽기만 하는 클라이언트. 확인용 호출(getUser)이 세션·PKCE 쿠키를 바꾸거나 지우지 않게 한다
// (세션이 끊겨 있으면 auth-js가 저장소를 비우면서 코드 교환에 쓸 PKCE 값까지 지운다)
export async function createReadOnlyServerSupabase() {
  const cookieStore = await cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll() {},
      },
    },
  );
}
```

#### `web/src/lib/googleCalendar.ts`

```ts
import { createBrowserSupabase } from "@/lib/supabase/client";

export const CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events";

/**
 * 캘린더 쓰기 권한을 처음 받을 때 부른다(증분 승인, PRD F-01).
 * 부르는 곳: 준비하기 결과의 "캘린더에도 등록", 설정의 캘린더 연결·재연결, LMS 과제 자동 등록 켜기.
 *
 * Google 화면을 거쳐 /auth/callback?connect=calendar로 돌아오고, 콜백이 토큰을 백엔드에 저장한 뒤
 * next 경로로 보낸다(?calendar=connected 또는 ?calendar=error). 성공하면 페이지를 떠나고,
 * 시작하지 못하면 화면에 띄울 오류 문구를 돌려준다. 목 모드에서는 부르지 않는다.
 */
export async function connectGoogleCalendar(next: string): Promise<string | null> {
  const supabase = createBrowserSupabase();
  const redirectTo = new URL("/auth/callback", window.location.origin);
  redirectTo.searchParams.set("connect", "calendar");
  redirectTo.searchParams.set("next", next);
  // 로그인한 계정을 Google 계정 선택에 미리 고른다. 다른 계정을 고르면 콜백이 막는다
  const email = (await supabase.auth.getSession()).data.session?.user.email;
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: redirectTo.toString(),
      scopes: CALENDAR_SCOPE,
      // refresh token을 받으려면 offline + consent. 이미 받은 범위는 유지한다
      queryParams: {
        access_type: "offline",
        prompt: "consent",
        include_granted_scopes: "true",
        ...(email ? { login_hint: email } : {}),
      },
    },
  });
  return error ? "Google 캘린더 연결을 시작하지 못했어요. 잠시 후 다시 시도해 주세요." : null;
}
```

### 웹: 온보딩과 프로필 입력

#### `web/src/screens/Onboarding.tsx`

```tsx
import { useEffect, useMemo, useState } from "react";
import {
  consentRequired,
  errorMessage,
  fieldErrors,
  getDepartments,
  getMe,
  getProfile,
  LMS_CONNECT_READY,
  saveConsents,
  saveProfile,
  updateIncomeConsent,
} from "@/api/client";
import ConsentStep, { type ConsentChoice } from "@/components/onboarding/ConsentStep";
import IncomeConsentStep from "@/components/onboarding/IncomeConsentStep";
import LmsInviteStep from "@/components/onboarding/LmsInviteStep";
import ProfileStep from "@/components/onboarding/ProfileStep";
import Skeleton from "@/components/Skeleton";
import {
  buildProfileSteps,
  fromFormValues,
  toFormValues,
  validateProfile,
  withoutIncome,
  type ProfileErrors,
  type ProfileFormValues,
} from "@/lib/profileFields";
import useAsyncData from "@/lib/useAsyncData";

// 동의 문구를 바꾸면 버전도 바꾼다 (profiles.consent_version에 남는다)
const CONSENT_VERSION = "2026-10-07";
const CONSENT_FAILED = "동의를 저장하지 못했어요. 잠시 후 다시 눌러 주세요.";
const PROFILE_FAILED = "프로필을 저장하지 못했어요. 입력한 값은 그대로 있으니 다시 눌러 주세요.";

type Stage =
  | { kind: "consent" }
  | { kind: "profile"; index: number }
  | { kind: "income_consent"; index: number }
  | { kind: "lms" };

interface OnboardingProps {
  onDone: () => void;
}

export default function Onboarding({ onDone }: OnboardingProps) {
  // 학과 목록을 못 불러와도 온보딩은 진행한다 (학과는 나중에 설정에서 고른다)
  const request = useAsyncData(
    () => Promise.all([getMe(), getProfile(), getDepartments().catch(() => [])]),
    [],
  );
  const [stage, setStage] = useState<Stage | null>(null);
  const [values, setValues] = useState<ProfileFormValues | null>(null);
  const [errors, setErrors] = useState<ProfileErrors>({});
  const [incomeConsented, setIncomeConsented] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const departments = request.data?.[2];
  const steps = useMemo(() => buildProfileSteps(departments ?? []), [departments]);

  useEffect(() => {
    if (!request.data) return;
    const [me, profile] = request.data;
    setValues(toFormValues(profile));
    setIncomeConsented(me.income_info_consented);
    setStage(me.consented ? { kind: "profile", index: 0 } : { kind: "consent" });
  }, [request.data]);

  if (request.error) {
    return <p className="mx-auto max-w-[640px] rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">{request.error}</p>;
  }
  if (!request.data || !stage || !values) {
    return <Skeleton className="mx-auto h-[420px] w-full max-w-[640px] rounded-[18px]" />;
  }

  const [me, profile] = request.data;
  // LMS 연결이 준비되지 않았으면(실제 모드, LMS API 전) 마지막 LMS 단계를 건너뛴다
  const finish = () => (me.lms?.status === "active" || !LMS_CONNECT_READY ? onDone() : setStage({ kind: "lms" }));
  // 소득 단계는 선택 동의를 했을 때만 입력받고, 안 했으면 동의를 한 번 더 묻는다
  const openStep = (index: number) => {
    setErrors({});
    setError(null);
    if (index >= steps.length) finish();
    else if (steps[index].id === "income" && !incomeConsented) setStage({ kind: "income_consent", index });
    else setStage({ kind: "profile", index });
  };

  const agree = async (choice: ConsentChoice) => {
    setSaving(true);
    setError(null);
    try {
      const result = await saveConsents(CONSENT_VERSION, choice.incomeInfo);
      setIncomeConsented(result.income_info_agreed_at !== null);
      setStage({ kind: "profile", index: 0 });
    } catch (caught) {
      setError(errorMessage(caught, CONSENT_FAILED));
    } finally {
      setSaving(false);
    }
  };

  const agreeIncome = async (index: number) => {
    setSaving(true);
    setError(null);
    try {
      await updateIncomeConsent(true);
      setIncomeConsented(true);
      setStage({ kind: "profile", index });
    } catch (caught) {
      if (consentRequired(caught) === "terms_privacy") setStage({ kind: "consent" });
      setError(errorMessage(caught, CONSENT_FAILED));
    } finally {
      setSaving(false);
    }
  };

  // 단계마다 저장해서, 중간에 나가도 입력한 값이 남는다
  const saveStep = async (index: number) => {
    const nextErrors = validateProfile(values, steps[index].fields);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    setSaving(true);
    setError(null);
    try {
      const next = fromFormValues(values, profile);
      // 소득 3항목은 선택 동의를 했을 때만 보낸다 (설정의 ProfileForm과 같다)
      await saveProfile(incomeConsented ? next : withoutIncome(next));
      openStep(index + 1);
    } catch (caught) {
      // 동의가 빠졌으면 그 동의를 다시 묻는다(API 13장). 항목 오류는 입력란 아래에 보여 준다
      const consent = consentRequired(caught);
      const onIncomeStep = steps[index].id === "income";
      setErrors(fieldErrors(caught) as ProfileErrors);
      setError(errorMessage(caught, PROFILE_FAILED));
      if (consent === "terms_privacy") setStage({ kind: "consent" });
      if (consent === "income_info") {
        // 다른 곳에서 소득 동의를 철회했다. 소득 단계면 동의부터 다시 묻고, 아니면 소득 값은 빼고 다시 저장하게 한다
        setIncomeConsented(false);
        if (onIncomeStep) setStage({ kind: "income_consent", index });
        else setError("소득·수급 정보 동의가 꺼져 있어요. 소득 정보는 빼고 저장하니 다시 눌러 주세요.");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="mx-auto w-full max-w-[640px] rounded-[18px] border border-[#e5e7eb] bg-white p-8 max-[760px]:p-5">
      <p className="text-[13px] font-semibold text-[#4f6ef7]">UNIPIVOT 시작하기</p>
      <h1 className="mt-2 text-[24px] font-bold leading-[1.45]">{me.display_name}님에게 맞는 기회를 찾아드릴게요</h1>
      <div className="mt-6 border-t border-[#e5e7eb] pt-6">
        {stage.kind === "consent" && <ConsentStep saving={saving} onAgree={agree} />}
        {stage.kind === "profile" && (
          <ProfileStep
            step={steps[stage.index]}
            index={stage.index}
            total={steps.length}
            values={values}
            errors={errors}
            saving={saving}
            onChange={(key, value) => setValues((current) => (current ? { ...current, [key]: value } : current))}
            onBack={stage.index > 0 ? () => setStage({ kind: "profile", index: stage.index - 1 }) : undefined}
            onSkip={() => openStep(stage.index + 1)}
            onNext={() => saveStep(stage.index)}
          />
        )}
        {stage.kind === "income_consent" && (
          <IncomeConsentStep
            saving={saving}
            onAgree={() => agreeIncome(stage.index)}
            onSkip={() => openStep(stage.index + 1)}
            onBack={stage.index > 0 ? () => setStage({ kind: "profile", index: stage.index - 1 }) : undefined}
          />
        )}
        {stage.kind === "lms" && <LmsInviteStep onFinish={onDone} />}
        {error && <p role="alert" className="mt-4 text-[13px] text-[#c53030]">{error}</p>}
      </div>
    </section>
  );
}
```

#### `web/src/lib/profileFields.ts`

```ts
import type { Department, Profile } from "@/types/api";

// 판정용 프로필 17개 항목을 온보딩 4단계와 설정 화면이 함께 쓴다 (ERD profiles 컬럼과 1:1)
export type ProfileKey = keyof Profile;
export type ProfileFormValues = Record<ProfileKey, string>;
export type ProfileErrors = Partial<Record<ProfileKey, string>>;

export interface ProfileFieldConfig {
  key: ProfileKey;
  label: string;
  kind: "text" | "number" | "date" | "select";
  options?: { value: string; label: string }[];
  allowEmpty?: boolean; // select에 "선택 안 함"을 둘지 (기본 true)
  min?: number;
  max?: number;
  step?: number; // 1이면 정수만 받는다 (서버 int 항목)
  maxLength?: number; // 글자 수 상한 (서버 max_length와 같게)
  unit?: string;
  placeholder?: string;
  hint?: string;
}

export interface ProfileStepConfig {
  id: "academic" | "grades" | "age_region" | "income";
  title: string;
  description: string;
  sensitive?: boolean;
  fields: ProfileFieldConfig[];
}

const SIDO = [
  "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시",
  "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도",
  "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도",
];

// 소득·수급 3항목은 선택 동의(소득·수급 정보)를 해야 저장된다 (동의 없이 값을 보내면 403)
export function withoutIncome(profile: Profile): Profile {
  return { ...profile, income_bracket: null, median_income_pct: null, welfare_status: null };
}

// 학과 선택지는 GET /meta/departments 목록으로 만든다
export function buildProfileSteps(departments: Department[]): ProfileStepConfig[] {
  return [
    {
      id: "academic",
      title: "학적",
      description: "학과·학년·학적 상태 조건을 판정해요.",
      fields: [
        {
          key: "department",
          label: "학과",
          kind: "select",
          options: departments.map((department) => ({ value: department.name, label: department.name })),
          hint: departments.length === 0 ? "학과 목록을 불러오지 못했어요. 나중에 설정에서 고를 수 있어요." : undefined,
        },
        {
          key: "grade",
          label: "학년",
          kind: "select",
          options: [1, 2, 3, 4, 5, 6].map((grade) => ({ value: String(grade), label: `${grade}학년` })),
        },
        {
          key: "enrollment_status",
          label: "학적 상태",
          kind: "select",
          options: [
            { value: "enrolled", label: "재학" },
            { value: "on_leave", label: "휴학" },
            { value: "deferred_graduation", label: "졸업 유예" },
            { value: "graduated", label: "졸업" },
          ],
        },
        {
          key: "semesters_completed",
          label: "마친 학기 수",
          kind: "number",
          min: 0,
          max: 16,
          step: 1,
          unit: "학기",
          hint: "지금 다니는 학기는 빼고 세요. \"8학기 이내\" 같은 조건을 판정할 때 써요.",
        },
        {
          key: "is_international",
          label: "외국인 유학생",
          kind: "select",
          options: [
            { value: "false", label: "아니요" },
            { value: "true", label: "예" },
          ],
          hint: "유학생 전용 공고를 판정할 때 써요.",
        },
      ],
    },
    {
      id: "grades",
      title: "성적",
      description: "교내 장학금은 대부분 직전학기 성적을 봐요.",
      fields: [
        { key: "credits_total", label: "누적 이수학점", kind: "number", min: 0, max: 200, step: 0.5, unit: "학점" },
        { key: "credits_last_semester", label: "직전학기 이수학점", kind: "number", min: 0, max: 30, step: 0.5, unit: "학점" },
        { key: "gpa_total", label: "누적 평점", kind: "number", min: 0, max: 4.5, step: 0.01 },
        { key: "gpa_last_semester", label: "직전학기 장학용 평점(F 포함)", kind: "number", min: 0, max: 4.5, step: 0.01 },
        {
          key: "gpa_scale",
          label: "평점 만점",
          kind: "select",
          allowEmpty: false,
          options: [
            { value: "4.5", label: "4.5" },
            { value: "4.3", label: "4.3" },
          ],
        },
      ],
    },
    {
      id: "age_region",
      title: "나이·지역",
      description: "청년 정책은 만 나이와 주민등록 주소를 봐요.",
      fields: [
        { key: "birth_date", label: "생년월일", kind: "date" },
        {
          key: "military_service_months",
          label: "병역 복무 개월 수",
          kind: "number",
          min: 0,
          max: 60,
          step: 1,
          unit: "개월",
          hint: "해당자만 입력해요. 복무 기간만큼 청년 나이 상한이 늘어나는 정책이 있어요.",
        },
        {
          key: "region_sido",
          label: "거주 시·도",
          kind: "select",
          options: SIDO.map((sido) => ({ value: sido, label: sido })),
          hint: "주민등록 주소 기준이에요.",
        },
        { key: "region_sigungu", label: "거주 시·군·구", kind: "text", maxLength: 40, placeholder: "예: 안산시 단원구" },
      ],
    },
    {
      id: "income",
      title: "소득",
      description: "소득 기준이 있는 장학금·청년 정책을 판정해요. 모르면 비워 두세요.",
      sensitive: true,
      fields: [
        {
          key: "income_bracket",
          label: "학자금 지원구간",
          kind: "select",
          options: Array.from({ length: 11 }, (_, bracket) => ({
            value: String(bracket),
            label: bracket === 0 ? "기초·차상위" : `${bracket}구간`,
          })),
        },
        {
          key: "median_income_pct",
          label: "기준 중위소득",
          kind: "number",
          min: 0,
          max: 500,
          step: 1,
          unit: "%",
          hint: "가구 기준이에요. 학자금 지원구간과 서로 바꿔 계산하지 않아요.",
        },
        {
          key: "welfare_status",
          label: "기초생활수급·차상위",
          kind: "select",
          options: [
            { value: "none", label: "해당 없음" },
            { value: "near_poverty", label: "차상위계층" },
            { value: "basic_livelihood", label: "기초생활수급" },
          ],
        },
      ],
    },
  ];
}

const numericKeys = new Set<ProfileKey>([
  "grade", "semesters_completed", "credits_total", "credits_last_semester", "gpa_total",
  "gpa_last_semester", "gpa_scale", "military_service_months", "income_bracket", "median_income_pct",
]);
const booleanKeys = new Set<ProfileKey>(["is_international"]);

export function toFormValues(profile: Profile): ProfileFormValues {
  const values = {} as ProfileFormValues;
  for (const key of Object.keys(profile) as ProfileKey[]) {
    const value = profile[key];
    values[key] = value === null || value === undefined ? "" : String(value);
  }
  return values;
}

// 빈 칸은 null(판정 불가로 남김), 숫자 항목은 number, 예/아니요 항목은 boolean으로 바꾼다
export function fromFormValues(values: ProfileFormValues, base: Profile): Profile {
  const next: Record<string, unknown> = { ...base };
  for (const key of Object.keys(values) as ProfileKey[]) {
    const raw = values[key].trim();
    if (key === "gpa_scale") next[key] = raw === "" ? base.gpa_scale : Number(raw);
    else if (raw === "") next[key] = null;
    else if (booleanKeys.has(key)) next[key] = raw === "true";
    else next[key] = numericKeys.has(key) ? Number(raw) : raw;
  }
  return next as unknown as Profile;
}

export function validateProfile(values: ProfileFormValues, fields: ProfileFieldConfig[]): ProfileErrors {
  const errors: ProfileErrors = {};
  for (const field of fields) {
    const raw = values[field.key]?.trim() ?? "";
    if (raw === "" || field.kind !== "number") continue;
    const value = Number(raw);
    if (Number.isNaN(value)) errors[field.key] = "숫자로 입력해 주세요.";
    else if (field.step === 1 && !Number.isInteger(value)) errors[field.key] = "소수점 없이 입력해 주세요.";
    else if (field.min !== undefined && value < field.min) errors[field.key] = `${field.min} 이상으로 입력해 주세요.`;
    else if (field.max !== undefined && value > field.max) errors[field.key] = `${field.max} 이하로 입력해 주세요.`;
  }
  const scale = Number(values.gpa_scale || "4.5");
  for (const key of ["gpa_total", "gpa_last_semester"] as const) {
    const onStep = fields.some((field) => field.key === key);
    if (onStep && values[key] !== "" && Number(values[key]) > scale) {
      errors[key] = `평점 만점(${scale})보다 클 수 없어요.`;
    }
  }
  return errors;
}
```

#### `web/src/components/profile/ProfileFieldInput.tsx`

```tsx
import type { ProfileFieldConfig } from "@/lib/profileFields";

interface ProfileFieldInputProps {
  field: ProfileFieldConfig;
  value: string;
  error?: string;
  onChange: (value: string) => void;
}

export default function ProfileFieldInput({ field, value, error, onChange }: ProfileFieldInputProps) {
  const id = `profile-${field.key}`;
  const messageId = `${id}-message`;
  const inputClass = `mt-2 h-[42px] w-full rounded-[10px] border bg-white px-3 text-[14px] text-[#181a20] outline-none focus:border-[#4f6ef7] ${
    error ? "border-[#c53030]" : "border-[#e5e7eb]"
  }`;
  const message = error ?? field.hint;

  return (
    <div>
      <label htmlFor={id} className="text-[13px] font-semibold text-[#181a20]">
        {field.label}
      </label>
      {field.kind === "select" ? (
        <select
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={message ? messageId : undefined}
          className={inputClass}
        >
          {field.allowEmpty !== false && <option value="">선택 안 함</option>}
          {field.options?.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : (
        <div className="relative">
          <input
            id={id}
            type={field.kind}
            inputMode={field.kind === "number" ? "decimal" : undefined}
            value={value}
            min={field.min}
            max={field.max}
            step={field.step}
            maxLength={field.maxLength}
            placeholder={field.placeholder}
            onChange={(event) => onChange(event.target.value)}
            aria-invalid={Boolean(error)}
            aria-describedby={message ? messageId : undefined}
            className={`${inputClass} ${field.unit ? "pr-12" : ""}`}
          />
          {field.unit && (
            <span className="pointer-events-none absolute right-3 top-[29px] -translate-y-1/2 text-[13px] text-[#667085]">
              {field.unit}
            </span>
          )}
        </div>
      )}
      {message && (
        <p id={messageId} className={`mt-1 text-[12px] leading-5 ${error ? "text-[#c53030]" : "text-[#667085]"}`}>
          {message}
        </p>
      )}
    </div>
  );
}
```

#### `web/src/components/ProfileForm.tsx`

```tsx
import { useEffect, useMemo, useState } from "react";
import Button from "@/components/Button";
import ProfileFieldInput from "@/components/profile/ProfileFieldInput";
import {
  buildProfileSteps,
  fromFormValues,
  toFormValues,
  validateProfile,
  withoutIncome,
  type ProfileErrors,
  type ProfileFormValues,
} from "@/lib/profileFields";
import type { Department, Profile } from "@/types/api";

interface ProfileFormProps {
  profile: Profile;
  departments: Department[]; // GET /meta/departments
  incomeConsented: boolean; // GET /me의 income_info_consented
  saving?: boolean;
  serverErrors?: ProfileErrors; // 저장할 때 서버가 준 항목별 오류 (422 VALIDATION_FAILED)
  error?: string | null; // 저장 실패 문구
  submitLabel?: string;
  onCancel?: () => void;
  onSave: (profile: Profile) => void;
}

// 설정 화면용: 온보딩 4단계와 같은 항목 정의를 한 화면에 모두 보여준다
export default function ProfileForm({
  profile,
  departments,
  incomeConsented,
  saving = false,
  serverErrors,
  error,
  submitLabel = "저장",
  onCancel,
  onSave,
}: ProfileFormProps) {
  const [values, setValues] = useState<ProfileFormValues>(() => toFormValues(profile));
  const [errors, setErrors] = useState<ProfileErrors>({});
  const steps = useMemo(() => buildProfileSteps(departments), [departments]);
  // 소득 항목은 선택 동의를 했을 때만 입력받는다 (동의 전에는 저장하면 403)
  const editableFields = steps.flatMap((step) => (step.id === "income" && !incomeConsented ? [] : step.fields));

  useEffect(() => setValues(toFormValues(profile)), [profile]);
  useEffect(() => setErrors(serverErrors ?? {}), [serverErrors]);

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        const nextErrors = validateProfile(values, editableFields);
        setErrors(nextErrors);
        if (Object.keys(nextErrors).length > 0) return;
        const next = fromFormValues(values, profile);
        // 동의를 철회한 직후 화면에 남은 소득 값이 있어도 보내지 않는다
        onSave(incomeConsented ? next : withoutIncome(next));
      }}
    >
      <div className="flex flex-col gap-5">
        {steps.map((step) => (
          <section key={step.id} className={step.sensitive ? "rounded-[14px] bg-[#fff8e1] p-4" : ""}>
            <h3 className="text-[15px] font-bold">{step.title}</h3>
            {step.sensitive && (
              <p className="mt-1 text-[12px] font-semibold text-[#b7791f]">
                {incomeConsented
                  ? "자격 판정에만 쓰고, 동의를 철회하거나 탈퇴하면 바로 지워요"
                  : "소득·수급 정보는 선택 동의를 하면 입력할 수 있어요"}
              </p>
            )}
            {(step.id !== "income" || incomeConsented) && (
              <div className="mt-3 grid grid-cols-2 gap-4 max-[600px]:grid-cols-1">
                {step.fields.map((field) => (
                  <ProfileFieldInput
                    key={field.key}
                    field={field}
                    value={values[field.key]}
                    error={errors[field.key]}
                    onChange={(value) => setValues((current) => ({ ...current, [field.key]: value }))}
                  />
                ))}
              </div>
            )}
          </section>
        ))}
      </div>
      {error && <p role="alert" className="mt-4 text-[13px] text-[#c53030]">{error}</p>}
      <div className="mt-6 flex justify-end gap-2">
        {onCancel && <Button secondary onClick={onCancel}>취소</Button>}
        <Button type="submit" disabled={saving}>
          {saving ? "저장 중" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
```

### 웹: 설정

#### `web/src/app/(app)/settings/page.tsx`

```tsx
"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { CalendarResult } from "@/components/ConnectedServices";
import { useAppNavigate } from "@/lib/routes";
import Settings from "@/screens/Settings";

// 캘린더 연결 콜백이 돌려보낸 결과(?calendar=connected·error)를 한 번 읽고 주소에서 지운다.
// 새로 고침해도 같은 안내가 다시 뜨지 않게 하려는 것이다
function SettingsPage() {
  const navigate = useAppNavigate();
  const router = useRouter();
  const query = useSearchParams().get("calendar");
  const [calendarResult] = useState<CalendarResult | null>(
    query === "connected" || query === "error" ? query : null,
  );

  useEffect(() => {
    if (query) router.replace("/settings", { scroll: false });
  }, [query, router]);

  return <Settings navigate={navigate} calendarResult={calendarResult} />;
}

export default function Page() {
  return (
    <Suspense>
      <SettingsPage />
    </Suspense>
  );
}
```

#### `web/src/screens/Settings.tsx`

```tsx
import { useState } from "react";
import {
  consentRequired,
  DELETE_ACCOUNT_READY,
  deleteAccount,
  errorMessage,
  fieldErrors,
  getDepartments,
  getLmsConnection,
  getMe,
  getProfile,
  getSettings,
  NOTIFICATION_SETTINGS_READY,
  saveProfile,
  saveSettings,
} from "@/api/client";
import Button from "@/components/Button";
import ConnectedServices, { type CalendarResult } from "@/components/ConnectedServices";
import Header from "@/components/Header";
import IncomeConsentSetting from "@/components/IncomeConsentSetting";
import Modal from "@/components/Modal";
import NotificationSettings from "@/components/NotificationSettings";
import ProfileForm from "@/components/ProfileForm";
import Skeleton from "@/components/Skeleton";
import type { ProfileErrors } from "@/lib/profileFields";
import useAsyncData from "@/lib/useAsyncData";
import type { Me, Profile, Settings as SettingsData } from "@/types/api";
import type { Route } from "@/types/route";

interface SettingsProps {
  navigate: (route: Route) => void;
  calendarResult?: CalendarResult | null; // 캘린더 연결에서 돌아온 결과 (/settings?calendar=…)
}

const PROFILE_FAILED = "프로필을 저장하지 못했어요. 입력한 값은 그대로 있으니 다시 눌러 주세요.";

function SettingsSkeleton() {
  return (
    <>
      <Skeleton className="h-[70px] w-[320px]" />
      <Skeleton className="h-48 rounded-2xl" />
      <Skeleton className="h-44 rounded-2xl" />
      <Skeleton className="h-52 rounded-2xl" />
    </>
  );
}

export default function Settings({ navigate, calendarResult = null }: SettingsProps) {
  const request = useAsyncData(
    () =>
      Promise.all([
        getMe(),
        getProfile(),
        getSettings(),
        getLmsConnection(),
        getDepartments().catch(() => []),
      ]),
    [],
  );
  const [meOverride, setMeOverride] = useState<Me | null>(null);
  const [profileOverride, setProfileOverride] = useState<Profile | null>(null);
  const [settingsOverride, setSettingsOverride] =
    useState<SettingsData | null>(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteText, setDeleteText] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileError, setProfileError] = useState<{ message: string; fields: ProfileErrors } | null>(null);
  const [toast, setToast] = useState("");

  if (request.loading) return <SettingsSkeleton />;
  if (request.error || !request.data) {
    return (
      <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">
        {request.error ?? "설정을 불러오지 못했어요."}
      </p>
    );
  }

  const me = meOverride ?? request.data[0];
  const profile = profileOverride ?? request.data[1];
  const settings = settingsOverride ?? request.data[2];
  const departments = request.data[4];
  const age = profile.birth_date
    ? 2026 - Number(profile.birth_date.slice(0, 4))
    : null;
  const enrollmentLabels = {
    enrolled: "재학",
    on_leave: "휴학",
    deferred_graduation: "졸업 유예",
    graduated: "졸업",
  };
  const showToast = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(""), 2400);
  };
  const updateSettings = async (next: SettingsData) => {
    setSettingsOverride(await saveSettings(next));
  };
  const openProfile = (open: boolean) => {
    setProfileError(null);
    setProfileOpen(open);
  };
  // 저장하면 서버가 공고를 다시 판정한다. 내 정보(입력 개수)는 실패해도 저장 결과에 영향이 없게 따로 다시 받는다
  const submitProfile = async (next: Profile) => {
    setSavingProfile(true);
    setProfileError(null);
    try {
      setProfileOverride(await saveProfile(next));
      getMe().then(setMeOverride).catch(() => undefined);
      setProfileOpen(false);
      showToast("프로필을 바꿨어요. 공고를 다시 판정했어요");
    } catch (caught) {
      const consent = consentRequired(caught);
      if (consent === "terms_privacy") navigate({ name: "onboarding" });
      // 다른 곳에서 소득 동의를 철회했다: 내 정보를 다시 받아 소득 입력란을 닫는다
      if (consent === "income_info") getMe().then(setMeOverride).catch(() => undefined);
      setProfileError({ message: errorMessage(caught, PROFILE_FAILED), fields: fieldErrors(caught) as ProfileErrors });
    } finally {
      setSavingProfile(false);
    }
  };
  const removeAccount = async () => {
    setDeleteError(null);
    try {
      await deleteAccount();
      navigate({ name: "onboarding" });
    } catch (caught) {
      setDeleteError(errorMessage(caught, "탈퇴하지 못했어요. 잠시 후 다시 눌러 주세요."));
    }
  };

  return (
    <>
      <Header title="설정" subtitle="프로필, 연결 서비스와 알림 설정을 관리해요." />
      <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-[18px] font-semibold">내 프로필</h2>
            <p className="mt-1 text-[12px] text-[#667085]">
              {me.profile_completion.filled}/{me.profile_completion.total}개 입력 완료
            </p>
          </div>
          <Button secondary onClick={() => openProfile(true)}>수정</Button>
        </div>
        <div className="mt-4 grid grid-cols-5 gap-3 max-[900px]:grid-cols-2">
          {[
            ["학적", `${profile.department ?? "미입력"} · ${profile.enrollment_status ? enrollmentLabels[profile.enrollment_status] : "미입력"}`],
            ["성적", profile.gpa_last_semester ? `${profile.gpa_last_semester} / ${profile.gpa_scale}` : "미입력"],
            ["나이", age ? `${age}세` : "미입력"],
            ["지역", [profile.region_sido, profile.region_sigungu].filter(Boolean).join(" ") || "미입력"],
            ["소득", profile.income_bracket !== null ? `${profile.income_bracket}구간` : "미입력"],
          ].map(([label, value]) => (
            <div key={label} className="rounded-[12px] bg-[#f7f8fa] p-3">
              <p className="text-[11px] text-[#667085]">{label}</p>
              <p className="mt-1 text-[13px] font-semibold">{value}</p>
            </div>
          ))}
        </div>
      </section>
      <ConnectedServices
        me={me}
        lms={request.data[3]}
        calendarResult={calendarResult}
        onMeChange={setMeOverride}
      />
      {NOTIFICATION_SETTINGS_READY && <NotificationSettings settings={settings} onChange={updateSettings} />}
      <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
        <h2 className="text-[18px] font-semibold">계정</h2>
        <IncomeConsentSetting consented={me.income_info_consented} onChanged={async () => {
          setMeOverride(await getMe());
          setProfileOverride(await getProfile());
        }} />
        <button
          type="button"
          onClick={() => {
            setDeleteError(null);
            setDeleteOpen(true);
          }}
          className="mt-4 text-[13px] font-semibold text-[#c53030]"
        >
          탈퇴
        </button>
      </section>
      <Modal open={profileOpen} title="프로필 수정" onClose={() => openProfile(false)}>
        <ProfileForm
          profile={profile}
          departments={departments}
          incomeConsented={me.income_info_consented}
          saving={savingProfile}
          serverErrors={profileError?.fields}
          error={profileError?.message}
          onCancel={() => openProfile(false)}
          onSave={submitProfile}
        />
      </Modal>
      <Modal open={deleteOpen} title="계정 탈퇴" onClose={() => setDeleteOpen(false)}>
        {DELETE_ACCOUNT_READY ? (
          <>
            <p className="text-[14px] leading-6 text-[#344054]">
              모든 개인 정보와 토큰을 지워요. 공유한 포스터 공고는 이름 없이 남아요.
            </p>
            <label className="mt-4 block text-[13px] font-semibold">
              확인을 위해 탈퇴를 입력해 주세요
              <input value={deleteText} onChange={(event) => setDeleteText(event.target.value)} className="mt-2 h-[42px] w-full rounded-[10px] border border-[#e5e7eb] px-3 outline-none focus:border-[#c53030]" />
            </label>
            {deleteError && <p role="alert" className="mt-3 text-[13px] text-[#c53030]">{deleteError}</p>}
            <div className="mt-6 flex justify-end gap-2">
              <Button secondary onClick={() => setDeleteOpen(false)}>취소</Button>
              <Button disabled={deleteText !== "탈퇴"} onClick={removeAccount}>탈퇴</Button>
            </div>
          </>
        ) : (
          <>
            {/* TODO(api): DELETE /me가 생기면 지운다 */}
            <p className="text-[14px] leading-6 text-[#344054]">
              탈퇴는 아직 준비 중이에요. 준비되면 이 화면에서 바로 탈퇴할 수 있어요.
            </p>
            <div className="mt-6 flex justify-end">
              <Button onClick={() => setDeleteOpen(false)}>확인</Button>
            </div>
          </>
        )}
      </Modal>
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white">
          {toast}
        </div>
      )}
    </>
  );
}
```

#### `web/src/components/ConnectedServices.tsx` (새 파일)

```tsx
import { useState } from "react";
import { disconnectLms, errorMessage, MOCK_NOW, reconnectCalendar } from "@/api/client";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import { formatRelativeTime } from "@/lib/format";
import type { LmsConnection, Me } from "@/types/api";

export type CalendarResult = "connected" | "error";

interface ConnectedServicesProps {
  me: Me;
  lms: LmsConnection; // GET /lms/connection
  calendarResult: CalendarResult | null; // Google 화면에서 돌아온 결과 (/settings?calendar=…)
  onMeChange: (me: Me) => void; // 목 모드는 연결 결과를 바로 돌려준다
}

const RESULT_NOTICE: Record<CalendarResult, { text: string; tone: string }> = {
  connected: { text: "Google Calendar를 연결했어요.", tone: "text-[#15803d]" },
  error: { text: "Google Calendar를 연결하지 못했어요. 연결하기를 다시 눌러 주세요.", tone: "text-[#c53030]" },
};

// 설정의 "연결된 서비스": Google Calendar 연결(증분 승인, API 4장)과 LearningX 연결 상태·해제
export default function ConnectedServices({ me, lms: initialLms, calendarResult, onMeChange }: ConnectedServicesProps) {
  const [connecting, setConnecting] = useState(false);
  const [calendarError, setCalendarError] = useState<string | null>(null);
  const [lms, setLms] = useState(initialLms);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [disconnectError, setDisconnectError] = useState<string | null>(null);
  // 돌아온 결과는 지금 상태와 맞을 때만 보여 준다(연결됐는데 "못 했어요"를 띄우지 않는다)
  const notice = calendarResult && (calendarResult === "connected") === me.calendar_connected
    ? RESULT_NOTICE[calendarResult]
    : null;

  // 실제 모드는 Google 화면으로 떠나므로 성공하면 이 함수가 끝나지 않고 "Google로 이동 중"이 남는다
  const connectCalendar = async () => {
    setConnecting(true);
    setCalendarError(null);
    try {
      onMeChange(await reconnectCalendar());
    } catch (caught) {
      setCalendarError(errorMessage(caught, "Google Calendar 연결을 시작하지 못했어요. 잠시 후 다시 시도해 주세요."));
    } finally {
      setConnecting(false);
    }
  };

  const disconnect = async () => {
    setDisconnectError(null);
    try {
      setLms(await disconnectLms());
      setDisconnectOpen(false);
    } catch (caught) {
      setDisconnectError(errorMessage(caught, "연결을 해제하지 못했어요. 잠시 후 다시 눌러 주세요."));
    }
  };

  return (
    <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
      <h2 className="text-[18px] font-semibold">연결된 서비스</h2>
      <div className="mt-4 flex flex-col divide-y divide-[#e5e7eb]">
        <div className="flex items-center justify-between gap-4 py-4">
          <div>
            <p className="text-[14px] font-semibold">Google Calendar</p>
            <p className="mt-1 text-[12px] text-[#667085]">
              {me.calendar_connected ? "연결됨" : "연결되지 않음. 연결하면 준비 일정을 캘린더에도 넣을 수 있어요."}
            </p>
            {(calendarError || notice) && (
              <p role="status" className={`mt-1 text-[12px] font-semibold ${calendarError ? "text-[#c53030]" : notice?.tone}`}>
                {calendarError ?? notice?.text}
              </p>
            )}
          </div>
          {!me.calendar_connected && (
            <Button secondary disabled={connecting} onClick={connectCalendar}>
              {connecting ? "Google로 이동 중" : "연결하기"}
            </Button>
          )}
        </div>
        <div className="flex items-center justify-between gap-4 py-4">
          <div>
            <p className="text-[14px] font-semibold">LearningX</p>
            <p className="mt-1 text-[12px] text-[#667085]">
              {lms.status === "active"
                ? `토큰 끝 4자리 ${lms.token_last4} · 마지막 동기화 ${lms.last_synced_at ? formatRelativeTime(lms.last_synced_at, MOCK_NOW) : "없음"}`
                : "연결되지 않음"}
            </p>
          </div>
          {lms.status === "active" && (
            <Button secondary onClick={() => setDisconnectOpen(true)}>연결 해제</Button>
          )}
        </div>
      </div>
      <Modal open={disconnectOpen} title="LearningX 연결 해제" onClose={() => setDisconnectOpen(false)}>
        <p className="text-[14px] leading-6 text-[#344054]">
          연결을 해제하면 토큰을 바로 지워요. LearningX 설정에서도 토큰을 삭제해 주세요.
        </p>
        {disconnectError && <p role="alert" className="mt-3 text-[13px] text-[#c53030]">{disconnectError}</p>}
        <div className="mt-6 flex justify-end gap-2">
          <Button secondary onClick={() => setDisconnectOpen(false)}>취소</Button>
          <Button onClick={disconnect}>연결 해제</Button>
        </div>
      </Modal>
    </section>
  );
}
```

#### `web/src/components/NotificationSettings.tsx` (새 파일)

```tsx
import Badge from "@/components/Badge";
import type { NotificationType, Settings } from "@/types/api";

interface NotificationSettingsProps {
  settings: Settings; // GET /me/settings (P1)
  onChange: (next: Settings) => void;
}

const notificationOptions: { type: NotificationType; label: string }[] = [
  { type: "new_eligible", label: "새 지원 가능 공고" },
  { type: "deadline_soon", label: "공고 마감 임박" },
  { type: "new_assignment", label: "새 LMS 과제" },
  { type: "new_material", label: "새 강의자료" },
  { type: "task_due", label: "할 일 마감" },
  { type: "schedule_change", label: "수업 일정 변경" },
  { type: "profile_needed", label: "프로필 정보 필요" },
];

function Toggle({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-11 shrink-0 rounded-full ${checked ? "bg-[#4f6ef7]" : "bg-[#e5e7eb]"}`}
    >
      <span className={`absolute top-1 size-4 rounded-full bg-white transition ${checked ? "left-6" : "left-1"}`} />
    </button>
  );
}

// 설정의 알림 구역 (P1, F-06): 푸시 켜기, 종류별 끄기, LMS 과제 자동 캘린더 등록
export default function NotificationSettings({ settings, onChange }: NotificationSettingsProps) {
  return (
    <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
      <div className="flex items-center gap-2">
        <h2 className="text-[18px] font-semibold">알림</h2>
        <Badge tone="gray">P1</Badge>
      </div>
      <div className="mt-4 flex items-center justify-between gap-4">
        <span className="text-[14px] font-semibold">푸시 알림 켜기</span>
        <Toggle
          checked={settings.push_enabled}
          label="푸시 알림 켜기"
          onChange={(checked) => onChange({ ...settings, push_enabled: checked })}
        />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 max-[700px]:grid-cols-1">
        {notificationOptions.map((option) => (
          <div key={option.type} className="flex items-center justify-between gap-3 rounded-[10px] bg-[#f7f8fa] p-3">
            <span className="text-[13px]">{option.label}</span>
            <Toggle
              checked={!settings.muted_notification_types.includes(option.type)}
              label={option.label}
              onChange={(checked) =>
                onChange({
                  ...settings,
                  muted_notification_types: checked
                    ? settings.muted_notification_types.filter((item) => item !== option.type)
                    : [...settings.muted_notification_types, option.type],
                })
              }
            />
          </div>
        ))}
      </div>
      <div className="mt-4 flex items-center justify-between gap-4">
        <span className="text-[14px] font-semibold">LMS 과제 마감을 Google Calendar에 자동으로 넣기</span>
        <Toggle
          checked={settings.calendar_auto_lms}
          label="LMS 과제 마감을 Google Calendar에 자동으로 넣기"
          onChange={(checked) => onChange({ ...settings, calendar_auto_lms: checked })}
        />
      </div>
    </section>
  );
}
```

#### `web/src/components/IncomeConsentSetting.tsx`

```tsx
import { useState } from "react";
import { errorMessage, updateIncomeConsent } from "@/api/client";
import Button from "@/components/Button";
import Modal from "@/components/Modal";

interface IncomeConsentSettingProps {
  consented: boolean; // GET /me의 income_info_consented
  onChanged: () => Promise<void>; // 내 정보·프로필 다시 불러오기
}

// 설정 화면: 소득·수급 정보 선택 동의 켜기·끄기 (PATCH /me/consents)
export default function IncomeConsentSetting({ consented, onChanged }: IncomeConsentSettingProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = async (agree: boolean) => {
    setSaving(true);
    setError(null);
    try {
      await updateIncomeConsent(agree);
      // 동의는 바뀌었다. 화면을 다시 불러오지 못한 것은 동의 실패와 다르게 알린다
      await onChanged().catch(() => setError("동의는 바꿨어요. 화면을 새로 고치면 바뀐 내용이 보여요."));
    } catch (caught) {
      setError(errorMessage(caught, "동의를 바꾸지 못했어요. 잠시 후 다시 눌러 주세요."));
    } finally {
      setSaving(false);
      setConfirmOpen(false);
    }
  };

  return (
    <>
      <div className="mt-4 flex items-center justify-between gap-4">
        <div>
          <p className="text-[14px] font-semibold">소득·수급 정보 수집·이용 (선택)</p>
          <p className="mt-1 text-[12px] text-[#667085]">자격 판정에만 쓰고, 탈퇴하면 바로 지워요.</p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={consented}
          aria-label="소득·수급 정보 수집·이용 동의"
          disabled={saving}
          onClick={() => (consented ? setConfirmOpen(true) : change(true))}
          className={`relative h-6 w-11 shrink-0 rounded-full ${consented ? "bg-[#4f6ef7]" : "bg-[#e5e7eb]"}`}
        >
          <span className={`absolute top-1 size-4 rounded-full bg-white transition ${consented ? "left-6" : "left-1"}`} />
        </button>
      </div>
      {error && <p role="alert" className="mt-2 text-[12px] text-[#c53030]">{error}</p>}
      <Modal open={confirmOpen} title="소득·수급 정보 동의 철회" onClose={() => setConfirmOpen(false)}>
        <p className="text-[14px] leading-6 text-[#344054]">
          입력한 소득·수급 정보가 바로 지워져요. 소득 조건이 있는 공고는 다시 판정해요.
        </p>
        <div className="mt-6 flex justify-end gap-2">
          <Button secondary onClick={() => setConfirmOpen(false)}>취소</Button>
          <Button disabled={saving} onClick={() => change(false)}>동의 철회</Button>
        </div>
      </Modal>
    </>
  );
}
```

### 웹: 그 밖의 화면

#### `web/src/components/AppFrame.tsx`

```tsx
"use client";

import { createContext, Fragment, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  getMe,
  getNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  recordEvent,
} from "@/api/client";
import AppShell from "@/components/AppShell";
import StatusPreview from "@/dev/StatusPreview";
import { pathnameToRoute, useAppNavigate } from "@/lib/routes";
import useAsyncData from "@/lib/useAsyncData";
import type { AppNotification, Me } from "@/types/api";

// Make의 App.tsx가 하던 일: 내 정보·알림 불러오기, 동의 전이면 온보딩으로 보내기, 상태 미리보기.
// 동의를 마친 사용자가 앱을 열면 app_open을 한 번 기록한다(서버가 KST 하루 1건만 남긴다)
const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext);

const showDevTools = process.env.NEXT_PUBLIC_USE_MOCKS === "true";

export default function AppFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const navigate = useAppNavigate();
  const [revision, setRevision] = useState(0);
  const [notificationsOverride, setNotificationsOverride] = useState<AppNotification[] | null>(null);
  const [unreadOverride, setUnreadOverride] = useState<number | null>(null);
  const meRequest = useAsyncData(getMe, [revision]);
  const openRecorded = useRef(false);
  const notificationsRequest = useAsyncData(getNotifications, [revision]);

  useEffect(() => {
    setNotificationsOverride(null);
    setUnreadOverride(null);
  }, [revision]);

  useEffect(() => {
    if (meRequest.data && !meRequest.data.consented) router.replace("/onboarding");
  }, [meRequest.data, router]);

  useEffect(() => {
    if (!meRequest.data?.consented || openRecorded.current) return;
    openRecorded.current = true;
    recordEvent("app_open");
  }, [meRequest.data]);

  return (
    <MeContext.Provider value={meRequest.data}>
      <AppShell
        route={pathnameToRoute(pathname)}
        notifications={notificationsOverride ?? notificationsRequest.data ?? []}
        unreadNotifications={unreadOverride ?? meRequest.data?.unread_notifications ?? 0}
        markNotificationRead={async (id) => {
          const notifications = await markNotificationRead(id);
          setNotificationsOverride(notifications);
          setUnreadOverride(notifications.filter((item) => item.read_at === null).length);
        }}
        markAllNotificationsRead={async () => {
          setNotificationsOverride(await markAllNotificationsRead());
          setUnreadOverride(0);
        }}
        navigate={navigate}
      >
        <Fragment key={revision}>{children}</Fragment>
      </AppShell>
      {showDevTools && <StatusPreview onChange={() => setRevision((value) => value + 1)} />}
    </MeContext.Provider>
  );
}
```

#### `web/src/components/LmsConnectModal.tsx`

```tsx
import { useState } from "react";
import { connectLms, LMS_CONNECT_READY } from "@/api/client";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import type { LmsConnection } from "@/types/api";

interface LmsConnectModalProps {
  open: boolean;
  onClose: () => void;
  onConnected: (connection: LmsConnection) => void;
}

type ConnectStatus = "idle" | "checking" | "success" | "failure";

export default function LmsConnectModal({
  open,
  onClose,
  onConnected,
}: LmsConnectModalProps) {
  const [step, setStep] = useState(1);
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<ConnectStatus>("idle");
  const [connected, setConnected] = useState<LmsConnection | null>(null);

  const close = () => {
    setStep(1);
    setToken("");
    setStatus("idle");
    setConnected(null);
    onClose();
  };

  const connect = async () => {
    setStatus("checking");
    try {
      const result = await connectLms(token);
      setConnected(result);
      setStatus("success");
      onConnected(result);
    } catch {
      setStatus("failure");
    } finally {
      setToken("");
    }
  };

  // TODO(api): LMS 연결 API(9장)가 생기면 이 안내를 지운다. 그 전에는 토큰을 받지 않는다
  if (!LMS_CONNECT_READY) {
    return (
      <Modal open={open} title="LearningX 연결" onClose={close}>
        <p className="text-[14px] leading-6 text-[#344054]">
          LearningX 연결은 아직 준비 중이에요. 준비되면 이 화면에서 과제와 새 강의자료를 바로 볼 수 있어요.
        </p>
        <div className="mt-6 flex justify-end"><Button onClick={close}>확인</Button></div>
      </Modal>
    );
  }

  return (
    <Modal open={open} title="LearningX 연결" onClose={close}>
      <div className="mb-5 flex gap-2">
        {[1, 2, 3].map((item) => (
          <div
            key={item}
            className={`h-1.5 flex-1 rounded-full ${
              item <= step ? "bg-[#4f6ef7]" : "bg-[#e5e7eb]"
            }`}
          />
        ))}
      </div>
      {step === 1 && (
        <>
          <p className="text-[14px] font-semibold">액세스 토큰을 발급해 주세요.</p>
          <p className="mt-2 rounded-[10px] bg-[#eef2ff] p-3 text-[13px] leading-6 text-[#344054]">
            LearningX &gt; 계정 &gt; 설정 &gt; 승인된 통합 &gt; + 새 액세스 토큰
          </p>
          <div className="mt-4 grid grid-cols-3 gap-2">
            {[1, 2, 3].map((item) => (
              <div
                key={item}
                className="flex aspect-[4/3] items-center justify-center rounded-[10px] bg-[#e5e7eb] text-[12px] font-semibold text-[#667085]"
              >
                안내 {item}
              </div>
            ))}
          </div>
          <div className="mt-6 flex justify-end">
            <Button onClick={() => setStep(2)}>토큰 입력하기</Button>
          </div>
        </>
      )}
      {step === 2 && (
        <>
          <label>
            <span className="mb-2 block text-[14px] font-semibold">발급한 토큰 붙여넣기</span>
            <input
              type="password"
              autoComplete="off"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="토큰은 가려서 표시해요"
              className="h-[44px] w-full rounded-[10px] border border-[#e5e7eb] px-3 text-[14px] outline-none focus:border-[#4f6ef7]"
            />
          </label>
          <p className="mt-2 text-[12px] text-[#667085]">
            토큰 원문은 화면에 다시 표시하지 않아요.
          </p>
          <div className="mt-6 flex justify-between">
            <Button secondary onClick={() => setStep(1)}>이전</Button>
            <Button onClick={() => setStep(3)} disabled={!token.trim()}>다음</Button>
          </div>
        </>
      )}
      {step === 3 && status === "idle" && (
        <>
          <p className="text-[14px] leading-6 text-[#344054]">
            입력한 토큰으로 LearningX 과목과 과제를 불러올게요.
          </p>
          <div className="mt-6 flex justify-between">
            <Button secondary onClick={() => setStep(2)}>이전</Button>
            <Button onClick={connect}>연결하기</Button>
          </div>
        </>
      )}
      {step === 3 && status === "checking" && (
        <div className="py-10 text-center">
          <div className="mx-auto size-8 animate-spin rounded-full border-4 border-[#e5e7eb] border-t-[#4f6ef7]" />
          <p className="mt-4 text-[14px] font-semibold">토큰을 확인하고 있어요</p>
        </div>
      )}
      {step === 3 && status === "success" && connected && (
        <div className="py-6 text-center">
          <p className="text-[20px] font-bold text-[#15803d]">8개 과목을 불러왔어요</p>
          <p className="mt-2 text-[12px] text-[#667085]">
            연결된 토큰 끝 4자리 {connected.token_last4}
          </p>
          <div className="mt-6"><Button onClick={close}>완료</Button></div>
        </div>
      )}
      {step === 3 && status === "failure" && (
        <div className="py-6 text-center">
          <p className="text-[16px] font-bold text-[#c53030]">
            토큰을 확인할 수 없어요. 복사할 때 앞뒤 공백이 들어갔는지 확인해 주세요
          </p>
          <div className="mt-6">
            <Button onClick={() => {
              setStep(2);
              setStatus("idle");
            }}>
              다시 입력하기
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
```

#### `web/src/app/(app)/planner/page.tsx`

```tsx
"use client";

import { useAppNavigate } from "@/lib/routes";
import Planner from "@/screens/Planner";

export default function PlannerPage() {
  const navigate = useAppNavigate();
  return <Planner navigate={navigate} />;
}
```

#### `web/src/screens/Planner.tsx`

```tsx
import { useEffect, useState } from "react";
import {
  addManualPlannerTask,
  deleteManualPlannerTask,
  getMe,
  getPlanner,
  MOCK_TODAY,
  setPlannerTaskDone,
  updateManualPlannerTask,
} from "@/api/client";
import Button from "@/components/Button";
import Header from "@/components/Header";
import PlannerCalendar from "@/components/PlannerCalendar";
import PlannerDayPanel from "@/components/PlannerDayPanel";
import Skeleton from "@/components/Skeleton";
import useAsyncData from "@/lib/useAsyncData";
import type { PlannerResponse, PlannerTask } from "@/types/api";
import type { Route } from "@/types/route";

function monthRange(year: number, month: number) {
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const prefix = `${year}-${String(month).padStart(2, "0")}`;
  return { from: `${prefix}-01`, to: `${prefix}-${String(lastDay).padStart(2, "0")}` };
}

function PlannerSkeleton() {
  return (
    <>
      <Skeleton className="h-[70px] w-[390px]" />
      <div className="grid grid-cols-[1.77fr_1fr] gap-5">
        <Skeleton className="h-[650px] rounded-2xl" />
        <Skeleton className="h-[650px] rounded-2xl" />
      </div>
    </>
  );
}

export default function Planner({ navigate }: { navigate: (route: Route) => void }) {
  const [view, setView] = useState({
    year: Number(MOCK_TODAY.slice(0, 4)),
    month: Number(MOCK_TODAY.slice(5, 7)),
  });
  const [selectedDate, setSelectedDate] = useState(MOCK_TODAY);
  const [plannerOverride, setPlannerOverride] =
    useState<PlannerResponse | null>(null);
  const range = monthRange(view.year, view.month);
  const request = useAsyncData(
    () => Promise.all([getPlanner(range.from, range.to), getMe()]),
    [range.from, range.to],
  );

  useEffect(() => {
    setPlannerOverride(null);
  }, [range.from, range.to]);

  if (request.loading) return <PlannerSkeleton />;
  if (request.error || !request.data) {
    return (
      <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">
        {request.error ?? "일정을 불러오지 못했어요."}
      </p>
    );
  }

  const planner = plannerOverride ?? request.data[0];
  const me = request.data[1];
  const calendarConnected = me.calendar_connected;
  const selectedTasks = planner.items.filter(
    (task) => task.due_date === selectedDate,
  );
  const selectedMarkers = planner.markers.filter(
    (marker) => marker.date === selectedDate,
  );

  const refresh = async () => {
    setPlannerOverride(await getPlanner(range.from, range.to));
  };
  const toggleTask = async (task: PlannerTask) => {
    await setPlannerTaskDone(task.id, !task.is_done);
    await refresh();
  };

  return (
    <>
      <Header
        title="플래너"
        subtitle="공고 준비, LMS 과제, 수업 일정을 한곳에서 관리해요."
      />
      <section className="grid grid-cols-[1.77fr_1fr] gap-5 max-[1000px]:grid-cols-1">
        <PlannerCalendar
          year={view.year}
          month={view.month}
          planner={planner}
          selectedDate={selectedDate}
          onSelectDate={setSelectedDate}
          onMonthChange={(year, month) => setView({ year, month })}
        />
        <PlannerDayPanel
          date={selectedDate}
          tasks={selectedTasks}
          markers={selectedMarkers}
          onToggle={toggleTask}
          onAdd={async (title, date) => {
            await addManualPlannerTask(title, date);
            setSelectedDate(date);
            await refresh();
          }}
          onEdit={async (id, title, date) => {
            await updateManualPlannerTask(id, title, date);
            setSelectedDate(date);
            await refresh();
          }}
          onDelete={async (id) => {
            await deleteManualPlannerTask(id);
            await refresh();
          }}
        />
      </section>
      {/* 캘린더 연결은 설정 한 곳에서 한다(Google 화면을 거쳐 설정으로 돌아온다) */}
      <section className="flex items-center justify-between gap-4 rounded-[14px] border border-[#e5e7eb] bg-white p-[18px]">
        <div>
          <p className="text-[14px] font-semibold">
            <b className="mr-3 text-[#4f6ef7]">G</b>
            {calendarConnected ? "Google Calendar 연결됨" : "Google Calendar 연결 안 됨"}
          </p>
          <p className="ml-7 mt-1 text-[12px] text-[#667085]">
            {calendarConnected
              ? "준비 중인 공고 마감일과 LMS 과제 마감일을 Google Calendar에 등록해요."
              : "설정에서 연결하면 준비 일정과 마감일을 Google Calendar에 넣을 수 있어요."}
          </p>
        </div>
        {!calendarConnected && (
          <Button secondary onClick={() => navigate({ name: "settings" })}>
            설정에서 연결
          </Button>
        )}
      </section>
    </>
  );
}
```

#### `web/src/components/OpportunityPreparation.tsx`

```tsx
import { useState } from "react";
import {
  getOpportunity,
  MOCK_TODAY,
  prepareOpportunity,
} from "@/api/client";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import StatusBadge from "@/components/StatusBadge";
import {
  formatKstDate,
  formatKstShortDate,
  getDdayValue,
  isDeadlineSoon,
} from "@/lib/format";
import type { OpportunityDetail, PrepareResult } from "@/types/api";
import type { Route } from "@/types/route";

interface OpportunityPreparationProps {
  detail: OpportunityDetail;
  calendarConnected: boolean;
  navigate: (route: Route) => void;
  onOpenProfile: () => void;
  onOpenOriginal: () => void;
  onDetailChange: (detail: OpportunityDetail) => void;
}

type StepStatus = "idle" | "running" | "done";

const wait = (milliseconds: number) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

function deadlineCopy(detail: OpportunityDetail): string {
  const days = getDdayValue(detail.deadline_at, MOCK_TODAY);
  if (days === null) return "상시 모집";
  if (days === 0) return "오늘 마감";
  if (days > 0) return `마감까지 ${days}일`;
  return "마감됨";
}

export default function OpportunityPreparation({
  detail,
  calendarConnected,
  navigate,
  onOpenProfile,
  onOpenOriginal,
  onDetailChange,
}: OpportunityPreparationProps) {
  const [steps, setSteps] = useState<[StepStatus, StepStatus]>(["idle", "idle"]);
  const [result, setResult] = useState<PrepareResult | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [includeCalendar, setIncludeCalendar] = useState(true);
  const [finishing, setFinishing] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [targetDate, setTargetDate] = useState(""); // 상시 공고의 준비 목표일
  const ineligible = detail.eligibility.display_status === "ineligible";
  const deadlineSoon = isDeadlineSoon(detail.deadline_at, MOCK_TODAY);
  const applicationPeriod = `${detail.apply_start_at ? formatKstDate(detail.apply_start_at) : "시작일 미정"} ~ ${
    detail.deadline_at ? formatKstDate(detail.deadline_at) : "상시"
  }`;
  const reason = ineligible ? detail.eligibility.reason_text : detail.eligibility.summary;

  const startPreparation = async () => {
    setConfirmOpen(false);
    setCompleted(false);
    setResult(null);
    setSteps(["running", "idle"]);
    await wait(600);
    setSteps(["done", "running"]);
    const [prepared] = await Promise.all([
      prepareOpportunity(detail.id, false, targetDate || undefined),
      wait(600),
    ]);
    setSteps(["done", "done"]);
    setResult(prepared);
    const updated = await getOpportunity(detail.id);
    onDetailChange(updated);
  };

  const finishPreparation = async () => {
    setFinishing(true);
    if (includeCalendar && calendarConnected) {
      await prepareOpportunity(detail.id, true, targetDate || undefined);
    }
    const updated = await getOpportunity(detail.id);
    onDetailChange(updated);
    setFinishing(false);
    setCompleted(true);
  };

  const action = (() => {
    if (result) {
      return <Badge tone="green">일정 생성 완료</Badge>;
    }
    if (detail.prep.prepared && !result) {
      const progress =
        detail.prep.tasks_total > 0
          ? (detail.prep.tasks_done / detail.prep.tasks_total) * 100
          : 0;
      return (
        <div className="w-[210px]">
          <div className="flex justify-between text-[12px] font-semibold">
            <span>서류 {detail.prep.tasks_done}/{detail.prep.tasks_total} 완료</span>
            <button type="button" onClick={() => navigate({ name: "planner" })} className="text-[#4f6ef7]">
              플래너에서 보기
            </button>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#e5e7eb]">
            <div className="h-full rounded-full bg-[#4f6ef7]" style={{ width: `${progress}%` }} />
          </div>
        </div>
      );
    }
    if (detail.eligibility.display_status === "eligible") {
      if (!detail.deadline_at) {
        return (
          <div className="flex items-end gap-2">
            <label className="text-[12px] font-semibold text-[#667085]">
              목표일
              <input
                type="date"
                value={targetDate}
                min={MOCK_TODAY}
                onChange={(event) => setTargetDate(event.target.value)}
                className="mt-1 block h-[42px] rounded-[10px] border border-[#e5e7eb] px-3 text-[14px] text-[#181a20]"
              />
            </label>
            <Button onClick={startPreparation} disabled={!targetDate}>준비 일정 만들기</Button>
          </div>
        );
      }
      return <Button onClick={startPreparation}>준비 일정 만들기</Button>;
    }
    if (detail.eligibility.display_status === "missing_info") {
      return <Button onClick={onOpenProfile}>정보 입력</Button>;
    }
    if (detail.eligibility.display_status === "needs_review") {
      return <Button onClick={onOpenOriginal}>원문 보기</Button>;
    }
    return (
      <div className="flex gap-2">
        <span title="대체 공고 추천은 준비 중이에요">
          <Button disabled>대체 공고 보기</Button>
        </span>
        <Button secondary onClick={() => setConfirmOpen(true)}>그래도 준비하기</Button>
      </div>
    );
  })();

  return (
    <>
      <section className="flex items-center justify-between gap-5 rounded-2xl border border-[#e5e7eb] bg-white p-[22px] max-[760px]:items-start">
        <div>
          <div className="flex gap-2">
            <StatusBadge displayStatus={detail.eligibility.display_status} />
            {detail.needs_review && detail.eligibility.display_status === "eligible" && (
              <Badge tone="gray">원문 확인 필요</Badge>
            )}
          </div>
          <p className="mt-2 text-[16px] font-semibold">{reason}</p>
          <p className={`mt-2 text-[13px] ${deadlineSoon ? "font-semibold text-[#c53030]" : "text-[#667085]"}`}>
            {deadlineCopy(detail)}
          </p>
          <p className="mt-1 text-[12px] text-[#667085]">신청 기간 {applicationPeriod}</p>
        </div>
        {action}
      </section>
      {steps[0] !== "idle" && (
        <section className="rounded-[14px] border border-[#e5e7eb] bg-white p-[18px]">
          <h2 className="text-[15px] font-semibold">준비 일정 생성</h2>
          <div className="mt-3 flex flex-col gap-2">
            {["필요 서류 확인", "마감일에서 거꾸로 일정 짜기"].map((label, index) => (
              <div key={label} className="flex items-center justify-between rounded-[10px] bg-[#f7f8fa] px-4 py-3 text-[13px]">
                <span>{label}</span>
                <Badge tone={steps[index] === "done" ? "green" : "blue"}>
                  {steps[index] === "done" ? "완료" : steps[index] === "running" ? "진행 중" : "대기"}
                </Badge>
              </div>
            ))}
          </div>
        </section>
      )}
      {result && (
        <section className="rounded-[14px] border border-[#cfd7ff] bg-white p-[18px]">
          <h2 className="text-[16px] font-semibold">준비 일정을 만들었어요</h2>
          <div className="mt-3 flex flex-col gap-2">
            {result.tasks.map((task) => (
              <div key={task.id} className="flex justify-between rounded-[10px] bg-[#f7f8fa] px-4 py-3 text-[13px]">
                <span>{task.title}</span>
                <span className="text-[#667085]">{formatKstShortDate(task.due_date)}</span>
              </div>
            ))}
          </div>
          <label className="mt-4 flex items-center gap-2 text-[13px] font-medium">
            <input
              type="checkbox"
              checked={includeCalendar && calendarConnected}
              disabled={!calendarConnected}
              onChange={(event) => setIncludeCalendar(event.target.checked)}
              className="accent-[#4f6ef7]"
            />
            마감일을 Google Calendar에도 넣기
          </label>
          {!calendarConnected && <p className="mt-2 text-[12px] text-[#667085]">설정에서 Google Calendar를 연결하면 함께 넣을 수 있어요</p>}
          <div className="mt-4 flex justify-end">
            <Button onClick={finishPreparation} disabled={finishing}>
              {finishing ? "완료 중" : "완료"}
            </Button>
          </div>
        </section>
      )}
      {completed && (
        <div className="fixed bottom-6 left-1/2 z-[90] flex -translate-x-1/2 items-center gap-3 rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white">
          준비 일정을 만들었어요
          <button type="button" onClick={() => navigate({ name: "planner" })} className="text-[#cfd7ff]">
            플래너에서 보기
          </button>
        </div>
      )}
      <Modal open={confirmOpen} title="그래도 준비하기" onClose={() => setConfirmOpen(false)}>
        <p className="text-[14px] leading-6 text-[#344054]">
          지원 조건을 충족하지 못한 공고예요. 그래도 준비 일정을 만들까요?
        </p>
        <div className="mt-6 flex justify-end gap-2">
          <Button secondary onClick={() => setConfirmOpen(false)}>취소</Button>
          <Button onClick={startPreparation}>그래도 만들기</Button>
        </div>
      </Modal>
    </>
  );
}
```

### 규칙과 스킬

#### `web/CLAUDE.md`

```markdown
# web — Next.js 화면

Figma Make 시안을 옮긴 코드다. 아래 화면·데이터 규칙을 지키며 이어서 만든다.

기준 문서는 `docs/API_명세_v0.4.md`(계약), `docs/PRD_v0.9.md`(기능·우선순위), `docs/판정엔진_규칙.md`(판정 라벨·화면 문구)다.

## 구조

- `src/app/` 라우트. `(app)`은 사이드바가 있는 화면(`AppFrame`), `(auth)`는 로그인·온보딩, `auth/callback`은 로그인 콜백
- `src/screens/` 화면, `src/components/` 공통 조각. 페이지 파일은 화면에 `navigate`와 주소에서 읽은 값만 넘긴다
- `src/lib/routes.ts` Route ↔ URL 변환, `src/components/AppFrame.tsx` 내 정보·알림·동의 확인
- `src/api/client.ts` 화면이 쓰는 데이터 함수. 계정 함수는 `accountClient.ts`, LMS 함수는 `lmsClient.ts`에 두고 client.ts가 다시 내보낸다
- `src/api/http.ts` 실제 API 호출과 오류 도구(`apiFetch`, `errorMessage`, `fieldErrors`, `waitForRun`), `src/api/mockClient.ts` 목 모드 구현
- `src/mocks/` 목데이터, `src/dev/` 상태 미리보기(목 모드에서만 보인다)
- `src/types/api.ts` API 명세와 1:1인 타입. LMS·강의자료 타입은 `lms.ts`에 두고 api.ts가 다시 내보낸다

## 데이터

- 화면은 `src/api/client.ts` 함수로만 데이터를 받는다. 함수 이름·인자·반환 타입은 그대로 두고 안쪽만 목에서 `apiFetch`로 바꾼다(스킬 `mock-to-api`).
- 오류 문구는 `errorMessage(error, 화면 문구)`로 만들고, 422 항목 오류는 `fieldErrors`로 입력란 아래에 보여 준다. 실제 모드에서 아직 API가 없는 계정·LMS 기능은 목데이터 대신 빈 값이나 `NOT_READY` 오류를 준다(알림 설정 P1만 목 값).
- 타입 필드 이름은 API 명세와 같아야 한다. 없는 값이 필요하면 만들지 말고 그 자리에 `// TODO(api):`를 남긴다.
- `NEXT_PUBLIC_USE_MOCKS=true`면 목데이터와 상태 미리보기를 쓴다. 목 상태는 메모리에만 있어 새로고침하면 초기화된다.
- Supabase는 로그인과 세션 토큰에만 쓴다. 데이터는 DB를 직접 읽지 않고 FastAPI로만 받는다.
- 날짜·D-day·카테고리 이름은 `src/lib/format.ts`로만 만든다. 시간대는 KST, 마감일이 없으면 "상시"다.
- 페이지 파일은 `"use client"`로 쓰고, 주소 쿼리를 읽으면 `Suspense`로 감싼다. 화면 코드에서 `window`·`localStorage`를 직접 쓰지 않는다. 한 파일은 300줄을 넘지 않게 나눈다.

## 판정 라벨 (4종 고정)

| display_status | 라벨 | 톤 | 주 행동 버튼 |
| --- | --- | --- | --- |
| eligible | 지원 가능 | green | 준비 일정 만들기 |
| missing_info | 정보 필요 | yellow | 정보 입력 |
| needs_review | 원문 확인 필요 | gray | 원문 보기 |
| ineligible | 지원 어려움 | red | 대체 공고 보기 |

- "확인 필요"는 홈 요약 카드에서 정보 필요와 원문 확인 필요를 합쳐 부를 때만 쓴다.
- 지원 어려움 공고는 홈 목록 맨 아래 "지원 어려움 N개" 묶음 안에만 둔다. 기본은 접힘이다.
- `needs_review`가 true인 지원 가능 공고는 라벨 옆에 작은 "원문 확인 필요" 배지를 붙인다.

## 기준값

- 마감 임박은 D-3 이내(당일 포함), 새 공고는 서버가 준 `is_new`를 그대로 쓴다.
- 카테고리 칩: 전체, 장학금, 교내 프로그램, 청년정책, 공모전, 대외활동, 기타(research·exam·etc). 상세에서는 research를 "연구 참여", exam을 "시험·자격"으로 쓴다.
- 포스터는 JPG·PNG·WEBP·HEIC와 2쪽 이하 PDF, 20MB 이하다.
- 포스터 공고는 "내가 올린 포스터"로 표시하고 업로더 이름은 보여주지 않는다(`uploaded_by_me`). LMS 토큰은 끝 4자리만 보여준다.

## 디자인 토큰 (새 색·글꼴 추가 금지)

- 주색 #4f6ef7(hover #425fe0), 연한 주색 #eef2ff, 강조 테두리 #cfd7ff
- 글자 #181a20, 보조 #667085, 본문 보조 #344054, 비활성 #a0a4ab
- 배경 #f7f8fa, 카드 흰색, 테두리 #e5e7eb. 모서리는 버튼 10px, 카드 14–18px, 칩은 완전히 둥글게
- 상태 톤(글자/배경): green #15803d/#ecfdf3, yellow #b7791f/#fff8e1, red #c53030/#fef2f2, gray #475467/#f2f4f7
- 글꼴은 `src/app/layout.tsx`의 Inter + Noto Sans KR(next/font). `prefers-reduced-motion` 규칙을 유지하고, 움직임은 사용자 동작(열기·펼치기·완료)에 대한 반응에만 쓴다.

## 문구

- 해요체 평서문. 버튼은 실제로 일어나는 동작을 쓰고, 같은 동작은 흐름 내내 같은 이름을 쓴다("준비 일정 만들기" → 토스트 "준비 일정을 만들었어요").
- 오류는 무엇이 잘못됐고 어떻게 고치는지 말한다. 사과하거나 뭉뚱그리지 않는다. API 에러는 `code`로 분기한다(API 명세 13장).
- 빈 화면은 다음 행동 하나를 버튼과 함께 안내한다.
- 소득·수급 같은 민감 항목 위에는 "자격 판정에만 쓰고, 탈퇴하면 바로 지워요"를 붙인다.

## 하지 않는 것

- 라우터·상태관리 라이브러리 추가(아이콘은 lucide-react만), 채팅 UI
- 실명이나 토큰 원문 표시
- 화면 컴포넌트 안에서 `fetch` 직접 호출(데이터는 `client.ts`로만)
```

#### `.claude/skills/mock-to-api/SKILL.md`

```markdown
---
name: mock-to-api
description: web/src/api/client.ts의 목 함수를 실제 FastAPI 호출로 바꿀 때 쓴다. 화면 코드는 그대로 두고 함수 안쪽만 apiFetch로 바꾸며, 목 모드도 계속 동작하게 남긴다.
---

# 목 함수를 실제 API로 바꾸기

1. **대상 확인.** `docs/Nextjs_이식_가이드.md`의 "목 함수 → 실제 API" 표에서 함수와 엔드포인트를 찾는다. `api/`에 그 엔드포인트가 있고 테스트가 통과하는지 먼저 확인한다. 없으면 `api-endpoint` 스킬부터 한다.
2. **목 구현 옮기기.** 바꿀 함수의 기존 목 구현을 `src/api/mockClient.ts`로 같은 이름으로 옮긴다.
3. **교체.** 함수는 이름·인자·반환 타입을 그대로 두고 `USE_MOCKS`(`http.ts`)면 `mockClient`를, 아니면 `apiFetch`를 부른다. 함수가 `client.ts`가 다시 내보내는 파일(`accountClient.ts`·`lmsClient.ts`)에 있으면 그 파일에서 바꾼다.
4. **비동기 작업.** 202와 `run_id`를 받는 API는 `waitForRun`으로 결과를 기다리고, 진행 단계는 화면이 쓰던 형태로 넘긴다.
5. **에러.** `ApiError.code`로 분기한다(API 명세 13장 "프론트 처리" 열). 화면 문구는 `errorMessage`, 422 항목 오류는 `fieldErrors`로 만든다. 문구는 `web/CLAUDE.md`의 문구 규칙을 따른다.
6. **검사.** `npm run typecheck`, `NEXT_PUBLIC_USE_MOCKS=true npm run build`가 통과하고, `NEXT_PUBLIC_USE_MOCKS=false`로 실제 API를 붙여 그 화면 흐름을 한 번 눌러 본다.
7. **표 갱신.** 이식 가이드 표에서 해당 줄 비고에 "실제 API 연결"을 적는다.
```
