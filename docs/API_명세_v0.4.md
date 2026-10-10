# API 명세 — 학내 정보 에이전트 MVP

> 📝 문서 상태: 초안 v0.4 · 2026-10-06 · 기준 문서: PRD v0.9, ERD v0.9
>
> v0.4 변경: 캘린더 증분 승인, 선택 동의·학과 목록·사용 이벤트 API, 판정 결과 묶음(clause)·모름 사유·기준일, 공고 공개 범위, 포스터 공유·신고·강의자료 번역 우선 하향, LMS GET 제한, 실행 단계의 도구 선택 표시, 에러 코드 추가
>
> v0.4 보강(10/9, S1-5): 피드 판정 갱신, counts 기준, cursor 규칙
>
> v0.4 보강(10/10, S1-6): 공고 상세의 판정·공개 범위·순서·처리 과정 규칙
>
> v0.4 보강(10/10, S1-6b): 공고 상세 review_reasons
>
> v0.3 변경: 디자인 초안 대조 반영 — 엔드포인트 6개 추가(동의 기록, 설정, 알림함 목록·읽음, 과목 상세), 피드·상세에 `display_status`·`easy_summary`·`is_new`·조건 문구·`eligibility.summary`, 서류와 플래너 할 일 연결, 포스터 2쪽 PDF, 플래너 마감 `markers`, 상시 공고 `target_date`, LMS 과목 새 자료 수·`course.html_url`, 알림 `link.course_id`, 에러 코드 4개(`CONSENT_REQUIRED`·`PAGE_LIMIT_EXCEEDED`·`DB_UNAVAILABLE`·`INTERNAL_ERROR`)
>
> v0.2 변경: 강의자료 API를 구간 요약 + 선택 구간 번역 구조로 변경, 분량 상한을 토큰 기준으로 변경
>
> 이 문서는 **프론트(Next.js)와 백엔드(FastAPI) 사이의 계약**이다. W1에 확정하면 프론트는 이 형식의 목데이터로 화면을 먼저 만들고, 백엔드는 같은 형식으로 실제 응답을 맞춘다. FastAPI가 자동 생성하는 OpenAPI(`/docs`)가 최종 기준이 되도록 Pydantic 모델을 이 문서대로 작성하고, 프론트 타입은 `openapi-typescript`로 생성한다.

---

## 목차

1. 공통 규칙
2. 비동기 작업(에이전트 실행) 패턴
3. 엔드포인트 한눈에 보기
4. 인증 · 내 정보
5. 공고 피드 · 상세 · 신고
6. 업로드 · 포스터
7. 준비하기 · 플래너 · 캘린더
8. 강의계획서 · 강의자료
9. LMS 연동
10. 알림
11. 에이전트 실행 조회
12. 내부 · 운영 API
13. 에러 코드
14. 결정이 필요한 것

부록: 프론트 반영 목록

---

## 1. 공통 규칙

| 항목 | 규칙 |
| --- | --- |
| Base URL | `https://{api-host}/api/v1` |
| 인증 | `Authorization: Bearer {Supabase access token}`. FastAPI가 Supabase JWT를 검증해 `user_id`를 얻는다. 4장의 로그인 콜백을 제외한 모든 사용자 API에 필요 |
| 데이터 접근 | 프론트는 DB를 직접 읽지 않는다(기존). DB의 모든 테이블에 RLS가 켜져 있고 클라이언트 쓰기 정책은 없다. 백엔드는 테이블 소유자로 연결해 RLS를 받지 않으므로, 공고 조회 쿼리에 5장의 공개 범위를 직접 건다 |
| 형식 | JSON, 필드명 `snake_case`, UTF-8 |
| 시간 | 일시는 ISO 8601 + 오프셋 (`2026-10-15T23:59:00+09:00`), 날짜만은 `YYYY-MM-DD`. DB는 UTC 저장. 날짜로 바꿀 때(due_date, D-day, 판정 기준일)는 항상 Asia/Seoul 기준이다. 날짜에 따라 결과가 바뀌는 코드는 현재 시각을 인자로 받는다(테스트에서 고정) |
| ID | UUID 문자열. Canvas ID는 숫자 그대로 |
| 목록 | 커서 페이지네이션: `?limit=20&cursor={next_cursor}` → 응답 `{ "items": [...], "next_cursor": "..." \| null }` |
| 업로드 | `multipart/form-data`, 파일 1개, 최대 20MB. 강의자료 분량 상한은 업로드가 아니라 요약 요청 때 토큰 기준으로 판정(8장) |
| 에러 | `{ "error": { "code": "LMS_TOKEN_INVALID", "message": "사람이 읽는 메시지", "details": {} } }` (13장) |
| 상태 코드 | 200 조회·수정, 201 생성, 202 비동기 작업 접수, 204 삭제, 400 잘못된 요청, 401 인증 없음, 403 권한 없음, 404 없음, 409 충돌·중복, 413 파일 초과, 422 검증 실패, 429 한도 초과, 502 외부 서비스 오류 |
| 비밀값 | LMS 토큰·Google 토큰은 **요청 본문으로 받기만 하고 어떤 응답에도 내보내지 않는다.** 로그와 에러 추적에서 Authorization 헤더와 토큰 모양 문자열을 가린다. 프로필 값은 LLM 호출과 `tool_calls.input`에 넣지 않는다 |
| 파일 URL | Storage 파일은 API가 만든 서명 URL로만 준다. 수명은 5분이다(v0.3 `poster_url`의 1시간을 줄임) |
| 외부 호출 | LearningX 클라이언트는 GET 요청과 9장의 허용 경로만 호출한다 |

## 2. 비동기 작업(에이전트 실행) 패턴

LLM을 부르는 작업(포스터 추출, 준비하기, 계획서 추출, 강의자료 요약, LMS 동기화)은 수 초–수십 초가 걸린다. 그래서 요청은 바로 `202`와 `run_id`를 돌려주고, 프론트는 실행 상태를 조회한다. 이 실행 기록이 곧 "처리 과정 표시"(F-42)와 성공률·응답시간·비용 측정의 원천이다.

```mermaid
sequenceDiagram
    participant FE as Next.js
    participant API as FastAPI
    participant AG as 에이전트 워커
    FE->>API: POST /posters/extract {file_id}
    API->>AG: agent_runs 생성 후 작업 큐에 넣기
    API-->>FE: 202 {run_id}
    loop 1.5초 간격 (최대 60초)
        FE->>API: GET /runs/{run_id}
        API-->>FE: {status: running, steps: [...]}
    end
    AG->>API: 도구 호출마다 tool_calls 기록, 끝나면 result 저장
    FE->>API: GET /runs/{run_id}
    API-->>FE: {status: succeeded, result: {...}}
```

- 접수 응답: `202 { "run_id": "uuid", "status": "running" }`
- 폴링 간격 1.5초, 60초가 지나도 끝나지 않으면 "백그라운드에서 계속 처리 중" 안내 후 폴링 중단(완료되면 웹 푸시)
- 같은 작업을 중복 요청하면 진행 중인 `run_id`를 그대로 돌려준다(예: 같은 공고 준비하기 연타)
- MVP 작업 큐는 FastAPI `BackgroundTasks`로 시작하고, 부하가 생기면 별도 워커로 분리

## 3. 엔드포인트 한눈에 보기

