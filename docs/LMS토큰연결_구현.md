# LMS 토큰 연결 — LearningX 토큰을 확인·암호화해 저장하고 수강 과목을 받아 둔다

> 📝 기준: PRD v0.9 F-50 · API 명세 v0.4 8·9·13장 · ERD v0.9 3-2 · 2026-10-16 LearningX 녹화 · 2026-10-16
>
> 함께 보는 파일: `알림함화면_구현.md`(먼저 합쳤다, main f22a8e9) · `LMS녹화_안내.md`(이 PR의 입력)

남은 P0 중 가장 큰 덩어리가 LMS 넷(F-50·51·52·14)인데, 그 입구인 **토큰 연결(F-50)** 이다. 오늘 네가 돌린 녹화로 응답 모양이 확정돼서 지어낸 값 없이 짤 수 있게 됐다.

이 PR이 하는 일: 학생이 LearningX 개인 액세스 토큰을 붙여넣으면 **확인 → 암호화 저장 → 수강 과목 받아 두기**까지. 과제·주차 항목·공지 동기화(F-51·F-52)와 강의계획서(F-14)는 다음 PR이고, 이 PR은 그 셋이 올라설 바닥을 깐다.

**규모와 확인:**
- **api가 주로 바뀐다.** 새 파일 12개(코드 7 + 테스트 5), 바꾸는 파일 9개(api 6 + web 3). web 쪽은 이 PR이 바꾼 계약을 타입에 반영하는 것뿐이다.
- **DB 변경이 없다.** `lms_connections`·`lms_courses`·`lms_assignments`·`lms_module_items`·`syllabi`·`syllabus_items`가 모두 있고 `lms_courses.last_viewed_at`도 있다. db push가 필요 없다.
- 엔드포인트 네 개를 코드로 처음 연다: `POST`·`GET`·`DELETE /lms/connection`, `GET /lms/courses`. **명세에 이미 있는 경로라 새 엔드포인트를 더하지 않는다.**
- api `764 passed, 170 skipped`(DB 없이), DB를 붙이면 `934 passed`. 전에는 `727 passed, 156 skipped` / `883 passed`였다(+37 / +51).
- **되돌림 시험 35가지를 모두 잡았다.**
- 따로 띄운 검토 에이전트가 한 번 봤다. 지적 19건 중 **높음 2건·중간 5건을 고쳤고**, 그중 하나는 **토큰이 평문 HTTP로 나갈 수 있는 구멍**이었다(아래 "검토에서 고친 것").

## 녹화로 확정한 것

네가 돌린 두 번의 녹화(8과목 목록 + 6과목의 과제 17건·주차 항목 87건·공지 16건)에서 코드가 따르기로 한 사실이다. 전부 명세 8장·ERD 3-2·PRD 5-6에도 적었다.

| 확정 | 왜 중요한가 |
| --- | --- |
| 과제 마감일 = `due_at ?? lock_at` | 17건 중 **5건이 `due_at`이 null이고 `lock_at`만** 있었다. `due_at`만 봤으면 마감의 3분의 1을 놓친다 |
| 제출 여부 = `submission.workflow_state` ∈ {`submitted`, `graded`} | `has_submitted_submissions`는 **과목 전체 기준**이라 내가 안 낸 과제에도 true다. 이름만 보고 썼으면 F-51의 "제출하면 플래너 자동 완료"가 전부 오작동한다. 퀴즈는 자동 채점돼 바로 `graded`다 |
| 주차 항목 중복은 `canvas_item_id`로만 가린다 | 한 모듈에 **제목이 같은 항목이 둘씩**(87건 중 15쌍, 대면·온라인 영상). 제목으로 묶으면 새 자료를 놓친다 |
| 항목에 `File` 타입이 **0건** | 전부 `ExternalTool`(LearningX 출석·영상 LTI)·`Page`·`Quiz`·`Assignment`다. F-52를 "새 파일 감지"로 짰으면 영원히 0건이다 — **"새 자료"는 새 항목**이다 |
| `position`을 믿지 않는다 | 사회봉사는 "1주차"가 `position: 17`이고, 항목 position에 구멍이 있다(`[1,2,3,4,7,8]`). 정렬에만 쓰고 주차 번호는 이름에서 읽는다 |
| 모듈 이름 꼴이 셋 | `1주차` · `5주차 (개천절 대체휴일)` · `Week 3 : Software Configuration Management III …` |
| 과목명 = `202620HY23525_데이터베이스` | 앞에서 연도·학기·과목번호를 떼어 **포털 계획서 링크**를 만든다(F-14). `_` 뒤가 화면 이름이다. 꼴이 다른 과목은 링크를 만들지 않는다 |
| 학기 종료일은 `courses[].end_at` | `term.end_at`이 null이다. 토큰 만료일 안내에 쓴다 |
| 빈 과목이 흔하다 | 6과목 중 2과목이 과제 0건, 그중 하나는 모듈 16개가 전부 빈 항목이다. 빈 과목은 오류가 아니다 |
| 모듈 항목이 과제를 가리킨다 | `Assignment` 항목의 `content_id` = 과제 id, `Quiz` 항목은 퀴즈 id(과제의 `quiz_id`). 주차 ↔ 과제 연결이 공짜로 나온다(F-51에서 쓴다) |

## 정한 것

| 항목 | 정한 것 | 이유 |
| --- | --- | --- |
| 연결 순서 | 토큰 확인(`GET /api/v1/users/self`) → 수강 과목 목록 → **한 트랜잭션에 저장**. 확인 실패는 422 `LMS_TOKEN_INVALID`, 과목 목록 실패는 502 `LMS_API_ERROR`이고 **둘 다 아무것도 저장하지 않는다** | 과목을 못 읽으면 과제·자료도 못 읽어서 연결해 둘 뜻이 없다. 반쯤 연결된 상태를 만들지 않는다 |
| 실행 기록 | 두 호출을 **한 실행(`lms_sync`) 안의 도구 두 개**(`check_lms_token`·`fetch_lms_courses`)로 남긴다. 실패한 토큰 확인도 실행으로 남는다 | api/CLAUDE.md "외부 호출은 `agent_run` → `run.tool` 안에서만". 연결 성공률·지연이 AOP 지표로 나온다 |
| 허용 경로 | 녹화에서 쓴 **여섯 경로만** 코드 상수(`ALLOWED_PATHS`)에 두고, 그 밖은 요청을 만들기 전에 예외. GET만 보낸다 | 명세 9장. 토큰이 계정 전체 권한이라 클라이언트가 할 수 있는 일을 좁게 묶어 둔다 |
| 다음 쪽 따라가기 | `Link: rel="next"`는 **스킴·호스트가 같고 허용 경로일 때만** 따라간다. 리다이렉트는 따라가지 않고 3xx도 오류다 | 서버가 준 주소를 믿으면 그곳으로 토큰을 보낸다. `https`를 `http`로 바꿔 주면 평문으로 나간다 |
| 못 받은 목록 | 쪽 상한(10쪽)·시간 예산(60초)에 걸리면 **받은 것을 돌려주지 않고 예외**다 | 부분 목록을 전체로 쓰면 아래 "과목 내리기"가 멀쩡한 과목을 내린다 |
| 과목 내리기 | 이번 목록에 없던 과목은 `is_active`를 내려 목록에서만 뺀다(행은 남긴다). **목록이 비어 오면 내리지 않는다** | 학기 사이·필터 때문에 비어 올 수 있다. 그때 전부 내리면 F-50에는 `POST /lms/sync`가 없어서 토큰을 다시 붙여넣기 전까지 과목이 하나도 안 보인다 |
| 어떤 과목을 받나 | 학생 등록(`enrollments[].type = student`)이고 `workflow_state`가 `available`·`completed`인 과목만. 과목 번호가 bigint를 넘거나 bool이면 버린다 | 조교·청강 과목의 과제는 내 것이 아니다. 이상한 번호를 그대로 넣으면 DB가 터져 500이 난다(명세대로면 502여야 한다) |
| 토큰 | 요청으로만 받고 앞뒤 공백을 뗀다. Fernet으로 암호화해 저장하고 응답·로그·`tool_calls`에는 **끝 4자리만** 간다 | PRD 7장. 복사할 때 공백이 자주 섞인다 |
| 연결 상태 | DB에 있는 값을 그대로 내려준다(`active`·`error`·`disconnected`) | `GET /me`의 `lms.status`와 web 타입이 세 값이다. API만 둘로 뭉개면 같은 계정이 화면마다 다른 상태로 보인다 |
| 과목 목록 숫자 | `open_assignments`·`new_materials`·`next_due`는 **지금 저장된 것으로 센다**(F-51·F-52 전에는 0·null) | 0은 거짓이 아니다 — 저장된 미제출 과제가 없다는 사실이다. 가짜 값을 넣지 않는다 |
| 녹화 샘플 | `tests/lms_samples.py`에 **과목 응답만** 넣고 값(과목 번호·이름·사용자 번호)은 바꿨다. 과제·모듈·공지 샘플은 F-51·F-52에서 더한다 | 모양은 그대로 두고 네 수강 내역이 레포에 남지 않게 한다. 쓰지 않는 샘플을 미리 넣어 두지 않는다 |

## 레포에 넣는 법

DB 변경이 없다. 합친 뒤 db push를 하지 않는다. `.env`에 새로 넣을 비밀값도 없다(`LMS_API_BASE`는 학교 LMS 주소이고 기본값이 그대로 맞다).

```text
web·api 개발 서버를 끄고 시작해. npm run dev나 uvicorn이 켜져 있으면 꺼 줘.
LMS 토큰 연결 PR을 넣자. docs/LMS토큰연결_구현.md를 docs/에 넣었어.
1. main을 최신으로 받아. git merge-base --is-ancestor f22a8e9 main이 실패하면(알림함 화면 PR이 없는 main) 멈추고 알려줘. 성공하면 feat/F-50-lms-connection 브랜치를 만들어.
2. 바꿀 파일의 기록을 봐: git log --oneline f22a8e9..main -- api/app/config.py api/app/main.py api/app/logging_redact.py api/.env.example api/tests/fakes.py api/tests/test_security.py web/src/types/lms.ts web/src/mocks/lms.ts web/src/components/CourseSyllabus.tsx docs/API_명세_v0.4.md docs/ERD_v0.9.md docs/PRD_v0.9.md
   아무 커밋도 나오지 않아야 해. 커밋이 나오거나 아래 새 파일 12개 중 이미 있는 것이 있으면 바꾸기 전에 멈추고 알려줘.
3. 문서 "코드"의 파일 21개를 문서 내용으로 통째로 만들거나 바꿔. 파일 경로는 "코드" 아래 #### 제목 그대로고, 내용은 고치지 마. .env·.env.local은 읽거나 고치지 마(.env.example만 바꾼다).
   새 파일 12개: api/app/lms/__init__.py, api/app/lms/client.py, api/app/lms/parse.py, api/app/lms/service.py, api/app/repositories/lms.py, api/app/routers/lms.py, api/app/schemas/lms.py, api/tests/lms_samples.py, api/tests/test_lms_parse.py, api/tests/test_lms_client.py, api/tests/test_lms_api.py, api/tests/test_lms_db.py
   바꾸는 파일 9개: api/app/config.py, api/app/main.py, api/app/logging_redact.py, api/.env.example, api/tests/fakes.py, api/tests/test_security.py, web/src/types/lms.ts, web/src/mocks/lms.ts, web/src/components/CourseSyllabus.tsx
4. 문서 "문서에 반영하기"의 요청도 이 브랜치에서 해(API 명세 다섯 곳, ERD 한 곳, PRD 세 곳).
5. 검사: api에서 uv run ruff format --check .와 uv run ruff check .을 돌리고, uv run pytest로 764 passed, 170 skipped인지 봐(Windows에서는 한 건이 더 건너뛰어져 763 passed, 171 skipped일 수 있어. 그 한 건은 앞 PR들과 같아). web에서는 npm run typecheck와 npm run build를 돌려.
6. 통과하면 커밋하고 PR을 열어. 제목은 "feat(F-50): LearningX 토큰 연결 — 확인·암호화 저장·수강 과목, GET과 허용 경로만"이고, 설명에 새로 만든·바꾼 파일, 검사 결과, 코드로 처음 여는 경로 네 개(POST·GET·DELETE /lms/connection, GET /lms/courses), 10/16 녹화로 확정한 필드 규칙(마감일 due_at ?? lock_at, 제출은 submission.workflow_state, 항목 중복은 canvas_item_id), 허용 경로 여섯 개와 GET 전용, DB 변경이 없다는 것, 과제·자료 동기화(F-51·F-52)는 다음 PR이라는 것을 적어.
7. gh pr checks --watch로 CI를 기다려. web·api 작업이 모두 통과하고 api 로그에 "934 passed"가 있으면 squash로 합치고 브랜치를 지워. 다르면 합치지 말고 무엇이 다른지 알려줘.
```

- [ ] api: `uv run ruff check .`·`ruff format --check .` 통과, `uv run pytest` `764 passed, 170 skipped`(Windows는 `763 passed, 171 skipped`)
- [ ] web: `npm run typecheck`·`npm run build` 통과(라우트 12개 그대로)
- [ ] PR CI의 api 작업에 `934 passed`

## 합친 뒤 확인

실제 토큰이 필요하다. **녹화 때 쓴 토큰을 지웠으면 LearningX에서 새로 발급**해(계정 → 설정 → 승인된 통합 → + 새 액세스 토큰, 만료일은 학기 종료일). 토큰은 터미널 기록에 남지 않게 `Read-Host`로 받는다.

```powershell
# api를 띄운 뒤, 로그인한 브라우저의 세션 토큰을 $env:JWT에 담아 두고
$env:LMS = Read-Host "LearningX 토큰"
curl.exe -s -X POST -H "Authorization: Bearer $env:JWT" -H "Content-Type: application/json" `
  -d "{""access_token"":""$env:LMS""}" http://localhost:8000/api/v1/lms/connection
```

1. **연결:** `201`과 `{"status":"active","token_last4":"…","courses":8,"first_sync_run_id":"…"}`. `courses`가 네 수강 과목 수와 같아야 한다(조교·미개설 과목은 빠진다).
2. **실행 기록:** `GET /api/v1/runs/{first_sync_run_id}`가 `succeeded`이고 도구가 `check_lms_token`·`fetch_lms_courses` 둘이다.
3. **과목 목록:** `GET /api/v1/lms/courses`에 과목이 `short_name`(`데이터베이스`)과 `portal_syllabus_url`로 온다. 그 주소를 브라우저에 붙여 넣으면 그 과목 강의계획서 팝업이 떠야 한다(**F-14의 핵심 링크라 한 번은 눌러 봐**). `open_assignments`·`new_materials`는 0이고 `next_due`는 null이다(F-51 전이라 맞다).
4. **DB에 토큰이 평문으로 없는지:** `select token_last4, left(access_token, 8) as 암호문 from lms_connections;` → 암호문이 `gAAAAA`로 시작해야 한다.
5. **상태·해제:** `GET /lms/connection`이 `active`와 끝 4자리. `DELETE /lms/connection`은 `204`이고, 다시 `GET`하면 `404 LMS_NOT_CONNECTED`다. 해제 뒤에도 `GET /lms/courses`에는 과목이 남아 있다(기록은 지우지 않는다).
6. **틀린 토큰:** 아무 문자열로 1번을 하면 `422 LMS_TOKEN_INVALID`이고, `lms_connections`에 행이 생기지 않는다.
7. **로그에 토큰이 없는지:** uvicorn 로그를 `Select-String "~"`로 훑어 토큰 조각이 없는지 본다.

## 구조

```text
api/app/lms/
  client.py      LearningX 호출. GET·허용 경로만, 쪽 이어 받기, 남의 주소·평문 http·리다이렉트 거부
  parse.py       과목명 → 화면 이름·포털 연도·학기·과목번호, 포털 계획서 링크
  service.py     연결 흐름: 토큰 확인 → 과목 목록 → 저장(실행 하나로 기록)
api/app/repositories/lms.py   lms_connections·lms_courses SQL과 과목 목록 숫자
api/app/routers/lms.py        POST·GET·DELETE /lms/connection, GET /lms/courses
api/app/schemas/lms.py        요청·응답 모델(명세 8장)
api/tests/lms_samples.py      녹화한 과목 응답(값은 바꿨다)
```

연결 한 번에 일어나는 일:

```text
POST /lms/connection
  └ LmsService.connect
      ├ agent_run(lms_sync) ─ run.tool(check_lms_token)   → GET /api/v1/users/self      (실패: 422)
      │                     └ run.tool(fetch_lms_courses) → GET /api/v1/courses         (실패: 502)
      ├ student_courses()  학생·열린 과목·성한 번호만
      ├ repo.save_courses  upsert + 이번에 없던 과목 내리기(목록이 비면 건너뛴다)
      └ repo.save_connection  Fernet 암호문 + 끝 4자리 + canvas_user_id
