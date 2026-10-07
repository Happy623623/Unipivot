# API 명세 v0.4 변경분 — 멘토 피드백 반영

> 📝 기준: API 명세 v0.3 → v0.4 · 2026-10-06 · 기준 문서: PRD v0.9, ERD v0.9
>
> 엔드포인트 3개를 더하고(`PATCH /me/consents`, `GET /meta/departments`, `POST /events`), 기존 API의 요청·응답·규칙을 바꾸고, 5곳의 우선순위를 내린다. 예시는 새 필드만 보이게 줄였다. 멘토가 요청한 판정 결과 JSON 형식은 5장 공고 상세 응답에 있다.
>
> 문서 상태 줄: `v0.4 변경: 캘린더 증분 승인, 선택 동의·학과 목록·사용 이벤트 API, 판정 결과 묶음(clause)·모름 사유·기준일, 공고 공개 범위, 포스터 공유·신고·강의자료 번역 우선 하향, LMS GET 제한, 실행 단계의 도구 선택 표시, 에러 코드 추가`

---

## 3장 엔드포인트 한눈에 보기 (추가·변경 행)

| 분류 | 메서드 · 경로 | 설명 | 기능 | 우선 |
| --- | --- | --- | --- | --- |
| 인증 | `POST /auth/google/tokens` (변경) | 캘린더를 연결할 때 Google 토큰 저장 (로그인 때는 부르지 않음) | F-01, F-32 | P0 |
| 인증 | `GET /auth/hyin/start` · `GET /auth/hyin/callback` | HY-in 인증 | F-05 | P2 |
| 내 정보 | `PATCH /me/consents` (신설) | 소득·수급 선택 동의와 철회 | F-02, F-06 | P0 |
| 메타 | `GET /meta/departments` (신설) | 학과 목록 | F-02 | P0 |
| 사용 기록 | `POST /events` (신설) | 화면에서만 알 수 있는 사용 이벤트 기록 | 8장 지표 | P0 |
| 공고 | `POST /opportunities/{id}/reports` | 신고 | F-17 | P1 |
| 강의자료 | `POST /materials` · `GET /materials/{file_id}` · `GET /materials` | 축소판 요약 | F-15 | P1 |
| 강의자료 | `POST /materials/{file_id}/translations` | 구간 번역 | — | 삭제 (확장 범위) |
| 운영 | `POST /internal/jobs/crawl-contests` · `POST /admin/opportunities/{id}/restore` | 공모전 수집, 숨김 복구 | F-12, F-17 | P1 |

---

## 1장 공통 규칙 (행 추가·보강)

| 항목 | 규칙 |
| --- | --- |
| 데이터 접근 (보강) | 프론트는 DB를 직접 읽지 않는다(기존). DB의 모든 테이블에 RLS가 켜져 있고 클라이언트 쓰기 정책은 없다. 백엔드는 테이블 소유자로 연결해 RLS를 받지 않으므로, 공고 조회 쿼리에 5장의 공개 범위를 직접 건다 |
| 시간 (보강) | 날짜로 바꿀 때(due_date, D-day, 판정 기준일)는 항상 Asia/Seoul 기준이다. 날짜에 따라 결과가 바뀌는 코드는 현재 시각을 인자로 받는다(테스트에서 고정) |
| 파일 URL (신설) | Storage 파일은 API가 만든 서명 URL로만 준다. 수명은 5분이다(v0.3 `poster_url`의 1시간을 줄임) |
| 비밀값 (보강) | 로그와 에러 추적에서 Authorization 헤더와 토큰 모양 문자열을 가린다. 프로필 값은 LLM 호출과 `tool_calls.input`에 넣지 않는다 |
| 외부 호출 (신설) | LearningX 클라이언트는 GET 요청과 9장의 허용 경로만 호출한다 |

---

## 4장 인증 · 내 정보

### Google 캘린더 연결 — `POST /auth/google/tokens` 설명 교체

로그인과 캘린더 연결을 나눈다(증분 승인). 요청·응답 형식은 v0.2 그대로다.

1. **로그인**: supabase-js Google 로그인으로 기본 범위(이메일·프로필)만 받는다. 이 API는 부르지 않는다. `GET /me`의 `calendar_connected`는 false다.
2. **연결**: 캘린더가 필요한 순간에 Google 로그인을 한 번 더 부른다. 그 순간은 준비하기 결과 화면에서 "캘린더에도 등록"을 고를 때, 설정에서 캘린더를 연결할 때, LMS 과제 자동 등록을 켤 때다. 요청 값은 다음과 같다.
   - scope: `https://www.googleapis.com/auth/calendar.events`
   - `access_type=offline`, `prompt=consent`, `include_granted_scopes=true`
   - 돌아올 화면은 redirectTo의 `next`로 넘긴다

   콜백에서 받은 provider 토큰을 이 API로 보낸다.