| 분류 | 메서드 · 경로 | 설명 | 기능 | 우선 |
| --- | --- | --- | --- | --- |
| 인증 | `POST /auth/google/tokens` | 캘린더를 연결할 때 Google 토큰 저장 (로그인 때는 부르지 않음) | F-01, F-32 | P0 |
| 인증 | `GET /auth/hyin/start` · `GET /auth/hyin/callback` | HY-in 인증 | F-05 | P2 |
| 내 정보 | `GET /me` | 내 계정·연동 상태 요약 | F-01 | P0 |
| 내 정보 | `GET /me/profile` · `PATCH /me/profile` | 판정용 프로필 조회·수정(수정 시 재판정) | F-02–F-04 | P0 |
| 내 정보 | `POST /me/consents` | 약관·개인정보 동의 기록 | F-02 | P0 |
| 내 정보 | `GET /me/settings` · `PATCH /me/settings` | 알림·LMS 과제 자동 등록 설정 | F-06 | P1 |
| 내 정보 | `PATCH /me/consents` | 소득·수급 선택 동의와 철회 | F-02, F-06 | P0 |
| 메타 | `GET /meta/departments` | 학과 목록 | F-02 | P0 |
| 사용 기록 | `POST /events` | 화면에서만 알 수 있는 사용 이벤트 기록 | 8장 지표 | P0 |
| 내 정보 | `DELETE /me` | 탈퇴(모든 개인 데이터·토큰 삭제) | 7장 | P0 |
| 공고 | `GET /opportunities` | 추천 피드 | F-40 | P0 |
| 공고 | `GET /opportunities/{id}` | 공고 상세(조건별 판정표·서류·준비 상태) | F-41 | P0 |
| 공고 | `GET /opportunities/{id}/alternatives` | 대체 공고 | F-23 | P1 |
| 공고 | `POST /opportunities/{id}/reports` | 신고 | F-17 | P1 |
| 업로드 | `POST /files` | 파일 업로드 → `file_id` | F-13–F-15 | P0 |
| 포스터 | `POST /posters/extract` | 포스터 추출(비동기) | F-13 | P0 |
| 포스터 | `POST /posters/confirm` | 확인·수정 후 공고 등록(중복이면 병합) | F-13, F-16 | P0 |
| 준비 | `POST /opportunities/{id}/prepare` | 준비하기(서류·역산 일정·캘린더, 비동기) | F-30–F-32 | P0 |
| 플래너 | `GET /planner/tasks` · `POST /planner/tasks` | 플래너 조회·직접 추가 | F-43 | P0 |
| 플래너 | `PATCH /planner/tasks/{id}` · `DELETE /planner/tasks/{id}` | 완료 체크·수정·삭제 | F-31, F-43 | P0 |
| 캘린더 | `POST /calendar/events` · `DELETE /calendar/events/{id}` | 캘린더 등록·해제 | F-32 | P0 |
| 캘린더 | `GET /calendar/ics` | .ics 내려받기 | F-34 | P1 |
| 계획서 | `POST /syllabi/extract` · `POST /syllabi/{id}/confirm` | 계획서 일정 추출·확정 | F-14 | P0 |
| 강의자료 | `POST /materials` · `GET /materials/{file_id}` · `GET /materials` | 축소판 요약 | F-15 | P1 |
| 강의자료 | `POST /materials/{file_id}/translations` | 구간 번역 | — | 삭제 (확장 범위) |
| LMS | `POST /lms/connection` · `GET /lms/connection` · `DELETE /lms/connection` | 토큰 연결·상태·해제 | F-50 | P0 |
| LMS | `POST /lms/sync` | 즉시 동기화(대시보드 접속 시) | F-51 | P0 |
| LMS | `GET /lms/courses` | 수강 과목 + 계획서 바로가기 | F-14, F-51 | P0 |
| LMS | `GET /lms/courses/{id}` | 과목 상세: 과제·주차 자료·공지·계획서·내 자료, 열람 기록 | F-14, F-15, F-51–F-53 | P0 |
| LMS | `GET /lms/assignments` | 과제·제출 상태 | F-51 | P0 |
| LMS | `GET /lms/updates` | 새 주차학습 항목·과목 공지 피드 | F-52, F-53 | P0 |
| 알림 | `POST /push/subscriptions` · `DELETE /push/subscriptions` | 웹 푸시 구독·해제 | F-33 | P0 |
| 알림 | `GET /notifications` | 알림함 목록과 안 읽은 수 | F-35 | P0 |
| 알림 | `POST /notifications/read` | 읽음 처리(선택 또는 전체) | F-35 | P0 |
| 실행 | `GET /runs/{id}` | 에이전트 실행 상태·처리 과정·결과 | F-42 | P0 |
| 내부 | `POST /internal/jobs/{job}` | 스케줄러 배치(크롤링·LMS 동기화·알림) | 6장 | P0 |
| 내부 | `POST /internal/eval/run` | 테스트 시나리오 실행 | 8장 | P0 |
| 운영 | `POST /internal/jobs/crawl-contests` · `POST /admin/opportunities/{id}/restore` | 공모전 수집, 숨김 복구 | F-12, F-17 | P1 |

## 4. 인증 · 내 정보

### `POST /auth/google/tokens`

로그인과 캘린더 연결을 나눈다(증분 승인). 요청·응답 형식은 v0.2 그대로다.

1. **로그인**: supabase-js Google 로그인으로 기본 범위(이메일·프로필)만 받는다. 이 API는 부르지 않는다. `GET /me`의 `calendar_connected`는 false다.
2. **연결**: 캘린더가 필요한 순간에 Google 로그인을 한 번 더 부른다. 그 순간은 준비하기 결과 화면에서 "캘린더에도 등록"을 고를 때, 설정에서 캘린더를 연결할 때, LMS 과제 자동 등록을 켤 때다. 요청 값은 다음과 같다.
   - scope: `https://www.googleapis.com/auth/calendar.events`
   - `access_type=offline`, `prompt=consent`, `include_granted_scopes=true`
   - 돌아올 화면은 redirectTo의 `next`로 넘긴다

   콜백에서 받은 provider 토큰을 이 API로 보낸다.
3. **끊김**: refresh가 실패하면(만료·취소) 서버는 저장한 토큰을 지운다. 그 뒤 캘린더가 필요한 API는 `409 CALENDAR_NOT_CONNECTED`(`details.reason`: `not_connected` · `expired`)를 돌려주고, 프론트는 2번 연결 흐름으로 보낸다.

S1-1 완료 조건을 다음으로 바꾼다. 로그인만으로는 캘린더 권한을 묻지 않는다. 연결 후 이벤트를 만들 수 있다. access token이 만료된 뒤 refresh로 다시 만들 수 있다.

```json
// Request
{ "provider_token": "ya29...", "provider_refresh_token": "1//0g..." }

// Response 200
{ "calendar_connected": true, "scope": "calendar.events" }
```

에러: `GOOGLE_REFRESH_TOKEN_MISSING`(422, 재로그인 필요)

### `GET /auth/hyin/start` · `GET /auth/hyin/callback` (P1)

`start`는 HY-in OAuth 인증 페이지로 302 리다이렉트한다. `callback`은 받은 정보 중 **재학 여부·소속 학과·입학년도만** 프로필에 반영하고 학번·성명은 버린 뒤 프론트 설정 화면으로 리다이렉트한다.

### `GET /me`

```json
{
  "user_id": "uuid",
  "display_name": "김현준",
  "hyin_verified": false,
  "calendar_connected": false,
  "lms": { "status": "active", "last_synced_at": "2026-10-01T10:30:00+09:00" },
  "profile_completion": { "filled": 6, "total": 16 },
  "consented": true,
  "income_info_consented": false,
  "unread_notifications": 3
}
```

- `consented`: 약관·개인정보 동의를 마쳤는지. false면 프론트가 온보딩 동의 단계로 보낸다
- `unread_notifications`: 헤더 알림 배지 숫자
- `income_info_consented`: 소득·수급 정보 선택 동의를 했는지. false면 소득 입력란을 열지 않는다
- `profile_completion.total`에 유학생 여부가 더해져 15에서 16이 된다
- `calendar_connected`는 로그인만 한 상태에서는 false다(증분 승인)
- `hyin_verified`는 F-05가 P2라 MVP에서는 늘 false다

### `POST /me/consents` · `PATCH /me/consents`

```json
// POST /me/consents (온보딩 동의 단계) Request
{ "consent_version": "2026-10-06", "agree_terms": true, "agree_privacy": true, "agree_income_info": false }

// Response 200
{ "terms_agreed_at": "2026-10-06T14:00:00+09:00", "privacy_agreed_at": "2026-10-06T14:00:00+09:00",
  "income_info_agreed_at": null, "consent_version": "2026-10-06" }

// PATCH /me/consents (온보딩 소득 단계, 설정) Request
{ "agree_income_info": true }

// Response 200
{ "income_info_agreed_at": "2026-10-06T14:05:00+09:00" }
```

- `agree_income_info`는 선택 동의다. 빼면 false로 본다
- PATCH로 false를 보내면 동의 시각과 소득 3항목(`income_bracket`, `median_income_pct`, `welfare_status`)을 한 번에 지우고, 그 사용자의 판정을 다시 계산한다
- 필수 동의 전에는 PATCH도 `403 CONSENT_REQUIRED`를 돌려준다
- 둘 중 하나라도 false면 `422 VALIDATION_FAILED`
- 동의 전에는 `/me/profile` 수정과 공고·플래너 API가 `403 CONSENT_REQUIRED`를 돌려준다
- POST /me/consents에서 갖고 있던 소득 동의를 빼도 소득 3항목을 지우고 판정을 다시 계산한다.

### `GET /me/profile` · `PATCH /me/profile`

모든 필드 nullable. `PATCH`는 보낸 필드만 바꾸고 `null`을 보내면 지운다. 수정되면 해당 사용자의 판정을 다시 계산한다(코드 비교라 동기 처리).

```json
// PATCH Request (F-03 즉석 입력도 같은 API 사용)
{ "gpa_last_semester": 3.62, "semesters_completed": 5 }

// Response 200
{
  "profile": {
    "department": "인공지능학과", "grade": 3, "enrollment_status": "enrolled",
    "semesters_completed": 5,
    "credits_total": 98.0, "credits_last_semester": 18.0,
    "gpa_total": 3.71, "gpa_last_semester": 3.62, "gpa_scale": 4.5,
    "birth_date": null, "military_service_months": null,
    "region_sido": "경기도", "region_sigungu": "안산시",
    "income_bracket": null, "median_income_pct": null, "welfare_status": null,
    "is_international": false,
    "admission_year": null, "hyin_verified_at": null
  },
  "rejudged": { "changed": 3, "eligible": 12, "undetermined": 7, "ineligible": 9 }
}
```