```

## 확인한 것

| 확인 | 결과 |
| --- | --- |
| api 테스트 | DB 없이 `765 passed, 170 skipped`, DB를 붙이면 `935 passed`. 새 테스트 52개(파싱 8 · 클라이언트 15 · API 15 · DB 14) |
| 클라이언트(respx로 가로채기) | 허용 경로 6개만 통과하고 7가지 경로는 막힘(로그인 정보·과목 상세·같이 듣는 학생·남의 제출·계정·OAuth·숫자 아닌 과목) · 토큰은 헤더로만 · `per_page=100`·`include[]` 확인 · 쪽 이어 받기 · **남의 호스트·허용 외 경로·평문 http·`javascript:` 다음 쪽은 따라가지 않음** · 리다이렉트(302) 거부 · 쪽 상한에 걸리면 부분 목록을 주지 않고 예외 · 401/403/429 구분 · 연결 실패 문구와 로그에 토큰 없음 · `rel="next"`가 두 번째 조각이 아니어도 읽음 |
| API | 연결 성공(끝 4자리·과목 수·실행 id, 토큰은 암호문으로만 저장) · 조교·미개설·열린지 모를 과목·bigint 넘는 번호 제외 · 틀린 토큰 422에 아무것도 저장 안 함(실행은 `check_lms_token`까지만 남음) · 과목 목록 500 → 502, 401 → 422 · 다시 연결하면 토큰 교체(공백 제거) · **빈 목록이 와도 앞서 받은 과목이 남음** · 상태 조회·해제·해제 뒤 404 · 과목 목록의 `short_name`·포털 링크(꼴이 다른 과목은 null) · 다른 칸이 섞인 요청 422 · 네 경로 모두 로그인 필요 |
| DB(실제 스키마) | 토큰 저장·교체(한 사용자 한 줄) · 오류 표시가 재연결로 지워짐 · 상태 세 값이 그대로 나감 · 암호문이 `repr`에 안 찍힘 · 해제하면 토큰만 지워지고 과목은 남음 · 과목명 → 포털 칸 파싱(꼴이 다르면 LearningX 학기 이름) · 수강 뺀 과목 내리기와 되살리기 · **빈 목록으로는 안 내림** · 미제출 수(마감 지난 것도 셈)·가장 가까운 할 일(과제 vs 확정된 계획서 일정) · 새 자료는 마지막으로 과목을 본 뒤 생긴 것만 · 주차 항목은 같은 과목을 듣는 사람 모두에게 셈 · **화면 이름순 정렬(DB가 어떤 순서로 주든)** · 남의 연결·과목과 섞이지 않음 |
| 되돌림 시험 38가지 | 허용 경로 검사 · 다음 쪽의 호스트·경로·**스킴(평문 http)** · 첫 쪽만 받기 · 쪽 상한 · 못 받은 목록을 그대로 주기 · `rel=next` 조각 · 리다이렉트 따라가기 · 3xx를 성공으로 보기 · 오류 문구에 토큰 넣기 · 학생 과목 필터 · 열린지 모를 과목 세기 · bigint 넘는 번호 저장 · 토큰 확인을 실행 밖에서 하기 · 422/502 가르기 둘 · 저장 순서 · 암호화 · 끝 4자리 · 과목명 파싱 · 계획서 링크 가드 · 과목 내리기 · 빈 목록으로 내리기 · `is_active` 필터 · `user_id` 조건 · **정렬을 빼기 · 화면 이름 대신 과목명으로 정렬 · 정렬을 DB에 맡기기** · 새 자료 기준 시각 · 지난 과제 넣기 · 제출 상태 필터 · 오류 표시 지우기 · 상태 뭉개기 · 암호문 `repr` · 요청 추가 칸 · **LearningX 토큰 모양을 로그 가림에서 빼기** → **모두 잡혔다** |
| 빌드·검사 | api `ruff check`·`ruff format --check` 통과(191 파일). web `npm run typecheck`·`npm run build` 통과. 실제 LearningX에는 접속하지 않았다(모든 테스트는 respx로 가로챈 가짜 응답이다) |

### 검토에서 고친 것

| 지적 | 고친 것 |
| --- | --- |
| **다음 쪽 주소의 `http://`를 허용해서 토큰이 평문으로 나갈 수 있다** | 스킴까지 같아야 따라간다. 평문 http 다음 쪽 테스트를 더했다 |
| **과목 목록이 비거나 잘리면 그 사용자의 모든 과목이 내려간다** | 목록이 비면 내리지 않고, 끝까지 못 받은 목록은 아예 예외로 끝낸다(쪽 상한을 20→10쪽으로 줄이고 60초 예산을 더했다). API·DB 테스트 둘 다 더했다 |
| `workflow_state`가 없는 과목을 세는 건 같은 PR의 명세와 다르다 | `available`·`completed`만 센다. 그 샘플과 테스트를 더했다 |
| 토큰 확인 호출이 `agent_run` 밖이라 api/CLAUDE.md 규칙 위반 | 같은 실행 안의 도구 `check_lms_token`으로 옮겼다. 실패한 확인도 실행으로 남는다(명세·PRD 도구 표에도 더했다) |
| LearningX가 준 과목 번호를 그대로 넣어 500이 난다(bigint 초과·bool) | 번호 검사를 더했다. 이상한 번호는 과목에서 빠진다 |
| 리다이렉트를 따라가거나 3xx를 성공으로 보면 토큰이 샌다 | `follow_redirects=False`를 못 박고 3xx도 오류로 본다. 302 테스트를 더했다 |
| `rel="next"`가 두 번째 조각이 아니면 조용히 목록이 잘린다 | 모든 조각에서 찾는다 |
| web 타입이 이 PR이 바꾼 계약과 어긋난다 | `portal_syllabus_url`·`token_last4`를 nullable로, `next_due.kind`를 `syllabus_item`으로 고쳤다. 링크가 없으면 "포털에서 강의계획서 열기" 버튼을 그리지 않는다 |
| 연결 상태를 `active`·`error`로 뭉개면 `GET /me`와 답이 달라진다 | DB 값을 그대로 내려준다(세 값). 그 테스트를 더했다 |
| 기존 로그 가림이 LearningX 토큰을 못 잡는다(`18742~xxxxxxxx` 통과) | 패턴을 넓혔다(`\b\d{1,8}~[A-Za-z0-9_~-]{8,}`). 명세 예시 토큰과 `_`·`-` 섞인 모양을 테스트에 넣었다 |
| 암호문이 `Connection`의 기본 `repr`에 찍힌다 | `field(repr=False)`로 뺐다 |
| "로그에 토큰이 없다" 단정이 무의미했다(가림이 그 모양을 잡아 줘서 통과) | 가림이 잡지 못하는 모양으로 재고, 레코드의 `args`까지 본다 |
| 포털 링크 테스트가 코드와 같은 서식을 써서 항상 통과한다 | 전체 주소를 리터럴로 고정했다 |
| 가짜 저장소에 `user_id` 단정이 빠진 메서드가 둘 | 넣었다 |
| 주석의 녹화 숫자가 문서와 어긋난다(8과목 vs 6과목) | 과목 목록은 8과목, 과제·모듈·공지는 6과목이라고 적었다 |

### CI에서 고친 것

| 걸린 것 | 고친 것 |
| --- | --- |
| **과목 목록을 `order by c.name`으로 DB에 맡겨서 CI에서만 순서가 달랐다**(DB의 정렬 규칙은 환경마다 한글과 숫자의 앞뒤가 다르다. 샌드박스에는 `C` 로케일밖에 없어 미리 못 잡았다) | SQL의 `order by`를 빼고 `ordered()`가 **화면 이름(`short_name`) 순**으로 정렬한다. 학생이 보는 이름 순이라 목록 순서도 자연스러워진다. DB 없이 도는 테스트를 더해서 이제 로컬에서도 잡힌다(명세 8장에 순서 규칙을 적었다) |

고치지 않은 지적은 "남은 것"에 적었다(재시도·호출 제한·`mark_error`가 아직 안 불리는 것).

## 남은 것

- **`POST /lms/sync`가 없다**(F-51). 그래서 연결한 뒤 과목 목록을 다시 받으려면 토큰을 다시 붙여넣어야 한다. F-51이 주기 동기화를 넣으면 풀린다.
- **`mark_error`를 부르는 곳이 아직 없다.** 폐기된 토큰을 알아차릴 기회가 주기 동기화뿐이라, `GET /lms/connection`의 `status = error`는 F-51부터 실제로 나온다. `LearningXError.forbidden`(학교가 경로를 닫은 경우)도 F-51에서 쓴다.
- **429·5xx 재시도가 없다.** 지금은 바로 502이고 사용자가 다시 누른다. 30분마다 도는 F-51 배치에는 백오프가 필요하다.
- **`POST /lms/connection`에 호출 제한이 없다.** 로그인한 계정 하나로 임의 문자열을 반복 보내 학교 LMS에 인증 요청을 쏟을 수 있다. 앱 전체에 호출 제한이 없어 이 PR에서 혼자 넣지 않았다.
- **외부 호출 동안 요청용 DB 연결을 쥔다**(캘린더도 같다). 느린 LearningX 하나가 요청 풀(10개)을 오래 잡을 수 있다. 시간 예산 60초로 상한만 걸어 뒀다.
- 과제·주차 항목·공지 **녹화 샘플은 아직 레포에 없다**(F-51·F-52에서 `tests/lms_samples.py`에 더한다). **그때까지 `out2` 폴더를 지우지 마.**
- `GET /lms/courses/{id}`·`GET /lms/assignments`·`GET /lms/updates`는 F-51·F-52다. web 학업 화면은 아직 목이다(`lmsClient.ts`).
- api 응답 모델 이름(`ConnectionView`·`CourseItem`)이 web 타입 이름(`LmsConnection`·`Course`)과 다르다. 바꾸려면 web 화면 여러 곳을 건드려서 이 PR에서는 두었다.

## 문서에 반영하기

녹화로 확정한 사실과 이 PR이 정한 규칙을 기준 문서에 적는다. 새 엔드포인트·필드·컬럼은 없고, **이미 있던 설명을 녹화 결과로 확정하는 수정**이다. ERD 변경은 없다(표·컬럼 그대로).

````text
문서 세 개를 고쳐 줘. 같은 브랜치에서 해. 아래 "찾을 줄"은 파일에 한 번만 나온다.

[1] docs/API_명세_v0.4.md — 9장 LMS 제한의 허용 경로
찾을 줄:
- 허용 경로는 9/28 점검 스크립트에서 쓴 기능만이다: 사용자 확인, 수강 과목 목록, 과목별 과제(제출 상태 포함), 모듈과 항목, 과목 공지, 공지 첨부 다운로드(P1). 실제 경로 문자열은 점검 스크립트 기준으로 코드 상수에 둔다
이 줄 하나를 아래 블록으로 바꿔(줄 끝까지 그대로):

- **10/16 녹화로 확정한 필드 규칙**(6과목·과제 17건·주차 항목 87건):
  - 과제 마감일은 `due_at ?? lock_at`이다. 녹화한 17건 중 5건은 `due_at`이 null이고 `lock_at`만 있었다
  - 제출 여부는 `submission.workflow_state`가 `submitted`·`graded`인지로 본다. **`has_submitted_submissions`는 과목 전체 기준**이라 내가 안 낸 과제에도 true다(쓰지 않는다). 퀴즈는 자동 채점돼 바로 `graded`로 온다
  - 주차 항목은 `canvas_item_id`로만 같은 항목인지 가린다. 제목이 같은 항목이 한 모듈에 둘씩 있다(녹화 87건 중 15쌍)
  - 항목 `type`은 `ExternalTool`(LearningX 출석·영상 LTI)·`Page`·`Quiz`·`Assignment`였고 **`File`은 한 건도 없었다**. 자료 파일은 Canvas에 없고 LearningX 안에서만 열린다(PRD 5-6). 바로가기는 `html_url`을 쓴다
  - `Assignment` 항목의 `content_id`는 과제 id, `Quiz` 항목의 `content_id`는 퀴즈 id(과제의 `quiz_id`)다 → 주차와 과제를 이어 "4주차 과제"로 보여줄 수 있다
  - 모듈 `position`과 항목 `position`은 연속이 아니고 1부터 시작하지도 않는다(지운 항목·재배치). 정렬에만 쓰고 주차 번호는 모듈 이름에서 읽는다. 이름은 `1주차`·`5주차 (개천절 대체휴일)`·`Week 3 : …`가 섞인다
  - 과제가 0건이고 모듈 항목이 모두 비어 있는 과목이 흔하다(녹화 6과목 중 2과목). 빈 과목은 오류가 아니다
- 허용 경로는 10/16 녹화로 확정했다(코드 상수는 `api/app/lms/client.py`의 `ALLOWED_PATHS`). 이 여섯 개뿐이고, 쿼리는 아래 그대로 보낸다(`per_page=100`):

  | 쓰임 | 경로 | 쿼리 |
  | --- | --- | --- |
  | 토큰 확인 | `GET /api/v1/users/self` | — |
  | 수강 과목 | `GET /api/v1/courses` | `enrollment_state=active&include[]=term` |
  | 과제·제출 | `GET /api/v1/courses/{id}/assignments` | `include[]=submission` |
  | 주차 모듈·항목 | `GET /api/v1/courses/{id}/modules` | `include[]=items` |
  | 모듈 항목(보충) | `GET /api/v1/courses/{id}/modules/{module_id}/items` | — |
  | 과목 공지 | `GET /api/v1/courses/{id}/discussion_topics` | `only_announcements=true` |

  쪽이 나뉘면 `Link: rel="next"`를 따라가되 **스킴·호스트가 우리 LearningX와 같고 허용 경로일 때만** 따라간다(`https`를 `http`로 바꿔 주면 토큰이 평문으로 나가고, 남의 주소를 주면 그곳으로 토큰을 보낸다). 리다이렉트는 따라가지 않고 3xx도 오류로 본다. 한 목록은 10쪽(1,000건)·60초까지만 받고, **끝까지 받지 못하면 부분 목록을 쓰지 않고 오류로 끝낸다**(부분 목록을 전체로 쓰면 수강 과목을 지운다). 공지 첨부 다운로드(P1)는 아직 허용 경로가 아니다

[2] docs/API_명세_v0.4.md — `POST /lms/connection` 설명
찾을 두 줄(붙어 있다):
- 성공하면 바로 첫 동기화를 시작하고 `first_sync_run_id`를 돌려준다
- 이미 연결돼 있으면 토큰을 교체한다
이 두 줄을 아래 블록으로 바꿔:

- 성공하면 바로 첫 동기화를 시작하고 `first_sync_run_id`를 돌려준다. **F-50의 첫 동기화는 수강 과목 목록까지**이고(실행 하나 = `trigger_type` `lms_sync`), 과제·주차 항목·공지는 F-51·F-52가 채운다
- `courses`는 저장한 과목 수다. **학생 등록(`enrollments[].type = student`)이 아닌 과목과 아직 열지 않은 과목(`workflow_state`가 `available`·`completed`가 아닌 것)은 세지 않는다**
- 과목 목록을 읽지 못하면(끝까지 받지 못한 경우도) `502 LMS_API_ERROR`이고 토큰도 저장하지 않는다(과목을 못 읽으면 과제·자료도 못 읽어서 연결해 둘 뜻이 없다). 과목 목록에서 401이면 `422 LMS_TOKEN_INVALID`다
- 이번 목록에 없던 과목은 `is_active`를 내려 목록에서 뺀다(기록은 남긴다). **목록이 비어 오면 내리지 않는다** — 학기 사이나 필터 때문에 비어 올 수 있고, 그때 전부 내리면 사용자가 토큰을 다시 붙여넣기 전까지 과목이 하나도 안 보인다
- 토큰 확인과 과목 목록 호출은 같은 실행(`lms_sync`) 안의 도구 두 개(`check_lms_token`·`fetch_lms_courses`)로 기록한다. 실패한 토큰 확인도 실행으로 남는다
- 이미 연결돼 있으면 토큰을 교체한다(오류 표시도 지운다)
- 토큰은 앞뒤 공백을 떼고 받는다(복사할 때 자주 섞인다)

[3] docs/API_명세_v0.4.md — `GET /lms/connection` 아래 문장
찾을 줄의 맨 앞에 아래 문장을 붙여(한 줄로 이어 쓴다):
`status`는 DB에 있는 값을 그대로 준다(`active` · `error` · `disconnected`, `GET /me`의 `lms.status`와 같은 세 가지).
즉 그 줄이 이렇게 된다:

`status`는 DB에 있는 값을 그대로 준다(`active` · `error` · `disconnected`, `GET /me`의 `lms.status`와 같은 세 가지). `status = error`이면 `last_error`에 사용자용 메시지(예: "토큰이 만료되었거나 삭제되었어요"). 연결 안 됨은 `404 LMS_NOT_CONNECTED`.

[4] docs/API_명세_v0.4.md — `GET /lms/courses` 예시의 과목 id
찾을 줄:       "canvas_course_id": 23525,
이렇게 바꿔:   "canvas_course_id": 214023,
(들여쓰기는 그대로 둔다)

[5] docs/API_명세_v0.4.md — `GET /lms/courses` 설명
찾을 줄:
- `portal_syllabus_url`은 사용자 브라우저에서 여는 링크다. **서버는 이 주소에 요청하지 않는다**(포털 robots.txt)
이 줄 **앞에** 아래 두 줄을 넣어(그 줄은 그대로 둔다):

- `canvas_course_id`는 Canvas 과목 id(예: 214023)이고, 과목명 안의 과목번호(23525)와 다르다. 포털 링크에 들어가는 번호는 과목명에서 뽑는다
- `short_name`은 과목명 `_` 뒤다. 과목명이 그 꼴이 아니면 이름 전체가 `short_name`이고 `portal_syllabus_url`은 null이다

[6] docs/ERD_v0.9.md — 7장 비고
찾을 줄:
- **강의계획서**: LMS 계획서는 포털 iframe이고
이 줄 **앞에** 아래 한 줄을 넣어:

- **LMS 응답 규칙(10/16 녹화)**: `lms_assignments.due_at`은 Canvas `due_at ?? lock_at`이다(녹화 17건 중 5건이 `due_at` null). `submission_state`는 Canvas `submission.workflow_state`를 그대로 쓰고(`unsubmitted`·`submitted`·`graded` 관측, `pending_review`는 아직 못 봄), 과목 전체 기준인 `has_submitted_submissions`는 쓰지 않는다. `lms_module_items.canvas_item_id`가 유일 키다 — 한 모듈에 제목이 같은 항목이 둘씩 있다(87건 중 15쌍). `item_type`은 `ExternalTool`·`Page`·`Quiz`·`Assignment`가 관측됐고 `File`은 0건이다. `module_name`은 `1주차`·`Week 3 : …` 꼴이 섞이고 Canvas `position`은 연속이 아니라 저장하지 않는다. `lms_courses.term`은 과목명에서 만든 `2026-2`이고, 과목명 꼴이 다르면 LearningX가 준 학기 이름(`2026년 2학기`)을 넣는다

[7] docs/PRD_v0.9.md — 5-6절 LMS 연동
찾을 줄:
> 🔍 **2026-09-28 실제 점검 결과** —
이 줄 **앞에** 아래 블록을 넣어(9/28 기록은 그대로 둔다):