3. **끊김**: refresh가 실패하면(만료·취소) 서버는 저장한 토큰을 지운다. 그 뒤 캘린더가 필요한 API는 `409 CALENDAR_NOT_CONNECTED`(`details.reason`: `not_connected` · `expired`)를 돌려주고, 프론트는 2번 연결 흐름으로 보낸다.

S1-1 완료 조건을 다음으로 바꾼다. 로그인만으로는 캘린더 권한을 묻지 않는다. 연결 후 이벤트를 만들 수 있다. access token이 만료된 뒤 refresh로 다시 만들 수 있다.

### `GET /me` (필드 추가)

```json
{ "...": "v0.3 필드 그대로", "calendar_connected": false, "income_info_consented": false }
```

- `profile_completion.total`에 유학생 여부가 더해져 15에서 16이 된다
- `hyin_verified`는 F-05가 P2라 MVP에서는 늘 false다

### `POST /me/consents` (필드 추가) · `PATCH /me/consents` (신설)

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

### `GET /me/profile` · `PATCH /me/profile` (변경)

```json
{ "...": "v0.3 필드 그대로", "department": "기계공학과", "is_international": false }
```

- `department`에는 `GET /meta/departments`의 이름만 쓸 수 있다. 없는 이름은 `422 VALIDATION_FAILED`(`details.fields.department`)
- `is_international`을 추가한다(boolean, null이면 미입력)
- 소득 3항목은 선택 동의 전이면 `403 CONSENT_REQUIRED`(`details.consent = "income_info"`)
- 거주지역(`region_sido`, `region_sigungu`)은 주민등록 주소 기준이다. 입력 화면에 그렇게 적는다

### `GET /meta/departments` (신설)

```json
{ "items": [ { "name": "기계공학과", "college": "공학대학", "field_group": "공학계열" } ] }
```

- 위 값은 형식 예시다. 실제 목록은 seed 마이그레이션으로 넣는다
- `is_active`인 학과만 `sort_order`, 이름 순으로 준다. 로그인이 필요하다

### `POST /events` (신설)

```json
// Request
{ "event": "profile_prompt_shown", "opportunity_id": "uuid" }

// Response 204
```

- 프론트가 보내는 이벤트는 3가지다: `app_open`(앱을 열 때, KST 하루 1건만 저장), `profile_prompt_shown`(정보 입력창을 띄울 때), `lms_guide_opened`(LMS 연결 가이드를 열 때)
- `profile_prompt_submitted`, `lms_connected`는 서버가 해당 API 안에서 직접 기록한다. 프론트가 보내면 `422 VALIDATION_FAILED`
- 화면은 응답을 기다리지 않는다. 기록에 실패해도 화면은 그대로 둔다

---

## 5장 공고 피드 · 상세 · 신고

### 공개 범위 (신설)

피드·상세·플래너는 모두 같은 규칙을 쓴다(ERD 5장, RLS와 같음).

- 활성 공고: 포스터는 올린 본인만, 과목 공지 공고는 그 과목 수강생만, 나머지는 로그인 사용자 모두 볼 수 있다
- 준비를 시작한 공고는 마감(`expired`)·숨김(`hidden`)이 되어도 본인에게 상세·서류·플래너가 계속 보인다. 피드에는 나오지 않는다
- 그 밖의 숨김·과목 비공개 공고는 `404 NOT_FOUND`다(v0.2 그대로)

### `GET /opportunities` (변경)

- `uploader_masked`를 지우고 `uploaded_by_me`(boolean)를 넣는다. 포스터 카드는 주최 자리에 "내가 올린 포스터"를 쓴다
- 그 밖은 v0.3 그대로다

### `GET /opportunities/{id}` (변경)

예시는 "직전학기 12학점 이상 (단, 4학년은 9학점)" 공고와 학년 미입력·10학점 프로필이다.

```json
{
  "...": "v0.3 필드 그대로",
  "status": "active",
  "uploaded_by_me": false,
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
      { "requirement_id": "uuid", "clause_no": 1, "field": "credits_last_semester", "label": "직전학기 취득학점",
        "condition_text": "12학점 이상", "user_value_text": "10학점", "outcome": "fail", "unknown_reason": null,
        "evidence_text": "직전학기 12학점 이상 (단, 4학년은 9학점)", "is_ambiguous": false },
      { "requirement_id": "uuid", "clause_no": 2, "field": "grade", "label": "학년",
        "condition_text": "4학년이 아님", "user_value_text": null, "outcome": "unknown", "unknown_reason": "missing_profile",
        "evidence_text": "직전학기 12학점 이상 (단, 4학년은 9학점)", "is_ambiguous": false },
      { "requirement_id": "uuid", "clause_no": 2, "field": "credits_last_semester", "label": "직전학기 취득학점",
        "condition_text": "9학점 이상", "user_value_text": "10학점", "outcome": "pass", "unknown_reason": null,
        "evidence_text": "직전학기 12학점 이상 (단, 4학년은 9학점)", "is_ambiguous": false }
    ]
  }
}
```

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