- `department`에는 `GET /meta/departments`의 이름만 쓸 수 있다. 없는 이름은 `422 VALIDATION_FAILED`(`details.fields.department`)
- `is_international`을 추가한다(boolean, null이면 미입력)
- 소득 3항목은 선택 동의 전이면 `403 CONSENT_REQUIRED`(`details.consent = "income_info"`)
- 거주지역(`region_sido`, `region_sigungu`)은 주민등록 주소 기준이다. 입력 화면에 그렇게 적는다
- 보낸 항목 중 값이 실제로 바뀐 것만 저장하고, 바뀐 값이 있으면 그 사용자의 활성 공고를 모두 다시 판정한다. rejudged.changed는 판정이 있던 공고 중 라벨(display_status)이 바뀐 수이고, eligible·undetermined·ineligible은 GET /opportunities의 counts와 같은 기준이다.

에러: `VALIDATION_FAILED`(422, 예: `gpa_last_semester > gpa_scale`)

### `GET /me/settings` · `PATCH /me/settings` (P1)

```json
{ "push_enabled": true, "muted_notification_types": ["new_material"], "calendar_auto_lms": true }
```

- `PATCH`는 보낸 필드만 바꾸고, 행이 없으면 기본값으로 만든다
- `calendar_auto_lms`를 끄면 이후 새 과제만 캘린더에 넣지 않는다. 이미 등록한 일정은 지우지 않는다

### `GET /meta/departments`

```json
{ "items": [ { "name": "기계공학과", "college": "공학대학", "field_group": "공학계열" } ] }
```

- 위 값은 형식 예시다. 실제 목록은 seed 마이그레이션으로 넣는다
- `is_active`인 학과만 `sort_order`, 이름 순으로 준다. 로그인이 필요하다

### `POST /events`

```json
// Request
{ "event": "profile_prompt_shown", "opportunity_id": "uuid" }

// Response 204
```

- 프론트가 보내는 이벤트는 3가지다: `app_open`(앱을 열 때, KST 하루 1건만 저장), `profile_prompt_shown`(정보 입력창을 띄울 때), `lms_guide_opened`(LMS 연결 가이드를 열 때)
- `profile_prompt_submitted`, `lms_connected`는 서버가 해당 API 안에서 직접 기록한다. 프론트가 보내면 `422 VALIDATION_FAILED`
- 화면은 응답을 기다리지 않는다. 기록에 실패해도 화면은 그대로 둔다

### `DELETE /me`

`204`. Google·LMS 토큰, 프로필, 업로드 파일, 판정·플래너·캘린더 기록을 삭제한다. 사용자가 올린 공유 포스터 공고는 남기되 업로더를 비운다(ERD `on delete set null`). Google 캘린더에 이미 등록된 일정은 지우지 않는다.

## 5. 공고 피드 · 상세 · 신고

### 공개 범위

피드·상세·플래너는 모두 같은 규칙을 쓴다(ERD 5장, RLS와 같음).

- 활성 공고: 포스터는 올린 본인만, 과목 공지 공고는 그 과목 수강생만, 나머지는 로그인 사용자 모두 볼 수 있다
- 준비를 시작한 공고는 마감(`expired`)·숨김(`hidden`)이 되어도 본인에게 상세·서류·플래너가 계속 보인다. 피드에는 나오지 않는다
- 그 밖의 숨김·과목 비공개 공고는 `404 NOT_FOUND`다(v0.2 그대로)
- 준비를 시작한 공고는 병합(merged)되거나 수강을 끝낸 과목의 공지여도 본인에게 보인다. 공개 범위 안의 마감 공고(마감일이 지났거나 expired)는 준비하지 않아도 상세가 열린다(피드 include_expired로 카드가 보인다).

### `GET /opportunities`

| 파라미터 | 값 | 기본 |
| --- | --- | --- |
| `eligibility` | `eligible` \| `undetermined` \| `ineligible` \| `all`, 쉼표로 여러 개 | `all` |
| `category` | ERD `opportunity_category` 값, 쉼표로 여러 개 | 전체 |
| `source_type` | ERD `source_type` 값, 쉼표로 여러 개 | 전체 |
| `sort` | `deadline` \| `recent` | `deadline` |
| `include_expired` | `true` \| `false` | `false` |
| `limit`, `cursor` | 1–50 | 20 |

서버는 `status = active`이고, `visible_canvas_course_id`가 없거나 사용자가 그 과목 수강생인 공고만 내려준다.

- `eligibility`는 쉼표로 여러 값을 받는다. 홈은 기본 목록을 `eligibility=eligible,undetermined`로 부르고, "지원 어려움 N개" 묶음을 펼칠 때 `eligibility=ineligible`로 따로 부른다
- `sort=deadline`은 마감일 없는 공고를 맨 뒤로 보낸다
- `counts`는 카테고리 필터와 상관없이 전체 기준이다(ERD 집계 쿼리)

```json
{
  "items": [
    {
      "id": "uuid",
      "title": "2026-2 한양브레인 장학금",
      "organizer": "ERICA 학생지원팀",
      "category": "scholarship",
      "source_type": "school_notice",
      "deadline_at": "2026-10-15T23:59:00+09:00",
      "d_day": 14,
      "easy_summary": "직전학기 성적이 좋은 학생에게 등록금 일부를 감면해 줘요.",
      "is_new": true,
      "eligibility": {
        "status": "undetermined",
        "display_status": "missing_info",
        "summary": "직전학기 이수학점을 입력하면 판정할 수 있어요",
        "missing_fields": ["credits_last_semester"]
      },
      "recommend_reason": "인공지능학과 · 성적장학",
      "needs_review": false,
      "uploaded_by_me": false,
      "course_name": null,
      "prepared": false
    },
    {
      "id": "uuid",
      "title": "데이터베이스 연구실 연구 참여 학생 모집",
      "category": "research",
      "source_type": "lms_announcement",
      "deadline_at": null,
      "easy_summary": "데이터베이스 연구실에서 학부 연구 참여 학생을 모집해요.",
      "is_new": false,
      "eligibility": { "status": "eligible", "display_status": "eligible", "summary": "제시된 조건 없음", "missing_fields": [] },
      "needs_review": true,
      "uploaded_by_me": false,
      "course_name": "데이터베이스",
      "prepared": false
    }
  ],
  "next_cursor": "eyJkIjoiMjAyNi0xMC0xNSJ9",
  "counts": {
    "eligible": 8, "new_eligible": 2,
    "undetermined": 3, "missing_info": 2, "needs_review": 1,
    "ineligible": 9,
    "deadline_soon": 2
  }
}
```

- `uploaded_by_me`: 내가 올린 포스터인지. 포스터 카드는 주최 자리에 "내가 올린 포스터"를 쓴다. 업로더 이름은 표시하지 않는다
- `recommend_reason`(F-24, P1)은 MVP 초기엔 `null`이어도 된다
- `eligibility.display_status`: `eligible` \| `missing_info` \| `needs_review` \| `ineligible`. 화면 라벨(지원 가능·정보 필요·원문 확인 필요·지원 어려움)에 1:1로 대응한다
- `easy_summary`는 카드 설명 한 줄, `is_new`는 등록 7일 이내이고 아직 상세를 열지 않은 지원 가능 공고다
- 응답 전에 그 사용자의 낡은 판정을 다시 계산한다(기준은 ERD 5장).
- 요건 추출에 실패한 공고의 eligibility는 status undetermined, display_status needs_review, summary "원문 확인 필요: 자격 요건을 정리하지 못함", missing_fields []다. 판정 엔진이 오류를 낸 공고는 summary가 "원문 확인 필요: 조건을 판정하지 못함"이다.
- counts는 eligibility·category·source_type·include_expired와 상관없이 지금 보이는 활성 공고(마감 전) 전체 기준이다.
- sort=recent는 등록 최신순이다. 두 정렬 모두 값이 없는 공고가 맨 뒤이고, 값이 같으면 id 순이다.
- include_expired=true면 마감이 지났거나 expired인 공고도 준다.
- cursor는 같은 정렬·필터로 다음 페이지를 부를 때만 쓴다. 정렬·필터를 바꾸면 처음부터 다시 부른다. 다르거나 망가진 cursor는 422 VALIDATION_FAILED(details.fields.cursor)다.
- 알 수 없는 eligibility·category·source_type 값은 422 VALIDATION_FAILED이고 details.fields에 파라미터별로 한 번에 담는다. eligibility에 all이 섞이면 거르지 않는다.
- 판정한 뒤 같은 요청 안에서 들어온 공고는 다음 요청부터 보인다.