> 🔍 **2026-10-16 녹화 결과**(6과목·과제 17건·주차 항목 87건, 개인정보 지운 응답을 저장) — 토큰 발급·조회 모두 다시 성공. 확정한 것: 과제 마감일은 `due_at ?? lock_at`(17건 중 5건이 `due_at` null) · 제출 여부는 `submission.workflow_state`(과목 전체 기준인 `has_submitted_submissions`는 쓸 수 없다) · **주차 항목에 `File` 타입이 0건**이고 전부 LearningX 출석·영상 LTI(`ExternalTool`)·`Page`·`Quiz`·`Assignment`라 "새 자료"는 파일이 아니라 **새 항목**이다 · 한 모듈에 제목이 같은 항목이 둘씩 있어(15쌍) 중복은 `canvas_item_id`로만 가린다 · 모듈·항목 `position`은 연속이 아니다(1주차가 position 17인 과목이 있다) · 과제 0건·항목 0건인 과목이 흔하다(6과목 중 2과목). 자세한 필드 규칙은 API 명세 8장에 적었다
>

[8] docs/PRD_v0.9.md — F-52 줄
찾을 줄의 앞부분:
| F-52 | 주차학습 새 자료 감지 | 동기화 때(F-51과 같은 주기) 모듈 항목 ID를 이전 결과와 비교해
그 줄 전체를 아래 한 줄로 바꿔:

| F-52 | 주차학습 새 자료 감지 | 동기화 때(F-51과 같은 주기) 모듈 항목 ID(`canvas_item_id`)를 이전 결과와 비교해 새 항목을 감지(제목은 같은 것이 섞여 있어 쓰지 않는다). 항목은 파일이 아니라 LearningX 출석·영상·퀴즈·과제 링크다(10/16 녹화) → "기계학습 8주차 '08 - …' 등록" 알림 + LMS 바로가기. 사용자가 LMS에서 직접 열어 학습 완료를 인정받고, 받은 파일을 올리면 과목 자동 지정 | P0 | 새 항목이 다음 동기화 때 1회만 알림 |

[9] docs/PRD_v0.9.md — 에이전트 도구 표
찾을 줄:
| fetch_lms_assignments | **외부 API** · LearningX(Canvas) | 과목별 과제·마감일·제출 여부. GET 요청과 허용 경로만 |
이 줄 **앞에** 아래 두 줄을 넣어:

| check_lms_token | **외부 API** · LearningX(Canvas) | 토큰 확인(`GET /api/v1/users/self`). 연결(F-50) 때 저장 전에 부른다 |
| fetch_lms_courses | **외부 API** · LearningX(Canvas) | 수강 과목 목록과 학기. 토큰 연결(F-50)의 첫 동기화에서 부른다 |

[10] docs/API_명세_v0.4.md — `GET /lms/courses` 목록 순서
찾을 줄:
- `new_materials`는 `last_viewed_at` 이후 생긴 주차 항목 수다. `next_due`는 미제출 과제와 확정된 강의계획서 일정 중 가장 가까운 것이고, 없으면 null이다
이 줄 **뒤에** 아래 한 줄을 넣어:

- 항목은 `short_name` 순(글자 코드 순)으로 내려준다. 순서는 서버가 정하고 DB의 정렬 규칙(collation)에 맡기지 않는다 — 환경마다 한글과 숫자의 앞뒤가 달라진다

문서 머리의 보강 이력 줄이 있으면 "v0.9 보강 (2026-10-16): LMS 응답 규칙 확정(10/16 녹화), 허용 경로 여섯 개"를 같은 꼴로 한 줄 더해 줘.
````

## 코드

아래 파일 21개를 그대로 만들거나 바꾼다. 샌드박스에서 `ruff`·`pytest`(DB 포함)·web `typecheck`·`build`를 통과하고 되돌림 시험 38가지를 잡은 코드다. 실제 LearningX에는 접속하지 않았다.

### api (새 파일)

#### `api/app/lms/__init__.py`

```python
"""LearningX(Canvas) 연동 (F-50·F-51·F-52). 클라이언트는 GET과 허용 경로만 쓴다."""

from app.lms.client import ALLOWED_PATHS, LearningXClient, LearningXError
from app.lms.parse import PORTAL_SYLLABUS_URL, CourseName, course_name

__all__ = [
    "ALLOWED_PATHS",
    "PORTAL_SYLLABUS_URL",
    "CourseName",
    "LearningXClient",
    "LearningXError",
    "course_name",
]
```

#### `api/app/lms/parse.py`

```python
"""과목명 파싱과 포털 계획서 링크 (F-14·F-50).

LearningX 과목명은 `202620HY23525_데이터베이스` 꼴이다(2026-10-16 녹화, 8과목 모두 같았다).
앞에서 연도(2026)·학기 코드(20)·과목번호(23525)를 떼어 포털 계획서 링크를 만들고, `_` 뒤를 화면 이름으로 쓴다.
꼴이 다르면 이름 전체를 화면 이름으로 쓰고 링크를 만들지 않는다 — 없는 번호로 포털을 열면 빈 창이 뜬다.

포털에는 서버가 요청하지 않는다(robots.txt). 링크는 사용자 브라우저에서만 연다(API 명세 8장).
"""

import re
from dataclasses import dataclass

# 명세 8장의 링크 그대로. 사용자 브라우저에서 열면 그 과목 계획서 팝업이 뜬다
PORTAL_SYLLABUS_URL = (
    "https://portal.hanyang.ac.kr/openPop.do?header=hidden"
    "&url=/haksa/SughAct/findSuupPlanDocHyIn.do&flag=BB"
    "&year={year}&term={term}&suup={course_no}&language=ko"
)
# 학기 코드 → 표시. 1·2학기만 녹화로 확인했고 계절학기는 한양대 코드 규칙을 따랐다
TERM_NAMES: dict[int, str] = {10: "1", 11: "여름", 20: "2", 21: "겨울"}
_COURSE_NAME = re.compile(r"^(?P<year>\d{4})(?P<term>\d{2})HY(?P<no>\d{3,6})_(?P<short>.+)$")


@dataclass(frozen=True)
class CourseName:
    """과목명에서 뽑은 값. 꼴이 다르면 short_name만 있고 나머지는 None이다."""

    short_name: str
    portal_year: int | None = None
    portal_term: int | None = None
    portal_course_no: str | None = None

    @property
    def syllabus_url(self) -> str | None:
        """포털 계획서 링크. 번호를 못 뽑았으면 없다."""
        if self.portal_year is None or self.portal_term is None or not self.portal_course_no:
            return None
        return PORTAL_SYLLABUS_URL.format(
            year=self.portal_year, term=self.portal_term, course_no=self.portal_course_no
        )

    def term(self, fallback: str | None = None) -> str | None:
        """학기 표시(`2026-2`). 꼴이 다르면 LearningX가 준 학기 이름을 쓴다."""
        if self.portal_year is None or self.portal_term is None:
            return fallback
        name = TERM_NAMES.get(self.portal_term)
        return f"{self.portal_year}-{name}" if name else fallback


def course_name(name: str) -> CourseName:
    found = _COURSE_NAME.match(name.strip())
    if not found:
        return CourseName(short_name=name.strip())
    return CourseName(
        short_name=found["short"].strip(),
        portal_year=int(found["year"]),
        portal_term=int(found["term"]),
        portal_course_no=found["no"],
    )
```

#### `api/app/lms/client.py`

```python
"""LearningX(Canvas) API 클라이언트 (F-50, API 명세 9장).

지키는 것(명세 9장·PRD 7장):
- **GET만 보낸다.** 다른 방법은 요청을 만들기 전에 예외다
- **허용 경로만 부른다.** 2026-09-28 점검과 10-16 녹화에서 쓴 경로뿐이고, 그 밖은 예외다
- 쪽이 나뉘면 `Link: rel="next"`를 따라가되 **우리 주소와 허용 경로인 쪽만** 따라간다
  (서버가 준 주소를 그대로 믿으면 엉뚱한 곳에 토큰을 보낼 수 있다)
- 토큰은 예외 문구·로그에 넣지 않는다. 호출하는 쪽도 토큰을 입력으로 기록하지 않는다

- 다음 쪽 주소는 **우리와 같은 스킴·호스트·허용 경로**일 때만 따라간다. `https`를 `http`로 바꿔 주면
  평문으로 토큰을 보내게 되므로 스킴도 고정한다
- 리다이렉트는 따라가지 않는다(`follow_redirects=False`). 3xx도 오류로 본다
- 목록을 끝까지 읽지 못하면(쪽 상한·시간 예산) 받은 것을 돌려주지 않고 예외다. 부분 목록을 "전체"로
  잘못 쓰면 수강 과목을 지우는 일이 생긴다(F-50 연결의 과목 내리기)

녹화에서 확인한 것(2026-10-16): 수강 과목 응답은 8과목이 한 쪽에 들어왔고(per_page=100), 과제·모듈·공지는
6과목에서 받았다. `include[]=items`로 모듈 항목이 함께 왔다(항목이 없는 주차는 `items: []`).
함께 오지 않는 과목이 있을 수 있어 항목만 따로 받는 경로도 둔다.
"""

import logging
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 20.0  # httpx는 연결·읽기·쓰기에 각각 걸린다
BUDGET_SECONDS = 60.0  # 한 목록을 끝까지 받는 데 쓸 수 있는 전체 시간
PER_PAGE = 100
MAX_PAGES = 10  # 한 쪽에 100건이라 1,000건까지. 넘으면 끝까지 못 읽은 것으로 본다

# 허용 경로. 쿼리는 뺀 경로만 본다(명세 9장 "허용 경로 밖이면 요청을 보내기 전에 예외")
ALLOWED_PATHS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/api/v1/users/self$"),
    re.compile(r"^/api/v1/courses$"),
    re.compile(r"^/api/v1/courses/\d+/assignments$"),
    re.compile(r"^/api/v1/courses/\d+/modules$"),
    re.compile(r"^/api/v1/courses/\d+/modules/\d+/items$"),
    re.compile(r"^/api/v1/courses/\d+/discussion_topics$"),
)


class LearningXError(Exception):
    """LearningX가 거절했거나 닿지 못했다. status가 401이면 토큰을 다시 받아야 한다."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def unauthorized(self) -> bool:
        return self.status == 401

    @property
    def forbidden(self) -> bool:
        """학교가 그 경로를 닫았다. 토큰 문제와 구분해 기능 범위를 줄인다."""
        return self.status == 403


def allowed(path: str) -> bool:
    return any(pattern.match(path) for pattern in ALLOWED_PATHS)


def next_link(header: str) -> str | None:
    """`Link` 헤더의 rel="next" 주소. 없으면 None이다."""
    for part in header.split(","):
        pieces = part.split(";")
        # rel은 두 번째가 아닐 수 있다(`<url>; type="application/json"; rel="next"`)
        if any('rel="next"' in piece.replace(" ", "") for piece in pieces[1:]):
            return pieces[0].strip().strip("<>")
    return None


class LearningXClient:
    def __init__(self, *, api_base: str, timeout: float = TIMEOUT_SECONDS) -> None:
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        base = urlsplit(self.api_base)
        self._scheme = base.scheme or "https"
        self._host = base.netloc.lower()

    async def me(self, token: str) -> dict[str, Any]:
        """토큰 확인 (명세 9장: 저장 전에 이 경로로 확인한다)."""
        body = await self._get(token, "/api/v1/users/self")
        if not isinstance(body, dict):
            raise LearningXError("LearningX 응답을 읽지 못했어요.")
        return body

    async def courses(self, token: str) -> list[dict[str, Any]]:
        """수강 중인 과목. 학기 정보를 함께 받는다."""
        return await self._list(
            token, "/api/v1/courses", {"enrollment_state": "active", "include[]": "term"}
        )

    async def assignments(self, token: str, course_id: int) -> list[dict[str, Any]]:
        """과목 과제와 내 제출 상태(F-51)."""
        return await self._list(
            token, f"/api/v1/courses/{course_id}/assignments", {"include[]": "submission"}
        )

    async def modules(self, token: str, course_id: int) -> list[dict[str, Any]]:
        """주차 모듈과 그 안의 항목(F-52)."""
        return await self._list(
            token, f"/api/v1/courses/{course_id}/modules", {"include[]": "items"}
        )

    async def module_items(
        self, token: str, course_id: int, module_id: int
    ) -> list[dict[str, Any]]:
        """항목이 모듈과 함께 오지 않은 과목에서만 쓴다."""
        return await self._list(token, f"/api/v1/courses/{course_id}/modules/{module_id}/items")

    async def announcements(self, token: str, course_id: int) -> list[dict[str, Any]]:
        """과목 공지(F-53)."""
        return await self._list(
            token,
            f"/api/v1/courses/{course_id}/discussion_topics",
            {"only_announcements": "true"},
        )

    # ── 안쪽 ────────────────────────────────────────────────────────────────

    async def _list(
        self, token: str, path: str, params: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """목록 경로. 쪽이 나뉘면 끝까지 모은다."""
        url = self._url(path, {**(params or {}), "per_page": str(PER_PAGE)})
        items: list[dict[str, Any]] = []
        until = time.monotonic() + BUDGET_SECONDS
        for _ in range(MAX_PAGES):
            body, link = await self._fetch(token, url)
            if not isinstance(body, list):
                raise LearningXError("LearningX 응답을 읽지 못했어요.")
            items.extend(row for row in body if isinstance(row, dict))
            following = next_link(link)
            if not following or not self._ours(following):
                return items
            if time.monotonic() > until:
                raise LearningXError(f"LearningX 목록을 끝까지 받지 못했어요: {path}")
            url = following
        raise LearningXError(f"LearningX 목록이 너무 길어 끝까지 받지 못했어요: {path}")

    async def _get(self, token: str, path: str) -> Any:
        body, _ = await self._fetch(token, self._url(path, {}))
        return body

    def _url(self, path: str, params: dict[str, str]) -> str:
        if not allowed(path):
            raise LearningXError(f"허용하지 않은 LearningX 경로예요: {path}")
        query = "&".join(f"{key}={value}" for key, value in params.items())
        return f"{self.api_base}{path}{'?' + query if query else ''}"

    def _ours(self, url: str) -> bool:
        """다음 쪽 주소가 우리 LearningX의 허용 경로인지. 아니면 따라가지 않는다."""
        parts = urlsplit(url)
        # 스킴까지 같아야 한다. https를 http로 바꿔 주면 토큰이 평문으로 나간다
        return (
            parts.scheme == self._scheme
            and parts.netloc.lower() == self._host
            and allowed(parts.path)
        )

    async def _fetch(self, token: str, url: str) -> tuple[Any, str]:
        """GET 한 번. 토큰은 헤더로만 보내고 예외 문구에는 넣지 않는다."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
                )
        except httpx.HTTPError as exc:
            raise LearningXError("LearningX에 연결하지 못했어요.") from exc
        # 3xx도 오류다. 리다이렉트를 따라가면 그 주소로 토큰을 보내게 된다
        if not 200 <= response.status_code < 300:
            raise LearningXError(
                f"LearningX가 요청을 거절했어요({response.status_code}).", response.status_code
            )
        try:
            return response.json(), response.headers.get("Link", "")
        except ValueError as exc:
            raise LearningXError("LearningX 응답을 읽지 못했어요.") from exc
```

#### `api/app/lms/service.py`

```python
"""LearningX 연결 (F-50). 토큰을 확인하고 암호화해 저장한 뒤 수강 과목을 받아 둔다.

순서(명세 8장): `GET /api/v1/users/self`로 확인 → 과목 목록 → 저장. 두 호출 모두 실행 하나(`lms_sync`)
안에서 도구로 기록한다(api/CLAUDE.md: 외부 호출은 agent_run 안에서만). 확인에 실패하면 아무것도 저장하지
않고 422 `LMS_TOKEN_INVALID`다(실행은 실패로 남는다). 과목 목록을 읽지 못하면 502 `LMS_API_ERROR`이고 역시 저장하지 않는다
(과목을 못 읽으면 과제·자료도 못 읽어서 연결해 둘 뜻이 없다).

토큰은 암호화해서만 저장하고, 응답·로그·`tool_calls.input`에 넣지 않는다. 화면에는 끝 4자리만 간다.
과제·주차 항목·공지 동기화는 F-51·F-52다. 여기서는 과목 목록까지만 받는다.
"""

import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends

from app.agent_log import LogConnect, agent_run
from app.config import Settings, get_settings
from app.crypto import encrypt
from app.db import get_log_connect
from app.errors import ApiError
from app.lms.client import LearningXClient, LearningXError
from app.repositories.lms import LmsRepoDep, LmsRepository
from app.schemas.lms import ConnectResult

logger = logging.getLogger(__name__)

TOKEN_INVALID = "토큰을 확인할 수 없어요. 복사할 때 앞뒤 공백이 들어갔는지 확인해 주세요."
TOKEN_EXPIRED = "토큰이 만료되었거나 삭제되었어요."
API_ERROR = "LearningX가 응답하지 않아요. 잠시 후 다시 시도해 주세요."
# 학생 등록인 과목만 본다(청강·조교 과목은 과제가 내 것이 아니다)
STUDENT = "student"
OPEN_STATES = ("available", "completed")  # 그 밖(unpublished 등)은 아직 열지 않은 과목이다
BIGINT_MAX = 2**63 - 1  # Canvas 번호는 bigint 칸에 들어가야 한다


def _canvas_id(value: Any) -> bool:
    """과목 번호로 쓸 수 있는 값인지. bool과 bigint를 넘는 수는 거른다(그대로 넣으면 DB가 터진다)."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= BIGINT_MAX


def student_courses(courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """내가 학생으로 듣는, 열려 있는 과목만. 2026-10-16 녹화의 8과목은 모두 student·available이었다."""
    mine = []
    for course in courses:
        enrollments = course.get("enrollments") or []
        is_student = any(
            isinstance(one, dict) and one.get("type") == STUDENT for one in enrollments
        )
        if (
            is_student
            and course.get("workflow_state") in OPEN_STATES
            and _canvas_id(course.get("id"))
        ):
            mine.append(course)
    return mine


class LmsService:
    def __init__(
        self,
        repo: LmsRepository,
        client: LearningXClient,
        *,
        encryption_key: str,
        log_connect: LogConnect,
    ) -> None:
        self.repo = repo
        self.client = client
        self.key = encryption_key
        self.log_connect = log_connect

    async def connect(self, user_id: str, token: str, now: datetime) -> ConnectResult:
        async with agent_run(self.log_connect, trigger="lms_sync", user_id=user_id) as run:
            async with run.tool("check_lms_token") as call:
                me = await self._check(token)
                call.output = {"ok": True}  # 사용자 번호·토큰은 기록하지 않는다
            async with run.tool("fetch_lms_courses") as call:
                courses = student_courses(await self._courses(token))
                call.output = {"courses": len(courses)}
            saved = await self.repo.save_courses(user_id, courses, now=now)
            await self.repo.save_connection(
                user_id,
                token=encrypt(token, self.key),
                last4=token[-4:],
                canvas_user_id=me.get("id") if isinstance(me.get("id"), int) else None,
                now=now,
            )
            run_id = run.id
        return ConnectResult(
            status="active", token_last4=token[-4:], courses=saved, first_sync_run_id=run_id
        )

    async def _check(self, token: str) -> dict[str, Any]:
        try:
            return await self.client.me(token)
        except LearningXError as exc:
            logger.info("LearningX 토큰 확인 실패: status %s", exc.status)
            raise ApiError(422, "LMS_TOKEN_INVALID", TOKEN_INVALID) from exc

    async def _courses(self, token: str) -> list[dict[str, Any]]:
        try:
            return await self.client.courses(token)
        except LearningXError as exc:
            if exc.unauthorized:
                raise ApiError(422, "LMS_TOKEN_INVALID", TOKEN_EXPIRED) from exc
            logger.warning("LearningX 과목 목록 실패: status %s", exc.status)
            raise ApiError(502, "LMS_API_ERROR", API_ERROR) from exc


def get_lms_service(
    repo: LmsRepoDep,
    settings: Annotated[Settings, Depends(get_settings)],
    log_connect: Annotated[LogConnect, Depends(get_log_connect)],
) -> LmsService:
    return LmsService(
        repo,
        LearningXClient(api_base=settings.lms_api_base),
        encryption_key=settings.token_encryption_key,
        log_connect=log_connect,
    )


LmsServiceDep = Annotated[LmsService, Depends(get_lms_service)]
```

