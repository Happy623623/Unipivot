# 학업 화면을 실제 API에 붙이기 (F-50·F-51·F-52·F-14·F-45)

> 📝 기준: API 명세 v0.4 4·8·9장 · `docs/Nextjs_이식_가이드.md`의 "목 함수 → 실제 API" 표 · 스킬 `mock-to-api` · 2026-10-17
>
> 먼저 합칠 것: `과목상세_구현.md`(PR #43) → `설정API_구현.md` → `과제캘린더등록_구현.md` → **이 문서**

학업 화면·과목 상세·LearningX 연결 창·설정의 알림 구역이 아직 목데이터였다. 이제 실제 API를 부른다. **화면 코드는 거의 그대로고, 함수 안쪽과 "준비 중" 플래그만 바뀐다.**

| 바뀐 함수 | 실제 API |
| --- | --- |
| `getLmsConnection` · `connectLms` · `disconnectLms` | `GET` · `POST` · `DELETE /lms/connection` |
| `syncLmsNow` (새로) | `POST /lms/sync` → `GET /runs/{id}` |
| `getCourses` · `getCourse` | `GET /lms/courses` · `GET /lms/courses/{id}` |
| `getLmsUpdates` | `GET /lms/updates` |
| `getSettings` · `saveSettings` | `GET` · `PATCH /me/settings` |

DB 변경 없음. api는 테스트 파일 하나만 는다.

## 정한 것

1. **연결이 없으면 404가 정상이다.** 서버는 `GET /lms/connection`에 404 `LMS_NOT_CONNECTED`를 준다. 화면에서 "연결 안 됨"은 오류가 아니므로 `lmsClient`가 404만 골라 "연결 안 됨" 상태로 바꾼다(다른 오류는 그대로 올린다).
2. **연결할 때는 첫 동기화까지 기다린다.** 서버는 과목만 먼저 받아 두고 과제는 첫 동기화(`first_sync_run_id`)로 받는다. 기다리지 않으면 연결 직후 화면이 "과목 8개, 과제 0건"으로 보인다. 창에는 "토큰을 확인하고 과제를 받아오고 있어요"라고 쓴다. 60초를 넘기면 기다리지 않고 연결된 것으로 끝낸다(동기화는 서버에서 계속된다).
3. **학업 화면을 열면 한 번 동기화한다**(명세 9장: 대시보드 접속 시). 받는 동안 **저장해 둔 과제·자료를 그대로 보여 주고**, 새로 받으면 그때 목록을 다시 받아 그린다. 마지막 동기화가 5분 안이면 서버가 건너뛰므로 대부분은 아무 일도 일어나지 않는다.
4. **연결 창의 "8개 과목을 불러왔어요"가 진짜 숫자가 된다.** 지금까지 화면에 8이 박혀 있었다. `POST /lms/connection` 응답의 `courses`를 쓴다(그래서 `connectLms`는 연결 상태 대신 **연결 결과**(`LmsConnectResult`)를 돌려준다).
5. **"준비 중" 플래그 두 개를 지운다**(`LMS_CONNECT_READY`·`NOTIFICATION_SETTINGS_READY`). API가 생겼으니 실제 모드에서도 연결 창과 알림 설정이 열린다.
6. **설정은 화면이 전체를 보내고 서버가 받은 항목만 바꾼다.** `PATCH`라 세 칸을 다 보내도 결과가 같다(화면은 토글 하나 누를 때마다 전체를 보낸다).
7. **강의자료 요약(`getMaterial`)만 아직 준비 중이다.** `GET /materials/{file_id}`가 없다(P1). 실제 모드에서는 안내만 띄운다.
8. **공지는 실제 모드에서 아직 안 온다**(F-53). 타입과 화면은 이미 공지를 그릴 줄 알고, 서버가 채우기 시작하면 그대로 나온다.
9. **web 타입과 API 응답 모델이 어긋나면 CI가 잡는다.** 칸 이름을 **안에 든 묶음까지** 길로 펴서 대조하는 테스트를 api에 넣었다(`tests/test_web_contract.py`, 12쌍·중첩 포함). F-14에서 `module_items[].module_name`·`html_url`이 어긋나 화면이 깨질 뻔했던 일을 한 번 더 겪지 않으려는 것이다. 타입·null 여부는 보지 않는다(그건 `typecheck`가 잡는다).
10. **오류는 코드로 가린다.** 연결 창은 토큰이 틀린 것(`422 LMS_TOKEN_INVALID`)과 LearningX가 멈춘 것(`502`)·서버에 닿지 못한 것을 다르게 말한다(명세 13장). 설정 저장이 실패하면 토글을 **되돌리고** 안내한다.
11. **설정 토글은 누르는 즉시 움직인다**(낙관적 반영). 서버 응답으로 다시 덮어쓰지 않는다 — 연달아 누르면 늦게 온 응답이 마지막 클릭을 되돌린다.
12. **목 모드도 실제와 같은 길을 돈다.** 목의 `connectLms`가 실제와 같은 모양(`LmsConnectResult`)을 주고, 목 동기화는 첫 호출에서 "받았다"를 줘서 **목록 다시 받기 경로를 목에서도 한 번 돈다.** 목이 실제와 달라서 버그가 가려지는 일을 줄인다.

## 레포에 넣는 법

````text
캘린더 PR(feat/F-51-assignment-calendar)을 먼저 합친 뒤, 그 main에서 새 브랜치 feat/F-51-web-academics를 따고
docs/web학업화면_구현.md(방금 받은 파일)를 docs/에 넣은 뒤 아래를 해 줘.

[1] 문서 맨 아래 "코드" 절의 파일 10개를 그대로 만들거나 덮어써 줘. `#### `경로`` 아래 코드 블록이 그 파일의 전체 내용이다.
    새 파일: api/tests/test_web_contract.py
    바뀌는 파일: web/src/types/lms.ts · web/src/api/lmsClient.ts · web/src/api/accountClient.ts · web/src/api/mockClient.ts
                 web/src/components/LmsConnectModal.tsx · web/src/components/ConnectedServices.tsx
                 web/src/screens/Academics.tsx · web/src/screens/Onboarding.tsx · web/src/screens/Settings.tsx

[2] "문서에 반영하기" 절대로 docs/Nextjs_이식_가이드.md를 고쳐 줘(5곳).

[3] DB 변경 없다.

[4] 검사: web> npm run typecheck && npm run build
         그리고 NEXT_PUBLIC_USE_MOCKS=true npm run build (목 모드도 그대로 돌아야 한다)
    api> uv run ruff check . && uv run ruff format --check . && uv run pytest
    로컬은 `884 passed, 266 skipped` 근처(Windows는 passed 하나 적고 skipped 하나 많다). CI에서는 `1150 passed`다.

[5] 통과하면 "feat(F-51): web 학업 화면을 실제 LMS API에 연결" 커밋으로 PR을 올려 줘.
    본문에 "목 → 실제 API: LMS 연결·동기화·과목·새 소식·설정", "DB 변경 없음",
    "web 타입과 API 모델 칸 이름 대조 테스트 추가"를 적어 줘.
````

## 합친 뒤 확인

```bash
# 실제 모드로 띄운다(.env.local의 NEXT_PUBLIC_USE_MOCKS=false, NEXT_PUBLIC_API_BASE_URL 확인)
cd api && uv run uvicorn app.main:app --reload   # 다른 창에서
cd web && npm run dev
```

1. **학업** 화면 → "LearningX 연결하기" → 토큰 붙여넣기 → "토큰을 확인하고 과제를 받아오고 있어요" → **진짜 과목 수**가 보인다.
2. 학업 화면에 과목 카드와 "새 소식"이 실제 자료로 뜬다. 과목을 누르면 상세의 다섯 탭이 채워지고, 뒤로 나오면 그 과목의 **새 자료 수가 0**이 된다(열었으니까).
3. 학업 화면을 **새로고침**하면 동기화가 한 번 돈다. 5분 안이면 아무 일도 없고, 5분이 지났으면 받은 뒤 목록이 다시 그려진다.
4. **설정** 화면에 알림 구역이 보인다. 토글을 바꾸고 새로고침해도 그대로다(서버에 저장된다).
5. 설정에서 LearningX 연결을 끊으면 학업 화면이 "연결해 주세요"로 돌아간다.

## 구조

```text
web/src/api/lmsClient.ts        연결(404 → "연결 안 됨") · connectLms(첫 동기화까지 기다림)
                                syncLmsNow(202면 결과까지 기다리고 true) · 과목 · 상세 · 새 소식
web/src/api/accountClient.ts    getSettings · saveSettings (PATCH)
web/src/api/mockClient.ts       connectLms가 실제와 같은 모양을 주고, syncLms는 "건너뜀"이다
web/src/types/lms.ts            LmsConnectResult(status·token_last4·courses·first_sync_run_id)
web/src/components/LmsConnectModal.tsx  준비 중 안내 삭제 · 진짜 과목 수 · 기다리는 동안 안내
web/src/screens/Academics.tsx   화면을 열면 동기화 → 끝나면 목록을 다시 받는다
web/src/screens/Settings.tsx    알림 구역을 늘 보여 준다
web/src/screens/Onboarding.tsx  LMS 단계를 늘 보여 준다
api/tests/test_web_contract.py  web 타입 ↔ API 응답 모델 칸 이름 대조(12쌍)
```

## 확인한 것

| 확인 | 결과 |
| --- | --- |
| web 빌드 | `npm run typecheck`·`npm run build` 통과(라우트 12개). **목 모드 빌드도 통과**(`NEXT_PUBLIC_USE_MOCKS=true`) |
| 계약(칸 이름) | web 타입 ↔ API 응답 모델 **12쌍 모두 같음**(안에 든 묶음까지 — `CourseDetail`은 37개 길)(`Me`·`Settings`·`LmsConnection`·`LmsConnectResult`·`Course`·`CourseDetail`·`Assignment`·`LmsSyncResult`·`SyncStarted`·`SyncSkipped`·새 소식 두 종류). 공지(`announcement`)만 API에 아직 없다(F-53) |
| api 테스트 | DB 없이 `884 passed, 266 skipped`, DB를 붙이면 `1150 passed`. 이 PR로 더한 테스트 12개(계약 대조) |
| 되돌림 시험 7가지 | web 타입에서 칸 빼기 · 새 소식 합집합에서 칸 빼기 · 칸 이름 바꾸기 · **안쪽 칸 빼기(`module_items[].module_name`)** · **안쪽 칸 이름 바꾸기(`course.html_url`)** · **한 줄 묶음에서 칸 빼기(`course.short_name`)** · `Me` 안쪽 칸 빼기 → **모두 잡혔다**(대조 테스트가 헛돌지 않는다) |
| 목 모드 | 연결·동기화·과목·상세·새 소식·설정이 목 그대로 돈다. `connectLms`의 목이 실제와 **같은 모양**을 주도록 바꿨다(목으로 개발하다 실제에서 깨지지 않게) |

### 검토에서 고친 것

검토를 한 번 돌렸고, 실제 모드에서만 터지는 것들이 나왔다. 목 모드로는 보이지 않는 종류라 특히 값졌다.

| 지적 | 고친 것 |
| --- | --- |
| **연결 직후 화면이 빈 채로 남는다.** 연결하면 `connectLms`가 첫 동기화까지 기다린다 → 그래서 바로 뒤에 부른 `POST /lms/sync`는 "5분 안에 받았다"며 건너뛴다(200) → 목록을 다시 받지 않는다. 과목 0개·새 소식 0개인 화면이 새로고침할 때까지 남는다. **목 모드에서는 절대 재현되지 않는다** | 연결 성공을 받으면 연결 상태만 바꾸지 않고 **목록도 다시 받는다**(`setSyncedAt`). 서버는 이미 과목을 받아 뒀으니 바로 채워진다 |
| **연결 창이 1단계로 되돌아간다.** 연결 전/후 화면이 다른 트리라서, 연결 성공으로 화면이 바뀌는 순간 React가 창을 **다시 만든다** → "N개 과목을 불러왔어요" 대신 "액세스 토큰을 발급해 주세요"가 다시 뜬다 | 창을 두 트리에서 **같은 자리·같은 `key`**로 그린다 |
| **연결 실패 문구가 늘 "토큰을 확인할 수 없어요"였다.** LearningX가 멈춰 있어도(502), 서버에 못 닿아도 같은 말을 했다 — 공백을 지워도 영원히 안 된다(명세 13장 위반) | `LMS_TOKEN_INVALID`일 때만 토큰·공백 안내를 하고, 나머지는 서버 문구나 "잠시 후 다시 시도해 주세요"를 쓴다 |
| **설정 저장 실패가 조용히 묻혔다.** `onChange`가 결과를 안 보니 실패하면 처리되지 않은 오류만 남고, 토글은 제자리로 돌아간다("눌렀는데 안 눌린다") | 실패하면 **되돌리고 안내 토스트**를 띄운다. 겸사겸사 토글을 낙관적으로 반영해, 연달아 누를 때 늦게 온 응답이 마지막 클릭을 덮어쓰는 문제도 없앴다 |
| **동기화가 실패해도 화면이 모른다.** 토큰이 막히면 서버가 연결 상태를 `error`로 바꾸는데, web은 연결 상태를 다시 받지 않아 "연결됨"이 그대로 남는다 | `syncLmsNow`가 **실패했을 때도 true**를 돌려 목록·연결 상태를 다시 받게 했다(그러면 끊김 배너가 뜬다) |
| **계약 테스트가 안에 든 묶음을 안 봤다.** 하필 F-14에서 어긋났던 `module_items[].module_name`·`html_url`이 검사 대상 밖이었다 | 길로 펴서(`course.id`·`module_items[].module_name`) 비교한다. `$ref`를 따라 내려가고, 한 줄로 쓴 묶음도 읽는다. 중첩 칸을 지우거나 이름을 바꾸는 되돌림 시험 4가지로 확인했다 |
| 끊김 배너가 서버가 준 이유(`last_error`)를 버리고 늘 "토큰이 만료됐거나 삭제됐어요"라고 했다 | `last_error`가 있으면 그걸 보여 준다(502로 끊긴 경우도 있다) |
| 빈 화면에 다음 행동 안내가 없었다(`web/CLAUDE.md` 규칙) | 과목이 0이면 "아직 받아온 과목이 없어요" + 다시 받아오기 버튼, 새 소식이 0이면 최근 2주 기준이라는 안내를 넣었다 |
| 설정 화면에서는 LearningX를 연결할 수 없는데 "연결되지 않음"만 떠 있었다 | "학업 화면에서 연결할 수 있어요"를 덧붙였다 |
| 온보딩의 LMS 단계 주석이 코드와 반대였다(준비 중 플래그 시절 주석) | 고쳤다 |


## 남은 것

- **실제 브라우저 흐름은 샌드박스에서 못 돌렸다.** Supabase 로그인이 필요해서다. 합친 뒤 위 "합친 뒤 확인"의 다섯 단계를 한 번 눌러 봐 줘 — 특히 ①연결 창과 ③새로고침 동기화.
- **web에는 자동 테스트 틀이 없다**(러너가 없다). 이 PR의 안전망은 타입 검사·빌드와 칸 이름 대조 테스트다. 화면 로직까지 테스트하고 싶으면 러너를 넣는 PR을 따로 하는 게 맞다.
- **새 소식은 첫 쪽(50개)만 받는다.** `next_cursor`로 "더 보기"를 붙이는 건 아직이다. 최근 14일 기준이라 지금 규모에서는 한 쪽에 들어간다.
- **연결 창이 첫 동기화를 최대 60초 기다린다.** 과목 8개면 보통 10초 안쪽이지만, 그동안 창에는 스피너와 "창을 닫지 말아 주세요"만 있고 취소 수단이 없다. 중간에 닫아도 연결은 끝까지 간다(화면이 연결 상태로 바뀐다). 실행의 단계(`GET /runs/{id}`의 `steps`)를 보여 주는 게 다음 개선이다.
- **목 모드의 오류는 `ApiError`가 아니다**(`MockApiError`). 그래서 연결 창의 코드별 문구 분기는 목에서 타지 않고 기본 문구가 나온다. 실제 모드에서는 제대로 갈린다.
- **동기화 중 표시가 없다.** 받는 동안 저장해 둔 자료를 그대로 보여 주고, 끝나면 조용히 다시 그린다. 스피너가 필요하면 `syncLmsNow`가 돌아올 때까지 작은 표시를 붙이면 된다.
- 과제 목록 전용 화면(`GET /lms/assignments`)은 아직 없다. 과목 상세의 과제 탭과 플래너가 그 자리를 메우고 있다.
- `getMaterial`(강의자료 요약, P1)과 공지(F-53)는 그대로 준비 중이다.

## 문서에 반영하기

````text
docs/Nextjs_이식_가이드.md 한 파일만 고치면 된다. "목 함수 → 실제 API" 표의 다섯 줄이고,
아래 "찾을 줄"은 파일에 한 번만 나온다.

[1] 설정
찾을 줄:
| `getSettings` · `saveSettings` | `GET` · `PATCH /me/settings` | P1. API 전까지 실제 모드는 설정에서 알림 구역을 숨긴다 |
이 줄을 아래 줄로 바꿔:
| `getSettings` · `saveSettings` | `GET` · `PATCH /me/settings` | 실제 API 연결(10/17) · 화면은 설정 전체를 보내고 서버는 받은 항목만 바꾼다 |

[2] LMS 연결 — 한 줄을 두 줄로 바꾼다(동기화 줄이 는다)
찾을 줄:
| `getLmsConnection` · `connectLms` · `disconnectLms` | `GET` · `POST` · `DELETE /lms/connection` | API 전까지 실제 모드는 '연결되지 않음', 연결 창은 준비 중 안내 |
이 줄을 아래 두 줄로 바꿔:
| `getLmsConnection` · `connectLms` · `disconnectLms` | `GET` · `POST` · `DELETE /lms/connection` | 실제 API 연결(10/17) · 연결이 없으면 404라 '연결 안 됨'으로 바꿔 준다. `connectLms`는 연결 결과(`LmsConnectResult`)를 주고 첫 동기화까지 기다린다 |
| `syncLmsNow` (새로) | `POST /lms/sync` → `waitForRun` | 실제 API 연결(10/17) · 학업 화면을 열 때 한 번. 5분 안에 받았으면 서버가 건너뛰고 false다 |

[3] 과목·과목 상세
찾을 줄:
| `getCourses` · `getCourse` | `GET /lms/courses` · `GET /lms/courses/{id}` | |
이 줄을 아래 줄로 바꿔:
| `getCourses` · `getCourse` | `GET /lms/courses` · `GET /lms/courses/{id}` | 실제 API 연결(10/17) · 상세를 열면 서버가 '봤다'고 적어 새 자료 수가 줄어든다 |

[4] 새 소식
찾을 줄:
| `getLmsUpdates` | `GET /lms/updates` | |
이 줄을 아래 줄로 바꿔:
| `getLmsUpdates` | `GET /lms/updates` | 실제 API 연결(10/17) · 최근 14일 한 쪽(50개). 공지는 F-53이 채운다 |

[5] 강의자료 요약
찾을 줄:
| `getMaterial` | `GET /materials/{file_id}` | 8장 필드 이름 대조 필요 |
이 줄을 아래 줄로 바꿔:
| `getMaterial` | `GET /materials/{file_id}` | 8장 필드 이름 대조 필요 · API 전까지 실제 모드는 준비 중 안내 |
````

## 코드

아래 파일 10개를 그대로 만들거나 덮어쓴다. 샌드박스에서 `typecheck`·빌드(실제·목 두 모드)와 api `ruff`·`pytest`(DB 포함)를 통과한 코드다.

### web (데이터 함수·타입)

#### `web/src/types/lms.ts`

```ts
// LMS·강의자료 타입 (API 명세 8·9장). 화면은 @/types/api에서 가져간다
import type { RunStatus } from "@/types/api";

// GET /lms/connection
export interface LmsConnection {
  status: "active" | "error" | "disconnected";
  token_last4: string | null;
  last_synced_at: string | null;
  last_error: string | null;
}

// POST /lms/connection — 토큰을 확인하고 수강 과목을 받아 둔 결과(첫 동기화가 바로 시작된다)
export interface LmsConnectResult {
  status: "active";
  token_last4: string;
  courses: number;
  first_sync_run_id: string | null;
}

// GET /lms/courses
export interface Course {
  id: string;
  canvas_course_id: number;
  name: string;
  short_name: string;
  has_syllabus: boolean;
  portal_syllabus_url: string | null; // 과목명 꼴이 달라 번호를 못 뽑으면 null
  open_assignments: number;
  new_materials: number;
  next_due: {
    kind: "assignment" | "syllabus_item";
    title: string;
    due_at: string;
  } | null;
}

// POST /lms/sync (F-51) — 202면 run_id, 5분 안에 이미 받았으면 200 + skipped
export interface SyncStarted {
  run_id: string;
  status: "running";
}
export interface SyncSkipped {
  skipped: true;
  last_synced_at: string | null;
}
export type SyncResponse = SyncStarted | SyncSkipped;

// POST /internal/jobs/lms-sync (30분 배치, 서비스 키로만 부른다 — 프론트에서 쓰지 않는다)
export interface LmsSyncJobResult {
  users: number;
  synced: number;
  failed: number;
  skipped: number;
  new_assignments: number;
  due_changed: number;
  submitted: number;
}

// GET /runs/{id}의 result (kind: "lms_sync"). 공지는 F-53이라 아직 0이다
export interface LmsSyncResult {
  kind: "lms_sync";
  courses: number;
  assignments: { new: number; due_changed: number; submitted: number };
  new_module_items: number;
  new_announcements: number;
  calendar_events: number; // 캘린더에 새로 넣은 과제 마감 수(설정을 켠 사람만)
  calendar_moved: number; // 마감이 바뀌어 시각을 고친 일정 수
}

// GET /lms/assignments?state=open|submitted|all&lms_course_id= (주지 않으면 open)
export type AssignmentState = "open" | "submitted" | "all";
export interface Assignment {
  id: string;
  course: { id: string; short_name: string };
  title: string;
  due_at: string | null; // 마감이 없는 과제도 있다(due_at·lock_at 둘 다 없음)
  submission_state: SubmissionState;
  html_url: string | null;
  planner_task_id: string | null;
  calendar_registered: boolean;
}

// GET /lms/courses/{id}
export type SubmissionState =
  "unsubmitted" | "submitted" | "graded" | "pending_review";
export type AnnouncementCategory =
  "schedule_change" | "material" | "opportunity" | "general";
export interface CourseDetail {
  course: {
    id: string;
    short_name: string;
    html_url: string;
    has_syllabus: boolean;
    portal_syllabus_url: string | null;
  }; // html_url: 과목 홈 (API v0.3 보완)
  // LMS가 비워 보내는 칸은 null이 올 수 있다(마감 없는 과제, 주차 이름·링크 없는 항목)
  assignments: {
    id: string;
    title: string;
    due_at: string | null;
    submission_state: SubmissionState;
    html_url: string | null;
  }[];
  module_items: {
    id: string;
    module_name: string | null;
    title: string;
    item_type: string | null;
    html_url: string | null;
    is_new: boolean;
    uploaded_file_id: string | null;
  }[];
  announcements: {
    id: string;
    title: string;
    summary: string | null;
    category: AnnouncementCategory | null;
    posted_at: string | null;
    opportunity_id: string | null;
  }[];
  syllabus_items: {
    id: string;
    item_type: "midterm" | "final" | "presentation" | "assignment" | "etc";
    title: string;
    starts_at: string | null;
    is_confirmed: boolean;
  }[];
  materials: {
    file_id: string;
    original_name: string | null;
    status: RunStatus;
  }[];
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

// GET /lms/updates?since=&type=module_item,assignment&lms_course_id=&cursor=
// since를 주지 않으면 최근 14일. announcement는 F-53이 채운다(그때까지 비어 있다)
export type LmsUpdateType = "module_item" | "assignment" | "announcement";
export type LmsUpdate =
  | {
      type: "module_item";
      id: string;
      course: { id: string; short_name: string };
      module_name: string | null;
      title: string;
      item_type: string | null;
      html_url: string | null;
      first_seen_at: string;
      uploaded_file_id: string | null;
    }
  | {
      type: "announcement";
      id: string;
      course: { id: string; short_name: string };
      title: string;
      summary: string | null;
      posted_at: string;
      category: AnnouncementCategory | null;
      attachment_count: number;
      opportunity_id: string | null;
      planner_task_id: string | null;
    }
  | {
      type: "assignment";
      id: string;
      course: { id: string; short_name: string };
      title: string;
      due_at: string | null;
      submission_state: SubmissionState;
      html_url: string | null;
      first_seen_at: string;
    };
export interface LmsUpdateList {
  items: LmsUpdate[];
  next_cursor: string | null;
}
```

#### `web/src/api/lmsClient.ts`

```ts
import { ApiError, apiFetch, notReady, USE_MOCKS, waitForRun } from "@/api/http";
import * as mock from "@/api/mockClient";
import type {
  Course,
  CourseDetail,
  LmsConnectResult,
  LmsConnection,
  LmsUpdate,
  MaterialDetail,
  SyncResponse,
} from "@/types/api";

// LMS 연결·동기화·과목·새 소식·강의자료 (API 명세 8·9장). 화면은 client.ts를 거쳐 쓴다.
// TODO(api): 강의자료 요약(GET /materials/{file_id}, 8장)만 아직 없다. 그때까지 실제 모드는 준비 중 안내다

const DISCONNECTED: LmsConnection = {
  status: "disconnected",
  token_last4: null,
  last_synced_at: null,
  last_error: null,
};

// 연결이 없으면 서버가 404 LMS_NOT_CONNECTED를 준다. 화면에는 "연결 안 됨"이 정상 상태다
function asDisconnected(error: unknown): LmsConnection {
  if (error instanceof ApiError && error.code === "LMS_NOT_CONNECTED") return DISCONNECTED;
  throw error;
}

// GET /lms/connection
export function getLmsConnection(): Promise<LmsConnection> {
  if (USE_MOCKS) return mock.getLmsConnection();
  return apiFetch<LmsConnection>("/lms/connection").catch(asDisconnected);
}

// POST /lms/connection. 토큰은 서버로만 보내고 클라이언트에 저장하지 않는다.
// 서버가 수강 과목을 먼저 받아 두고 과제는 첫 동기화로 받는다. 그 동기화까지 기다렸다가
// 끝내야 학업 화면이 "과목은 있는데 과제가 0"으로 보이지 않는다(오래 걸리면 기다리지 않는다)
export async function connectLms(token: string): Promise<LmsConnectResult> {
  if (USE_MOCKS) return mock.connectLms(token);
  const result = await apiFetch<LmsConnectResult>("/lms/connection", {
    method: "POST",
    body: JSON.stringify({ access_token: token }),
  });
  if (result.first_sync_run_id) {
    await waitForRun(result.first_sync_run_id).catch(() => undefined);
  }
  return result;
}

// POST /lms/sync 뒤 결과까지 기다린다. **화면이 목록을 다시 받아야 하면 true**다.
// 마지막 동기화가 5분 안이면 서버가 건너뛰므로(200) 다시 받을 것이 없다.
// 실패했을 때도 true다 — 토큰이 막혔으면 연결 상태가 error로 바뀌어 화면에 알려야 한다
export async function syncLmsNow(): Promise<boolean> {
  if (USE_MOCKS) return mock.syncLmsNow();
  const started = await syncLms().catch(() => null);
  if (started === null) return true;
  if (!("run_id" in started)) return false;
  return (await waitForRun(started.run_id).catch(() => null)) !== null;
}

// DELETE /lms/connection. 토큰만 지우고 과목·과제 기록은 남는다
export async function disconnectLms(): Promise<LmsConnection> {
  if (USE_MOCKS) return mock.disconnectLms();
  await apiFetch<void>("/lms/connection", { method: "DELETE" }).catch(asDisconnected);
  return DISCONNECTED;
}

// POST /lms/sync (F-51). 202면 run_id, 마지막 동기화가 5분 안이면 200 + skipped다.
// 목 모드는 받아 둔 목데이터가 곧 결과라 건너뛴 것으로 친다
export function syncLms(): Promise<SyncResponse> {
  if (USE_MOCKS) return mock.syncLms();
  return apiFetch<SyncResponse>("/lms/sync", { method: "POST" });
}

// GET /lms/courses
export async function getCourses(): Promise<Course[]> {
  if (USE_MOCKS) return mock.getCourses();
  const { items } = await apiFetch<{ items: Course[] }>("/lms/courses");
  return items;
}

// GET /lms/courses/{id}. 부르면 서버가 그 과목을 "봤다"고 적는다(새 자료 수가 줄어든다)
export function getCourse(id: string): Promise<CourseDetail> {
  if (USE_MOCKS) return mock.getCourse(id);
  return apiFetch<CourseDetail>(`/lms/courses/${encodeURIComponent(id)}`);
}

// GET /lms/updates. 최근 14일 새 소식을 처음 본 순으로. 한 쪽(50개)만 쓴다
export async function getLmsUpdates(): Promise<LmsUpdate[]> {
  if (USE_MOCKS) return mock.getLmsUpdates();
  const { items } = await apiFetch<{ items: LmsUpdate[]; next_cursor: string | null }>(
    "/lms/updates",
  );
  return items;
}

export function getMaterial(fileId: string): Promise<MaterialDetail> {
  return USE_MOCKS ? mock.getMaterial(fileId) : notReady("강의자료 요약은 아직 준비 중이에요.");
}
```

#### `web/src/api/accountClient.ts`

```ts
import { ApiError, apiFetch, notReady, USE_MOCKS } from "@/api/http";
import * as mock from "@/api/mockClient";
import { connectGoogleCalendar } from "@/lib/googleCalendar";
import type {
  ClientEvent,
  ConsentResult,
  Department,
  IncomeConsentResult,
  Me,
  NotificationList,
  NotificationReadResult,
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

// 설정 밖(공고 상세의 "캘린더에 넣기")에서 캘린더 권한을 받으러 갈 때. 끝나면 next로 돌아온다.
// 목 모드는 Google로 가지 않고 그 자리에서 연결한 것으로 친다(부르는 쪽이 이어서 등록한다)
export async function connectCalendar(next: string): Promise<void> {
  if (USE_MOCKS) {
    await mock.reconnectCalendar();
    return;
  }
  const error = await connectGoogleCalendar(next);
  if (error) throw new ApiError("CALENDAR_CONNECT_FAILED", error, 0);
  return new Promise<void>(() => {}); // 페이지가 Google로 넘어가므로 끝나지 않는다
}

// POST /events. 기록용이라 기다리지 않고, 실패해도 화면은 그대로 둔다 (API 4장)
export function recordEvent(event: ClientEvent, opportunityId?: string): void {
  if (USE_MOCKS) return;
  apiFetch<void>("/events", {
    method: "POST",
    body: JSON.stringify(opportunityId ? { event, opportunity_id: opportunityId } : { event }),
  }).catch(() => undefined);
}

// GET /me/settings. 바꾼 적이 없으면 서버가 기본값을 준다(푸시 켬·끈 종류 없음·자동 등록 켬)
export function getSettings(): Promise<Settings> {
  return USE_MOCKS ? mock.getSettings() : apiFetch<Settings>("/me/settings");
}

// PATCH /me/settings. 화면은 설정 전체를 보내고 서버는 받은 항목만 바꾼다
export function saveSettings(settings: Settings): Promise<Settings> {
  if (USE_MOCKS) return mock.saveSettings(settings);
  return apiFetch<Settings>("/me/settings", {
    method: "PATCH",
    body: JSON.stringify(settings),
  });
}

// 알림함 한 쪽에 담는 알림 수. 서버 최대값은 50이다(API 명세 10장)
export const NOTIFICATION_PAGE_SIZE = 20;

export interface NotificationParams {
  unreadOnly?: boolean;
  limit?: number;
  cursor?: string | null;
}

// GET /notifications (10장). 보낼 때가 지난 알림만 최신순으로 오고, unread_count는 필터와 상관없이 전체 기준이다.
// cursor는 unread_only가 같은 목록에서만 쓸 수 있어 다르면 422다(부르는 쪽이 처음부터 다시 받는다)
export function getNotifications(params: NotificationParams = {}): Promise<NotificationList> {
  if (USE_MOCKS) return mock.getNotifications(Boolean(params.unreadOnly));
  const query = new URLSearchParams({ limit: String(params.limit ?? NOTIFICATION_PAGE_SIZE) });
  if (params.unreadOnly) query.set("unread_only", "true");
  if (params.cursor) query.set("cursor", params.cursor);
  return apiFetch<NotificationList>(`/notifications?${query}`);
}

// POST /notifications/read. 새 안 읽은 수를 돌려준다(헤더 배지에 쓴다)
export function markNotificationRead(id: string): Promise<number> {
  return readNotifications({ ids: [id] });
}

export function markAllNotificationsRead(): Promise<number> {
  return readNotifications({ all: true });
}

async function readNotifications(body: { ids: string[] } | { all: true }): Promise<number> {
  if (USE_MOCKS) return mock.markNotificationsRead(body);
  const result = await apiFetch<NotificationReadResult>("/notifications/read", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return result.unread_count;
}

// 탈퇴를 받을지. TODO(api): DELETE /me(4장)가 생기면 deleteAccount를 바꾸고 지운다.
// 그 전까지 실제 모드는 탈퇴 창에서 준비 중이라고 먼저 알린다
export const DELETE_ACCOUNT_READY = USE_MOCKS;

export function deleteAccount(): Promise<void> {
  if (USE_MOCKS) return mock.deleteAccount();
  return notReady("탈퇴는 아직 준비 중이에요. 준비되면 이 화면에서 바로 탈퇴할 수 있어요.");
}
```

#### `web/src/api/mockClient.ts`

```ts
import { ApiError } from "@/api/http";
import { getDevScenario } from "@/dev/scenarios";
import { countItems } from "@/lib/feedCounts";
import { courseDetails, courses, lmsUpdates, materials, opportunities } from "@/mocks";
import { mockDepartments, mockNow } from "@/mocks/account";
import { rejudgeStoredOpportunity } from "@/mocks/rejudge";
import { setStoredMark } from "@/mocks/store";
import {
  listStoredNotifications,
  readAllStoredNotifications,
  readStoredNotifications,
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
  Category,
  ConsentResult,
  Course,
  CourseDetail,
  Department,
  FeedResponse,
  IncomeConsentResult,
  LmsConnectResult,
  LmsConnection,
  LmsUpdate,
  MaterialDetail,
  Me,
  NotificationList,
  OpportunityDetail,
  OpportunityMark,
  Profile,
  Settings,
  SyncResponse,
} from "@/types/api";

// 목 모드(NEXT_PUBLIC_USE_MOCKS=true)에서 쓰는 구현 (스킬 mock-to-api).
// 실제 모드 분기가 있는 함수의 목 구현과, 목 함수들이 같이 쓰는 응답 도구를 둔다
const WAIT_MS = 300;

export class MockApiError extends Error {
  constructor(
    public code: "poster_read_failed" | "lms_invalid",
    message: string,
  ) {
    super(message);
  }
}

// 응답이 없는 함수(204처럼 undefined)는 그대로 돌려준다. JSON.parse(undefined)는 오류라 약속이 끝나지 않는다
function clone<T>(value: T): T {
  return value === undefined ? value : (JSON.parse(JSON.stringify(value)) as T);
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

// 목 모드는 cursor·limit를 쓰지 않는다(여섯 건이라 한 쪽에 다 들어간다)
export function getNotifications(unreadOnly: boolean): Promise<NotificationList> {
  return respond(listStoredNotifications(unreadOnly));
}

export function markNotificationsRead(body: { ids: string[] } | { all: true }): Promise<number> {
  if ("all" in body) return respond(readAllStoredNotifications(mockNow));
  return respond(readStoredNotifications(body.ids, mockNow));
}

// 공고 피드·상세 (client.ts)

// 실제 API처럼 관심 없음 공고는 includeNotInterested일 때만 주고, 요약 카드 숫자(카테고리와 상관없는 전체
// 기준)에서는 늘 뺀다
export function getFeed(
  categories: Category[] | null,
  sort: "deadline" | "recent",
  includeNotInterested: boolean,
): Promise<FeedResponse> {
  if (getDevScenario() === "empty_feed") {
    return respond({ items: [], next_cursor: null, counts: countItems([]) });
  }
  const shown = opportunities.filter((item) => item.my_mark !== "not_interested");
  const items = (includeNotInterested ? opportunities : shown).filter((item) => !categories || categories.includes(item.category));
  items.sort((a, b) =>
    sort === "deadline"
      ? (a.d_day ?? Number.MAX_SAFE_INTEGER) - (b.d_day ?? Number.MAX_SAFE_INTEGER)
      : // 실제 API는 등록 최신순이다. 목데이터에는 등록 시각이 없어 새 공고만 앞으로 보낸다
        Number(b.is_new) - Number(a.is_new),
  );
  return respond({ items, next_cursor: null, counts: countItems(shown) });
}

// 정보 입력으로 프로필(목 저장소)이 채워졌으면 그 자리에서 다시 판정한 것처럼 바꿔서 준다
export function getOpportunity(id: string): Promise<OpportunityDetail> {
  const detail = rejudgeStoredOpportunity(id, getStoredProfile());
  if (!detail) return Promise.reject(new Error("공고를 찾을 수 없어요."));
  return respond(detail);
}

// 실제 API처럼 없는 공고에 표시를 붙이면 404 NOT_FOUND이고, 지우기는 늘 된다
export function setOpportunityMark(id: string, mark: OpportunityMark | null): Promise<void> {
  if (!setStoredMark(id, mark) && mark !== null) {
    return rejectAfter(new ApiError("NOT_FOUND", "공고를 찾을 수 없어요.", 404));
  }
  return respond(undefined);
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

export function connectLms(token: string): Promise<LmsConnectResult> {
  const normalized = token.trim();
  if (token !== normalized || normalized.length < 8) {
    return rejectAfter(new MockApiError("lms_invalid", "LearningX 토큰을 확인할 수 없어요."));
  }
  const connection = connectStoredLms(normalized.slice(-4));
  return respond({
    status: "active",
    token_last4: connection.token_last4 ?? normalized.slice(-4),
    courses: courses.length,
    first_sync_run_id: null, // 목 모드는 받아 둔 목데이터가 곧 결과다
  });
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

// 목 모드는 받아 둔 목데이터가 곧 최신이다. 실제 모드와 같은 두 모양을 번갈아 준다 —
// 첫 번째는 "받았다"(화면이 목록을 다시 받는 경로를 목에서도 한 번 돈다), 그 뒤는 "건너뜀"
let syncedOnce = false;

export function syncLms(): Promise<SyncResponse> {
  if (syncedOnce) return respond({ skipped: true, last_synced_at: mockNow });
  syncedOnce = true;
  return respond({ run_id: "mock-sync-run", status: "running" });
}

// 목 모드는 /runs를 부르지 않고 바로 끝난 것으로 친다(목 자료는 이미 최신이다)
export function syncLmsNow(): Promise<boolean> {
  return syncLms().then((started) => "run_id" in started);
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

### web (화면)

#### `web/src/components/LmsConnectModal.tsx`

```tsx
import { useState } from "react";
import { ApiError, connectLms, errorMessage } from "@/api/client";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import type { LmsConnectResult, LmsConnection } from "@/types/api";

interface LmsConnectModalProps {
  open: boolean;
  onClose: () => void;
  onConnected: (connection: LmsConnection) => void;
}

type ConnectStatus = "idle" | "checking" | "success" | "failure";

const TOKEN_FAILURE = "토큰을 확인할 수 없어요. 복사할 때 앞뒤 공백이 들어갔는지 확인해 주세요";
const RETRY_FAILURE = "지금은 LearningX에서 받아올 수 없어요. 잠시 후 다시 시도해 주세요";

export default function LmsConnectModal({
  open,
  onClose,
  onConnected,
}: LmsConnectModalProps) {
  const [step, setStep] = useState(1);
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<ConnectStatus>("idle");
  const [connected, setConnected] = useState<LmsConnectResult | null>(null);
  const [failure, setFailure] = useState(TOKEN_FAILURE);

  const close = () => {
    setStep(1);
    setToken("");
    setStatus("idle");
    setConnected(null);
    setFailure(TOKEN_FAILURE);
    onClose();
  };

  const connect = async () => {
    setStatus("checking");
    try {
      const result = await connectLms(token);
      setConnected(result);
      setStatus("success");
      onConnected({
        status: result.status,
        token_last4: result.token_last4,
        last_synced_at: null, // 방금 받았다. 정확한 시각은 다음에 연결 상태를 받을 때 온다
        last_error: null,
      });
    } catch (caught) {
      // 토큰이 틀린 것(422)과 LearningX가 멈춘 것(502)·서버에 닿지 못한 것은 다른 일이다.
      // 명세 13장의 문구를 그대로 쓰고, 토큰 문제일 때만 공백 안내를 붙인다
      const invalid = caught instanceof ApiError && caught.code === "LMS_TOKEN_INVALID";
      setFailure(invalid ? TOKEN_FAILURE : errorMessage(caught, RETRY_FAILURE));
      setStatus("failure");
    } finally {
      setToken("");
    }
  };

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
          <p className="mt-4 text-[14px] font-semibold">토큰을 확인하고 과제를 받아오고 있어요</p>
          <p className="mt-1 text-[12px] text-[#667085]">조금 걸릴 수 있어요. 창을 닫지 말아 주세요.</p>
        </div>
      )}
      {step === 3 && status === "success" && connected && (
        <div className="py-6 text-center">
          <p className="text-[20px] font-bold text-[#15803d]">
            {connected.courses}개 과목을 불러왔어요
          </p>
          <p className="mt-2 text-[12px] text-[#667085]">
            연결된 토큰 끝 4자리 {connected.token_last4}
          </p>
          <div className="mt-6"><Button onClick={close}>완료</Button></div>
        </div>
      )}
      {step === 3 && status === "failure" && (
        <div className="py-6 text-center">
          <p className="text-[16px] font-bold text-[#c53030]">{failure}</p>
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

#### `web/src/components/ConnectedServices.tsx`

```tsx
import { useState } from "react";
import { disconnectLms, errorMessage, nowIso, reconnectCalendar } from "@/api/client";
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
                ? `토큰 끝 4자리 ${lms.token_last4} · 마지막 동기화 ${lms.last_synced_at ? formatRelativeTime(lms.last_synced_at, nowIso()) : "없음"}`
                : "연결되지 않음. 학업 화면에서 연결할 수 있어요."}
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

#### `web/src/screens/Academics.tsx`

```tsx
import { useEffect, useRef, useState } from "react";
import {
  getCourses,
  getLmsConnection,
  getLmsUpdates,
  nowIso,
  syncLmsNow,
  todayKst,
} from "@/api/client";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import Header from "@/components/Header";
import LmsConnectModal from "@/components/LmsConnectModal";
import Skeleton from "@/components/Skeleton";
import { formatDday, formatRelativeTime, isDeadlineSoon } from "@/lib/format";
import useAsyncData from "@/lib/useAsyncData";
import type { LmsConnection, LmsUpdate } from "@/types/api";
import type { Route } from "@/types/route";

interface AcademicsProps {
  navigate: (route: Route) => void;
}

function AcademicsSkeleton() {
  return (
    <>
      <Skeleton className="h-[70px] w-[430px]" />
      <Skeleton className="h-[62px] w-full rounded-[14px]" />
      <div className="grid grid-cols-3 gap-4">
        <Skeleton className="h-[230px] rounded-2xl" />
        <Skeleton className="h-[230px] rounded-2xl" />
        <Skeleton className="h-[230px] rounded-2xl" />
      </div>
    </>
  );
}

function updateRoute(update: LmsUpdate): Route {
  if (update.type === "module_item") {
    return { name: "course", id: update.course.id, tab: "materials" };
  }
  if (update.type === "announcement") {
    return { name: "course", id: update.course.id, tab: "announcements" };
  }
  return { name: "course", id: update.course.id, tab: "assignments" };
}

function UpdateItem({
  update,
  navigate,
}: {
  update: LmsUpdate;
  navigate: (route: Route) => void;
}) {
  const heading =
    update.type === "module_item"
      ? `${update.course.short_name} ${update.module_name} 자료`
      : update.type === "announcement"
        ? `${update.course.short_name} 공지`
        : `${update.course.short_name} ${
            isDeadlineSoon(update.due_at, todayKst()) ? "과제 마감 임박" : "새 과제"
          }`;
  const note =
    update.type === "module_item"
      ? update.title
      : update.type === "announcement"
        ? update.summary
        : `${update.title} · ${formatDday(update.due_at, todayKst())}`;
  const color =
    update.type === "assignment"
      ? "text-[#c53030]"
      : update.type === "announcement"
        ? "text-[#b7791f]"
        : "text-[#4f6ef7]";

  return (
    <button
      type="button"
      onClick={() => navigate(updateRoute(update))}
      className="flex w-full gap-3 rounded-[10px] p-1 text-left hover:bg-[#f7f8fa]"
    >
      <span className={`mt-1 text-[12px] ${color}`}>●</span>
      <span className="min-w-0">
        <b className="block text-[14px] font-semibold">{heading}</b>
        <span className="mt-0.5 block truncate text-[12px] text-[#667085]">{note}</span>
      </span>
    </button>
  );
}

export default function Academics({ navigate }: AcademicsProps) {
  const [syncedAt, setSyncedAt] = useState(0); // 동기화가 끝나면 올려서 목록을 다시 받는다
  const request = useAsyncData(
    () => Promise.all([getLmsConnection(), getCourses(), getLmsUpdates()]),
    [syncedAt],
  );
  const [connectionOverride, setConnectionOverride] =
    useState<LmsConnection | null>(null);
  const [connectOpen, setConnectOpen] = useState(false);
  // 연결하면 서버가 이미 과목을 받아 뒀다(첫 동기화도 끝났다). 목록을 다시 받아야 화면이 채워진다
  const connected = (next: LmsConnection) => {
    setConnectionOverride(next);
    setSyncedAt(Date.now());
  };
  const status = (connectionOverride ?? request.data?.[0])?.status ?? null;

  // 화면을 열면 LMS를 한 번 받아 온다(명세 9장). 마지막 동기화가 5분 안이면 서버가 건너뛴다.
  // 받는 동안에도 저장해 둔 과제·자료를 그대로 보여 주고, 새로 받으면 그때 다시 그린다.
  // 다시 받는 동안에는 status가 잠깐 비므로, 화면을 열어 둔 동안 한 번만 부르게 막아 둔다
  const asked = useRef(false);
  useEffect(() => {
    if (status !== "active" || asked.current) return;
    asked.current = true;
    let alive = true;
    syncLmsNow().then((fresh) => {
      if (alive && fresh) setSyncedAt(Date.now());
    });
    return () => {
      alive = false;
    };
  }, [status]);

  if (request.loading) return <AcademicsSkeleton />;
  if (request.error || !request.data) {
    return (
      <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">
        {request.error ?? "학업 정보를 불러오지 못했어요."}
      </p>
    );
  }

  const [, courses, updates] = request.data;
  const connection = connectionOverride ?? request.data[0];

  if (connection.status === "disconnected") {
    return (
      <>
        <Header title="학업" subtitle="LMS 과제와 새 자료를 확인하고 강의자료를 요약할 수 있어요." />
        <section className="flex min-h-[480px] flex-col items-center justify-center rounded-[18px] border border-[#e5e7eb] bg-white p-8 text-center">
          <Badge tone="yellow">LearningX 미연결</Badge>
          <h2 className="mt-4 text-[24px] font-bold">LearningX를 연결해 주세요</h2>
          <p className="mt-2 text-[14px] text-[#667085]">
            연결하면 과제 마감일과 새 강의자료를 한곳에서 확인할 수 있어요.
          </p>
          <div className="mt-6"><Button onClick={() => setConnectOpen(true)}>LearningX 연결하기</Button></div>
        </section>
        {/* 연결 창은 연결 전·후 트리에서 **같은 자리(세 번째)**에 둔다. 자리가 바뀌면 React가 창을
            새로 만들어 "연결했어요" 대신 1단계가 다시 뜬다 */}
        <LmsConnectModal
          key="lms-connect"
          open={connectOpen}
          onClose={() => setConnectOpen(false)}
          onConnected={connected}
        />
      </>
    );
  }

  return (
    <>
      <Header title="학업" subtitle="LMS 과제와 새 자료를 확인하고 강의자료를 요약할 수 있어요." />
      {connection.status === "error" ? (
        <section className="flex items-center justify-between gap-4 rounded-[14px] bg-[#fef2f2] p-[18px]">
          <p className="text-[13px] font-semibold text-[#c53030]">
            {connection.last_error ?? "LearningX 연결이 끊겼어요. 토큰이 만료됐거나 삭제됐어요"}
          </p>
          <Button secondary onClick={() => setConnectOpen(true)}>다시 연결</Button>
        </section>
      ) : (
        <section className="flex items-center gap-3 rounded-[14px] bg-[#eef2ff] p-[18px]">
          <Badge tone="green">LearningX 연결됨</Badge>
          <p className="text-[13px] font-medium text-[#344054]">
            마지막 동기화: {connection.last_synced_at ? formatRelativeTime(connection.last_synced_at, nowIso()) : "아직 없음"} · 토큰 끝 4자리 {connection.token_last4}
          </p>
        </section>
      )}
      <section className="grid grid-cols-4 gap-4 max-[1100px]:grid-cols-2 max-[760px]:grid-cols-1">
        {courses.map((course) => (
          <button
            type="button"
            key={course.id}
            onClick={() => navigate({ name: "course", id: course.id })}
            className="min-h-[230px] rounded-2xl border border-[#e5e7eb] bg-white p-[18px] text-left transition hover:-translate-y-0.5 hover:border-[#cfd7ff]"
          >
            <h2 className="text-[17px] font-semibold">{course.name}</h2>
            <div className="mt-3 flex gap-2">
              <Badge>과제 {course.open_assignments}</Badge>
              <Badge tone="yellow">새 자료 {course.new_materials}</Badge>
            </div>
            <p className="mt-3 text-[12px] font-medium text-[#667085]">다음 일정</p>
            <p className="mt-2 text-[14px] font-semibold">
              {course.next_due
                ? `${course.next_due.title} · ${formatDday(course.next_due.due_at, todayKst())}`
                : "예정된 일정 없음"}
            </p>
            <span className="mt-3 block text-[12px] font-semibold text-[#4f6ef7]">
              과제 · 자료 · 공지 · 계획서 보기&nbsp; →
            </span>
          </button>
        ))}
      </section>
      {courses.length === 0 && (
        <section className="rounded-2xl border border-[#e5e7eb] bg-white p-8 text-center">
          <p className="text-[14px] font-semibold">아직 받아온 과목이 없어요</p>
          <p className="mt-2 text-[13px] text-[#667085]">
            이번 학기 수강 과목이 LearningX에 올라와 있는지 확인하고 다시 받아와 주세요.
          </p>
          <div className="mt-5">
            <Button secondary onClick={() => setSyncedAt(Date.now())}>다시 받아오기</Button>
          </div>
        </section>
      )}
      <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
        <h2 className="text-[18px] font-semibold">새로 들어온 학업 정보</h2>
        {updates.length === 0 && (
          <p className="mt-3 text-[13px] text-[#667085]">
            최근 2주 동안 새로 올라온 자료나 과제가 없어요. 과목을 누르면 지난 자료도 볼 수 있어요.
          </p>
        )}
        <div className="mt-3 flex flex-col gap-3">
          {updates.map((update) => (
            <UpdateItem
              key={`${update.type}-${update.id}`}
              update={update}
              navigate={navigate}
            />
          ))}
        </div>
      </section>
      <LmsConnectModal
        key="lms-connect"
        open={connectOpen}
        onClose={() => setConnectOpen(false)}
        onConnected={connected}
      />
    </>
  );
}
```

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
  changeValue,
  fromFormValues,
  toFormValues,
  validateProfile,
  withoutError,
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
  // 이미 LearningX를 연결한 사람은 마지막 LMS 단계를 건너뛴다
  const finish = () => (me.lms?.status === "active" ? onDone() : setStage({ kind: "lms" }));
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
            onChange={(key, value) => {
              setValues((current) => (current ? changeValue(current, key, value) : current));
              setErrors((current) => withoutError(current, key));
            }}
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
import { DEGREE_LABELS, regionText, type ProfileErrors } from "@/lib/profileFields";
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
  const academicStatus = [
    profile.degree_program ? DEGREE_LABELS[profile.degree_program] : null,
    profile.enrollment_status ? enrollmentLabels[profile.enrollment_status] : null,
  ].filter(Boolean).join(" ");
  const showToast = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(""), 2400);
  };
  // 토글은 누르는 즉시 움직이고(낙관), 저장에 실패하면 되돌리고 알려 준다. 서버 응답으로
  // 다시 덮어쓰지 않는다 — 연달아 누르면 늦게 온 응답이 마지막 클릭을 덮어쓴다
  const updateSettings = async (next: SettingsData) => {
    const before = settings;
    setSettingsOverride(next);
    try {
      await saveSettings(next);
    } catch (caught) {
      setSettingsOverride(before);
      showToast(errorMessage(caught, "설정을 저장하지 못했어요. 잠시 후 다시 눌러 주세요."));
    }
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
            ["학적", `${profile.department ?? "미입력"} · ${academicStatus || "미입력"}`],
            ["성적", profile.gpa_last_semester ? `${profile.gpa_last_semester} / ${profile.gpa_scale}` : "미입력"],
            ["나이", age ? `${age}세` : "미입력"],
            ["지역", regionText(profile)],
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
      <NotificationSettings settings={settings} onChange={updateSettings} />
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

### api (계약 대조 테스트)

#### `api/tests/test_web_contract.py`

```python
"""web 타입(`web/src/types/*.ts`)과 API 응답 모델의 칸 이름이 같은지 본다.

`api/CLAUDE.md`: "응답 모델 이름은 `web/src/types/api.ts`와 같게 한다". 이름이 어긋나면 목을 실제
호출로 바꾸는 순간 화면이 빈칸을 그린다(F-14에서 `module_name`·`html_url`이 그랬다).

안에 든 묶음까지 본다: `course.id`·`module_items[].module_name`처럼 길로 펴서 비교한다.
타입·null 여부는 보지 않는다(그건 화면 쪽 typecheck가 잡는다).

web 폴더가 없는 환경(배포 이미지 등)에서는 건너뛴다.
"""

import re
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.main import create_app

WEB_TYPES = Path(__file__).resolve().parents[2] / "web" / "src" / "types"

pytestmark = pytest.mark.skipif(not WEB_TYPES.is_dir(), reason="web 폴더가 없어서 건너뜀")

# (web 타입 이름, API 응답 모델 이름). 화면이 실제 API로 받는 것만 적는다
PAIRS = [
    ("Me", "Me"),
    ("Settings", "Settings"),
    ("LmsConnection", "ConnectionView"),
    ("LmsConnectResult", "ConnectResult"),
    ("Course", "CourseItem"),
    ("CourseDetail", "CourseDetail"),
    ("Assignment", "AssignmentItem"),
    ("LmsSyncResult", "LmsSyncResult"),
    ("SyncStarted", "SyncStarted"),
    ("SyncSkipped", "SyncSkipped"),
]
# `GET /lms/updates`는 종류별로 모양이 다르다(web은 합집합 하나로 적는다)
UPDATE_PAIRS = [("module_item", "ModuleItemUpdate"), ("assignment", "AssignmentUpdate")]


def _text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(WEB_TYPES.glob("*.ts")))


def _strip_comments(body: str) -> str:
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return "\n".join(line.split("//")[0] for line in body.split("\n"))


def _segments(body: str) -> list[str]:
    """`;`(묶음 바깥)로 끊어 "이름: 값" 토막들로 만든다."""
    found, buffer, depth = [], "", 0
    for char in body:
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        if char == ";" and depth == 0:
            found.append(buffer)
            buffer = ""
            continue
        buffer += char
    return found + [buffer]


def _ts_paths(body: str, prefix: str = "") -> set[str]:
    """칸 이름을 길로 펴서 모은다(묶음은 `a.b`, 묶음 배열은 `a[].b`)."""
    found: set[str] = set()
    for segment in _segments(_strip_comments(body)):
        match = re.match(r"\s*(\w+)\??:\s*(.*)$", segment, re.S)
        if match is None:
            continue
        name, value = match.group(1), match.group(2)
        found.add(prefix + name)
        if "{" not in value:
            continue
        inner, rest = _braced(value)
        found |= _ts_paths(
            inner, f"{prefix}{name}{'[]' if rest.lstrip().startswith('[]') else ''}."
        )
    return found


def _braced(value: str) -> tuple[str, str]:
    """`{ ... }` 안쪽과 그 뒤에 남은 것(배열인지 보려고)."""
    start, depth = value.index("{"), 0
    for index in range(start, len(value)):
        depth += (value[index] == "{") - (value[index] == "}")
        if depth == 0:
            return value[start + 1 : index], value[index + 1 :]
    raise AssertionError("묶음이 닫히지 않았어요")


def _ts_interface(text: str, name: str) -> str:
    body = re.search(rf"export interface {name} \{{(.*?)\n\}}", text, re.S)
    assert body is not None, f"web 타입 {name}을 찾지 못했어요"
    return body.group(1)


def _ts_union(text: str, kind: str) -> str:
    body = re.search(r"export type LmsUpdate =(.*?)export interface LmsUpdateList", text, re.S)
    assert body is not None
    return next(one for one in body.group(1).split("| {") if f'type: "{kind}"' in one)


def _api_paths(schemas: dict[str, Any], schema: dict[str, Any], prefix: str = "") -> set[str]:
    """OpenAPI 스키마를 같은 꼴의 길로 펴낸다($ref를 따라 내려간다)."""
    found: set[str] = set()
    for name, raw in schema.get("properties", {}).items():
        found.add(prefix + name)
        inner, array = _unwrap(schemas, raw)
        if inner is not None:
            found |= _api_paths(schemas, inner, f"{prefix}{name}{'[]' if array else ''}.")
    return found


def _unwrap(schemas: dict[str, Any], raw: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    """그 칸이 묶음(또는 묶음 배열)이면 그 스키마와 배열인지를 돌려준다."""
    for branch in raw.get("anyOf", [raw]):  # null 가능 칸은 anyOf로 온다
        if "$ref" in branch:
            found = schemas[branch["$ref"].rsplit("/", 1)[1]]
            return (found, False) if found.get("properties") else (None, False)
        if branch.get("type") == "array":
            inner, _ = _unwrap(schemas, branch.get("items", {}))
            if inner is not None:
                return inner, True
        if branch.get("properties"):
            return branch, False
    return None, False


@pytest.fixture(scope="module")
def schemas() -> dict[str, Any]:
    spec = create_app(Settings(_env_file=None)).openapi()  # type: ignore[call-arg]
    return spec["components"]["schemas"]


@pytest.mark.parametrize(("ts_name", "api_name"), PAIRS)
def test_the_web_type_has_the_same_fields(
    schemas: dict[str, Any], ts_name: str, api_name: str
) -> None:
    mine = _ts_paths(_ts_interface(_text(), ts_name))
    assert mine == _api_paths(schemas, schemas[api_name])


@pytest.mark.parametrize(("kind", "api_name"), UPDATE_PAIRS)
def test_the_update_union_matches(schemas: dict[str, Any], kind: str, api_name: str) -> None:
    mine = _ts_paths(_ts_union(_text(), kind))
    assert mine == _api_paths(schemas, schemas[api_name])
```