### `GET /opportunities/{id}`

```json
{
  "id": "uuid",
  "title": "2026-2 한양브레인 장학금",
  "organizer": "ERICA 학생지원팀",
  "category": "scholarship",
  "source_type": "school_notice",
  "original_url": "https://...",
  "easy_summary": "직전학기 성적이 좋은 학생에게 등록금 일부를 감면해주는 장학금이에요.",
  "apply_start_at": "2026-10-01T09:00:00+09:00",
  "deadline_at": "2026-10-15T23:59:00+09:00",
  "needs_review": false,
  "extraction_confidence": 0.92,
  "status": "active",
  "uploaded_by_me": false,
  "course_name": null,
  "poster_url": null,
  "attachments": [
    { "id": "uuid", "file_name": "2026-2 장학 안내.hwp", "source_url": "https://...", "extract_status": "succeeded" }
  ],
  "eligibility": {
    "status": "undetermined",
    "display_status": "missing_info",
    "basis_date": "2026-10-15",
    "requirements_version": 1,
    "missing_fields": ["grade"],
    "clauses": [
      { "clause_no": 1, "outcome": "unknown", "condition_count": 2 },
      { "clause_no": 2, "outcome": "pass", "condition_count": 2 }
    ],
    "conditions": [
      { "requirement_id": "uuid", "clause_no": 1, "field": "grade", "label": "학년",
        "condition_text": "4학년", "user_value_text": null, "outcome": "unknown", "unknown_reason": "missing_profile",
        "evidence_text": "직전학기 12학점 이상 (단, 4학년은 9학점)", "is_ambiguous": false },
      { "requirement_id": "uuid", "clause_no": 1, "field": "credits_last_semester", "label": "직전학기 이수학점",
        "condition_text": "12학점 이상", "user_value_text": "10학점", "outcome": "fail", "unknown_reason": null,
        "evidence_text": "직전학기 12학점 이상 (단, 4학년은 9학점)", "is_ambiguous": false },
      { "requirement_id": "uuid", "clause_no": 2, "field": "grade", "label": "학년",
        "condition_text": "4학년 제외", "user_value_text": null, "outcome": "unknown", "unknown_reason": "missing_profile",
        "evidence_text": "직전학기 12학점 이상 (단, 4학년은 9학점)", "is_ambiguous": false },
      { "requirement_id": "uuid", "clause_no": 2, "field": "credits_last_semester", "label": "직전학기 이수학점",
        "condition_text": "9학점 이상", "user_value_text": "10학점", "outcome": "pass", "unknown_reason": null,
        "evidence_text": "직전학기 12학점 이상 (단, 4학년은 9학점)", "is_ambiguous": false }
    ]
  },
  "documents": [
    { "id": "uuid", "name": "재학증명서", "issuer": "한양인 포털", "how_to": "포털 > 증명서 발급", "lead_days": 1, "effort_minutes": null, "form_url": null, "is_required": true, "task_id": "uuid", "is_done": true },
    { "id": "uuid", "name": "장학금 신청서", "issuer": "공고 첨부파일", "how_to": "공고 첨부 양식을 내려받아 작성", "lead_days": 0, "effort_minutes": 30, "form_url": "https://...", "is_required": true, "task_id": "uuid", "is_done": false }
  ],
  "prep": {
    "prepared": true,
    "prep_plan_id": "uuid",
    "tasks_total": 3,
    "tasks_done": 1,
    "calendar_events": [ { "id": "uuid", "provider": "google" } ]
  },
  "process": {
    "extraction": [
      { "seq": 1, "label": "공고 원문 읽기", "status": "succeeded", "latency_ms": 2100 },
      { "seq": 2, "label": "지원 자격 정리", "status": "succeeded", "latency_ms": 2340 }
    ],
    "evaluated_at": "2026-10-05T09:12:00+09:00",
    "prepare_run_id": null
  },
  "reported_by_me": false
}
```

- 조건 `outcome`: `pass` \| `fail` \| `unknown`
- `label`은 백엔드가 `field` → 한글 이름으로 변환해 내려준다(프론트에 매핑표를 두지 않기 위함)
- `condition_text`·`user_value_text`는 백엔드가 field·operator·value로 만든 화면용 문구다. 미입력이면 `user_value_text`는 null
- `eligibility.summary`는 상태 카드에 쓰는 사유 한 줄이다
- `conditions`는 v0.3처럼 평평한 목록이고, `clause_no`로 묶는다. `clauses`는 묶음별 결과 요약이다. 화면은 `condition_count`가 2 이상인 묶음을 "다음 중 하나" 상자로 그린다
- `unknown_reason` 값은 다음과 같다
  - `missing_profile`: 프로필 값이 없음. "정보 필요"로 이어진다
  - `ambiguous`: 요건이 모호함
  - `unsupported_field`: 프로필로 판정할 수 없는 조건
  - `basis_mismatch`: 지역 기준·소득 기준·평점 만점이 달라 비교할 수 없음
  - `null`: 결과가 충족이나 불충족임
- `missing_fields`에는 결과가 "모름"인 묶음에서 `missing_profile`인 조건의 항목만 넣는다. 이미 충족한 묶음의 빈 항목은 묻지 않는다(위 예에서는 묶음 2의 학년)
- `basis_date`: 만 나이·학년·재학 상태를 따진 기준일
- `status`: 공고 상태다. 준비한 공고가 마감·숨김이 되면 화면 위에 "마감된 공고예요" 같은 안내를 띄운다
- `attachments`: 학교 공지의 첨부다. `extract_status`는 `succeeded` · `failed` · `skipped`(에이전트가 읽지 않음) 중 하나다. 실패한 첨부가 있으면 `needs_review`가 true다
- `reported_by_me`는 P1이다(신고와 함께)
- `missing_fields`는 정보 입력창(F-03)에 띄울 항목이다
- 서류의 `task_id`·`is_done`은 준비하기 전에는 null이고, 체크는 기존 `PATCH /planner/tasks/{task_id}`로 한다
- `poster_url`은 포스터 공고의 원본 이미지(Storage 서명 URL, 5분), `course_name`은 과목 공지에서 온 공고의 과목명이다
- `process.extraction`은 추출 실행에서 라벨·상태·소요 시간만 뽑은 것이라 배치 실행이나 남의 포스터도 내려준다. `GET /runs/{id}`의 본인 실행 제한은 그대로 둔다
- 이 API를 부르면 `opportunity_views`를 upsert한다(`first_viewed_at` 유지, `last_viewed_at` 갱신)
- 응답 전에 그 공고를 지금 프로필로 다시 판정해 저장한다(evaluated_at = 요청 시각). reason_text는 피드 카드의 summary와 같다.
- 응답에 uploader_masked는 없다(피드와 같다. 업로더 표시는 공유와 함께 P1). poster_url은 포스터 업로드(W6)부터 채운다.
- 요건 추출에 실패한 공고의 eligibility는 status undetermined, display_status needs_review, reason_text "원문 확인 필요: 자격 요건을 정리하지 못함"이다. basis_date·evaluated_at은 null이고 missing_fields·clauses·conditions와 process.extraction은 []다. 판정 엔진이 오류를 낸 공고는 reason_text가 "원문 확인 필요: 조건을 판정하지 못함"이고 clauses·conditions가 []다.
- conditions는 묶음 순서이고, 묶음 안에서는 추출 순서(원문 순서)다. operator·value는 요건 값이고, user_value는 비교에 쓴 내 값(나이는 기준일의 만 나이, 미입력이면 null)이다.
- documents는 필수 서류가 먼저, 그다음 이름 순이다. attachments에는 학교 다운로드 주소(source_url)가 있는 첨부만 준다.
- 형식이 틀린 id는 422 VALIDATION_FAILED(details.fields.opportunity_id)다.
- 상세를 열면 opportunity_views를 upsert한다. first_viewed_at은 그대로 두고 last_viewed_at은 늦은 쪽을 남긴다. 404면 남기지 않는다.
- review_reasons(string[]): needs_review를 켠 이유(요건 추출·공지 가져오기)다. 주소를 지우고 공백을 한 칸으로 줄인 한 줄(최대 200자)씩이고, 10줄이 넘으면 앞 10줄 뒤에 '외 N건'이 온다. 첨부는 파일 이름으로 쓴다. 이유가 없거나 S1-6b 전에 추출한 공고는 []다. 화면은 처리 과정(F-42)에 일반 텍스트로 보여 준다(자동 링크·마크다운 없이).

### `GET /opportunities/{id}/alternatives` (P1)

부적격 공고에 대해 같은 카테고리·비슷한 난이도의 **적격** 공고 최대 3개. 응답은 피드 아이템과 같은 형식의 `items` 배열.

### `POST /opportunities/{id}/reports` (P1)

P1로 내린다. 형식은 그대로 둔다.