#### `api/app/schemas/lms.py`

```python
"""LearningX 연결과 과목 목록 (F-50·F-14, API 명세 8장).

토큰은 요청으로만 받고 응답에는 끝 4자리만 넣는다(`token_last4`). 과목 이름은 LearningX가 준
`202620HY23525_데이터베이스`를 그대로 두고, 화면에 쓸 짧은 이름(`short_name`)과 포털 계획서 링크를
함께 내려준다. 계획서 링크는 사용자 브라우저에서만 연다(서버는 포털에 요청하지 않는다).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# DB enum(lms_connection_status)·GET /me의 lms.status·web 타입과 같은 세 가지
ConnectionStatus = Literal["active", "error", "disconnected"]


class ConnectRequest(BaseModel):
    """LearningX 개인 액세스 토큰. 앞뒤 공백은 떼고 받는다(복사할 때 자주 섞인다)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    access_token: str = Field(min_length=8, max_length=500)


class ConnectResult(BaseModel):
    status: Literal["active"]  # 연결에 성공한 응답이라 늘 active다
    token_last4: str
    courses: int
    first_sync_run_id: str | None


class ConnectionView(BaseModel):
    status: ConnectionStatus
    token_last4: str | None
    last_synced_at: datetime | None  # KST 오프셋
    last_error: str | None


class NextDue(BaseModel):
    kind: Literal["assignment", "syllabus_item"]
    title: str
    due_at: datetime


class CourseItem(BaseModel):
    id: str
    canvas_course_id: int
    name: str  # LearningX 과목명 그대로
    short_name: str  # `_` 뒤만. 꼴이 다르면 이름 전체
    has_syllabus: bool
    portal_syllabus_url: str | None
    open_assignments: int
    new_materials: int
    next_due: NextDue | None


class CourseList(BaseModel):
    items: list[CourseItem]
```

#### `api/app/repositories/lms.py`

```python
"""LearningX 연결과 과목 (F-50·F-14, ERD 3-2).

- 토큰은 암호화한 값만 저장하고(`lms_connections.access_token`), 화면에는 끝 4자리만 보낸다
- 과목은 `(user_id, canvas_course_id)`로 upsert하고, 이번 동기화에 없던 과목은 `is_active`를 내린다
  (수강을 뺀 과목이다 — 과제·공지 기록은 남겨 두고 목록에서만 뺀다). **목록이 비어 오면 내리지 않는다**
- 과목 목록의 숫자는 지금 저장된 것으로 센다. 과제·주차 항목 동기화는 F-51·F-52라 그때까지 0이다
- 목록 순서는 `ordered()`가 정한다(화면 이름 순). DB의 정렬 규칙은 환경마다 달라서 쓰지 않는다
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection

from app.db import get_conn
from app.eligibility import KST
from app.lms.parse import course_name
from app.schemas.lms import ConnectionView, CourseItem, NextDue


@dataclass(frozen=True)
class Connection:
    status: str
    token_last4: str | None
    access_token: str = field(repr=False)  # 암호화된 값. 실수로 찍지 않게 repr에서 뺀다
    canvas_user_id: int | None
    last_synced_at: datetime | None
    last_error: str | None

    def view(self) -> ConnectionView:
        """DB에 있는 상태를 그대로 내려준다(active·error·disconnected)."""
        return ConnectionView(
            status=self.status,  # type: ignore[arg-type]  # DB enum이 세 값으로 묶어 준다
            token_last4=self.token_last4,
            last_synced_at=self.last_synced_at.astimezone(KST) if self.last_synced_at else None,
            last_error=self.last_error,
        )


_COURSES = (
    "select c.id, c.canvas_course_id, c.name, c.last_viewed_at,"
    " exists (select 1 from syllabi s where s.lms_course_id = c.id and s.user_id = c.user_id)"
    "   as has_syllabus,"
    " (select count(*) from lms_assignments a where a.user_id = c.user_id"
    "   and a.lms_course_id = c.id and a.submission_state = 'unsubmitted'"
    "   and a.removed_at is null) as open_assignments,"
    # 주차 항목은 과목 공통 표라 과목 번호로 잇는다. 마지막으로 과목을 본 뒤 생긴 것만 센다
    " (select count(*) from lms_module_items i where i.canvas_course_id = c.canvas_course_id"
    "   and i.first_seen_at > coalesce(c.last_viewed_at, c.synced_at)) as new_materials,"
    # 가장 가까운 것 하나: 미제출 과제와 확정된 계획서 일정 중에서(명세 8장)
    " (select json_build_object('kind', due.kind, 'title', due.title, 'due_at', due.at) from ("
    "    select 'assignment' as kind, a.title, a.due_at as at from lms_assignments a"
    "      where a.user_id = c.user_id and a.lms_course_id = c.id"
    "      and a.submission_state = 'unsubmitted' and a.removed_at is null and a.due_at >= %(now)s"
    "    union all"
    "    select 'syllabus_item', i.title, i.starts_at from syllabus_items i"
    "      join syllabi s on s.id = i.syllabus_id"
    "      where s.lms_course_id = c.id and s.user_id = c.user_id and i.is_confirmed"
    "      and i.starts_at >= %(now)s"
    "  ) as due order by due.at limit 1) as next_due"
    " from lms_courses c where c.user_id = %(uid)s and coalesce(c.is_active, true)"
    # 정렬은 ordered()가 한다. DB의 정렬 규칙(collation)은 환경마다 달라서 순서를 맡기지 않는다
)

_SAVE = (
    "insert into lms_connections (user_id, access_token, token_last4, canvas_user_id, status,"
    " last_synced_at, last_error) values (%(uid)s, %(token)s, %(last4)s, %(canvas)s, 'active',"
    " %(now)s, null)"
    " on conflict (user_id) do update set access_token = excluded.access_token,"
    " token_last4 = excluded.token_last4, canvas_user_id = excluded.canvas_user_id,"
    " status = 'active', last_synced_at = excluded.last_synced_at, last_error = null"
)

_UPSERT_COURSE = (
    "insert into lms_courses (user_id, canvas_course_id, name, term, portal_year, portal_term,"
    " portal_course_no, is_active, synced_at)"
    " values (%(uid)s, %(canvas)s, %(name)s, %(term)s, %(year)s, %(pterm)s, %(no)s, true, %(now)s)"
    " on conflict (user_id, canvas_course_id) do update set name = excluded.name,"
    " term = excluded.term, portal_year = excluded.portal_year,"
    " portal_term = excluded.portal_term, portal_course_no = excluded.portal_course_no,"
    " is_active = true, synced_at = excluded.synced_at"
)


class LmsRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def connection(self, user_id: str) -> Connection | None:
        row = await self._row(
            "select status, token_last4, access_token, canvas_user_id, last_synced_at, last_error"
            " from lms_connections where user_id = %s",
            (user_id,),
        )
        return Connection(**row) if row else None

    async def save_connection(
        self, user_id: str, *, token: str, last4: str, canvas_user_id: int | None, now: datetime
    ) -> None:
        """연결을 만들거나 토큰을 갈아 끼운다(명세 8장: 이미 연결돼 있으면 교체)."""
        await self.conn.execute(
            _SAVE,
            {
                "uid": user_id,
                "token": token,
                "last4": last4,
                "canvas": canvas_user_id,
                "now": now,
            },
        )

    async def mark_error(self, user_id: str, message: str) -> None:
        """다음 동기화에서 토큰이 막혔을 때. 화면은 이 문구로 다시 연결을 안내한다."""
        await self.conn.execute(
            "update lms_connections set status = 'error', last_error = %s where user_id = %s",
            (message, user_id),
        )

    async def delete_connection(self, user_id: str) -> bool:
        """토큰을 즉시 지운다. 과목·과제 기록은 남기고 동기화만 멈춘다(명세 8장)."""
        cursor = await self.conn.execute(
            "delete from lms_connections where user_id = %s", (user_id,)
        )
        return cursor.rowcount > 0

    async def save_courses(
        self, user_id: str, courses: list[dict[str, Any]], *, now: datetime
    ) -> int:
        """수강 과목을 저장하고, 이번에 없던 과목은 목록에서 뺀다. 저장한 과목 수를 돌려준다."""
        ids: list[int] = []
        for course in courses:
            canvas_id = course.get("id")
            name = (course.get("name") or "").strip()
            if not isinstance(canvas_id, int) or not name:
                continue
            parsed = course_name(name)
            term = (
                (course.get("term") or {}).get("name")
                if isinstance(course.get("term"), dict)
                else None
            )
            await self.conn.execute(
                _UPSERT_COURSE,
                {
                    "uid": user_id,
                    "canvas": canvas_id,
                    "name": name,
                    "term": parsed.term(term),
                    "year": parsed.portal_year,
                    "pterm": parsed.portal_term,
                    "no": parsed.portal_course_no,
                    "now": now,
                },
            )
            ids.append(canvas_id)
        # 빈 목록으로는 내리지 않는다. 학기 사이·필터·끊긴 목록 때문에 비어 올 수 있고,
        # 그때 전부 내리면 사용자가 토큰을 다시 붙여넣기 전까지 과목이 하나도 안 보인다
        if ids:
            await self.conn.execute(
                "update lms_courses set is_active = false"
                " where user_id = %s and not (canvas_course_id = any(%s::bigint[]))",
                (user_id, ids),
            )
        return len(ids)

    async def courses(self, user_id: str, *, now: datetime) -> list[CourseItem]:
        rows = await self._rows(_COURSES, {"uid": user_id, "now": now})
        return ordered([_course(row) for row in rows])

    # ── 조회 ────────────────────────────────────────────────────────────────

    async def _rows(self, query: str, params: Any) -> list[dict[str, Any]]:
        return await (await self.conn.execute(query, params)).fetchall()

    async def _row(self, query: str, params: Any) -> dict[str, Any] | None:
        return await (await self.conn.execute(query, params)).fetchone()


def ordered(items: list[CourseItem]) -> list[CourseItem]:
    """화면 이름 순. 같은 이름이면 과목명으로 가른다.

    DB에 `order by`를 맡기지 않는다 — 정렬 규칙(collation)이 환경마다 달라서 한글과 숫자의 앞뒤가
    바뀐다(2026-10-16 CI에서 걸렸다). 파이썬 글자 코드 순으로 정하면 어디서나 같다.
    """
    return sorted(items, key=lambda one: (one.short_name, one.name))


def _course(row: dict[str, Any]) -> CourseItem:
    parsed = course_name(row["name"])
    due = row["next_due"]
    return CourseItem(
        id=str(row["id"]),
        canvas_course_id=row["canvas_course_id"],
        name=row["name"],
        short_name=parsed.short_name,
        has_syllabus=row["has_syllabus"],
        portal_syllabus_url=parsed.syllabus_url,
        open_assignments=int(row["open_assignments"]),
        new_materials=int(row["new_materials"]),
        next_due=NextDue(
            kind=due["kind"],
            title=due["title"],
            due_at=datetime.fromisoformat(due["due_at"]).astimezone(KST),
        )
        if due
        else None,
    )


def get_lms_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> LmsRepository:
    return LmsRepository(conn)


LmsRepoDep = Annotated[LmsRepository, Depends(get_lms_repo)]
```

#### `api/app/routers/lms.py`

```python
"""LearningX 연결과 과목 (F-50·F-14, API 명세 8장). 토큰 연결·상태·해제와 수강 과목 목록."""

from fastapi import APIRouter, Response

from app.auth import CurrentUserDep
from app.clock import NowDep
from app.errors import ApiError
from app.lms.service import LmsServiceDep
from app.repositories.lms import LmsRepoDep
from app.schemas.lms import ConnectionView, ConnectRequest, ConnectResult, CourseList

router = APIRouter(prefix="/lms", tags=["LMS"])

NOT_CONNECTED = "LearningX를 연결해 주세요."


@router.post("/connection", status_code=201, response_model=ConnectResult)
async def connect(
    body: ConnectRequest, user: CurrentUserDep, service: LmsServiceDep, now: NowDep
) -> ConnectResult:
    """토큰을 확인하고 암호화해 저장한 뒤 수강 과목을 받아 둔다. 이미 연결돼 있으면 토큰을 교체한다."""
    return await service.connect(user.id, body.access_token, now)


@router.get("/connection", response_model=ConnectionView)
async def connection(user: CurrentUserDep, repo: LmsRepoDep) -> ConnectionView:
    """연결 상태와 토큰 끝 4자리. 연결이 없으면 404 LMS_NOT_CONNECTED다."""
    found = await repo.connection(user.id)
    if found is None:
        raise ApiError(404, "LMS_NOT_CONNECTED", NOT_CONNECTED)
    return found.view()


@router.delete("/connection", status_code=204)
async def disconnect(user: CurrentUserDep, repo: LmsRepoDep) -> Response:
    """토큰을 즉시 지운다. 과목·과제 기록은 남기고 동기화만 멈춘다."""
    if not await repo.delete_connection(user.id):
        raise ApiError(404, "LMS_NOT_CONNECTED", NOT_CONNECTED)
    return Response(status_code=204)


@router.get("/courses", response_model=CourseList)
async def courses(user: CurrentUserDep, repo: LmsRepoDep, now: NowDep) -> CourseList:
    """수강 과목과 포털 계획서 링크. 과제·새 자료 숫자는 저장된 동기화 결과로 센다."""
    return CourseList(items=await repo.courses(user.id, now=now))
```

### api (새 테스트)

#### `api/tests/lms_samples.py`

```python
"""LearningX 응답 샘플 (2026-10-16 녹화, 개인정보·서명값 제거).

학교 LMS에서 실제로 받은 응답의 **모양**을 그대로 두고 값만 바꿨다(과목 번호·이름·사용자 번호).
녹화에서 확인한 것 중 이 샘플이 담은 것:

- `users/self`에 email·login_id가 없다(학교 설정). 이름·아바타만 온다
- 과목명은 `202620HY23525_데이터베이스` 꼴이고 `course_code`도 같은 문자열이다
- `term.end_at`이 null이다 → 학기 종료일은 과목의 `end_at`에서 본다
- 학생 등록이 아닌 과목(조교·청강)과 `workflow_state`가 `unpublished`인 과목이 섞일 수 있다
- 과목명 꼴이 다른 과목도 있을 수 있다(계절·비정규 과목) → 계획서 링크를 만들지 않는다

과제·주차 항목·공지 샘플은 F-51·F-52에서 더한다(그 기능이 쓸 때 함께 넣는다).
"""

from typing import Any

CANVAS_USER_ID = 77001

USERS_SELF: dict[str, Any] = {
    "id": CANVAS_USER_ID,
    "name": "테스트 학생",
    "created_at": "2023-02-20T14:37:18+09:00",
    "sortable_name": "학생, 테스트",
    "short_name": "테스트 학생",
    "avatar_url": "https://lms.test/images/thumbnails/1/abcdefghijklmnopqrstuvwx",
    "locale": None,
    "effective_locale": "ko",
    "permissions": {
        "can_update_name": False,
        "can_update_avatar": True,
        "limit_parent_app_web_access": False,
    },
}

TERM: dict[str, Any] = {
    "id": 94,
    "name": "2026년 2학기",
    "start_at": "2026-08-24T15:00:00Z",
    "end_at": None,
    "created_at": "2026-08-03T01:19:50Z",
    "workflow_state": "active",
    "grading_period_group_id": None,
}


def course(
    canvas_id: int,
    name: str,
    *,
    role: str = "student",
    workflow_state: str = "available",
) -> dict[str, Any]:
    """녹화한 과목 한 건의 모양. 바꿀 것만 인자로 받는다."""
    return {
        "id": canvas_id,
        "name": name,
        "account_id": 5798,
        "uuid": "cOuRsEuUiD0000000000000000000000000000000",
        "start_at": "2026-08-24T15:00:00Z",
        "created_at": "2026-08-03T02:58:13Z",
        "course_code": name,
        "default_view": "feed",
        "root_account_id": 1,
        "enrollment_term_id": TERM["id"],
        "end_at": "2026-12-31T14:59:59Z",
        "public_syllabus": False,
        "storage_quota_mb": 2000,
        "term": TERM,
        "calendar": {"ics": "https://lms.test/feeds/calendars/course_x.ics"},
        "time_zone": "Asia/Seoul",
        "blueprint": False,
        "enrollments": [
            {
                "type": role,
                "role": "StudentEnrollment" if role == "student" else "TaEnrollment",
                "role_id": 11,
                "user_id": CANVAS_USER_ID,
                "enrollment_state": "active",
                "limit_privileges_to_course_section": False,
            }
        ],
        "hide_final_grades": False,
        "workflow_state": workflow_state,
        "course_format": "on_campus",
        "restrict_enrollments_to_course_dates": True,
    }


DATABASE = course(214023, "202620HY23525_데이터베이스")
MACHINE_LEARNING = course(216515, "202620HY23534_기계학습")
# 과목명 꼴이 다른 과목(계획서 링크를 만들 수 없다)
SEMINAR = course(219001, "대학원 세미나(비정규)")
# 조교로 들어간 과목과 아직 열지 않은 과목은 목록에서 뺀다
ASSISTING = course(219002, "202620HY23999_조교과목", role="ta")
UNPUBLISHED = course(219003, "202620HY23998_준비중", workflow_state="unpublished")

COURSES: list[dict[str, Any]] = [
    DATABASE,
    MACHINE_LEARNING,
    SEMINAR,
    ASSISTING,
    UNPUBLISHED,
]
MINE: list[dict[str, Any]] = [DATABASE, MACHINE_LEARNING, SEMINAR]
```