### `POST /opportunities/{id}/reports`

P1로 내린다. 형식은 그대로 둔다.

---

## 6장 업로드 · 포스터

- `POST /files`: 같은 사용자가 같은 파일(sha256)을 같은 kind로 다시 올리면 새로 저장하지 않고 `200 { "file_id": "기존 id", "reused": true }`를 준다. 새 파일은 v0.2처럼 201이다
- `POST /posters/confirm`: 저장한 포스터 공고는 올린 본인에게만 보인다. 확인 화면의 "다른 학생 피드에도 공개" 안내는 뺀다(공유는 P1)
- `poster_url`: 서명 URL 수명 5분

---

## 7장 준비하기 · 플래너 · 캘린더

### `POST /opportunities/{id}/prepare` (변경)

캘린더 연결이 없는데 `register_calendar`가 true이면, 준비 일정은 그대로 만든다. 결과의 `calendar_event`는 null이고 `calendar_error`는 `CALENDAR_NOT_CONNECTED`다. 프론트는 캘린더를 연결(4장)한 뒤 `POST /calendar/events`로 등록한다.

```json
{ "kind": "prepare", "...": "v0.3 그대로", "calendar_event": null, "calendar_error": "CALENDAR_NOT_CONNECTED" }
```

### `POST /calendar/events` (변경)

- 연결이 없거나 만료됐으면 `409 CALENDAR_NOT_CONNECTED`(`details.reason`)를 돌려준다

### `GET /calendar/ics` (P1, 설명 추가)

- 내려받기는 `calendar_events`에 기록하지 않는다

---

## 8장 강의계획서 · 강의자료

- `POST /materials` (P1, 축소판): 텍스트가 있는 PDF만 받는다. 추출 텍스트가 토큰 상한 이내면 문서 전체를 1회 요약한다. 넘으면 `413 MATERIAL_TOO_LONG`이고, 쪽 범위 선택은 없다. 업로드 화면에 "외부 AI 서비스로 보내 요약해요"를 고지한다
- 결과: `{ "kind": "material_summary", "file_id": "uuid", "overall_summary": "..." }`
- `GET /materials/{file_id}`에서 `sections`를 뺀다
- `POST /materials/{file_id}/translations`, 쪽 범위 요청 필드, `MATERIAL_NOT_READY`·`ALREADY_KOREAN` 오류는 명세에서 뺀다(확장 범위)

---

## 9장 LMS 연동

### 클라이언트 규칙 (신설)

- 백엔드 LearningX 클라이언트는 GET 요청만 보낸다. 허용 경로 밖이면 요청을 보내기 전에 예외를 던진다
- 허용 경로는 9/28 점검 스크립트에서 쓴 기능만이다: 사용자 확인, 수강 과목 목록, 과목별 과제(제출 상태 포함), 모듈과 항목, 과목 공지, 공지 첨부 다운로드(P1). 실제 경로 문자열은 점검 스크립트 기준으로 코드 상수에 둔다
- 테스트는 녹화한 응답(개인정보 제거)을 재생하는 가짜 클라이언트로 돌린다

### `POST /lms/connection` (설명 추가)

- 발급 가이드는 토큰 만료일을 학기 종료일로 넣도록 안내한다(LearningX 화면에 만료일 칸이 있는 경우)
- 실사용자 연결은 학교 회신을 받은 뒤에 연다. 그 전에는 팀원·테스트 계정만 연결한다

### `GET /lms/courses/{id}` · `GET /lms/updates` (변경)

- 분반 한정 공지(`is_section_specific`)는 내려주지 않는다

---

## 10장 알림

- 알림 행은 `(user_id, dedupe_key)`로 upsert한다(키 형식은 ERD 5장). 같은 공고의 마감 임박 알림은 D-3과 D-1에 한 번씩이다
- 공고 마감이 바뀌면 같은 키의 pending 알림에서 시각만 고친다. 과제를 제출했거나 준비를 취소하면 pending 알림을 지운다

---

## 11장 에이전트 실행 조회

### `GET /runs/{id}` · 상세의 `process.extraction` (필드 추가)

```json
{ "seq": 2, "tool": "read_attachment_text", "label": "첨부 '2026-2 장학 안내.hwp' 읽기",
  "status": "succeeded", "latency_ms": 900, "chosen_by": "agent", "note": "본문에 '첨부 참조'만 있어 첨부를 읽음" }
```