```json
// Request
{ "reason": "wrong_info", "detail": "마감일이 10/20으로 바뀌었어요" }

// Response 201
{ "reported": true, "hidden": false }
```

- 포스터 공고(`source_type = poster`)만 신고 가능. 그 외는 `400 REPORT_NOT_ALLOWED`
- 같은 사용자가 다시 신고하면 `409 ALREADY_REPORTED`
- 서로 다른 3명째 신고에서 `hidden: true`

## 6. 업로드 · 포스터

### `POST /files`

```
Content-Type: multipart/form-data
file: (binary)
kind: poster | syllabus | lecture_material
lms_course_id: (선택) uuid
lms_module_item_id: (선택) uuid — 새 자료 알림에서 넘어온 경우
```

```json
// Response 201
{ "file_id": "uuid", "kind": "lecture_material", "page_count": 42, "duplicate_of": null }
```

- 같은 사용자가 같은 파일(sha256)을 같은 kind로 다시 올리면 새로 저장하지 않고 `200 { "file_id": "기존 id", "reused": true }`를 준다. 새 파일은 `201`이다(`duplicate_of`로도 알려준다)
- 에러: `FILE_TOO_LARGE`(413), `PAGE_LIMIT_EXCEEDED`(413), `UNSUPPORTED_FILE_TYPE`(400), `DAILY_UPLOAD_LIMIT`(429)
- 허용 형식: poster는 jpg·png·webp·heic와 **2쪽 이하 PDF**, syllabus·lecture_material은 pdf. 포스터 PDF가 3쪽 이상이면 `413 PAGE_LIMIT_EXCEEDED`
- 업로드한 파일 이름을 `files.original_name`에 저장한다

### `POST /posters/extract`

```json
// Request
{ "file_id": "uuid" }

// Response 202
{ "run_id": "uuid", "status": "running" }
```

완료 시 `GET /runs/{run_id}`의 `result`:

```json
{
  "kind": "poster_extract",
  "draft": {
    "title": "2026 전국 대학생 SW 창업 아이디어톤",
    "organizer": "과학기술정보통신부",
    "category": "contest",
    "apply_start_at": null,
    "deadline_at": "2026-10-20T18:00:00+09:00",
    "easy_summary": "...",
    "requirements": [
      { "field": "enrollment_status", "operator": "in", "value": ["enrolled", "on_leave"], "condition_text": "재학생 또는 휴학생", "evidence_text": "국내 대학 재학생 및 휴학생", "is_ambiguous": false }
    ],
    "documents": [ { "name": "참가신청서", "issuer": "주최측 홈페이지", "lead_days": 2, "effort_minutes": 60, "form_url": null } ],
    "extraction_confidence": 0.71,
    "low_confidence_fields": ["deadline_at"]
  },
  "duplicate_candidate": { "opportunity_id": "uuid", "title": "2026 전국 대학생 SW 창업 아이디어톤" }
}
```

- `low_confidence_fields`는 확인 화면에서 강조 표시
- 확인 화면은 요건을 `condition_text` 문장으로 보여주고 행 단위로 지울 수 있다
- `duplicate_candidate`가 있으면 "이미 등록된 공고예요" 안내 후 그 공고로 이동 선택지 제공

### `POST /posters/confirm`

```json
// Request: 사용자가 확인 화면에서 고친 최종값
{ "run_id": "uuid", "draft": { "...": "위 draft와 같은 형식" } }

// Response 201
{ "opportunity_id": "uuid", "merged": false }
```

- 같은 공고가 이미 있으면 `merged: true`와 기존 공고 ID를 돌려준다(F-16)
- 저장한 포스터 공고는 올린 본인에게만 보인다. 확인 화면의 "다른 학생 피드에도 공개" 안내는 뺀다(공유는 P1)
- 등록 즉시 업로더 본인 판정을 계산한다. 다른 사용자 판정은 공유(P1)를 켤 때부터다

## 7. 준비하기 · 플래너 · 캘린더

### `POST /opportunities/{id}/prepare`

```json
// Request
{ "register_calendar": true, "calendar_provider": "google", "target_date": null }

// Response 202 (처음) 또는 200 (이미 준비한 공고면 기존 결과)
{ "run_id": "uuid", "status": "running" }
```

- 판정이 `ineligible`이면 `409 NOT_ELIGIBLE`. 프론트는 "그래도 준비하기"를 누르면 `{"force": true}`로 다시 보낸다
- `calendar_provider`가 `ics`면 캘린더 API를 부르지 않고 결과에 .ics 링크를 포함
- 캘린더 연결이 없는데 `register_calendar`가 true이면, 준비 일정은 그대로 만든다. 결과의 `calendar_event`는 null이고 `calendar_error`는 `CALENDAR_NOT_CONNECTED`다. 프론트는 캘린더를 연결(4장)한 뒤 `POST /calendar/events`로 등록한다

```json
{ "kind": "prepare", "...": "위 result와 같은 형식", "calendar_event": null, "calendar_error": "CALENDAR_NOT_CONNECTED" }
```
- `target_date`는 `deadline_at`이 null인 상시 공고에서 **필수**다. `planner_tasks.due_date`가 NOT NULL이라 화면에서 목표일을 받는다
- `build_prep_plan` 역산 규칙: 서류 할 일 = 마감 2일 전 − `lead_days`. 오늘보다 앞서면 오늘로 둬서 지난 날짜가 생기지 않게 한다

완료 시 `result`:

```json
{
  "kind": "prepare",
  "prep_plan_id": "uuid",
  "documents": [ { "id": "uuid", "name": "재학증명서", "issuer": "한양인 포털", "how_to": "...", "lead_days": 1 } ],
  "tasks": [
    { "id": "uuid", "title": "재학증명서 발급", "due_date": "2026-10-12", "document_id": "uuid" },
    { "id": "uuid", "title": "신청서 작성·제출", "due_date": "2026-10-14", "document_id": null }
  ],
  "calendar_event": { "id": "uuid", "provider": "google", "external_event_id": "abc123", "starts_at": "2026-10-15T23:59:00+09:00" }
}
```

### `GET /planner/tasks`

`?from=2026-09-29&to=2026-10-12&include_done=false`

```json
{
  "items": [
    {
      "id": "uuid",
      "title": "재학증명서 발급",
      "due_date": "2026-10-12",
      "is_done": false,
      "source": "prep_plan",
      "link": { "type": "opportunity", "id": "uuid", "title": "2026-2 한양브레인 장학금", "category": "scholarship" }
    },
    {
      "id": "uuid",
      "title": "과제.창업시장조사(개인별 제출)",
      "due_date": "2026-10-08",
      "is_done": true,
      "source": "lms_assignment",
      "link": { "type": "lms_assignment", "id": "uuid", "title": "AI창업캡스톤디자인", "html_url": "https://learning.hanyang.ac.kr/..." },
      "auto_completed": true
    }
  ],
  "markers": [
    { "kind": "deadline", "date": "2026-10-10", "title": "2026-2 한양브레인 장학금 마감", "opportunity_id": "uuid", "category": "scholarship" }
  ]
}
```

- `link.type`: `opportunity` \| `syllabus_item` \| `lms_assignment` \| `lms_announcement` \| `null`
- `auto_completed`: LMS 제출로 자동 완료된 항목(F-51)
- `markers`는 체크할 수 없는 표시 항목이다. 지금은 준비 중인 공고의 마감일(`kind = deadline`)만 있다
- `link.category`는 공고에서 온 할 일에만 있고, LMS·강의계획서 할 일은 칩에 과목명(`link.title`)을 쓴다
- LMS 과제의 `is_done`은 사용자가 바꿀 수 있고, 동기화는 미제출에서 제출로 바뀔 때만 true로 바꾼다

### `POST /planner/tasks` · `PATCH /planner/tasks/{id}` · `DELETE /planner/tasks/{id}`

```json
// POST (직접 추가, source = manual)
{ "title": "스터디 자료 정리", "due_date": "2026-10-05" }

// PATCH (보낸 필드만)
{ "is_done": true }
{ "due_date": "2026-10-11", "title": "재학증명서 발급(포털)" }
```

- `source = lms_assignment` 항목은 `is_done`만 수정 가능(제목·날짜는 LMS가 기준). 다른 필드는 `400 FIELD_READ_ONLY`
- `DELETE`는 `manual` 항목만 가능. 나머지는 `400 TASK_NOT_DELETABLE`

### `POST /calendar/events`

- 연결이 없거나 만료됐으면 `409 CALENDAR_NOT_CONNECTED`(`details.reason`)를 돌려준다

```json
// Request: 대상 셋 중 정확히 하나
{ "provider": "google", "opportunity_id": "uuid" }
{ "provider": "google", "syllabus_item_id": "uuid" }
{ "provider": "google", "lms_assignment_id": "uuid" }

// Response 201 (이미 등록돼 있으면 200 + 기존 이벤트)
{ "id": "uuid", "provider": "google", "external_event_id": "abc123", "title": "[마감] 2026-2 한양브레인 장학금", "starts_at": "2026-10-15T23:59:00+09:00", "all_day": false }
```