#### `api/tests/test_lms_parse.py`

```python
"""과목명 파싱과 포털 계획서 링크(F-14·F-50). 녹화한 8과목의 꼴을 그대로 쓴다."""

import pytest

from app.lms.parse import PORTAL_SYLLABUS_URL, course_name


@pytest.mark.parametrize(
    ("name", "short", "year", "term", "no"),
    [
        ("202620HY23525_데이터베이스", "데이터베이스", 2026, 20, "23525"),
        ("202620HY20165_사회봉사", "사회봉사", 2026, 20, "20165"),
        ("202620HY23530_글로벌SW창업디자인2", "글로벌SW창업디자인2", 2026, 20, "23530"),
        ("202620HY25123_AI+X공학융합프로젝트", "AI+X공학융합프로젝트", 2026, 20, "25123"),
        ("202510HY12345_선형대수", "선형대수", 2025, 10, "12345"),
    ],
)
def test_it_splits_the_course_name(name: str, short: str, year: int, term: int, no: str) -> None:
    parsed = course_name(name)
    assert parsed.short_name == short
    assert (parsed.portal_year, parsed.portal_term, parsed.portal_course_no) == (year, term, no)


def test_it_builds_the_portal_syllabus_link() -> None:
    parsed = course_name("202620HY23525_데이터베이스")
    assert parsed.syllabus_url == PORTAL_SYLLABUS_URL.format(year=2026, term=20, course_no="23525")
    assert "year=2026" in (parsed.syllabus_url or "")
    assert "suup=23525" in (parsed.syllabus_url or "")


def test_a_name_in_another_shape_keeps_the_whole_name_and_has_no_link() -> None:
    parsed = course_name("대학원 세미나(비정규)")
    assert parsed.short_name == "대학원 세미나(비정규)"
    assert parsed.syllabus_url is None
    assert parsed.portal_course_no is None


def test_the_term_label_comes_from_the_code_and_falls_back_to_learningx() -> None:
    assert course_name("202620HY23525_데이터베이스").term("2026년 2학기") == "2026-2"
    assert course_name("202510HY12345_선형대수").term(None) == "2025-1"
    assert course_name("202621HY12345_겨울특강").term(None) == "2026-겨울"
    # 꼴이 다르면 LearningX가 준 학기 이름을 그대로 쓴다
    assert course_name("세미나").term("2026년 2학기") == "2026년 2학기"
    assert course_name("세미나").term(None) is None
```

#### `api/tests/test_lms_client.py`

```python
"""LearningX 클라이언트(F-50): GET만·허용 경로만, 쪽 이어 받기, 남의 주소·평문 http는 따라가지 않음,
3xx·401·403 구분, 끝까지 못 받으면 예외, 토큰이 오류·로그에 남지 않음. HTTP는 respx로 가로챈다."""

import logging

import httpx
import pytest
import respx

from app.lms.client import MAX_PAGES, PER_PAGE, LearningXClient, LearningXError, allowed, next_link
from tests.lms_samples import COURSES, USERS_SELF

pytestmark = pytest.mark.anyio

BASE = "https://lms.test"
TOKEN = "18742~pAtB1g3TestTokenValue0000000000"
# 로그 가림(logging_redact)이 잡지 못하는 모양. "로그에 토큰이 없다"를 의미 있게 재는 데 쓴다
PLAIN_TOKEN = "plain-sample-value-not-token-shaped"


def client() -> LearningXClient:
    return LearningXClient(api_base=BASE + "/", timeout=2.0)


def test_only_the_recorded_paths_are_allowed() -> None:
    for path in (
        "/api/v1/users/self",
        "/api/v1/courses",
        "/api/v1/courses/214023/assignments",
        "/api/v1/courses/214023/modules",
        "/api/v1/courses/214023/modules/2749846/items",
        "/api/v1/courses/214023/discussion_topics",
    ):
        assert allowed(path), path
    for path in (
        "/api/v1/users/self/logins",  # 로그인 정보
        "/api/v1/courses/214023",  # 과목 상세(쓰지 않는다)
        "/api/v1/courses/214023/users",  # 같이 듣는 학생
        "/api/v1/courses/214023/students/submissions",  # 남의 제출
        "/api/v1/accounts",
        "/login/oauth2/token",
        "/api/v1/courses/abc/assignments",  # 번호가 아닌 과목
    ):
        assert not allowed(path), path


@respx.mock
async def test_it_sends_the_token_in_the_header_and_asks_for_a_hundred_at_a_time() -> None:
    route = respx.get(f"{BASE}/api/v1/courses").mock(httpx.Response(200, json=COURSES))
    got = await client().courses(TOKEN)
    assert len(got) == len(COURSES)
    request = route.calls[0].request
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.url.params["per_page"] == str(PER_PAGE)
    assert request.url.params["enrollment_state"] == "active"
    assert request.url.params["include[]"] == "term"


@respx.mock
async def test_it_follows_the_next_page_until_the_header_stops() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=COURSES[2:])
        return httpx.Response(
            200,
            json=COURSES[:2],
            headers={"Link": f'<{BASE}/api/v1/courses?page=2&per_page=100>; rel="next"'},
        )

    route = respx.get(url__startswith=f"{BASE}/api/v1/courses").mock(side_effect=handle)
    got = await client().courses(TOKEN)
    assert len(got) == len(COURSES)
    assert route.call_count == 2


@respx.mock
@pytest.mark.parametrize(
    "link",
    [
        '<https://evil.test/api/v1/courses?page=2>; rel="next"',  # 남의 주소
        '<https://lms.test/api/v1/accounts?page=2>; rel="next"',  # 허용하지 않은 경로
        '<http://lms.test/api/v1/courses?page=2>; rel="next"',  # 평문 http (토큰이 그대로 나간다)
        '<javascript:alert(1)>; rel="next"',
    ],
)
async def test_it_does_not_follow_a_next_page_somewhere_else(link: str) -> None:
    respx.get(f"{BASE}/api/v1/courses").mock(
        httpx.Response(200, json=COURSES[:1], headers={"Link": link})
    )
    elsewhere = respx.get(host="evil.test").mock(httpx.Response(200, json=[]))
    got = await client().courses(TOKEN)
    assert len(got) == 1
    assert not elsewhere.called


@respx.mock
async def test_it_refuses_to_hand_back_a_list_it_could_not_finish() -> None:
    """쪽 상한에 걸리면 받은 것을 돌려주지 않는다. 부분 목록을 전체로 쓰면 과목을 지운다."""
    route = respx.get(url__startswith=f"{BASE}/api/v1/courses").mock(
        httpx.Response(
            200,
            json=COURSES[:1],
            headers={"Link": f'<{BASE}/api/v1/courses?page=9&per_page=100>; rel="next"'},
        )
    )
    with pytest.raises(LearningXError) as caught:
        await client().courses(TOKEN)
    assert "끝까지" in str(caught.value)
    assert route.call_count == MAX_PAGES


async def test_it_refuses_a_path_outside_the_allowed_list_before_asking() -> None:
    with respx.mock:  # 아무 경로도 등록하지 않는다. 요청을 보내면 respx가 터진다
        with pytest.raises(LearningXError) as caught:
            await client()._get(TOKEN, "/api/v1/courses/214023/users")
    assert "허용하지 않은" in str(caught.value)


@respx.mock
async def test_a_wrong_token_is_unauthorized_and_a_closed_path_is_forbidden() -> None:
    respx.get(f"{BASE}/api/v1/users/self").mock(
        httpx.Response(401, json={"errors": [{"message": "Invalid access token."}]})
    )
    with pytest.raises(LearningXError) as unauthorized:
        await client().me(TOKEN)
    assert unauthorized.value.unauthorized and not unauthorized.value.forbidden

    respx.get(url__startswith=f"{BASE}/api/v1/courses/1/assignments").mock(httpx.Response(403))
    with pytest.raises(LearningXError) as forbidden:
        await client().assignments(TOKEN, 1)
    assert forbidden.value.forbidden and not forbidden.value.unauthorized


@respx.mock
async def test_it_reports_a_connection_problem_without_the_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """토큰은 오류 문구·로그에 남지 않는다. 로그 가림이 잡지 못하는 모양으로 재야 뜻이 있다."""
    respx.get(f"{BASE}/api/v1/users/self").mock(side_effect=httpx.ConnectError("no route"))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(LearningXError) as caught:
            await client().me(PLAIN_TOKEN)
    assert "연결하지 못했어요" in str(caught.value)
    assert PLAIN_TOKEN not in str(caught.value)
    assert PLAIN_TOKEN not in caplog.text
    assert all(PLAIN_TOKEN not in str(record.args or ()) for record in caplog.records)


@respx.mock
async def test_it_does_not_follow_a_redirect(caplog: pytest.LogCaptureFixture) -> None:
    """리다이렉트를 따라가면 그 주소로 토큰을 보낸다. 3xx는 오류로 끝낸다."""
    respx.get(f"{BASE}/api/v1/users/self").mock(
        httpx.Response(302, headers={"Location": "https://evil.test/steal"})
    )
    elsewhere = respx.get(host="evil.test").mock(httpx.Response(200, json={}))
    with pytest.raises(LearningXError) as caught:
        await client().me(TOKEN)
    assert caught.value.status == 302
    assert not elsewhere.called


@respx.mock
async def test_too_many_requests_is_an_external_error_not_a_token_problem() -> None:
    respx.get(f"{BASE}/api/v1/users/self").mock(httpx.Response(429, headers={"Retry-After": "30"}))
    with pytest.raises(LearningXError) as caught:
        await client().me(TOKEN)
    assert caught.value.status == 429
    assert not caught.value.unauthorized and not caught.value.forbidden


@respx.mock
async def test_it_reads_the_user_and_rejects_a_body_in_another_shape() -> None:
    respx.get(f"{BASE}/api/v1/users/self").mock(httpx.Response(200, json=USERS_SELF))
    assert (await client().me(TOKEN))["id"] == USERS_SELF["id"]

    respx.get(f"{BASE}/api/v1/users/self").mock(httpx.Response(200, json=[1, 2]))
    with pytest.raises(LearningXError):
        await client().me(TOKEN)


def test_it_reads_the_next_link_out_of_the_header() -> None:
    header = (
        '<https://lms.test/api/v1/courses?page=1>; rel="current",'
        '<https://lms.test/api/v1/courses?page=2>; rel="next",'
        '<https://lms.test/api/v1/courses?page=1>; rel="first"'
    )
    assert next_link(header) == "https://lms.test/api/v1/courses?page=2"
    assert next_link('<https://lms.test/api/v1/courses?page=1>; rel="current"') is None
    assert next_link("") is None
    # rel이 두 번째 조각이 아닐 수도 있다
    other = '<https://lms.test/api/v1/courses?page=2>; type="application/json"; rel="next"'
    assert next_link(other) == "https://lms.test/api/v1/courses?page=2"
```

#### `api/tests/test_lms_api.py`

```python
"""LearningX 연결 API(F-50): 토큰 확인·저장·교체·해제와 과목 목록.
LearningX 호출은 respx로 가로채고 SQL은 test_lms_db.py가 본다."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.agent_log import using
from app.clock import current_time
from app.config import Settings, get_settings
from app.crypto import decrypt
from app.db import get_log_connect
from app.lms.parse import course_name
from app.main import create_app
from app.repositories.lms import Connection, get_lms_repo, ordered
from app.schemas.lms import CourseItem
from tests.conftest import USER_ID, make_token
from tests.fakes import FakeLogConnection
from tests.lms_samples import COURSES, DATABASE, MINE, USERS_SELF

CONNECTION = "/api/v1/lms/connection"
COURSES_PATH = "/api/v1/lms/courses"
BASE = "https://lms.test"
TOKEN = "18742~pAtB1g3TestTokenValue0000000000"
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)  # 2026-10-16 12:00 KST


class FakeLmsRepository:
    def __init__(self) -> None:
        self.row: Connection | None = None
        self.saved_courses: list[dict[str, Any]] = []
        self.deactivated = 0

    async def connection(self, user_id: str) -> Connection | None:
        assert user_id == USER_ID
        return self.row

    async def save_connection(
        self,
        user_id: str,
        *,
        token: str,
        last4: str,
        canvas_user_id: int | None,
        now: datetime,
    ) -> None:
        assert user_id == USER_ID
        self.row = Connection(
            status="active",
            token_last4=last4,
            access_token=token,
            canvas_user_id=canvas_user_id,
            last_synced_at=now,
            last_error=None,
        )

    async def mark_error(self, user_id: str, message: str) -> None:
        if self.row:
            self.row = Connection(**{**self.row.__dict__, "status": "error", "last_error": message})

    async def delete_connection(self, user_id: str) -> bool:
        if self.row is None:
            return False
        self.row = None
        return True

    async def save_courses(
        self, user_id: str, courses: list[dict[str, Any]], *, now: datetime
    ) -> int:
        assert user_id == USER_ID
        if courses:  # 실제 저장소도 빈 목록으로는 과목을 내리지 않는다
            self.saved_courses = courses
        return len(courses)

    async def courses(self, user_id: str, *, now: datetime) -> list[CourseItem]:
        assert user_id == USER_ID
        items = []
        for one in self.saved_courses:
            parsed = course_name(one["name"])
            items.append(
                CourseItem(
                    id=f"course-{one['id']}",
                    canvas_course_id=one["id"],
                    name=one["name"],
                    short_name=parsed.short_name,
                    has_syllabus=False,
                    portal_syllabus_url=parsed.syllabus_url,
                    open_assignments=0,
                    new_materials=0,
                    next_due=None,
                )
            )
        return items


@pytest.fixture
def repo() -> FakeLmsRepository:
    return FakeLmsRepository()


@pytest.fixture
def log() -> FakeLogConnection:
    return FakeLogConnection()


@pytest.fixture
def client(
    settings: Settings, repo: FakeLmsRepository, log: FakeLogConnection
) -> Iterator[TestClient]:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: Settings(
        **{**settings.model_dump(), "lms_api_base": BASE}
    )
    app.dependency_overrides[get_lms_repo] = lambda: repo
    app.dependency_overrides[get_log_connect] = lambda: using(log)  # type: ignore[arg-type]
    app.dependency_overrides[current_time] = lambda: NOW
    with TestClient(app) as started:
        yield started


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


def learningx(*, me: int = 200, courses: int = 200) -> None:
    respx.get(f"{BASE}/api/v1/users/self").mock(
        httpx.Response(me, json=USERS_SELF if me == 200 else {"errors": [{"message": "no"}]})
    )
    respx.get(url__startswith=f"{BASE}/api/v1/courses").mock(
        httpx.Response(courses, json=COURSES if courses == 200 else {"errors": []})
    )


@respx.mock
def test_it_connects_and_keeps_only_my_student_courses(
    client: TestClient, repo: FakeLmsRepository, log: FakeLogConnection, settings: Settings
) -> None:
    learningx()
    response = client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "active"
    assert body["token_last4"] == TOKEN[-4:]
    assert body["courses"] == len(MINE)  # 조교 과목과 준비중 과목은 뺀다
    assert body["first_sync_run_id"] == log.run_id
    assert [one["id"] for one in repo.saved_courses] == [one["id"] for one in MINE]
    # 토큰은 암호화해서만 저장하고 응답에는 끝 4자리만 간다
    assert repo.row is not None
    assert repo.row.access_token != TOKEN
    assert decrypt(repo.row.access_token, settings.token_encryption_key) == TOKEN
    assert TOKEN not in response.text
    # 실행과 도구 호출이 기록됐고, 도구 입력에 토큰이 없다
    assert log.wrote("insert into agent_runs")
    assert log.tools() == ["check_lms_token", "fetch_lms_courses"]
    assert all(TOKEN not in str(params) for _, params in log.statements)


@respx.mock
def test_a_wrong_token_is_refused_and_nothing_is_saved(
    client: TestClient, repo: FakeLmsRepository, log: FakeLogConnection
) -> None:
    learningx(me=401)
    response = client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LMS_TOKEN_INVALID"
    assert repo.row is None and repo.saved_courses == []
    # 실패한 토큰 확인도 실행으로 남는다(지표에 쓴다). 과목은 받지 않는다
    assert log.tools() == ["check_lms_token"]
    assert any(
        "status = %s" in query and "failed" in str(params) for query, params in log.statements
    )


@respx.mock
def test_when_the_course_list_fails_the_connection_is_not_saved(
    client: TestClient, repo: FakeLmsRepository
) -> None:
    learningx(courses=500)
    response = client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LMS_API_ERROR"
    assert repo.row is None


@respx.mock
def test_a_token_that_lost_access_while_listing_courses_asks_to_reconnect(
    client: TestClient,
) -> None:
    learningx(courses=401)
    response = client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LMS_TOKEN_INVALID"


@respx.mock
def test_connecting_again_replaces_the_token(
    client: TestClient, repo: FakeLmsRepository, settings: Settings
) -> None:
    learningx()
    client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    second = "18742~sEcOnDtOkEnValue00000000000000"
    response = client.post(CONNECTION, json={"access_token": f"  {second}  "}, headers=headers())
    assert response.status_code == 201
    assert response.json()["token_last4"] == second[-4:]  # 앞뒤 공백은 떼고 받는다
    assert repo.row is not None
    assert decrypt(repo.row.access_token, settings.token_encryption_key) == second


@respx.mock
def test_it_shows_the_connection_and_forgets_it_on_disconnect(
    client: TestClient, repo: FakeLmsRepository
) -> None:
    assert client.get(CONNECTION, headers=headers()).status_code == 404
    assert client.delete(CONNECTION, headers=headers()).status_code == 404

    learningx()
    client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    view = client.get(CONNECTION, headers=headers())
    assert view.status_code == 200
    assert view.json() == {
        "status": "active",
        "token_last4": TOKEN[-4:],
        "last_synced_at": "2026-10-16T12:00:00+09:00",
        "last_error": None,
    }
    assert client.delete(CONNECTION, headers=headers()).status_code == 204
    assert client.get(CONNECTION, headers=headers()).status_code == 404
    assert repo.row is None


@respx.mock
def test_the_course_list_has_the_short_name_and_the_portal_link(client: TestClient) -> None:
    learningx()
    client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    items = client.get(COURSES_PATH, headers=headers()).json()["items"]
    assert [one["short_name"] for one in items] == [
        "데이터베이스",
        "기계학습",
        "대학원 세미나(비정규)",
    ]
    assert "suup=23525" in items[0]["portal_syllabus_url"]
    assert items[2]["portal_syllabus_url"] is None  # 과목명 꼴이 달라 링크를 만들 수 없다
    assert items[0]["name"] == "202620HY23525_데이터베이스"  # 원래 이름은 그대로 둔다


@respx.mock
def test_an_empty_course_list_does_not_wipe_the_courses_i_had(
    client: TestClient, repo: FakeLmsRepository
) -> None:
    learningx()
    client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    assert len(repo.saved_courses) == len(MINE)

    respx.get(url__startswith=f"{BASE}/api/v1/courses").mock(httpx.Response(200, json=[]))
    again = client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    assert again.status_code == 201
    assert again.json()["courses"] == 0
    assert len(repo.saved_courses) == len(MINE)  # 앞서 받은 과목이 그대로 남는다


@respx.mock
def test_courses_i_only_assist_or_that_are_not_open_yet_are_left_out(
    client: TestClient, repo: FakeLmsRepository
) -> None:
    learningx()
    no_state = {**DATABASE, "id": 219004}
    no_state.pop("workflow_state")  # 열렸는지 알 수 없는 과목도 세지 않는다
    huge = {**DATABASE, "id": 2**70}  # bigint를 넘는 번호는 저장하지 않는다(DB가 터진다)
    respx.get(url__startswith=f"{BASE}/api/v1/courses").mock(
        httpx.Response(200, json=[*COURSES, no_state, huge])
    )
    response = client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    assert response.json()["courses"] == len(MINE)
    assert [one["id"] for one in repo.saved_courses] == [one["id"] for one in MINE]


def test_the_course_list_order_does_not_depend_on_the_database() -> None:
    """정렬은 ordered()가 한다. DB의 정렬 규칙(collation)은 환경마다 한글·숫자 앞뒤가 바뀐다.

    DB 없이 도는 테스트라 CI에서만 걸리는 일이 없다(2026-10-16에 그렇게 한 번 걸렸다).
    """
    names = [
        "202620HY23534_기계학습",
        "대학원 세미나(비정규)",
        "2026 겨울 특강",
        "202620HY25123_AI+X공학융합프로젝트",
        "202620HY23525_데이터베이스",
    ]
    items = [
        CourseItem(
            id=f"course-{index}",
            canvas_course_id=index,
            name=name,
            short_name=course_name(name).short_name,
            has_syllabus=False,
            portal_syllabus_url=None,
            open_assignments=0,
            new_materials=0,
            next_due=None,
        )
        for index, name in enumerate(names, start=1)
    ]
    assert [one.short_name for one in ordered(items)] == [
        "2026 겨울 특강",  # 과목명 꼴이 아니라 이름 전체가 화면 이름이다
        "AI+X공학융합프로젝트",
        "기계학습",
        "대학원 세미나(비정규)",
        "데이터베이스",
    ]
    # 어느 순서로 들어와도 결과가 같다
    assert [one.name for one in ordered(items[::-1])] == [one.name for one in ordered(items)]


def test_it_refuses_a_body_with_another_field(client: TestClient) -> None:
    response = client.post(
        CONNECTION, json={"access_token": TOKEN, "lms": "other"}, headers=headers()
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", CONNECTION),
        ("get", CONNECTION),
        ("delete", CONNECTION),
        ("get", COURSES_PATH),
    ],
)
def test_every_lms_path_needs_a_login(client: TestClient, method: str, path: str) -> None:
    body = {"json": {"access_token": TOKEN}} if method == "post" else {}
    assert getattr(client, method)(path, **body).status_code == 401
```