- `chosen_by`: `agent`(모델이 고른 도구) 또는 `pipeline`(정해진 순서). 처리 과정 화면에서 모델이 고른 단계를 구분해 표시한다
- `note`: 모델이 고른 이유 한 줄이다. 공고 원문에서 온 내용만 담고 프로필 값은 담지 않는다

---

## 12장 내부 · 운영 API (변경 행)

| 경로 | 변경 |
| --- | --- |
| `POST /internal/eval/run` | 요청 예: `{ "scenario_codes": ["S01", "S09"], "now": "2026-10-12T09:00:00+09:00", "fixtures": "recorded" }`. `now`로 시계를 고정하고, `fixtures: recorded`면 LMS·Google·온통청년 대신 녹화한 응답을 쓴다. 테스트용 Google 계정에 만든 이벤트는 끝나면 지운다 |
| `GET /internal/metrics` | 기존 성공률·p50/p95·비용에 두 가지를 더한다. 하나는 제품 지표 5개(판정 불가 비율과 원인 상위 3개, 즉석 입력 응답률, 준비하기 전환율, LMS 연결 완료율, 주간 재방문율)이고, 다른 하나는 최근 eval 실행 기준의 판정 혼동행렬이다. 비용은 모델 단가표(적용 날짜 포함)로 계산한다 |
| `POST /internal/jobs/fetch-policies` | 담당이 Dev 2로 바뀐다. 형식은 그대로다 |
| `POST /internal/jobs/crawl-contests` · `POST /admin/opportunities/{id}/restore` | P1 |

---

## 13장 에러 코드 (추가·변경 행)

| 코드 | HTTP | 의미 | 프론트 처리 |
| --- | --- | --- | --- |
| `CONSENT_REQUIRED` (변경) | 403 | 동의 전. `details.consent`는 `terms_privacy`(필수 동의 전) 또는 `income_info`(소득 선택 동의 전) | 온보딩 동의 단계, 또는 소득 동의 안내 |
| `CALENDAR_NOT_CONNECTED` (변경) | 409 | 캘린더 연결이 없거나 만료. `details.reason`은 `not_connected` 또는 `expired` | 캘린더 연결(증분 승인) |
| `DB_UNAVAILABLE` (추가) | 503 | DB 연결 실패 | 잠시 후 재시도 |
| `INTERNAL_ERROR` (추가) | 500 | 처리하지 못한 예외 | 에러 화면 |
| `REPORT_NOT_ALLOWED` · `ALREADY_REPORTED` | — | P1 (신고와 함께) | — |
| `MATERIAL_NOT_READY` · `ALREADY_KOREAN` | — | 삭제 (구간 번역 제외) | — |

---

## 14장 결정이 필요한 것 (교체)

- [ ] 강의자료 토큰 상한 (P1 축소판) — 실제 강의자료로 측정
- [ ] 일일 업로드 한도 — 제안: 사용자당 하루 20개
- [ ] 작업 큐 — MVP는 FastAPI `BackgroundTasks`로 시작하고, 동기화 배치가 무거워지면 별도 워커로 분리할지
- [ ] 실행 상태 전달 — 폴링을 유지한다. Supabase Realtime으로 바꿔도 RLS 읽기 정책이 이미 있어 그대로 쓸 수 있다
- [ ] 요건 추출 에이전트 상한 — 공고당 도구 호출 4회와 입력 토큰 상한을 W2–3 실제 공지로 정한다

---

## 프론트 반영 목록 (`web/src/types/api.ts`와 화면)

실제 API로 바꾸는 작업(mock-to-api)을 할 때 같이 고친다.

| 위치 | 바꿀 것 |
| --- | --- |
| `Me` | `income_info_consented` 추가 |
| `Profile` | `is_international` 추가, `department`는 목록에서 고르는 값 |
| `OpportunityItem` | `uploader_masked` → `uploaded_by_me` |
| `OpportunityDetail` | `status`, `uploaded_by_me`, `attachments` 추가. `eligibility`에 `basis_date`, `requirements_version`, `clauses` 추가 |
| `Condition` | `clause_no`, `unknown_reason` 추가 |
| `ProcessStep` · `Run.steps` | `chosen_by`, `note` 추가 |
| `PrepareResult` | `calendar_error` 추가 |
| `MaterialDetail` | `sections`와 번역 필드 삭제 (P1 축소판) |
| 화면 | 판정표를 묶음으로 표시, 판정 기준일 표시. 로그인 화면의 "캘린더 권한을 함께 요청해요" 문구 삭제. 준비하기 결과 화면에 캘린더 연결 버튼. 온보딩에 학과 목록 선택·유학생 여부·소득 선택 동의 추가. 포스터 등록의 공개 안내, 카드·상세의 업로더 표시와 신고 버튼 숨김. 설정의 HY-in 숨김과 캘린더 연결 추가. 과목 상세 자료 탭의 구간 번역 숨김 |