에러: `CALENDAR_NOT_CONNECTED`(409, 재로그인 유도), `GOOGLE_API_ERROR`(502)

### `DELETE /calendar/events/{id}`

`204`. Google 캘린더에서도 삭제한다.

### `GET /calendar/ics` (P1)

- 내려받기는 `calendar_events`에 기록하지 않는다

`?opportunity_ids=uuid,uuid&lms_assignment_ids=uuid` → `Content-Type: text/calendar`, 파일 다운로드. 동시에 `calendar_events`에 `provider = ics`로 기록.

## 8. 강의계획서 · 강의자료

### `POST /syllabi/extract`

```json
// Request (계획서 PDF를 /files로 올린 뒤)
{ "file_id": "uuid", "lms_course_id": "uuid" }

// Response 202
{ "run_id": "uuid", "status": "running" }
```

완료 시 `result`:

```json
{
  "kind": "syllabus_extract",
  "syllabus_id": "uuid",
  "course_name": "데이터베이스",
  "items": [
    { "id": "uuid", "item_type": "midterm", "title": "중간고사", "starts_at": "2026-10-21T10:30:00+09:00" },
    { "id": "uuid", "item_type": "presentation", "title": "팀 프로젝트 발표", "starts_at": "2026-12-09T10:30:00+09:00" }
  ]
}
```

- 이미 계획서가 있는 과목이면 `409 SYLLABUS_EXISTS`(교체하려면 `{"replace": true}`)

### `POST /syllabi/{id}/confirm`

```json
// Request: 사용자가 고친 최종 일정과 등록 여부
{
  "items": [
    { "id": "uuid", "title": "중간고사", "starts_at": "2026-10-21T10:30:00+09:00", "selected": true },
    { "id": "uuid", "title": "팀 프로젝트 발표", "starts_at": "2026-12-09T10:30:00+09:00", "selected": false }
  ],
  "register_calendar": true,
  "calendar_provider": "google"
}

// Response 200
{ "confirmed": 1, "planner_tasks_created": 1, "calendar_events_created": 1 }
```

### `POST /materials` (P1, 축소판)

P1 축소판이다. 텍스트가 있는 PDF만 받고, 추출 텍스트가 토큰 상한 이내면 문서 전체를 1회 요약한다. 상한을 넘으면 `413 MATERIAL_TOO_LONG`이고 쪽 범위 선택은 없다. 업로드 화면에 "외부 AI 서비스로 보내 요약해요"를 고지한다.

```json
// Request
{ "file_id": "uuid" }

// Response 202 (이미 요약이 있으면 200 + GET /materials/{file_id}와 같은 본문)
{ "run_id": "uuid", "status": "running" }

// 완료 시 result
{ "kind": "material_summary", "file_id": "uuid", "overall_summary": "..." }
```

처리 순서: 텍스트 추출 → 토큰 상한 확인 → 전체 요약 1회. 구간 분할, 구간 번역, 스캔 페이지 Vision은 하지 않는다(확장 범위).

```json
// Response 413
{
  "error": {
    "code": "MATERIAL_TOO_LONG",
    "message": "자료가 길어서 한 번에 요약할 수 없어요. 요약할 쪽 범위를 골라주세요.",
    "details": {
      "total_pages": 142,
      "text_tokens": 185000,
      "limit_tokens": 80000,
      "suggested_ranges": [ { "start": 1, "end": 61 }, { "start": 62, "end": 118 }, { "start": 119, "end": 142 } ]
    }
  }
}
```

- `suggested_ranges`는 상한 안에 들어가도록 백엔드가 나눈 범위. 프론트는 이걸 버튼으로 보여주고, 사용자가 직접 범위를 입력할 수도 있게 한다
- 상한 초과는 `materials.over_limit = true`로 기록한다(유료화 수요 근거)
- 처리 중 `GET /runs/{run_id}`의 `steps`에 구간 진행이 나온다. 예: `{ "tool": "summarize_section", "label": "구간 요약 (4/12)" }`

완료 시 `result`: `{ "kind": "material_summary", "file_id": "uuid", "sections": 12, "source_language": "en" }`

### `GET /materials/{file_id}`

```json
{
  "file_id": "uuid",
  "file_name": "ML_Lectures_Week1-8.pdf",
  "course": { "lms_course_id": "uuid", "name": "기계학습" },
  "source_language": "en",
  "total_pages": 142,
  "processed_range": { "start": 1, "end": 61 },
  "status": "succeeded",
  "overall_summary": "## 전체 요약\n- 지도학습의 기본 개념부터 ..."
}
```

- 요약 필드는 Markdown이다. `sections`와 번역 필드는 확장 범위로 빠졌다

### `GET /materials` (P1)

내 문서함. `?lms_course_id=uuid&cursor=` → `{ "items": [{ "file_id", "file_name", "course", "created_at", "status", "total_sections", "translated_sections" }], "next_cursor" }`

## 9. LMS 연동

### 클라이언트 규칙

- 백엔드 LearningX 클라이언트는 GET 요청만 보낸다. 허용 경로 밖이면 요청을 보내기 전에 예외를 던진다
- 허용 경로는 9/28 점검 스크립트에서 쓴 기능만이다: 사용자 확인, 수강 과목 목록, 과목별 과제(제출 상태 포함), 모듈과 항목, 과목 공지, 공지 첨부 다운로드(P1). 실제 경로 문자열은 점검 스크립트 기준으로 코드 상수에 둔다
- 테스트는 녹화한 응답(개인정보 제거)을 재생하는 가짜 클라이언트로 돌린다

### `POST /lms/connection`

- 발급 가이드는 토큰 만료일을 학기 종료일로 넣도록 안내한다(LearningX 화면에 만료일 칸이 있는 경우)
- 실사용자 연결은 학교 회신을 받은 뒤에 연다. 그 전에는 팀원·테스트 계정만 연결한다

```json
// Request
{ "access_token": "18742~xxxxxxxx" }

// Response 201
{ "status": "active", "token_last4": "a9f2", "courses": 8, "first_sync_run_id": "uuid" }
```

- 저장 전에 `GET /api/v1/users/self`로 검증한다. 실패하면 저장하지 않고 `422 LMS_TOKEN_INVALID`
- 성공하면 바로 첫 동기화를 시작하고 `first_sync_run_id`를 돌려준다
- 이미 연결돼 있으면 토큰을 교체한다

### `GET /lms/connection`

```json
{ "status": "active", "token_last4": "a9f2", "last_synced_at": "2026-10-01T10:30:00+09:00", "last_error": null }
```

`status = error`이면 `last_error`에 사용자용 메시지(예: "토큰이 만료되었거나 삭제되었어요"). 연결 안 됨은 `404 LMS_NOT_CONNECTED`.

### `DELETE /lms/connection`

`204`. 토큰을 즉시 삭제한다. 과목·과제 기록은 남기되 동기화를 멈춘다. 프론트는 "LearningX 설정에서 토큰도 삭제하세요" 안내를 띄운다.

### `POST /lms/sync`

대시보드 접속 시 프론트가 호출한다.

```json
// Response 202
{ "run_id": "uuid", "status": "running" }

// Response 200 (마지막 동기화 5분 이내면 건너뜀)
{ "skipped": true, "last_synced_at": "2026-10-01T10:30:00+09:00" }
```

완료 시 `result`:

```json
{
  "kind": "lms_sync",
  "courses": 8,
  "assignments": { "new": 1, "due_changed": 0, "submitted": 2 },
  "new_module_items": 1,
  "new_announcements": 2
}
```

### `GET /lms/courses`

```json
{
  "items": [
    {
      "id": "uuid",
      "canvas_course_id": 23525,
      "name": "202620HY23525_데이터베이스",
      "short_name": "데이터베이스",
      "has_syllabus": false,
      "portal_syllabus_url": "https://portal.hanyang.ac.kr/openPop.do?header=hidden&url=/haksa/SughAct/findSuupPlanDocHyIn.do&flag=BB&year=2026&term=20&suup=23525&language=ko",
      "open_assignments": 2,
      "new_materials": 2,
      "next_due": { "kind": "assignment", "title": "Quiz 3", "due_at": "2026-10-11T23:59:00+09:00" }
    }
  ]
}
```

- `portal_syllabus_url`은 사용자 브라우저에서 여는 링크다. **서버는 이 주소에 요청하지 않는다**(포털 robots.txt)
- `new_materials`는 `last_viewed_at` 이후 생긴 주차 항목 수다. `next_due`는 미제출 과제와 확정된 강의계획서 일정 중 가장 가까운 것이고, 없으면 null이다

### `GET /lms/courses/{id}`