#### `api/tests/test_lms_db.py`

```python
"""LearningX 연결·과목 SQL(F-50)을 실제 스키마에 대고 확인한다: 토큰 저장·교체·삭제,
과목 upsert와 수강 뺀 과목 내리기, 과목 목록의 숫자와 격리.

트랜잭션을 되돌려 지운다. DATABASE_URL이 있을 때만 돈다.
"""

from datetime import timedelta
from typing import Any

import pytest

from app.eligibility import KST
from app.repositories.lms import LmsRepository
from tests.db_world import DATABASE_URL, connect, make_user
from tests.lms_samples import DATABASE, MACHINE_LEARNING, MINE, SEMINAR

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


@pytest.fixture
async def world() -> Any:
    """사용자 둘과 저장소. 트랜잭션은 끝에 되돌린다."""
    conn = await connect()
    try:
        now = (await (await conn.execute("select now() as now")).fetchone())["now"]
        yield {
            "repo": LmsRepository(conn),
            "conn": conn,
            "now": now,
            "me": await make_user(conn),
            "other": await make_user(conn),
        }
    finally:
        await conn.rollback()
        await conn.close()


async def test_it_saves_the_token_and_swaps_it_on_reconnect(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    assert await repo.connection(me) is None

    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=77001, now=now)
    first = await repo.connection(me)
    assert first is not None
    assert (first.status, first.token_last4, first.access_token) == ("active", "a9f2", "enc-1")
    assert first.canvas_user_id == 77001
    assert first.last_synced_at == now

    later = now + timedelta(minutes=5)
    await repo.save_connection(me, token="enc-2", last4="b8e1", canvas_user_id=77001, now=later)
    second = await repo.connection(me)
    assert second is not None
    assert (second.access_token, second.token_last4) == ("enc-2", "b8e1")
    rows = await (
        await world["conn"].execute(
            "select count(*) as n from lms_connections where user_id = %s", (me,)
        )
    ).fetchone()
    assert rows["n"] == 1  # 한 사용자당 한 줄이다


async def test_an_error_mark_is_cleared_when_the_token_is_replaced(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await repo.mark_error(me, "토큰이 만료되었거나 삭제되었어요.")
    broken = await repo.connection(me)
    assert broken is not None and broken.status == "error"
    assert broken.view().status == "error" and broken.view().last_error is not None

    await repo.save_connection(me, token="enc-2", last4="b8e1", canvas_user_id=1, now=now)
    fixed = await repo.connection(me)
    assert fixed is not None and (fixed.status, fixed.last_error) == ("active", None)


async def test_the_connection_status_goes_out_as_the_db_has_it(world: dict[str, Any]) -> None:
    """DB enum은 active·error·disconnected 셋이다. GET /me도 그 값을 그대로 쓰므로 뭉개지 않는다."""
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    for status in ("active", "error", "disconnected"):
        await conn.execute(
            "update lms_connections set status = %s where user_id = %s", (status, me)
        )
        found = await repo.connection(me)
        assert found is not None and found.view().status == status


async def test_the_connection_repr_does_not_show_the_token(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-secret-1", last4="a9f2", canvas_user_id=1, now=now)
    found = await repo.connection(me)
    assert found is not None and "enc-secret-1" not in repr(found)


async def test_disconnecting_removes_the_token_but_keeps_the_courses(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await repo.save_courses(me, MINE, now=now)

    assert await repo.delete_connection(me) is True
    assert await repo.connection(me) is None
    assert await repo.delete_connection(me) is False  # 두 번째는 지울 것이 없다
    assert len(await repo.courses(me, now=now)) == len(MINE)  # 과목 기록은 남는다


async def test_it_parses_the_course_name_into_the_portal_columns(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    assert await repo.save_courses(me, MINE, now=now) == len(MINE)
    rows = await (
        await conn.execute(
            "select canvas_course_id, name, term, portal_year, portal_term, portal_course_no"
            " from lms_courses where user_id = %s order by name",
            (me,),
        )
    ).fetchall()
    by_id = {row["canvas_course_id"]: row for row in rows}
    database = by_id[DATABASE["id"]]
    assert (database["portal_year"], database["portal_term"]) == (2026, 20)
    assert (database["portal_course_no"], database["term"]) == ("23525", "2026-2")
    assert database["name"] == DATABASE["name"]  # 원래 이름을 그대로 둔다
    seminar = by_id[SEMINAR["id"]]
    # 꼴이 다른 과목: 번호는 비우고 학기는 LearningX가 준 이름을 쓴다
    assert (seminar["portal_year"], seminar["portal_course_no"]) == (None, None)
    assert seminar["term"] == "2026년 2학기"


async def test_a_course_i_stopped_taking_drops_out_of_the_list(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, MINE, now=now)
    assert {one.canvas_course_id for one in await repo.courses(me, now=now)} == {
        one["id"] for one in MINE
    }

    # 다음 동기화에 데이터베이스만 남았다 → 나머지는 목록에서 빠지지만 행은 남는다
    await repo.save_courses(me, [DATABASE], now=now)
    assert [one.canvas_course_id for one in await repo.courses(me, now=now)] == [DATABASE["id"]]
    rows = await (
        await conn.execute(
            "select canvas_course_id, is_active from lms_courses where user_id = %s", (me,)
        )
    ).fetchall()
    assert {row["canvas_course_id"]: row["is_active"] for row in rows} == {
        DATABASE["id"]: True,
        MACHINE_LEARNING["id"]: False,
        SEMINAR["id"]: False,
    }

    # 다시 들으면 되살아난다
    await repo.save_courses(me, MINE, now=now)
    assert len(await repo.courses(me, now=now)) == len(MINE)


async def test_the_course_list_counts_what_is_stored_now(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = (await repo.courses(me, now=now))[0]
    # 과제·주차 항목 동기화는 F-51·F-52다. 그때까지 0이고 다음 할 일도 없다
    assert (course.open_assignments, course.new_materials, course.next_due) == (0, 0, None)
    assert course.has_syllabus is False
    assert course.short_name == "데이터베이스"
    assert "suup=23525" in (course.portal_syllabus_url or "")

    # 미제출 과제 둘(하나는 마감 지남)과 제출한 과제 하나를 넣으면 숫자가 맞는다
    row = await (
        await conn.execute(
            "select id from lms_courses where user_id = %s and canvas_course_id = %s",
            (me, DATABASE["id"]),
        )
    ).fetchone()
    course_id = row["id"]
    for canvas_id, title, due, state in (
        (1, "실습 2주차", now + timedelta(days=3), "unsubmitted"),
        (2, "실습 1주차", now - timedelta(days=3), "unsubmitted"),
        (3, "실습 3주차", now + timedelta(days=1), "submitted"),
    ):
        await conn.execute(
            "insert into lms_assignments (user_id, lms_course_id, canvas_assignment_id, title,"
            " due_at, submission_state) values (%s, %s, %s, %s, %s, %s)",
            (me, course_id, canvas_id, title, due, state),
        )
    counted = (await repo.courses(me, now=now))[0]
    assert counted.open_assignments == 2  # 마감이 지난 미제출도 센다
    assert counted.next_due is not None
    assert counted.next_due.kind == "assignment"
    assert counted.next_due.title == "실습 2주차"  # 아직 안 지난 것 중 가장 가까운 것
    assert counted.next_due.due_at == (now + timedelta(days=3)).astimezone(KST)


async def test_new_module_items_count_from_when_i_last_opened_the_course(
    world: dict[str, Any],
) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    await conn.execute(
        "update lms_courses set last_viewed_at = %s where user_id = %s",
        (now - timedelta(days=1), me),
    )
    for canvas_item_id, seen in ((11, now - timedelta(days=2)), (12, now), (13, now)):
        await conn.execute(
            "insert into lms_module_items (canvas_course_id, canvas_item_id, module_name, title,"
            " item_type, first_seen_at) values (%s, %s, '8주차', '08 - 자료', 'ExternalTool', %s)",
            (DATABASE["id"], canvas_item_id, seen),
        )
    assert (await repo.courses(me, now=now))[0].new_materials == 2  # 본 뒤에 생긴 둘만


async def test_an_empty_course_list_does_not_take_my_courses_away(world: dict[str, Any]) -> None:
    """학기 사이·필터·끊긴 목록 때문에 빈 목록이 올 수 있다. 그때 전부 내리면 복구할 길이 없다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, MINE, now=now)
    assert await repo.save_courses(me, [], now=now) == 0
    assert len(await repo.courses(me, now=now)) == len(MINE)


async def test_the_next_thing_due_can_be_a_syllabus_item(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = (await repo.courses(me, now=now))[0]
    row = await (
        await conn.execute(
            "insert into syllabi (user_id, lms_course_id, course_name, semester)"
            " values (%s, %s, '데이터베이스', '2026-2') returning id",
            (me, course.id),
        )
    ).fetchone()
    for item_type, title, starts, confirmed in (
        ("midterm", "중간고사", now + timedelta(days=2), True),
        ("final", "기말고사", now + timedelta(days=40), True),
        ("presentation", "발표(미확정)", now + timedelta(days=1), False),
    ):
        await conn.execute(
            "insert into syllabus_items (syllabus_id, item_type, title, starts_at, is_confirmed)"
            " values (%s, %s, %s, %s, %s)",
            (row["id"], item_type, title, starts, confirmed),
        )
    with_syllabus = (await repo.courses(me, now=now))[0]
    assert with_syllabus.has_syllabus is True
    assert with_syllabus.next_due is not None
    # 확인하지 않은 일정(발표)은 빼고, 확정된 것 중 가장 가까운 것이다
    assert (with_syllabus.next_due.kind, with_syllabus.next_due.title) == (
        "syllabus_item",
        "중간고사",
    )

    # 과제가 더 가까우면 과제가 이긴다
    await conn.execute(
        "insert into lms_assignments (user_id, lms_course_id, canvas_assignment_id, title,"
        " due_at, submission_state) values (%s, %s, 9, '실습 7주차', %s, 'unsubmitted')",
        (me, course.id, now + timedelta(hours=5)),
    )
    nearest = (await repo.courses(me, now=now))[0].next_due
    assert nearest is not None and (nearest.kind, nearest.title) == ("assignment", "실습 7주차")


async def test_the_list_is_sorted_by_the_name_on_screen(world: dict[str, Any]) -> None:
    """DB가 어떤 순서로 주든 화면 이름 순으로 정렬해 내려준다(정렬 규칙은 환경마다 다르다)."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, MINE, now=now)
    assert [one.short_name for one in await repo.courses(me, now=now)] == [
        "기계학습",
        "대학원 세미나(비정규)",
        "데이터베이스",
    ]


async def test_a_module_item_counts_for_everyone_taking_that_course(world: dict[str, Any]) -> None:
    """주차 항목은 과목 공통이다(ERD 3-2). 같은 과목을 듣는 사람이 넣어도 내 새 자료로 센다."""
    repo, me, other, now, conn = (
        world["repo"],
        world["me"],
        world["other"],
        world["now"],
        world["conn"],
    )
    await repo.save_courses(me, [DATABASE], now=now)
    await repo.save_courses(other, [DATABASE], now=now)
    await conn.execute("update lms_courses set last_viewed_at = %s", (now - timedelta(days=1),))
    await conn.execute(
        "insert into lms_module_items (canvas_course_id, canvas_item_id, module_name, title,"
        " item_type, first_seen_at) values (%s, 21, '9주차', '09 - 자료', 'ExternalTool', %s)",
        (DATABASE["id"], now),
    )
    assert (await repo.courses(me, now=now))[0].new_materials == 1
    assert (await repo.courses(other, now=now))[0].new_materials == 1


async def test_my_courses_and_connection_are_not_someone_elses(world: dict[str, Any]) -> None:
    repo, me, other, now = world["repo"], world["me"], world["other"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await repo.save_courses(me, MINE, now=now)

    assert await repo.connection(other) is None
    assert await repo.courses(other, now=now) == []
    assert await repo.delete_connection(other) is False
    # 남의 동기화가 내 과목을 내리지 않는다
    await repo.save_courses(other, [DATABASE], now=now)
    assert len(await repo.courses(me, now=now)) == len(MINE)
```

### api (바뀌는 파일)

#### `api/app/config.py`

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """api/.env에서 읽는 설정. 각 값의 의미는 .env.example 참고."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    token_encryption_key: str = ""
    cors_origins: list[str] = ["http://localhost:3000"]
    api_prefix: str = "/api/v1"
    # Gemini 플랫폼(Google Cloud). 모델 ID는 단가표(app/pricing.py) 키와 같아야 한다
    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    extraction_model: str = "gemini-3.8-flash"
    vision_model: str = "gemini-3.8-flash"
    guide_model: str = "gemini-3.5-flash-lite"  # 준비하기의 서류 안내(짧은 구조화 답)
    extraction_max_reads: int = 4  # 요건 추출 읽기 도구 상한(PRD 14장 미결, W2–3에 확정)
    extraction_max_tokens: int = 150_000
    youth_api_key: str = ""  # 온통청년 OPEN API 인증키(청년정책 수집, app/youth)
    # 포스터·계획서 업로드 파일을 두는 Supabase Storage(F-13). 버킷은 대시보드에서 비공개로 만든다
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "uploads"
    # 마감일 캘린더 등록(F-32). Supabase Google 로그인에 쓰는 OAuth 앱의 값과 같아야 한다.
    # 비워 두면 access token(55분)이 만료된 뒤 다시 연결해야 한다(갱신을 못 한다)
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    # 시험용으로만 바꾼다(가짜 Google로 E2E를 돌릴 때)
    google_token_url: str = "https://oauth2.googleapis.com/token"
    google_calendar_api_base: str = "https://www.googleapis.com/calendar/v3"
    # 비우면 SUPABASE_URL에서 만든다(https://<ref>.supabase.co/storage/v1)
    supabase_storage_base: str = ""
    # LearningX(Canvas) API. 시험용으로만 바꾼다(녹화 응답을 재생할 때)
    lms_api_base: str = "https://learning.hanyang.ac.kr"
    # /internal/* 호출에 쓰는 서비스 키(명세 12장의 X-Internal-Key). 비우면 그 경로가 모두 403이다
    internal_api_key: str = ""

    @property
    def storage_base_url(self) -> str:
        """Storage REST 주소. 시험용 주소를 넣었으면 그것을 쓴다."""
        if self.supabase_storage_base:
            return self.supabase_storage_base.rstrip("/")
        return f"{self.supabase_url.rstrip('/')}/storage/v1" if self.supabase_url else ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

#### `api/app/main.py`

```python
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import auth_settings_problem
from app.background import TaskRunner
from app.config import Settings, get_settings
from app.db import create_pools
from app.errors import UnhandledErrorMiddleware, register_error_handlers
from app.logging_redact import install_log_redaction
from app.routers import (
    auth,
    calendar,
    events,
    files,
    health,
    internal,
    lms,
    me,
    meta,
    notifications,
    opportunities,
    planner,
    posters,
    runs,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    # 로그인 설정이 틀렸으면 첫 요청을 기다리지 않고 시작할 때 알린다(.env를 고치면 서버를 다시 켠다)
    if problem := auth_settings_problem(settings):
        logger.warning("로그인 설정 확인: %s", problem)
    # 파일 업로드(F-13)는 Supabase Storage가 있어야 한다. 비었으면 첫 업로드에서 502가 난다
    if not settings.supabase_service_role_key or not settings.storage_base_url:
        logger.warning(
            "파일 저장소 설정 확인: SUPABASE_SERVICE_ROLE_KEY·SUPABASE_URL이 있어야 포스터를 올릴 수 있어요"
        )
    app.state.pool = app.state.log_pool = None
    if settings.database_url:
        app.state.pool, app.state.log_pool = create_pools(settings.database_url)
        await app.state.pool.open()
        await app.state.log_pool.open()
    yield
    # 돌던 준비하기를 잠깐 기다린다(못 끝내면 다음 요청이 멈춘 실행으로 보고 다시 만든다)
    await app.state.runner.drain(timeout=10)
    for pool in (app.state.pool, app.state.log_pool):
        if pool is not None:
            await pool.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    install_log_redaction()  # 로그에서 토큰을 가린다 (요청 처리 전에 건다)
    settings = settings or get_settings()
    app = FastAPI(title="UNIPIVOT API", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.runner = TaskRunner()  # 요청이 끝난 뒤 이어서 할 일(준비하기 실행)
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
    for router in (
        auth.router,
        calendar.router,
        files.router,
        internal.router,
        lms.router,
        me.router,
        meta.router,
        notifications.router,
        events.router,
        opportunities.router,
        planner.router,
        posters.router,
        runs.router,
    ):
        app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()
```

#### `api/app/logging_redact.py`

```python
"""로그에서 토큰을 가린다 (PRD 7장 토큰 보안). 앱을 만들 때 install_log_redaction()을 한 번 부른다.

가리는 것: Authorization 헤더, Bearer 토큰, token=… 값, JWT, Google access·refresh token,
LearningX(Canvas) 개인 액세스 토큰, Fernet 암호문, Anthropic·Google API 키, 주소에 붙은 API 키
(온통청년 apiKeyNm=… 등). 요청 주소처럼 문자열이 아닌 인자도 문자열로 바꿔 보고 가릴 것이 있으면 가린다.
"""

import logging
import re
from collections.abc import Mapping
from typing import Any

_REDACTED = "[REDACTED]"
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?(?:bearer\s+)?)[^\s'\",}]+"),
        r"\1" + _REDACTED,
    ),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1" + _REDACTED),
    (
        re.compile(r"(?i)((?:access_|refresh_|provider_)?token['\"]?\s*[:=]\s*['\"]?)[^\s'\",}&]+"),
        r"\1" + _REDACTED,
    ),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), _REDACTED),
    (re.compile(r"ya29\.[A-Za-z0-9._-]+"), _REDACTED),
    (re.compile(r"1//[A-Za-z0-9._-]{10,}"), _REDACTED),
    # LearningX(Canvas) 개인 액세스 토큰: `18742~...`. 접두 자릿수와 뒤 길이·글자가 제각각이다
    (re.compile(r"\b\d{1,8}~[A-Za-z0-9_~-]{8,}"), _REDACTED),
    (re.compile(r"gAAAAA[A-Za-z0-9_=-]{20,}"), _REDACTED),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), _REDACTED),
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), _REDACTED),
    # 주소에 붙은 키: apiKeyNm=…, api_key=…, x_api_key=…, serviceKey=…
    (
        re.compile(r"(?i)(?<![A-Za-z0-9])((?:apiKeyNm|api_?key|service_?key)=)[^&\s'\"]+"),
        r"\1" + _REDACTED,
    ),
)
# 이런 말이 든 서식 문자열이면 인자(문자열)를 통째로 가린다: logger.info("Authorization: %s", value)
_SENSITIVE_FORMAT = re.compile(r"(?i)authorization|bearer|token|secret|password|api[_-]?key")


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


_installed = False


def install_log_redaction() -> None:
    """모든 로그 레코드의 메시지·인자·예외 내용에서 토큰을 가린다. 여러 번 불러도 한 번만 건다.

    인자가 있는 레코드는 서식 문자열을 건드리지 않고 인자만 가린다. 인자 개수와 타입이 그대로라서
    uvicorn 접근 로그처럼 인자를 직접 꺼내 쓰는 포매터도 깨지지 않는다.
    """
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()
    formatter = logging.Formatter()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        if record.args:
            mask_all = isinstance(record.msg, str) and bool(_SENSITIVE_FORMAT.search(record.msg))

            def clean(item: Any) -> Any:
                if isinstance(item, str):
                    return _REDACTED if mask_all else redact(item)
                if item is None or isinstance(item, int | float):
                    return item
                try:
                    text = str(item)  # httpx 요청 로그의 주소(httpx.URL) 같은 객체
                except Exception:
                    return item  # 문자열로 못 바꾸는 값은 로그 쪽이 알아서 처리한다(부른 곳을 멈추지 않는다)
                cleaned = redact(text)
                return cleaned if cleaned != text else item

            if isinstance(record.args, Mapping):
                record.args = {key: clean(item) for key, item in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(clean(item) for item in record.args)
        elif isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(formatter.formatException(record.exc_info))
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
```

#### `api/.env.example`

```text
# Supabase DB 연결 문자열 (Project Settings > Database). 서버는 세션 풀러 주소를 권장
DATABASE_URL=postgresql://postgres.<project-ref>:<password>@<pooler-host>:5432/postgres
# Supabase 프로젝트 주소. 새 프로젝트는 이 주소의 JWKS 공개키로 토큰을 검증한다
SUPABASE_URL=https://<project-ref>.supabase.co
# 레거시 HS256 JWT 비밀키를 쓰는 프로젝트만 채운다. 비우면 JWKS로 검증
SUPABASE_JWT_SECRET=
# Google·LMS 토큰 암호화 키: uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 키를 바꿀 때는 "새키,옛키"처럼 쉼표로 이어 둔다. 새 키로 암호화하고 두 키 모두로 복호화한다
TOKEN_ENCRYPTION_KEY=
CORS_ORIGINS=["http://localhost:3000"]
# Gemini 플랫폼(Google Cloud) 프로젝트 ID. 로컬 인증: gcloud auth application-default login
GOOGLE_CLOUD_PROJECT=
GOOGLE_CLOUD_LOCATION=global
# 요건 추출·첨부 Vision 모델. 단가표(app/pricing.py)에 있는 ID만 쓴다
EXTRACTION_MODEL=gemini-3.8-flash
VISION_MODEL=gemini-3.8-flash
# 준비하기의 서류 안내 모델(사전에 없는 서류와 청년정책 제출 서류 글만 묻는다)
GUIDE_MODEL=gemini-3.5-flash-lite
# 요건 추출 상한: 읽기 도구 호출 수, 실행 전체 토큰(입력+출력)
EXTRACTION_MAX_READS=4
EXTRACTION_MAX_TOKENS=150000
# 온통청년 OPEN API 인증키(마이페이지 > OPEN API). 청년정책 수집(python -m app.youth.cli)에 쓴다
YOUTH_API_KEY=
# 포스터 파일을 두는 Supabase Storage(F-13). 대시보드 Storage에서 비공개(Public 끔) 버킷을 하나 만들고
# 그 이름을 적는다. 서비스 역할 키는 Project Settings > API Keys의 service_role이고, DB 전체를 읽고 쓸
# 수 있으니 이 값은 .env에만 두고 브라우저·레포에 넣지 않는다. 주소는 SUPABASE_URL에서 만든다
SUPABASE_STORAGE_BUCKET=uploads
SUPABASE_SERVICE_ROLE_KEY=
# 마감일 캘린더 등록(F-32)에 쓰는 Google OAuth 앱. Supabase Authentication > Providers > Google에
# 넣은 것과 같은 값이다(Google Cloud Console > API 및 서비스 > 사용자 인증 정보).
# 비워 두면 캘린더 권한이 55분 뒤 만료되고 학생이 다시 연결해야 한다. 비밀값은 .env에만 적는다
GOOGLE_OAUTH_CLIENT_ID=000000000000-abcdefghijklmnopqrstuvwxyz012345.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=
# /internal/* (지표 집계·시나리오 실행)을 부를 때 X-Internal-Key 헤더에 넣는 값. 비우면 그 경로가 모두 403이다
# 아무 긴 임의 문자열이면 된다: uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
INTERNAL_API_KEY=
# LearningX(Canvas) 주소(F-50). 학교 LMS 주소이고 비밀값이 아니다. 기본값이 한양대 주소라
# 그대로 두면 된다. 시험용으로 녹화 응답을 재생할 때만 바꾼다
LMS_API_BASE=https://learning.hanyang.ac.kr
```

#### `api/tests/fakes.py`

```python
"""단위 테스트용 가짜 저장소. 실제 저장소와 메서드 이름·반환 타입을 맞춘다."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from app.repositories.opportunities import FeedPage, FeedQuery, Refresh
from app.repositories.profiles import Consents
from app.schemas.me import (
    COMPLETION_FIELDS,
    INCOME_FIELDS,
    ConsentResult,
    IncomeConsentResult,
    Me,
    Profile,
    ProfileCompletion,
)
from app.schemas.meta import Department
from app.schemas.metrics import (
    EligibilityMatrix,
    Latency,
    Metrics,
    ProductMetrics,
    Ratio,
    ScenarioMetrics,
    UndeterminedRate,
)
from app.schemas.opportunities import FeedCounts, OpportunityDetail, OpportunityItem


class FakeProfileRepository:
    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, dict[str, str]] = {}
        self.locks: list[str] = []

    async def lock(self, user_id: str) -> None:
        self.locks.append(user_id)

    async def ensure(self, user_id: str, display_name: str | None) -> None:
        row = self.profiles.setdefault(
            user_id,
            {
                "display_name": None,
                "consented_at": None,
                "income_agreed_at": None,
                "profile": Profile(),
            },
        )
        row["display_name"] = row["display_name"] or display_name

    async def get_me(self, user_id: str) -> Me | None:
        row = self.profiles.get(user_id)
        if row is None:
            return None
        filled = sum(getattr(row["profile"], f) is not None for f in COMPLETION_FIELDS)
        return Me(
            user_id=user_id,
            display_name=row["display_name"] or "학생",
            hyin_verified=False,
            calendar_connected=user_id in self.tokens,
            lms=None,
            profile_completion=ProfileCompletion(filled=filled, total=len(COMPLETION_FIELDS)),
            consented=row["consented_at"] is not None,
            income_info_consented=row["income_agreed_at"] is not None,
            unread_notifications=0,
        )

    async def get_profile(self, user_id: str) -> Profile | None:
        row = self.profiles.get(user_id)
        return row["profile"] if row else None

    async def update_profile(self, user_id: str, values: dict[str, Any]) -> None:
        row = self.profiles[user_id]
        row["profile"] = row["profile"].model_copy(update=values)

    async def get_consents(self, user_id: str) -> Consents:
        row = self.profiles.get(user_id)
        if row is None:
            return Consents(terms_privacy=False, income_info=False)
        return Consents(
            terms_privacy=row["consented_at"] is not None,
            income_info=row["income_agreed_at"] is not None,
        )

    async def save_consent(
        self, user_id: str, version: str, agree_income_info: bool
    ) -> ConsentResult:
        now = datetime.now(UTC)
        row = self.profiles[user_id]
        row["consented_at"] = now
        self._set_income(row, agree_income_info, now)
        return ConsentResult(
            terms_agreed_at=now,
            privacy_agreed_at=now,
            income_info_agreed_at=row["income_agreed_at"],
            consent_version=version,
        )

    async def set_income_consent(self, user_id: str, agree: bool) -> IncomeConsentResult:
        row = self.profiles[user_id]
        self._set_income(row, agree, datetime.now(UTC))
        return IncomeConsentResult(income_info_agreed_at=row["income_agreed_at"])

    @staticmethod
    def _set_income(row: dict[str, Any], agree: bool, now: datetime) -> None:
        if agree:
            row["income_agreed_at"] = row["income_agreed_at"] or now
        else:  # 철회하면 소득 값도 지운다 (DB 제약과 같은 규칙)
            row["income_agreed_at"] = None
            row["profile"] = row["profile"].model_copy(update=dict.fromkeys(INCOME_FIELDS))

    async def save_google_tokens(self, user_id: str, access_token: str, refresh_token: str) -> None:
        self.tokens[user_id] = {"access_token": access_token, "refresh_token": refresh_token}


class FakeMetaRepository:
    def __init__(self) -> None:
        self.departments = [
            Department(name="인공지능학과", college="소프트웨어융합대학", field_group="공학계열"),
            Department(name="경영학부", college="경상대학", field_group="사회계열"),
        ]
        self.events: list[tuple[str, str, UUID | None]] = []

    async def list_departments(self) -> list[Department]:
        return list(self.departments)

    async def department_exists(self, name: str) -> bool:
        return any(department.name == name for department in self.departments)

    async def record_event(
        self, user_id: str, event: str, opportunity_id: UUID | None = None
    ) -> None:
        self.events.append((user_id, event, opportunity_id))


class FakeOpportunityRepository:
    """피드 API 단위 테스트용. 받은 요청을 남기고 정해 둔 목록·집계를 돌려준다."""

    def __init__(self) -> None:
        self.refreshes: list[tuple[str, bool, bool]] = []  # (user_id, force, include_expired)
        self.queries: list[FeedQuery] = []
        self.items: list[OpportunityItem] = []
        self.next_cursor: str | None = None
        self.changed = 0
        self.details: dict[str, OpportunityDetail] = {}  # 공고 id → 상세. 없으면 404
        self.detail_calls: list[tuple[str, str, str | None]] = []  # (user_id, 공고 id, 이름)
        self.openable: set[str] = set()  # 표시를 붙일 수 있는 공고 id. 없으면 404
        self.marks: dict[tuple[str, str], tuple[str, datetime]] = {}  # (user, 공고) → (표시, 시각)
        self.mark_calls: list[
            tuple[str, str, str | None, str | None]
        ] = []  # (user_id, 공고 id, 표시, 이름). 지우면 표시·이름이 None
        self.counts = FeedCounts(
            eligible=0,
            new_eligible=0,
            undetermined=0,
            missing_info=0,
            needs_review=0,
            ineligible=0,
            deadline_soon=0,
        )

    async def refresh_judgments(
        self,
        user_id: str,
        *,
        now: datetime,
        force: bool = False,
        include_expired: bool = False,
        display_name: str | None = None,
    ) -> Refresh:
        self.refreshes.append((user_id, force, include_expired))
        return Refresh(judged=0, changed=self.changed)

    async def feed_page(self, user_id: str, query: FeedQuery, *, now: datetime) -> FeedPage:
        self.queries.append(query)
        return FeedPage(items=list(self.items), next_cursor=self.next_cursor)

    async def feed_counts(self, user_id: str, *, now: datetime) -> FeedCounts:
        return self.counts

    async def detail(
        self,
        user_id: str,
        opportunity_id: str,
        *,
        now: datetime,
        display_name: str | None = None,
    ) -> OpportunityDetail | None:
        self.detail_calls.append((user_id, opportunity_id, display_name))
        return self.details.get(opportunity_id)

    async def set_mark(
        self,
        user_id: str,
        opportunity_id: str,
        mark: str,
        *,
        now: datetime,
        display_name: str | None = None,
    ) -> datetime | None:
        self.mark_calls.append((user_id, opportunity_id, mark, display_name))
        if opportunity_id not in self.openable:
            return None
        old = self.marks.get((user_id, opportunity_id))
        at = old[1] if old and old[0] == mark else now
        self.marks[(user_id, opportunity_id)] = (mark, at)
        return at

    async def clear_mark(self, user_id: str, opportunity_id: str) -> None:
        self.mark_calls.append((user_id, opportunity_id, None, None))
        self.marks.pop((user_id, opportunity_id), None)


class FakeMetricsRepository:
    """지표 집계 대역. 받은 기간만 적어 두고 빈 집계를 돌려준다."""

    def __init__(self) -> None:
        self.periods: list[tuple[date, date]] = []

    async def metrics(self, period: tuple[date, date]) -> Metrics:
        self.periods.append(period)
        start, end = period
        empty = Ratio(numerator=0, denominator=0, rate=None)
        return Metrics(
            from_date=start,
            to_date=end,
            scenarios=ScenarioMetrics(
                runs=0,
                passed=0,
                success_rate=0.0,
                latency=Latency(p50_ms=0, p95_ms=0),
                cost_usd=0.0,
                llm_calls=0,
                by_scenario=[],
            ),
            eligibility=EligibilityMatrix(
                run_started_at=None,
                checks=0,
                correct=0,
                accuracy=0.0,
                rows=[],
                eligible_to_ineligible=0,
                ineligible_to_eligible=0,
            ),
            product=ProductMetrics(
                undetermined=UndeterminedRate(**empty.model_dump(), top_missing_fields=[]),
                profile_prompt=empty,
                prepare_conversion=empty,
                lms_connect=empty,
                weekly_return=empty,
            ),
        )