```json
{
  "course": { "id": "uuid", "short_name": "선형대수", "has_syllabus": true, "portal_syllabus_url": "https://portal.hanyang.ac.kr/...", "html_url": "https://learning.hanyang.ac.kr/courses/..." },
  "assignments": [ { "id": "uuid", "title": "Homework 4", "due_at": "2026-10-13T23:59:00+09:00", "submission_state": "unsubmitted", "html_url": "https://learning.hanyang.ac.kr/..." } ],
  "module_items": [ { "id": "uuid", "module_name": "8주차", "title": "08 - Eigenvalues", "html_url": "https://learning.hanyang.ac.kr/...", "is_new": true, "uploaded_file_id": null } ],
  "announcements": [ { "id": "uuid", "title": "강의실 변경 안내", "summary": "다음 주 수업은 다른 강의실에서 한다", "category": "schedule_change", "posted_at": "2026-10-04T14:00:00+09:00", "opportunity_id": null } ],
  "syllabus_items": [ { "id": "uuid", "item_type": "midterm", "title": "중간고사", "starts_at": "2026-10-20T10:30:00+09:00", "is_confirmed": true } ],
  "materials": [ { "file_id": "uuid", "original_name": "08_eigen.pdf", "status": "succeeded" } ]
}
```

- 부르면 그 과목의 `last_viewed_at`을 지금으로 바꾼다. `is_new`는 바꾸기 전 값으로 계산한다
- 분반 한정 공지(`is_section_specific`)는 내려주지 않는다
- `course.html_url`은 "LMS에서 열기" 링크다

### `GET /lms/assignments`

`?state=open|submitted|all&lms_course_id=uuid`

```json
{
  "items": [
    {
      "id": "uuid",
      "course": { "id": "uuid", "short_name": "AI창업캡스톤디자인" },
      "title": "과제.비즈니스모델(개인별 제출)",
      "due_at": "2026-10-13T23:59:00+09:00",
      "submission_state": "unsubmitted",
      "html_url": "https://learning.hanyang.ac.kr/courses/.../assignments/...",
      "planner_task_id": "uuid",
      "calendar_registered": true
    }
  ]
}
```

### `GET /lms/updates`

새 주차학습 항목과 과목 공지를 한 피드로 보여준다(F-52, F-53).

`?since=2026-09-24T00:00:00+09:00&type=module_item,announcement,assignment&lms_course_id=uuid`

```json
{
  "items": [
    {
      "type": "module_item",
      "id": "uuid",
      "course": { "id": "uuid", "short_name": "기계학습" },
      "module_name": "8주차",
      "title": "08 - Ensemble Methods",
      "html_url": "https://learning.hanyang.ac.kr/courses/.../modules/items/...",
      "first_seen_at": "2026-10-01T09:00:00+09:00",
      "uploaded_file_id": null
    },
    {
      "type": "announcement",
      "id": "uuid",
      "course": { "id": "uuid", "short_name": "컴퓨터구조" },
      "title": "휴강 안내",
      "summary": "다음 주 월요일 수업은 휴강한다",
      "posted_at": "2026-09-23T14:00:00+09:00",
      "category": "schedule_change",
      "attachment_count": 0,
      "opportunity_id": null,
      "planner_task_id": "uuid"
    }
  ],
  "next_cursor": null
}
```

- `uploaded_file_id`: 사용자가 이 항목 알림에서 넘어가 PDF를 올렸으면 해당 파일. 프론트는 "업로드하기" 버튼 대신 "요약 보기"를 띄운다
- 공지 `category`: `schedule_change` \| `material` \| `opportunity` \| `general` \| `null`(분류 전)
- `opportunity`로 분류된 공지는 `opportunity_id`로 공고 상세에 연결
- `type`에 `assignment`(새 과제, 마감 D-3 이내 미제출 과제)를 더한다
- 분반 한정 공지(`is_section_specific`)는 내려주지 않는다

> 모듈 항목 알림에서 올린 파일은 `files.lms_module_item_id`로 연결된다(ERD v0.6). `POST /files`에 `lms_module_item_id`를 함께 보내면 된다.

## 10. 알림

- 알림 행은 `(user_id, dedupe_key)`로 upsert한다(키 형식은 ERD 5장). 같은 공고의 마감 임박 알림은 D-3과 D-1에 한 번씩이다
- 공고 마감이 바뀌면 같은 키의 pending 알림에서 시각만 고친다. 과제를 제출했거나 준비를 취소하면 pending 알림을 지운다

### `GET /notifications`

`?unread_only=false&limit=20&cursor=...`

```json
{
  "items": [
    {
      "id": "uuid", "type": "deadline_soon",
      "title": "장학금 마감이 가까워요", "body": "한양 브레인 보완 장학금 · D-3",
      "scheduled_at": "2026-10-05T09:00:00+09:00", "read_at": null,
      "link": { "type": "opportunity", "id": "uuid" }
    },
    {
      "id": "uuid", "type": "profile_needed",
      "title": "프로필 정보가 필요해요", "body": "경기도 청년 역량개발 지원사업 · 거주지역을 입력하면 판정할 수 있어요",
      "scheduled_at": "2026-10-05T08:00:00+09:00", "read_at": null,
      "link": { "type": "opportunity", "id": "uuid", "focus": "profile_input" }
    },
    {
      "id": "uuid", "type": "new_material",
      "title": "기계학습 8주차 자료가 올라왔어요", "body": "08 - Ensemble Methods",
      "scheduled_at": "2026-10-05T07:00:00+09:00", "read_at": "2026-10-05T07:40:00+09:00",
      "link": { "type": "lms_module_item", "id": "uuid", "course_id": "uuid" }
    }
  ],
  "unread_count": 3,
  "next_cursor": null
}
```

- `scheduled_at`이 지난 알림만 최신순으로 내려준다
- `link.type`은 `opportunity` \| `planner_task` \| `lms_assignment` \| `lms_module_item` \| `lms_announcement`이고, `focus: profile_input`이면 상세에서 정보 입력창을 바로 연다
- `lms_*` 링크에는 `course_id`를 함께 내려준다. `link.id`는 과제·자료·공지 ID라서 그것만으로는 과목 탭으로 이동할 수 없다

### `POST /notifications/read`

```json
// Request: 둘 중 하나
{ "ids": ["uuid", "uuid"] }
{ "all": true }

// Response 200
{ "unread_count": 0 }
```

### `POST /push/subscriptions`

브라우저 `PushManager.subscribe()` 결과를 그대로 보낸다.

```json
// Request
{ "endpoint": "https://fcm.googleapis.com/fcm/send/...", "keys": { "p256dh": "...", "auth": "..." }, "user_agent": "Chrome 129 / Android" }

// Response 201
{ "subscribed": true }
```

### `DELETE /push/subscriptions`

`{ "endpoint": "..." }` → `204`

### 푸시 페이로드 (서버 → 서비스 워커)

```json
{
  "type": "new_material",
  "title": "기계학습 8주차 자료가 올라왔어요",
  "body": "08 - Ensemble Methods",
  "url": "/lms/updates?focus=uuid",
  "notification_id": "uuid"
}
```

`type`: ERD `notification_type`(`new_eligible`, `new_assignment`, `new_material`, `schedule_change`, `task_due`, `deadline_soon`, `profile_needed`)

## 11. 에이전트 실행 조회

### `GET /runs/{id}`

본인 실행만 조회 가능(배치 실행은 403).

```json
{
  "id": "uuid",
  "trigger_type": "poster_upload",
  "status": "succeeded",
  "started_at": "2026-10-01T10:40:01+09:00",
  "finished_at": "2026-10-01T10:40:09+09:00",
  "latency_ms": 8120,
  "steps": [
    { "seq": 1, "tool": "extract_from_image", "label": "포스터에서 글자·날짜 읽기", "status": "succeeded", "latency_ms": 5210 },
    { "seq": 2, "tool": "extract_requirements", "label": "지원 자격 정리", "status": "succeeded", "latency_ms": 2340 },
    { "seq": 3, "tool": "check_eligibility", "label": "내 프로필과 비교", "status": "succeeded", "latency_ms": 12 }
  ],
  "result": { "kind": "poster_extract", "...": "작업별 결과(6–9장)" },
  "error": null
}
```

단계마다 모델이 고른 도구를 구분해 보여준다. 공고 상세의 `process.extraction`도 같은 형식이다.

```json
{ "seq": 2, "tool": "read_attachment_text", "label": "첨부 '2026-2 장학 안내.hwp' 읽기",
  "status": "succeeded", "latency_ms": 900, "chosen_by": "agent", "note": "본문에 '첨부 참조'만 있어 첨부를 읽음" }
```

- `steps`가 처리 과정 표시(F-42)의 데이터. `label`은 백엔드가 도구 이름 → 사용자용 문구로 바꿔서 준다
- `chosen_by`: `agent`(모델이 고른 도구) 또는 `pipeline`(정해진 순서). 처리 과정 화면에서 모델이 고른 단계를 구분해 표시한다
- `note`: 모델이 고른 이유 한 줄이다. 공고 원문에서 온 내용만 담고 프로필 값은 담지 않는다
- 토큰 수·비용은 사용자 응답에 넣지 않고 내부 지표로만 쓴다
- 실패 시 `status: "failed"`, `error: { "code": "LLM_TIMEOUT", "message": "..." }`
- label: read_attachment_text → 첨부 '파일명' 읽기, read_attachment_image → 첨부 '파일명' 이미지로 읽기, fetch_original → 공고 원문 페이지 읽기, submit_requirements → 지원 자격 정리, 그 밖은 도구 이름. 번호로 첨부를 못 찾으면 "첨부 N번"이다.
- 앞에서 읽은 곳의 뒷부분을 읽은 호출(시작 위치가 0보다 큼, Vision은 PDF 2쪽부터)은 "이어 읽기"다(예: 첨부 '파일명' 이어 읽기).
- 도구가 오류를 돌려줬거나 제출이 거절된 호출은 status failed다. tool_calls.status에는 succeeded로 남는다.
- note는 주소를 지우고 공백을 한 칸으로 줄인 한 줄이고 최대 200자다.

## 12. 내부 · 운영 API

`/internal/*`, `/admin/*`는 사용자 토큰이 아니라 **서비스 키**(`X-Internal-Key`) 또는 운영자 계정으로만 호출한다. 프론트에서 부르지 않는다.

| 경로 | 호출 주체 | 설명 |
| --- | --- | --- |
| `POST /internal/jobs/crawl-notices` | 스케줄러 | 학교 공지 수집 → 요건 추출 → 전체 판정 |
| `POST /internal/jobs/fetch-policies` | 스케줄러 | 온통청년 정책 수집 (담당 Dev 2) |
| `POST /internal/jobs/crawl-contests` | 스케줄러 | 공모전 수집 (P1) |
| `POST /internal/jobs/lms-sync` | 스케줄러(30분) | LMS 연결된 전체 사용자 동기화 |
| `POST /internal/jobs/send-notifications` | 스케줄러(5분) | 예약된 알림 발송 |
| `POST /internal/jobs/expire-opportunities` | 스케줄러(매일) | 마감 지난 공고 `expired` 처리 |
| `POST /internal/eval/run` | 개발자 | 요청 예: `{ "scenario_codes": ["S01", "S09"], "now": "2026-10-12T09:00:00+09:00", "fixtures": "recorded" }`. `now`로 시계를 고정하고, `fixtures: recorded`면 LMS·Google·온통청년 대신 녹화한 응답을 쓴다. 테스트용 Google 계정에 만든 이벤트는 끝나면 지운다. `agent_runs.scenario_code`로 기록 |
| `GET /internal/metrics` | 개발자 | 기간별 성공률·응답시간(p50·p95)·호출비용 집계에 두 가지를 더한다. 하나는 제품 지표 5개(판정 불가 비율과 원인 상위 3개, 즉석 입력 응답률, 준비하기 전환율, LMS 연결 완료율, 주간 재방문율)이고, 다른 하나는 최근 eval 실행 기준의 판정 혼동행렬이다. 비용은 모델 단가표(적용 날짜 포함)로 계산한다 |
| `POST /admin/opportunities/{id}/restore` | 운영자 | 신고로 숨겨진 공고 복구 (P1) |

## 13. 에러 코드

| 코드 | HTTP | 의미 | 프론트 처리 |
| --- | --- | --- | --- |
| `UNAUTHORIZED` | 401 | 토큰 없음·만료 | 로그인 화면 |
| `FORBIDDEN` | 403 | 남의 데이터·권한 없음 | 에러 화면 |
| `CONSENT_REQUIRED` | 403 | 동의 전. `details.consent`는 `terms_privacy`(필수 동의 전) 또는 `income_info`(소득 선택 동의 전) | 온보딩 동의 단계, 또는 소득 동의 안내 |
| `NOT_FOUND` | 404 | 대상 없음(숨김·과목 비공개 포함) | 에러 화면 |
| `VALIDATION_FAILED` | 422 | 입력값 검증 실패, `details.fields`에 필드별 사유 | 필드 아래 표시 |
| `FILE_TOO_LARGE` | 413 | 파일 크기 초과(20MB) | 안내 문구 |
| `PAGE_LIMIT_EXCEEDED` | 413 | 포스터 PDF 쪽수 초과(2쪽까지) | 안내 문구 |
| `MATERIAL_TOO_LONG` | 413 | 강의자료 토큰 상한 초과, `details.suggested_ranges` 제공 | 쪽 범위 선택 화면 |
| `UNSUPPORTED_FILE_TYPE` | 400 | 허용되지 않은 형식 | 안내 문구 |
| `DAILY_UPLOAD_LIMIT` | 429 | 하루 업로드 한도 초과, `details.reset_at` | 안내 문구 |
| `REPORT_NOT_ALLOWED` · `ALREADY_REPORTED` | 400 · 409 | 신고 불가·중복 신고 (P1, 신고와 함께) | 토스트 |
| `NOT_ELIGIBLE` | 409 | 부적격 공고 준비하기 | "그래도 준비하기" 확인 |
| `SYLLABUS_EXISTS` | 409 | 과목 계획서 이미 있음 | 교체 여부 확인 |
| `FIELD_READ_ONLY` · `TASK_NOT_DELETABLE` | 400 | LMS 과제 등 수정·삭제 불가 | 토스트 |
| `CALENDAR_NOT_CONNECTED` | 409 | 캘린더 연결이 없거나 만료. `details.reason`은 `not_connected` 또는 `expired` | 캘린더 연결(증분 승인) |
| `GOOGLE_REFRESH_TOKEN_MISSING` | 422 | 로그인 시 refresh token 못 받음 | 재로그인(동의 화면 다시) |
| `LMS_NOT_CONNECTED` | 404 | LMS 미연결 | 연결 가이드로 이동 |
| `LMS_TOKEN_INVALID` | 422 | 토큰 검증 실패·폐기됨 | 재연결 안내 |
| `GOOGLE_API_ERROR` · `LMS_API_ERROR` · `YOUTH_API_ERROR` | 502 | 외부 서비스 오류 | 잠시 후 재시도 |
| `LLM_TIMEOUT` · `LLM_ERROR` | 502 | LLM 호출 실패(실행 결과의 error로도 전달) | 재시도 버튼 |
| `RATE_LIMITED` | 429 | 같은 작업 과다 요청 | 잠시 후 재시도 |
| `DB_UNAVAILABLE` | 503 | DB 연결 실패 | 잠시 후 재시도 |
| `INTERNAL_ERROR` | 500 | 처리하지 못한 예외 | 에러 화면 |

## 14. 결정이 필요한 것

- [ ] 강의자료 토큰 상한 (P1 축소판) — 실제 강의자료로 측정
- [ ] 일일 업로드 한도 — 제안: 사용자당 하루 20개
- [ ] 작업 큐 — MVP는 FastAPI `BackgroundTasks`로 시작하고, 동기화 배치가 무거워지면 별도 워커로 분리할지
- [ ] 실행 상태 전달 — 폴링을 유지한다. Supabase Realtime으로 바꿔도 RLS 읽기 정책이 이미 있어 그대로 쓸 수 있다
- [ ] 요건 추출 에이전트 상한 — 공고당 도구 호출 4회와 입력 토큰 상한을 W2–3 실제 공지로 정한다

---

## 부록: 프론트 반영 목록 (`web/src/types/api.ts`와 화면)

실제 API로 바꾸는 작업(mock-to-api)을 할 때 같이 고친다.

| 위치 | 바꿀 것 |
| --- | --- |
| `Me` | `income_info_consented` 추가 |
| `Profile` | `is_international` 추가, `department`는 목록에서 고르는 값 |
| `OpportunityItem` | `uploader_masked` → `uploaded_by_me` |
| `OpportunityDetail` | `status`, `uploaded_by_me`, `attachments` 추가. `eligibility`에 `basis_date`, `requirements_version`, `clauses` 추가. review_reasons 추가(S1-6b) |
| `Condition` | `clause_no`, `unknown_reason` 추가 |
| `ProcessStep` · `Run.steps` | `chosen_by`, `note` 추가 |
| `PrepareResult` | `calendar_error` 추가 |
| `MaterialDetail` | `sections`와 번역 필드 삭제 (P1 축소판) |
| 화면 | 판정표를 묶음으로 표시, 판정 기준일 표시. 로그인 화면의 "캘린더 권한을 함께 요청해요" 문구 삭제. 준비하기 결과 화면에 캘린더 연결 버튼. 온보딩에 학과 목록 선택·유학생 여부·소득 선택 동의 추가. 포스터 등록의 공개 안내, 카드·상세의 업로더 표시와 신고 버튼 숨김. 설정의 HY-in 숨김과 캘린더 연결 추가. 과목 상세 자료 탭의 구간 번역 숨김 |