class FakeLogCursor:
    """agent_log가 쓰는 커서 흉내. `returning id`면 행을 하나 준다."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self.row


class FakeLogConnection:
    """실행 로그용 autocommit 연결 흉내(DB 없이 agent_run을 돌린다).

    쓴 문장을 statements에 모아 둬서, 테스트가 실행·도구 기록이 남았는지 본다.
    """

    autocommit = True

    def __init__(self, run_id: str = "00000000-0000-4000-8000-0000000000a1") -> None:
        self.run_id = run_id
        self.statements: list[tuple[str, Any]] = []

    async def execute(self, query: str, params: Any = None) -> FakeLogCursor:
        self.statements.append((query, params))
        if "returning id" not in query:
            return FakeLogCursor(None)
        if "agent_runs" in query:
            return FakeLogCursor({"id": self.run_id})
        return FakeLogCursor({"id": "00000000-0000-4000-8000-0000000000a2"})

    def wrote(self, needle: str) -> bool:
        return any(needle in query for query, _ in self.statements)

    def tools(self) -> list[str]:
        """기록된 도구 이름(tool_calls에 넣은 순서대로)."""
        return [
            params[2]
            for query, params in self.statements
            if "insert into tool_calls" in query and isinstance(params, tuple)
        ]
```

#### `api/tests/test_security.py`

```python
"""토큰 암호화 키 교체와 로그 마스킹 (PRD 7장 토큰 보안)."""

import logging

import httpx
import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.crypto import decrypt, encrypt, rotate
from app.logging_redact import install_log_redaction, redact

JWT_LIKE = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXZhbHVlLWhlcmU"
LMS_TOKEN = "1234~AbCdEfGhIjKlMnOpQrStUvWx"


def test_key_rotation() -> None:
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    stored = encrypt("1//refresh", old)
    both = f"{new},{old}"
    assert decrypt(stored, both) == "1//refresh"  # 키를 바꾼 뒤에도 옛 값을 읽는다
    rotated = rotate(stored, both)
    assert decrypt(rotated, new) == "1//refresh"  # 다시 암호화하면 새 키만으로 읽는다
    with pytest.raises(InvalidToken):
        decrypt(stored, new)


def test_redact_patterns() -> None:
    secrets = (
        JWT_LIKE,
        "ya29.a0AfH6SMBx",
        "1//0gAbCdEfGhIjKl",
        LMS_TOKEN,
        "gAAAAABlZ0123456789abcdefghij",
        "secret123",
        "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv",
        "AIza" + "B" * 35,
    )
    text = (
        f"Authorization: Bearer {secrets[0]} google={secrets[1]} refresh={secrets[2]}"
        f" lms={secrets[3]} stored={secrets[4]} access_token={secrets[5]} key={secrets[6]}"
        f" gemini={secrets[7]}"
    )
    cleaned = redact(text)
    assert not [secret for secret in secrets if secret in cleaned]
    assert redact("input_tokens=1200, 장학금 3건") == "input_tokens=1200, 장학금 3건"
    # LearningX 토큰은 접두 자릿수와 뒤 길이·글자가 제각각이다(명세 8장 예시는 짧다)
    for token in ("18742~xxxxxxxx", "18742~abc_def-ghi0000", "1234567~" + "a" * 30):
        assert token not in redact(f"lms={token}")
    assert redact("12~short") == "12~short"  # 토큰 모양이 아닌 글자는 그대로 둔다


def test_log_records_are_redacted(caplog: pytest.LogCaptureFixture) -> None:
    install_log_redaction()
    logger = logging.getLogger("unipivot.test")
    with caplog.at_level(logging.INFO, logger="unipivot.test"):
        logger.info("LMS 호출 Authorization: Bearer %s", LMS_TOKEN)
        logger.info(f"세션 토큰 확인 {JWT_LIKE}")
        logger.info(  # uvicorn 접근 로그와 같은 모양
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:5000",
            "GET",
            "/auth/callback?access_token=ya29.zzzzzz",
            "1.1",
            200,
        )
        try:
            raise RuntimeError("refresh failed for 1//0gAbCdEfGhIjKl")
        except RuntimeError:
            logger.exception("Google 토큰 갱신 실패")
    for secret in (LMS_TOKEN, JWT_LIKE, "ya29.zzzzzz", "1//0gAbCdEfGhIjKl"):
        assert secret not in caplog.text
    access = caplog.records[2]
    assert len(access.args) == 5 and access.args[4] == 200  # 인자 개수와 타입은 그대로


def test_api_key_in_request_url_is_redacted(caplog: pytest.LogCaptureFixture) -> None:
    """httpx는 요청 주소를 URL 객체로 넘겨 로그를 남긴다. 주소에 붙은 온통청년 키도 가린다."""
    install_log_redaction()
    key = "youthcenter-key-0123456789"
    url = httpx.URL(f"https://www.youthcenter.go.kr/go/ythip/getPlcy?apiKeyNm={key}&pageNum=1")
    logger = logging.getLogger("unipivot.test")
    with caplog.at_level(logging.INFO, logger="unipivot.test"):
        logger.info('HTTP Request: %s %s "%s %d %s"', "GET", url, "HTTP/1.1", 200, "OK")
    assert key not in caplog.text
    assert "apiKeyNm=[REDACTED]&pageNum=1" in caplog.text
    assert caplog.records[0].args[3] == 200  # 숫자 인자는 그대로
    assert redact("https://x.example/?serviceKey=abc&rows=10") == (
        "https://x.example/?serviceKey=[REDACTED]&rows=10"
    )
    assert redact("x_api_key=abc&n=1") == "x_api_key=[REDACTED]&n=1"
    assert redact("rapikey=abc") == "rapikey=abc"  # 다른 낱말 속의 apikey는 아니다


def test_log_argument_that_cannot_be_stringified_does_not_break_the_caller() -> None:
    """가릴 것을 찾으려고 인자를 문자열로 바꾸다 실패해도 로그를 부른 곳(요청 처리)은 멈추지 않는다."""
    install_log_redaction()

    class Unprintable:
        def __str__(self) -> str:
            raise RuntimeError("문자열로 바꿀 수 없음")

    logger = logging.getLogger("unipivot.test.unprintable")
    logger.setLevel(logging.INFO)  # 레코드를 만든다(가리기는 여기서 돈다)
    logger.propagate = False  # 처리기가 없어 서식은 만들지 않는다
    logger.info("값 %s", Unprintable())
```

### web (바뀌는 파일)

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

// GET /lms/courses
export interface Course {
  id: string;
  canvas_course_id: number;
  name: string;
  short_name: string;
  has_syllabus: boolean;
  portal_syllabus_url: string | null;  // 과목명 꼴이 달라 번호를 못 뽑으면 null
  open_assignments: number;
  new_materials: number;
  next_due: { kind: "assignment" | "syllabus_item"; title: string; due_at: string } | null;
}

// GET /lms/courses/{id}
export type SubmissionState = "unsubmitted" | "submitted" | "graded" | "pending_review";
export type AnnouncementCategory = "schedule_change" | "material" | "opportunity" | "general";
export interface CourseDetail {
  course: { id: string; short_name: string; html_url: string; has_syllabus: boolean; portal_syllabus_url: string | null }; // html_url: 과목 홈 (API v0.3 보완)
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

#### `web/src/mocks/lms.ts`

```ts
import type {
  Course,
  CourseDetail,
  LmsConnection,
  LmsUpdate,
  MaterialDetail,
} from "@/types/api";

export const lmsConnection: LmsConnection = {
  status: "active",
  token_last4: "4821",
  last_synced_at: "2026-10-05T09:30:00+09:00",
  last_error: null,
};

export const courses: Course[] = [
  { id: "linear-algebra", canvas_course_id: 2101, name: "선형대수", short_name: "선형대수", has_syllabus: true, portal_syllabus_url: "https://portal.example.edu/linear", open_assignments: 1, new_materials: 2, next_due: { kind: "syllabus_item", title: "Homework 4", due_at: "2026-10-13T23:59:00+09:00" } },
  { id: "analysis", canvas_course_id: 2102, name: "해석학", short_name: "해석학", has_syllabus: true, portal_syllabus_url: "https://portal.example.edu/analysis", open_assignments: 2, new_materials: 2, next_due: { kind: "assignment", title: "Homework 4", due_at: "2026-10-07T23:59:00+09:00" } },
  { id: "capstone", canvas_course_id: 2103, name: "DS창업캡스톤디자인1", short_name: "DS창업캡스톤디자인1", has_syllabus: true, portal_syllabus_url: "https://portal.example.edu/capstone", open_assignments: 1, new_materials: 2, next_due: { kind: "assignment", title: "창업아이템 정의", due_at: "2026-10-06T23:59:00+09:00" } },
  { id: "database", canvas_course_id: 2104, name: "데이터베이스", short_name: "데이터베이스", has_syllabus: false, portal_syllabus_url: "https://portal.example.edu/database", open_assignments: 2, new_materials: 2, next_due: { kind: "assignment", title: "SQL 실습", due_at: "2026-10-08T23:59:00+09:00" } },
];

function makeCourseDetail(course: Course, index: number): CourseDetail {
  const prefixes = ["기초 개념", "핵심 정리", "응용 문제"];
  return {
    course: {
      id: course.id,
      short_name: course.short_name,
      html_url: `https://lms.example.edu/courses/${course.canvas_course_id}`,
      has_syllabus: course.has_syllabus,
      portal_syllabus_url: course.portal_syllabus_url,
    },
    assignments: prefixes.map((title, assignmentIndex) => ({
      id: `${course.id}-a${assignmentIndex + 1}`,
      title: `${title} 과제`,
      due_at: `2026-10-${String(6 + index * 2 + assignmentIndex * 5).padStart(2, "0")}T23:59:00+09:00`,
      submission_state: assignmentIndex === 2 ? "submitted" : "unsubmitted",
      html_url: `https://lms.example.edu/${course.id}/assignments/${assignmentIndex + 1}`,
    })),
    module_items: [1, 2, 3, 4].map((week) => ({
      id: `${course.id}-m${week}`,
      module_name: `${week + 4}주차`,
      title: `${week + 4}주차 강의자료`,
      html_url: `https://lms.example.edu/${course.id}/modules/${week}`,
      is_new: week >= 3,
      uploaded_file_id: week === 4 ? `${course.id}-material` : null,
    })),
    announcements: [
      { id: `${course.id}-n1`, title: "다음 주 강의실 변경", summary: "다음 주 수업은 제2공학관 301호에서 진행해요.", category: "schedule_change", posted_at: "2026-10-05T08:00:00+09:00", opportunity_id: null },
      { id: `${course.id}-n2`, title: "보충 강의자료 등록", summary: "중간고사 대비 예제 자료를 추가했어요.", category: "material", posted_at: "2026-10-04T16:00:00+09:00", opportunity_id: null },
      { id: `${course.id}-n3`, title: "수업 연계 프로그램 안내", summary: "수강생이 참여할 수 있는 비교과 프로그램을 안내해요.", category: "opportunity", posted_at: "2026-10-03T11:00:00+09:00", opportunity_id: course.id === "database" ? "database-hackathon" : null },
    ],
    syllabus_items: [
      { id: `${course.id}-s1`, item_type: "midterm", title: "중간고사", starts_at: "2026-10-22T10:00:00+09:00", is_confirmed: true },
      { id: `${course.id}-s2`, item_type: "assignment", title: "Homework 4", starts_at: "2026-10-13T23:59:00+09:00", is_confirmed: true },
      { id: `${course.id}-s3`, item_type: "presentation", title: "팀 발표", starts_at: "2026-11-12T14:00:00+09:00", is_confirmed: false },
    ],
    materials: [{ file_id: `${course.id}-material`, original_name: `${course.short_name}_8주차.pdf`, status: "succeeded" }],
  };
}

export const courseDetails: Record<string, CourseDetail> = Object.fromEntries(
  courses.map((course, index) => [course.id, makeCourseDetail(course, index)]),
);

function makeMaterial(course: Course): MaterialDetail {
  const overLimit = course.id === "database";
  return {
    file_id: `${course.id}-material`,
    original_name: `${course.short_name}_8주차.pdf`,
    total_pages: overLimit ? 84 : 42,
    page_start: 1,
    page_end: 42,
    over_limit: overLimit,
    overall_summary: `${course.short_name} 8주차 핵심 개념과 예제를 정리한 자료예요.`,
    status: "succeeded",
    sections: [1, 2, 3, 4, 5].map((seq) => ({
      id: `${course.id}-section-${seq}`,
      seq,
      title: `${seq}부 핵심 개념`,
      page_start: (seq - 1) * 8 + 1,
      page_end: seq === 5 ? 42 : seq * 8,
      summary: `${seq}부의 정의와 주요 예제를 요약했어요.`,
      translation_status: seq === 1 ? "succeeded" : null,
      translation_url: seq === 1 ? `https://example.edu/materials/${course.id}/translation/1` : null,
    })),
  };
}

export const materials: Record<string, MaterialDetail> = Object.fromEntries(
  courses.map((course) => [`${course.id}-material`, makeMaterial(course)]),
);

export const lmsUpdates: LmsUpdate[] = [
  { type: "module_item", id: "analysis-m4", course: { id: "analysis", short_name: "해석학" }, module_name: "8주차", title: "Decision Trees", html_url: "https://lms.example.edu/analysis/modules/4", first_seen_at: "2026-10-05T09:20:00+09:00", uploaded_file_id: "analysis-material" },
  { type: "assignment", id: "capstone-a1", course: { id: "capstone", short_name: "DS창업캡스톤디자인1" }, title: "창업아이템 정의", due_at: "2026-10-06T23:59:00+09:00", submission_state: "unsubmitted" },
  { type: "announcement", id: "database-n1", course: { id: "database", short_name: "데이터베이스" }, title: "다음 주 강의실 변경", summary: "제2공학관 301호에서 수업해요.", posted_at: "2026-10-05T08:00:00+09:00", category: "schedule_change", attachment_count: 0, opportunity_id: null, planner_task_id: "task-db-notice" },
];
```

#### `web/src/components/CourseSyllabus.tsx`

```tsx
import { useState } from "react";
import Button from "@/components/Button";
import { formatKstLongDate } from "@/lib/format";
import type { CourseDetail } from "@/types/api";

interface CourseSyllabusProps {
  course: CourseDetail;
}

const itemLabels = {
  midterm: "중간",
  final: "기말",
  presentation: "발표",
  assignment: "과제",
  etc: "기타",
};

export default function CourseSyllabus({ course }: CourseSyllabusProps) {
  const [uploaded, setUploaded] = useState(false);
  const [toast, setToast] = useState(false);
  const [dates, setDates] = useState<Record<string, string>>(
    Object.fromEntries(
      course.syllabus_items.map((item) => [
        item.id,
        item.starts_at?.slice(0, 10) ?? "",
      ]),
    ),
  );
  const visibleItems = course.course.has_syllabus
    ? course.syllabus_items.filter((item) => item.is_confirmed)
    : course.syllabus_items;

  const schedule = (
    <div className="flex flex-col gap-3">
      {visibleItems.map((item) => (
        <article
          key={item.id}
          className="flex items-center justify-between gap-4 rounded-[12px] bg-[#f7f8fa] p-4"
        >
          <div>
            <p className="text-[12px] font-semibold text-[#4f6ef7]">
              {itemLabels[item.item_type]}
            </p>
            <p className="mt-1 text-[14px] font-semibold">{item.title}</p>
          </div>
          {uploaded ? (
            <input
              type="date"
              value={dates[item.id]}
              onChange={(event) =>
                setDates((current) => ({
                  ...current,
                  [item.id]: event.target.value,
                }))
              }
              className="rounded-[8px] border border-[#e5e7eb] px-2 py-1 text-[12px]"
            />
          ) : (
            <span className="text-[12px] text-[#667085]">
              {item.starts_at
                ? formatKstLongDate(item.starts_at)
                : "일정 미정"}
            </span>
          )}
        </article>
      ))}
    </div>
  );

  if (course.course.has_syllabus) return schedule;

  return (
    <>
      {!uploaded ? (
        <section className="rounded-[14px] border border-dashed border-[#e5e7eb] p-8 text-center">
          <p className="text-[16px] font-semibold">강의계획서를 직접 올려 주세요</p>
          <p className="mt-2 text-[13px] text-[#667085]">
            포털에서 강의계획서 열기 후 PDF로 저장해 올려 주세요
          </p>
          <div className="mt-5 flex justify-center gap-2">
            {/* 과목명에서 과목 번호를 못 뽑으면 포털 링크가 없다(계절·비정규 과목) */}
            {course.course.portal_syllabus_url && (
              <a
                href={course.course.portal_syllabus_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-[42px] items-center rounded-[10px] border border-[#e5e7eb] px-[18px] text-[14px] font-semibold"
              >
                포털에서 강의계획서 열기
              </a>
            )}
            <label className="inline-flex h-[42px] cursor-pointer items-center rounded-[10px] bg-[#4f6ef7] px-[18px] text-[14px] font-semibold text-white">
              PDF 올리기
              <input
                type="file"
                accept=".pdf"
                className="hidden"
                onChange={(event) =>
                  event.target.files?.[0] && setUploaded(true)
                }
              />
            </label>
          </div>
        </section>
      ) : (
        <>
          <p className="mb-4 text-[13px] text-[#667085]">
            추출된 일정을 확인하고 날짜를 수정해 주세요.
          </p>
          {schedule}
          <div className="mt-4 flex justify-end">
            <Button
              onClick={() => {
                setToast(true);
                setTimeout(() => setToast(false), 2200);
              }}
            >
              확인하고 플래너에 넣기
            </Button>
          </div>
        </>
      )}
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white">
          계획서 일정을 플래너에 넣었어요
        </div>
      )}
    </>
  );
}
```
