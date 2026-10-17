# LMS 과제·제출 동기화 — 30분마다 + 대시보드 접속 시, 새 과제는 할 일과 알림으로

> 📝 기준: PRD v0.9 F-51 · API 명세 v0.4 9장(LMS)·10장(알림)·11장(실행)·12장(배치) · ERD v0.9 LMS·플래너·알림 · 2026-10-17
>
> 먼저 합친 것: `LMS토큰연결_구현.md`(F-50, main 2c12e00) · `지표집계_구현.md`(main 63a0bd4)

F-50은 토큰을 받아 과목 목록까지 저장했다. 이 PR은 그 다음 — **과제와 제출 여부를 받아 플래너 할 일과 알림까지 잇는다**. 10/16 녹화(6과목·과제 17건)를 테스트 샘플로 옮겨서, 실제 LearningX에 접속하지 않고도 녹화한 모양 그대로 돌려 본다.

- `POST /lms/sync` — 대시보드를 열 때 부른다. 202 + `run_id`, 결과는 `GET /runs/{run_id}`
- `GET /lms/assignments` — 과제 목록(`?state=open|submitted|all&lms_course_id=`)
- `POST /internal/jobs/lms-sync` — 30분마다 도는 배치(서비스 키)

이걸로 학업 화면이 쓸 실제 자료가 생긴다. 시나리오 S16(새 과제 → 1건 등록 + 알림)·S17(마감 변경 → 기존 일정 수정)의 **플래너·알림 쪽**이 돌고, 캘린더 쪽은 따로 정한다(아래 "남은 것" 첫 줄).

## 정한 것

1. **마감은 `due_at ?? lock_at`.** 녹화 17건 중 5건은 `due_at`이 null이고 `lock_at`만 있었다. 둘 다 없는 과제는 마감 없이 저장하고 할 일을 만들지 않는다(`planner_tasks.due_date`가 not null이다).
2. **제출은 `submission.workflow_state`로만 본다.** 과목 전체 기준인 `has_submitted_submissions`는 내가 내지 않은 과제에도 true로 온다. `pending_review`(냈고 손 채점만 남음)도 제출로 센다 — 제출로 보지 않으면 할 일이 끝나지 않고 알림도 멈추지 않는다.
3. **이미 낸 과제로는 할 일도 알림도 만들지 않는다.** 연결하고 처음 받을 때 지난 학기 과제까지 한꺼번에 들어온다(녹화 17건 중 13건이 제출·채점 완료였다). 그때 "새 과제가 올라왔어요" 알림이 13개 쏟아지면 안 된다. `assignments.new` 수에는 센다(처음 저장한 과제라는 뜻이다).
4. **과목 하나의 과제 목록만 실패하면 그 과목만 두고 넘어간다.** 부분 목록으로 저장하면 못 받은 과제가 "사라진 과제"가 된다. 단 **한 과목도 받지 못하면 동기화 전체를 502로 끝낸다** — 성공으로 적으면 오류 표시가 지워지고 학생은 받았다고 믿는다. 401(토큰이 막힘)은 거기서 멈추고 연결을 `error`로 바꾼다.
5. **`last_synced_at`은 동기화를 시작할 때 찍는다**(한 문장 `claim_sync`). 두 가지를 같이 막는다 — 대시보드를 두 탭에서 열 때 같은 사용자를 동시에 두 번 동기화하는 것, 그리고 늘 실패하는 사용자가 30분 배치의 앞자리를 영구히 차지하는 것. 잘 받았는지는 `status`·`last_error`로 본다.
6. **마감이 바뀌면 기존 할 일의 날짜만 고친다.** 새로 만들지 않는다(PRD F-51 "마감 변경 시 기존 일정 수정"). 학생이 지운 할 일을 마감이 바뀔 때마다 되살리면 지울 방법이 없다. 예외는 **마감이 없다가 생긴 과제** — 그때는 할 일이 있을 수 없으니 새로 만든다.
7. **과제가 0건으로 와도 믿는다.** 과목 목록과 반대다. 녹화 6과목 중 2과목이 과제 0건이었고, 클라이언트는 끝까지 받지 못하면 예외라서 빈 목록은 "정말 없다"는 뜻이다.
8. **동기화 결과는 `save_lms_sync` 도구의 출력에서 다시 읽는다.** 수(새 과제·마감 변경·제출)는 그 실행만의 사실이라 과제 표에서 다시 셀 수 없다(어느 실행이 넣었는지 적지 않는다). 포스터 추출이 초안을 도구 출력에서 읽는 것과 같은 방식이다.
9. **캘린더에는 아직 쓰지 않는다.** 사용자 구글 캘린더에 실제로 일정을 만드는 일이라, 30분 배치가 자동으로 하기 전에 네가 정할 문제다. `GET /lms/assignments`의 `calendar_registered`는 이미 등록된 일정이 있으면 true로 내려간다.
10. **새 알림은 찾은 때 바로 보낸다.** 공고 알림처럼 KST 09:00을 기다리지 않는다(마감이 코앞일 수 있다). 명세 10장 예시의 `new_material`도 그 시각이다. 설정에서 끈 종류는 만들지 않고, 같은 과제는 `dedupe_key`로 한 번만 만든다(`new_assignment:asg:{id}`, ERD 5장 표).

## 레포에 넣는 법

아래 text 블록을 Claude Code에 그대로 붙여 넣어. 코드는 이 문서의 "코드" 절에서 가져간다.

````text
새 브랜치 feat/F-51-lms-sync를 main에서 따고, docs/LMS과제동기화_구현.md(방금 받은 파일)를 docs/에 넣은 뒤 아래를 해 줘.

[1] 문서 맨 아래 "코드" 절의 파일 19개를 그대로 만들거나 덮어써 줘. `#### `경로`` 아래 코드 블록이 그 파일의 전체 내용이다. 줄 하나 고치지 말고 그대로 옮겨.
    새 파일: api/app/lms/assignments.py · api/app/lms/sync.py · api/tests/test_lms_assignments.py · api/tests/test_lms_sync.py
    바뀌는 파일: api/app/lms/parse.py · api/app/lms/service.py · api/app/repositories/lms.py · api/app/repositories/notifications.py · api/app/repositories/runs.py · api/app/routers/lms.py · api/app/routers/internal.py · api/app/routers/runs.py · api/app/schemas/lms.py · api/app/schemas/prepare.py · api/tests/lms_samples.py · api/tests/test_lms_db.py · api/tests/fakes.py · api/tests/prepare_fakes.py · web/src/types/lms.ts

[2] "문서에 반영하기" 절의 블록대로 기준 문서를 고쳐 줘(API 명세 6곳 · ERD 2곳 · PRD 2곳). 거기 적힌 "찾을 줄"은 파일에 한 번만 나온다.

[3] DB 변경은 없다. 마이그레이션 파일을 만들지 말고 `npx supabase db push`도 하지 마.

[4] 검사:
    api> uv run ruff check . && uv run ruff format --check . && uv run pytest
    web> npm run typecheck && npm run build
    로컬은 DATABASE_URL이 없어서 DB 테스트를 건너뛴다(`812 passed, 215 skipped`가 나오면 맞다). CI에서는 `1027 passed`다.

[5] 통과하면 "feat(F-51): LMS 과제·제출 동기화와 과제 목록" 커밋으로 PR을 올려 줘. 본문에는 새 엔드포인트 세 개(POST /lms/sync · GET /lms/assignments · POST /internal/jobs/lms-sync)와 "DB 변경 없음"을 적어 줘.
````


## 합친 뒤 확인

```bash
# 1) 연결은 F-50에서 이미 했다고 보고, 동기화를 눌러 본다
curl -X POST localhost:8000/api/v1/lms/sync -H "Authorization: Bearer $TOKEN"
# → 202 {"run_id":"...","status":"running"}   (5분 안에 또 부르면 200 {"skipped":true,...})

# 2) 결과 보기
curl localhost:8000/api/v1/runs/<run_id> -H "Authorization: Bearer $TOKEN"
# → steps에 "수강 과목 받기 · 과제·제출 받기 · 바뀐 것 저장",
#   result에 {"kind":"lms_sync","courses":N,"assignments":{"new":..,"due_changed":..,"submitted":..}}

# 3) 과제 목록
curl "localhost:8000/api/v1/lms/assignments?state=open" -H "Authorization: Bearer $TOKEN"
curl "localhost:8000/api/v1/lms/assignments?state=all&lms_course_id=<uuid>" -H "Authorization: Bearer $TOKEN"

# 4) 플래너에 할 일이 생겼는지(마감 있는 미제출 과제만)
curl "localhost:8000/api/v1/planner?from=2026-10-01&to=2026-12-31" -H "Authorization: Bearer $TOKEN"

# 5) 알림함에 "새 과제가 올라왔어요"가 있는지
curl localhost:8000/api/v1/notifications -H "Authorization: Bearer $TOKEN"

# 6) 30분 배치(서비스 키)
curl -X POST localhost:8000/api/v1/internal/jobs/lms-sync -H "X-Internal-Key: $INTERNAL_API_KEY"
# → {"users":N,"synced":N,"failed":0,"skipped":0,"new_assignments":..,"due_changed":..,"submitted":..}
```

실제 LearningX에 붙이려면 `.env`의 `LMS_API_BASE`가 학교 주소여야 한다(F-50에서 넣었다). DB 변경은 없다 — 쓰는 표·칸이 모두 `supabase/migrations`에 이미 있다(`lms_assignments`, `planner_tasks.source = 'lms_assignment'`, `notifications.type = 'new_assignment'`, `notifications.dedupe_key`). **`npx supabase db push`는 필요 없다.**

## 구조

```text
api/app/lms/
  assignments.py   Canvas 과제 응답 → 저장할 값 (마감 due_at ?? lock_at, 제출 상태, 안 열린 과제 건너뛰기)
  sync.py          동기화 흐름: 과목 → 과목마다 과제 → 한 트랜잭션에 저장 → 플래너·알림
api/app/repositories/lms.py            과제 upsert·사라진 과제·목록·플래너 맞추기·claim
api/app/repositories/notifications.py  새 과제 알림 만들기·제출하면 멈추기
api/app/repositories/runs.py           동기화 결과를 도구 출력에서 다시 읽기, 단계 한글 이름
api/app/routers/lms.py                 POST /lms/sync, GET /lms/assignments
api/app/routers/internal.py            POST /internal/jobs/lms-sync (30분)
api/tests/lms_samples.py               녹화한 과제 응답(값은 바꿨다)
```

동기화 한 번에 일어나는 일:

```text
POST /lms/sync  (또는 30분 배치)
  ├ repo.claim_sync        "내가 한다"를 한 문장으로 못 박는다(5분 안이면 여기서 200)
  └ agent_run(lms_sync)
      ├ run.tool(fetch_lms_courses)      → GET /api/v1/courses               (401: 422 · 그 밖: 502)
      ├ repo.save_courses + active_courses
      ├ run.tool(fetch_lms_assignments)  → GET /courses/{id}/assignments     (과목마다, 401이면 멈춤)
      │                                     한 과목 실패 → 그 과목만 빼고 계속 / 전부 실패 → 502
      └ run.tool(save_lms_sync)          한 트랜잭션:
          ├ repo.save_assignments   upsert + 이번 목록에 없던 과제 removed_at
          ├ repo.sync_planner       새 과제 → 할 일 / 마감 변경 → 날짜 고치기 / 제출 → 완료
          ├ notes.drop_assignment_notices  제출한 과제의 아직 안 보낸 알림 지우기
          ├ notes.add_assignment_notices   새 과제 알림(이미 낸 과제·끈 종류는 제외)
          └ repo.touch_synced       잘 받았다고 적기(오류 표시 지우기, 시계는 뒤로 안 돌림)
```

## 확인한 것

| 확인 | 결과 |
| --- | --- |
| api 테스트 | DB 없이 `812 passed, 215 skipped`, DB를 붙이면 `1027 passed`. 새 테스트 92개(과제 읽기 13 · 동기화·목록·배치 34 · DB 45) |
| 과제 읽기(녹화 모양) | 마감 `due_at ?? lock_at`(둘 다 없으면 null) · `submitted_at` 보존 · 퀴즈는 `graded`로 와도 제출 · `pending_review`도 제출 · 과목 전체 기준 `has_submitted_submissions` 무시 · 안 열린 과제(`published: false`) 건너뛰기 · 모르는 제출 상태는 `unsubmitted` · `submission`이 없어도 동작 · bool·bigint 넘는 번호·과제 아닌 값 거르기 · 이름 없는 과제는 `(제목 없음)`으로 남김 · 깨진 시각은 비워 두기 |
| 동기화(respx로 가로채기) | 202 + `run_id` · 열린 과제만 저장 · 외부 호출이 모두 도구로 남고 **토큰은 입력·출력에 없음** · 결과가 `save_lms_sync` 출력에 들어감 · `GET /runs/{id}`가 그 결과를 보여 줌 · 새 과제 → 할 일 + 알림(마감 KST 표기) · 마감 없는 과제도 알림 · **이미 낸 과제는 알림 없음** · 제출 → 안 보낸 알림 지움 · 5분 안이면 건너뜀(200) · **두 번째 호출은 LearningX를 부르지 않음** · 5분 뒤에는 다시 받음 · 연결 없으면 404 · 401이면 연결 `error` · 503은 연결을 건드리지 않음 · 한 과목 403이면 그 과목만 빠짐 · **전 과목 실패는 성공으로 적지 않음** · 실패한 실행을 닫음 · 복호화 실패는 학생을 탓하지 않음 · 과제 0건 과목 정상 · 토큰은 헤더로만 |
| 과제 목록 | 기본 `open` · 필터 그대로 전달 · 모르는 `state`·uuid 아닌 과목 id는 422 · 마감 가까운 순(마감 없는 과제는 뒤) · 과목 필터 · KST 표기 · 할 일·캘린더 링크 · 로그인 필요 |
| 30분 배치 | 연결된 사람 모두 동기화 · **앞사람이 실패해도 뒷사람은 받음** · 그새 대시보드가 시작한 사람은 `skipped` · 서비스 키 없으면/틀리면 403 |
| DB(실제 스키마) | 과제 upsert·제목 갱신·`first_seen_at` 유지 · 같은 목록 두 번은 변화 없음 · 마감 변경·제출을 한 번만 보고함 · `submitted → graded`는 새 제출이 아님 · 사라진 과제 `removed_at`(빈 목록에서도, 두 번 찍지 않음) · 되돌아온 과제는 새 과제 · 수강 뺀 과목의 과제는 목록에서 빠짐 · `pending_review`는 제출 쪽 · 남의 과제·할 일·캘린더·끈 설정과 섞이지 않음 · 할 일: 미제출·마감 있는 과제만, 마감 옮기면 날짜만, 끝낸 할 일은 그대로, 지운 할 일은 안 되살림, 제출하면 자동 완료(완료 시각 한 번만) · 알림: 한 번만·끈 종류 제외·보낸 알림은 남김 · claim은 5분 창 안에서 한 번만, 해제한 연결은 안 가져감, 오류 문구를 지우지 않음 · `touch_synced`는 시계를 뒤로 돌리지 않고 해제한 연결을 되살리지 않음 · 실패한 사람이 배치 앞자리를 막지 않음 · 실행 결과 읽기(연결 실행은 결과 없음, 깨진 출력은 null, 남의 실행은 null, 단계 한글 이름) |
| 빌드·검사 | api `ruff check`·`ruff format --check` 통과(195 파일). web `npm run typecheck`·`npm run build` 통과. 실제 LearningX에는 접속하지 않았다(모든 테스트는 respx로 가로챈 녹화 응답이다) |

### 검토에서 고친 것 — 동기화 흐름·보안

| 지적 | 고친 것 |
| --- | --- |
| **실패한 동기화가 실행을 `running`으로 남긴다**(로그 연결을 못 얻으면 `agent_run` 밖에서 끝난다). `GET /runs/{id}`가 끝나지 않고 성공률 지표의 분모만 늘어난다 | 준비하기처럼 `except`에서 실행을 닫는다(`abandon_run`). 그 테스트를 더했다 |
| **늘 실패하는 사용자가 30분 배치의 앞자리를 영구히 차지한다**(실패하면 `last_synced_at`이 안 밀려서 매번 맨 앞). 그런 사용자가 50명을 넘으면 멀쩡한 사용자는 영원히 동기화되지 않는다 | `last_synced_at`을 **시작할 때** 찍는다(`claim_sync`). 실패해도 밀린다. 그 테스트를 더했다 |
| **같은 사용자를 동시에 두 번 동기화할 수 있다**(대시보드 두 탭, 또는 배치와 겹침). LearningX 호출이 두 배가 되고 같은 과제가 양쪽에서 "새 과제"로 센다 | 같은 `claim_sync` 한 문장이 자리를 잡는다. 둘째 호출은 200으로 건너뛴다 |
| **한 과목도 받지 못했는데 성공으로 적는다.** 학교가 과제 경로를 닫으면(403) 오류 표시가 지워지고 학생은 받았다고 믿는다 | 과목이 있는데 전부 실패하면 502로 끝낸다(`touch_synced`를 부르지 않는다). 그 테스트를 더했다 |
| **복호화 실패를 "토큰이 만료됐어요"로 적는다.** 암호화 키를 교체하다 옛 키를 먼저 지우면 **모든 사용자**에게 멀쩡한 토큰을 다시 받으라고 한다 | 저장한 토큰을 못 읽은 경우를 따로 둔다(`StoredTokenUnreadable`). 연결 상태를 바꾸지 않고, 배치는 그 사람만 건너뛴다 |
| 실패한 동기화가 준비하기 문구("준비 일정을 만들지 못했어요")로 나간다 | 작업별 문구 표를 뒀다(동기화는 "LMS 자료를 가져오지 못했어요") |
| 복호화한 토큰이 `SyncJob`의 기본 `repr`에 찍힌다(아직 찍는 곳은 없지만 `logger.debug` 한 줄이면 샌다) | `field(repr=False)`로 뺐다(`Connection.access_token`과 같다). 그 테스트를 더했다 |
| OpenAPI에 202만 적혀 있어서 생성 클라이언트가 200(건너뜀)을 못 본다 | `responses={200: SyncSkipped}`를 적었다 |
| "토큰은 헤더로만" 테스트가 호출이 0건이어도 통과한다(빈 루프) | 호출이 있었는지 먼저 본다 |
| 배치 테스트가 둘 다 실패하게 만들어서 "뒷사람은 받는다"를 보여 주지 못한다 | 첫 호출만 401로 막아 앞사람만 실패시킨다. 가짜 저장소도 사용자별 연결을 갖게 고쳤다 |
| `is_canvas_id`를 새로 만들었는데 `service.py`에 같은 함수가 그대로 남아 있다 | 하나로 합쳤다(`parse.py`) |
| LMS는 명세 **9장**인데 새 코드 주석이 8장(강의계획서)이라고 적혀 있다(F-50에서 잘못 쓴 것이 번졌다) | 이 PR이 건드리는 파일에서 모두 9장으로 고쳤다. PRD 5-6절의 같은 오타도 고친다 |

### 검토에서 고친 것 — SQL·DB

| 지적 | 고친 것 |
| --- | --- |
| **처음 본 과제가 이미 제출 상태여도 "새 과제"로 다룬다.** 연결 첫 동기화에 지난 과제가 한꺼번에 들어오면(녹화 17건 중 13건) 끝난 일에 대한 열린 할 일 13개와 "새 과제" 알림 13개가 생긴다 | 할 일은 SQL에서 `submission_state = 'unsubmitted'`인 과제만 만들고, 알림도 낸 과제는 건너뛴다. 그 테스트를 더했다 |
| **`dedupe_key`가 ERD 표와 다르다**(`new_assignment:lms_assignment:{id}` vs 표의 `new_assignment:asg:{id}`). 다음에 붙일 과제 마감 임박 알림과 키 꼴이 갈린다 | ERD 표 그대로 `asg:`로 바꿨다 |
| **`touch_synced`가 시계를 뒤로 돌린다.** 느린 동기화가 뒤에 시작한 동기화의 자리를 지우고, 그 사이 찍힌 오류 표시까지 지운다. 해제한 연결도 되살린다 | 시각이 앞으로만 가게 하고 `status <> 'disconnected'` 조건을 걸었다. 두 테스트를 더했다 |
| **수강을 뺀 과목의 과제가 목록에 영원히 남는다.** 더 받지 않으니 "사라진 과제" 표시도 안 붙고, 학생이 지울 방법이 없다 | 목록에서 `is_active` 조건으로 뺀다. 그 테스트를 더했다 |
| **`pending_review`가 `open`에도 `submitted`에도 안 들어간다.** 할 일이 끝나지 않고 알림도 멈추지 않는다 | 제출로 센다(`submitted` 필터는 `<> 'unsubmitted'`). 명세 9장·ERD에도 적었다 |
| 새 SQL의 `user_id` 조건 세 개(목록의 할 일·캘린더, 알림의 끈 설정)를 지워도 테스트가 통과한다 | 남의 할 일·캘린더 행이 내 목록에 붙지 않는지, 남이 끈 설정으로 내 알림이 사라지지 않는지 보는 테스트를 더했다 |
| `first_seen_at` 유지와 "사라진 과제를 두 번 찍지 않음"이 테스트에 걸리지 않는다 | 둘 다 테스트를 더했다 |
| 마감 옮기기 SQL이 과제 행을 주인 확인 없이 읽는다 | `a.user_id = t.user_id`를 걸었다(쓰기는 원래 내 할 일만 바꿨다) |
| 알림함의 "과제 → 과목" 잇기에 `user_id` 조건이 없다(이 PR이 그 분기를 처음 쓰게 만든다) | 조건을 걸었다 |
| 알림 종류를 f-string으로 SQL에 끼워 넣는다(api/CLAUDE.md: 값은 파라미터로) | 파라미터로 넘긴다 |

### 되돌림 시험 28가지

마감을 `due_at`만 보기 · 안 열린 과제 저장 · 모르는 제출 상태 그대로 쓰기 · `pending_review`를 제출로 안 보기 · 되돌아온 과제를 새 과제로 안 보기 · 마감 null→값을 못 가리기 · 사라진 과제를 매번 다시 찍기 · `first_seen_at` 밀어 쓰기 · 이미 낸 과제로 할 일 만들기 · 이미 낸 과제에 알림 보내기 · 남의 할 일 보기 · 남의 캘린더 행을 등록됐다고 보기 · 등록 안 끝난 캘린더 행을 등록됐다고 보기 · 수강 뺀 과목 과제 보여 주기 · 제출 필터에서 `pending_review` 빼기 · claim이 5분 창 무시 · 끝낼 때 시계 뒤로 돌리기 · 해제한 연결 되살리기 · 끈 종류도 알림 만들기 · 남이 끈 설정으로 내 알림 막기 · 보낸 알림까지 지우기 · 전 과목 실패를 성공으로 적기 · 실패한 실행 안 닫기 · 401 아닌 과목 오류로 전체 멈추기 · 복호화 실패를 토큰 만료로 적기 · 끝낸 할 일의 완료 시각 다시 찍기 · 실패 문구를 다른 작업 것으로 쓰기 → **27가지 모두 잡혔다.**

스물여덟 번째 하나는 못 잡는다: 마감 옮기기 SQL의 `a.user_id = t.user_id`를 지워도 테스트가 통과한다. 과제 id가 uuid라 남의 과제 id를 내 할 일이 가리키는 상황을 만들 수 없기 때문이다(쓰기는 `t.user_id`로 이미 묶여 있다). 규칙(api/CLAUDE.md "SQL에는 항상 `user_id` 조건")을 지키는 조건이라 남겨 뒀다.

되돌림 시험 중에 하나를 고치기도 했다. 할 일 만들기에서 "이미 낸 과제 제외"를 파이썬과 SQL 두 곳에서 걸었더니 **한 곳을 지워도 테스트가 통과했다**(다른 곳이 막아 준다). 거르는 조건을 SQL 한 곳에만 두고 파이썬 쪽을 지웠다.

## 남은 것

- **마감 캘린더 등록(S16·S17의 캘린더 쪽)이 비어 있다.** PRD F-51은 "새 과제는 캘린더·플래너 등록"이지만, 30분 배치가 사용자 구글 캘린더에 자동으로 일정을 만드는 일이라 이 PR에서는 하지 않았다. 지금 캘린더 코드(F-32)는 공고 마감만 넣을 수 있고 `events.patch`(마감 변경 시 수정)도 없다. 다음 PR 후보 세 가지:
  1. **자동 등록**: 동기화가 새 과제의 마감을 바로 캘린더에 넣는다(구글 연결이 있을 때만). S16·S17이 그대로 통과한다. 대신 학생 캘린더에 우리가 임의로 일정을 만든다.
  2. **학생이 켠 과목만**: 설정에 `calendar_auto_lms`가 이미 있다(web 타입). 켠 사람만 자동 등록한다.
  3. **버튼으로만**: 과제 목록의 "캘린더에 넣기"를 누를 때만 등록한다. 가장 안전하지만 S16의 "다음 동기화 때 등록"은 못 만족한다.
- **`GET /lms/courses/{id}`(과목 상세)와 `GET /lms/updates`는 아직 없다**(F-52·F-53). 과제 탭은 `GET /lms/assignments?lms_course_id=`로 채울 수 있다.
- **주차 항목·공지 동기화가 비어 있다**(F-52·F-53). 그래서 동기화 결과의 `new_module_items`·`new_announcements`는 늘 0이고, `GET /lms/courses`의 `new_materials`도 0이다. 녹화 샘플은 `out2` 폴더에 그대로 있다 — **지우지 마.**
- **web 학업 화면은 아직 목이다.** 이 PR은 타입만 맞췄다(`web/src/types/lms.ts`). 화면을 붙이는 PR에서 `lmsClient.ts`의 목을 `POST /lms/sync`·`GET /lms/assignments`로 바꾼다.
- **수강을 뺀 과목의 플래너 할 일은 남는다.** 목록에서는 뺐지만 할 일은 학생이 직접 지워야 한다. 자동으로 지우면 학생이 적어 둔 메모까지 사라진다.
- **배치가 요청 안에서 끝까지 돈다.** 50명 × 과목 6개 × 20초면 최악의 경우 매우 오래 걸린다. 지금은 사람이 부르는 단계라 두었다(명세 14장의 워커 큐 결정이 아직 열려 있다). 스케줄러를 붙일 때 202 + `run_id`로 바꾼다.
- **배치가 시각 하나로 돈다.** 50명을 도는 동안 `now`가 고정이라, 뒤쪽 사람의 `last_synced_at`이 배치 시작 시각으로 찍힌다. 30분 주기에서는 문제가 없지만 사람 수가 늘면 사람마다 시각을 다시 읽어야 한다.
- **429·5xx 재시도가 없다**(F-50에서 적은 것과 같다). 지금은 다음 30분 배치가 다시 받는다.
- **`POST /lms/sync`에 호출 제한이 없다.** 5분 창이 사실상 제한 역할을 하지만(한 사용자당), 앱 전체 호출 제한은 여전히 없다.

## 문서에 반영하기

이 PR이 정한 규칙을 기준 문서에 적는다. 새 엔드포인트는 명세에 이미 있고(9장·12장), **설명이 비어 있던 자리를 채우는 수정**이다. DB 변경은 없다(표·칸 그대로).

````text
문서 세 개를 고쳐 줘. 같은 브랜치에서 해. 아래 "찾을 줄"은 각 파일에 한 번만 나온다.

[1] docs/API_명세_v0.4.md — 9장 클라이언트 규칙의 제출 여부
찾을 줄:
  - 제출 여부는 `submission.workflow_state`가 `submitted`·`graded`인지로 본다. **`has_submitted_submissions`는 과목 전체 기준**이라 내가 안 낸 과제에도 true다(쓰지 않는다). 퀴즈는 자동 채점돼 바로 `graded`로 온다
이 줄을 아래 줄로 바꿔:
  - 제출 여부는 `submission.workflow_state`가 `submitted`·`graded`·`pending_review`인지로 본다. **`has_submitted_submissions`는 과목 전체 기준**이라 내가 안 낸 과제에도 true다(쓰지 않는다). 퀴즈는 자동 채점돼 바로 `graded`로 온다. `pending_review`는 녹화에서 못 봤지만 "냈고 손 채점만 남은" 상태라 제출로 센다 — 제출로 보지 않으면 할 일이 끝나지 않고 알림도 멈추지 않는다. 모르는 값이 오면 `unsubmitted`로 둔다(DB enum에 없는 값은 저장할 수 없다)

[2] docs/API_명세_v0.4.md — 9장 `POST /lms/sync` 머리말
찾을 줄:
대시보드 접속 시 프론트가 호출한다.
이 줄을 아래 줄로 바꿔:
대시보드 접속 시 프론트가 호출한다. 연결이 없으면 `404 LMS_NOT_CONNECTED`다.

[3] docs/API_명세_v0.4.md — 9장 `POST /lms/sync`의 응답 코드 블록 **뒤**
찾을 곳(세 줄이 이어진 자리다. 가운데 줄은 코드 블록을 닫는 ``` 세 글자다):
{ "skipped": true, "last_synced_at": "2026-10-01T10:30:00+09:00" }
```
(빈 줄)
완료 시 `result`:
→ 코드 블록을 닫는 ``` 와 "완료 시 `result`:" 사이에 아래 네 줄(끝의 빈 줄 포함)을 넣어:

- `last_synced_at`은 마지막으로 동기화를 **시작한** 시각이다. 시작할 때 한 문장으로 찍어 두기 때문에, 대시보드를 두 탭에서 열어도 한 번만 받고(둘째는 200), 늘 실패하는 사용자가 30분 배치의 앞자리를 영구히 차지하지도 않는다. 잘 받았는지는 `status`·`last_error`로 본다
- 과목 목록을 읽지 못하면 실행이 `502 LMS_API_ERROR`로 끝난다(토큰이 막힌 경우는 `422 LMS_TOKEN_INVALID`이고 연결 상태가 `error`가 된다). **과목 하나의 과제 목록만 실패하면 그 과목은 두고 나머지를 저장한다** — 부분 목록으로 저장하면 못 받은 과제가 "사라진 과제"가 된다. 한 과목도 받지 못하면 동기화 전체가 502다
- 202는 "시작했다"는 뜻이다. 결과와 실패 이유는 `GET /runs/{run_id}`로 본다

[4] docs/API_명세_v0.4.md — 9장 `POST /lms/sync`의 완료 결과 코드 블록 **뒤**
찾을 줄(그 코드 블록 다음에 오는 소제목이다):
### `GET /lms/courses`
이 소제목 **앞에** 아래 다섯 줄(끝의 빈 줄 포함)을 넣어:

- `courses`는 이번에 과제까지 받은 과목 수다. `new`는 처음 저장한 과제, `due_changed`는 마감이 바뀐 과제, `submitted`는 이번에 제출로 바뀐 과제 수다
- **처음 저장한 과제가 이미 제출된 상태면 할 일도 알림도 만들지 않는다**(`new`에는 센다). 연결하고 처음 받을 때 지난 학기 과제까지 한꺼번에 들어오기 때문이다(녹화 17건 중 13건이 제출·채점 완료였다)
- 새 과제는 플래너 할 일이 되고 `new_assignment` 알림이 생긴다(마감이 있는 미제출 과제만). 마감이 바뀌면 아직 끝내지 않은 할 일의 날짜만 고친다. 제출하면 할 일이 자동 완료되고 아직 보내지 않은 알림은 지워진다(10장)
- 마감 날짜를 캘린더에 넣는 일은 이 동기화에서 하지 않는다(사용자 캘린더에 쓰는 일이라 따로 정한다). `new_module_items`·`new_announcements`는 F-52·F-53이 채운다

[5] docs/API_명세_v0.4.md — 9장 `GET /lms/connection` 설명
찾을 줄의 끝에 한 문장을 덧붙인다. 찾을 줄:
`status`는 DB에 있는 값을 그대로 준다(`active` · `error` · `disconnected`, `GET /me`의 `lms.status`와 같은 세 가지). `status = error`이면 `last_error`에 사용자용 메시지(예: "토큰이 만료되었거나 삭제되었어요"). 연결 안 됨은 `404 LMS_NOT_CONNECTED`.
이 줄을 아래 줄로 바꿔:
`status`는 DB에 있는 값을 그대로 준다(`active` · `error` · `disconnected`, `GET /me`의 `lms.status`와 같은 세 가지). `status = error`이면 `last_error`에 사용자용 메시지(예: "토큰이 만료되었거나 삭제되었어요"). 연결 안 됨은 `404 LMS_NOT_CONNECTED`. `last_synced_at`은 마지막으로 동기화를 **시작한** 시각이다(`POST /lms/sync`).

[6] docs/API_명세_v0.4.md — 9장 `GET /lms/assignments` 쿼리 줄 **뒤**
찾을 줄:
`?state=open|submitted|all&lms_course_id=uuid`
이 줄 뒤에 아래 다섯 줄(빈 줄 포함)을 넣어:

- `state`를 주지 않으면 `open`(아직 내지 않은 과제)이다. `submitted`는 낸 과제(`submitted`·`graded`·`pending_review`), `all`은 둘 다다
- **LMS에서 사라진 과제와 수강을 뺀 과목의 과제는 어느 `state`에도 넣지 않는다**
- 마감이 가까운 순이고, 마감이 없는 과제는 뒤에 온다. 순서는 서버가 정하고 DB의 정렬 규칙에 맡기지 않는다(`GET /lms/courses`와 같은 이유)
- `planner_task_id`는 이 과제의 플래너 할 일(없으면 null), `calendar_registered`는 캘린더에 실제로 등록된 일정이 있는지다

[7] docs/API_명세_v0.4.md — 11장 실행 결과 종류
찾을 줄:
`result`는 `kind`로 가린다: 준비하기는 `prepare`(7장), 포스터 추출은 `poster_extract`(6장)다. 아직 돌고 있거나 실패한 실행은 null이다.
이 줄을 아래 줄로 바꿔:
`result`는 `kind`로 가린다: 준비하기는 `prepare`(7장), 포스터 추출은 `poster_extract`(6장), LMS 동기화는 `lms_sync`(9장)다. 아직 돌고 있거나 실패한 실행은 null이다. 코드를 남기지 못한 실패는 `error.code`가 `INTERNAL_ERROR`이고 문구는 작업마다 다르다(동기화는 "LMS 자료를 가져오지 못했어요").

[8] docs/API_명세_v0.4.md — 12장 배치 표
찾을 줄:
| `POST /internal/jobs/lms-sync` | 스케줄러(30분) | LMS 연결된 전체 사용자 동기화 |
이 줄을 아래 줄로 바꿔:
| `POST /internal/jobs/lms-sync` | 스케줄러(30분) | LMS 연결된 사용자의 과목·과제 동기화(F-51). 오래 안 한 사람부터 한 번에 50명까지 보고, 최근 5분 안에 동기화를 시작한 사람은 건너뛴다. 한 사람이 실패해도 다음 사람을 계속하고(실패는 그 사람의 실행 기록에 남는다), 토큰이 막힌 사람만 연결을 `error`로 바꾼다. 응답은 `{users, synced, failed, skipped, new_assignments, due_changed, submitted}`이고 `skipped`는 그새 대시보드가 동기화를 시작했거나 연결이 사라진 사람 수다 |

[9] docs/ERD_v0.9.md — LMS 응답 규칙의 제출 상태
찾을 줄의 일부를 바꾼다. 찾을 조각:
`pending_review`는 아직 못 봄
이 조각을 아래로 바꿔:
`pending_review`는 아직 못 봤지만 제출로 센다

[10] docs/ERD_v0.9.md — "새 자료 감지" 항목 **앞**
찾을 줄:
- **새 자료 감지**:
이 줄 **앞에** 아래 두 줄을 넣어:

- **과제 동기화(F-51)**: 과제는 `(user_id, canvas_assignment_id)`로 upsert한다. `first_seen_at`은 처음 본 때로 두고 다시 받을 때 밀지 않는다. 이번 목록에 없던 과제는 `removed_at`을 찍고(**목록이 비어 와도 찍는다** — 과제 0건인 과목이 흔하고, 클라이언트는 끝까지 받지 못하면 예외라 빈 목록은 "정말 없다"는 뜻이다), 다시 나타나면 지우고 새 과제로 센다. 수강을 뺀 과목(`lms_courses.is_active` false)의 과제는 더 받지 않으므로 목록에서 과목 조건으로 뺀다. `lms_connections.last_synced_at`은 동기화를 **시작할** 때 찍는다(같은 사용자를 동시에 두 번 동기화하지 않고, 실패한 사용자가 배치 앞자리를 차지하지 않게). 성공은 `status`·`last_error`로 적는다.
- **LMS 과제 할 일(F-51·F-43)**: `planner_tasks`에는 **마감이 있는 미제출 과제**만 넣는다(`due_date`가 not null이고, 연결 첫 동기화에 들어오는 지난 과제로 할 일을 만들지 않는다). 마감이 바뀌면 아직 끝내지 않은 할 일의 날짜만 고치고, 마감이 없다가 생긴 과제는 그때 할 일을 만든다. 값에서 값으로 바뀐 마감은 할 일을 새로 만들지 않는다 — 학생이 지운 할 일을 되살리지 않으려는 것이다. 제출하면 할 일을 완료로 바꾸고 아직 보내지 않은 알림(`notifications.status = pending`)을 지운다.

[11] docs/PRD_v0.9.md — 5-6절 녹화 결과 줄의 장 번호 오타
찾을 조각:
자세한 필드 규칙은 API 명세 8장에 적었다
이 조각을 아래로 바꿔:
자세한 필드 규칙은 API 명세 9장에 적었다

[12] docs/PRD_v0.9.md — 에이전트 도구 표
찾을 줄:
| fetch_lms_assignments | **외부 API** · LearningX(Canvas) | 과목별 과제·마감일·제출 여부. GET 요청과 허용 경로만 |
이 줄을 아래 두 줄로 바꿔:
| fetch_lms_assignments | **외부 API** · LearningX(Canvas) | 과목별 과제·마감일·제출 여부. GET 요청과 허용 경로만. 동기화(F-51)에서 과목을 차례로 돈다 |
| save_lms_sync | 코드 | 동기화에서 바뀐 것(새 과제·마감 변경·제출)을 저장하고 수를 실행 기록에 남긴다. `GET /runs/{id}`의 결과가 이 출력이다 |

문서 머리의 보강 이력 줄이 있으면 "v0.9 보강 (2026-10-17): LMS 과제 동기화 규칙(F-51)"을 같은 꼴로 한 줄 더해 줘.
````

## 코드

아래 파일 19개를 그대로 만들거나 바꾼다. 샌드박스에서 `ruff`·`pytest`(DB 포함)·web `typecheck`·`build`를 통과하고 되돌림 시험 28가지 중 27가지를 잡은 코드다. 실제 LearningX에는 접속하지 않았다.

### api (새 파일)

#### `api/app/lms/assignments.py`

```python
"""Canvas 과제 응답 → 저장할 값 (F-51, API 명세 9장의 10/16 녹화 규칙).

녹화(6과목·과제 17건)에서 확정한 것만 따른다:

- 마감은 `due_at ?? lock_at`이다. 17건 중 5건은 `due_at`이 null이고 `lock_at`만 있었다
- 제출 여부는 `submission.workflow_state`다. 과목 전체 기준인 `has_submitted_submissions`는 쓰지
  않는다(내가 내지 않은 과제에도 true로 온다). 퀴즈는 자동 채점돼 바로 `graded`로 왔다(17건 중 4건)
- `pending_review`(냈고 손 채점만 남음)도 제출로 센다. 녹화에서는 못 봤지만 DB enum에 있는 값이고,
  제출로 보지 않으면 할 일이 끝나지 않고 알림도 멈추지 않는다
- `submission`이 없거나 모르는 상태면 `unsubmitted`로 둔다. 모르는 값을 그대로 넣으면 DB enum이 막는다
- 아직 열지 않은 과제(`published`가 false)는 학생에게 보이지 않으니 건너뛴다(녹화 17건은 모두 true)

시각은 UTC(`timestamptz`)로 저장한다. 화면에서 KST로 바꾼다.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.lms.parse import is_canvas_id

logger = logging.getLogger(__name__)

# DB enum(lms_submission_state)에 있는 값. 그 밖은 unsubmitted로 둔다
STATES = ("unsubmitted", "submitted", "graded", "pending_review")
# 제출로 보는 상태(명세 9장). `pending_review`는 냈고 손 채점만 남은 상태라 제출로 센다
SUBMITTED = ("submitted", "graded", "pending_review")
NO_TITLE = "(제목 없음)"  # 이름이 빈 과제도 할 일이라 버리지 않는다


@dataclass(frozen=True)
class CanvasAssignment:
    """저장 직전의 과제 하나. `lms_assignments` 칸과 같은 이름이다."""

    canvas_assignment_id: int
    title: str
    due_at: datetime | None
    html_url: str | None
    submission_state: str
    submitted_at: datetime | None

    @property
    def submitted(self) -> bool:
        return self.submission_state in SUBMITTED


def assignments(raw: list[Any]) -> list[CanvasAssignment]:
    """과제 목록 응답을 저장할 값으로. 쓸 수 없는 항목은 건너뛴다."""
    items = []
    for one in raw:
        parsed = assignment(one)
        if parsed is not None:
            items.append(parsed)
    return items


def assignment(raw: Any) -> CanvasAssignment | None:
    """과제 하나. 번호가 없거나 아직 열지 않은 과제면 None이다."""
    if not isinstance(raw, dict) or not is_canvas_id(raw.get("id")):
        return None
    if raw.get("published") is False:  # 아직 열지 않은 과제는 학생에게 보이지 않는다
        return None
    submission = raw.get("submission") if isinstance(raw.get("submission"), dict) else {}
    state = _state(submission.get("workflow_state"))
    return CanvasAssignment(
        canvas_assignment_id=raw["id"],
        title=(raw.get("name") or "").strip() or NO_TITLE,
        due_at=moment(raw.get("due_at")) or moment(raw.get("lock_at")),
        html_url=raw.get("html_url") if isinstance(raw.get("html_url"), str) else None,
        submission_state=state,
        submitted_at=moment(submission.get("submitted_at")) if state in SUBMITTED else None,
    )


def _state(value: Any) -> str:
    if value in STATES:
        return str(value)
    if value is not None:
        logger.info("모르는 제출 상태라 unsubmitted로 둬요: %r", value)
    return "unsubmitted"


def moment(value: Any) -> datetime | None:
    """Canvas의 `2026-10-13T14:59:59Z` → UTC 시각. 꼴이 다르면 None이다."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.info("읽을 수 없는 시각이라 비워 둬요: %r", value)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
```

#### `api/app/lms/sync.py`

```python
"""LMS 동기화 (F-51, API 명세 8장). 과목 목록 → 과목마다 과제·제출 → 저장 → 플래너·알림.

두 곳에서 부른다. `POST /lms/sync`는 대시보드를 열 때(202 + `run_id`, 결과는 `GET /runs/{id}`)이고,
`POST /internal/jobs/lms-sync`는 30분마다 도는 배치다. 둘 다 같은 `_sync`를 쓴다.

지키는 것:
- 외부 호출은 모두 실행(`lms_sync`) 안의 도구로 기록한다(api/CLAUDE.md). 토큰은 입력에 넣지 않는다
- LearningX를 부르는 동안 요청용 DB 연결을 쥐지 않는다(준비하기와 같다). 받아 둔 뒤 한 트랜잭션에 쓴다
- 과목의 과제 목록을 끝까지 받지 못하면 **그 과목은 저장하지 않는다**. 부분 목록으로 저장하면 못 받은
  과제가 "사라진 과제"가 된다(저장소의 `removed_at`)
- 토큰이 막히면(401) 거기서 멈추고 연결을 `error`로 바꾼다. 화면이 다시 연결을 안내한다
- 마지막 동기화가 5분 안이면 건너뛴다(명세 9장). 대시보드를 여러 번 열어도 LearningX를 또 부르지 않는다

캘린더 등록은 아직 하지 않는다(사용자 구글 캘린더에 쓰는 일이라 따로 정한다). 주차 항목·공지는 F-52·F-53다.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, Request
from psycopg import AsyncConnection

from app.agent_log import AgentRun, LogConnect, abandon_run, agent_run, start_run
from app.background import RunnerDep, TaskRunner
from app.config import Settings, get_settings
from app.crypto import decrypt
from app.eligibility import KST
from app.errors import ApiError
from app.lms.assignments import CanvasAssignment, assignments
from app.lms.client import LearningXClient, LearningXError
from app.lms.service import API_ERROR, NOT_CONNECTED, TOKEN_EXPIRED, student_courses
from app.repositories.lms import AssignmentChanges, CourseRow, LmsRepository, SavedAssignment
from app.repositories.notifications import AssignmentNotice, NotificationRepository
from app.schemas.lms import SAVE_TOOL, SyncCounts, SyncResponse, SyncSkipped, SyncStarted

logger = logging.getLogger(__name__)
Connect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]

SKIP_AFTER = timedelta(minutes=5)  # 이 안에 동기화했으면 건너뛴다(명세 9장)
BATCH_USERS = 50  # 배치 한 번에 보는 사용자 수 상한. 넘으면 다음 차례에 간다
STOPPED = "동기화를 시작하지 못했어요. 잠시 후 다시 시도해 주세요."
TOKEN_UNREADABLE = "저장한 토큰을 읽을 수 없어요. 다시 연결해 주세요."
NEW_TITLE = "{course} 새 과제가 올라왔어요"


class StoredTokenUnreadable(Exception):
    """저장한 토큰을 복호화하지 못했다(암호화 키를 바꿨거나 값이 깨졌다).

    LearningX가 거절한 것이 아니므로 연결을 `error`로 바꾸지 않는다 — 키 문제로 모든 사용자에게
    "토큰이 만료됐어요"를 띄우면 멀쩡한 토큰을 다시 받게 만든다(app/crypto.py의 키 교체).
    """


@dataclass(frozen=True)
class Repos:
    """한 트랜잭션에서 쓰는 저장소 묶음. 테스트는 가짜로 바꿔 끼운다(api/CLAUDE.md)."""

    lms: LmsRepository
    notes: NotificationRepository

    @classmethod
    def of(cls, conn: AsyncConnection) -> "Repos":
        return cls(lms=LmsRepository(conn), notes=NotificationRepository(conn))


@dataclass(frozen=True)
class SyncJob:
    run_id: str
    user_id: str
    now: datetime
    token: str = field(repr=False)  # 복호화한 토큰. 실수로 찍지 않게 repr에서 뺀다


@dataclass(frozen=True)
class SyncOutcome:
    """동기화 한 번의 결과. `GET /runs/{id}`가 보여 주는 수와 같다(명세 9장)."""

    courses: int = 0
    created: int = 0
    due_changed: int = 0
    submitted: int = 0
    notices: int = 0
    failed_courses: int = 0

    def counts(self) -> SyncCounts:
        return SyncCounts(new=self.created, due_changed=self.due_changed, submitted=self.submitted)


@dataclass
class BatchOutcome:
    """배치 한 번의 결과(명세 12장). 실패한 사용자는 다음 차례에 다시 본다."""

    users: int = 0
    synced: int = 0
    failed: int = 0
    skipped: int = 0  # 그새 다른 쪽이 동기화를 시작했거나 연결이 사라진 사람
    new_assignments: int = 0
    due_changed: int = 0
    submitted: int = 0


class LmsSyncService:
    def __init__(
        self,
        *,
        transaction: Connect,
        log_connection: LogConnect,
        client: LearningXClient,
        encryption_key: str,
        runner: TaskRunner,
        repos: Callable[[AsyncConnection], Repos] = Repos.of,
    ) -> None:
        self.transaction = transaction  # 블록이 끝나면 커밋하는 연결(요청 트랜잭션과 따로)
        self.log_connection = log_connection
        self.client = client
        self.key = encryption_key
        self.runner = runner
        self.repos = repos

    # ── 사용자가 눌렀을 때 ──────────────────────────────────────────────────

    async def start(self, user_id: str, *, now: datetime) -> SyncResponse:
        """실행 행을 만들고 일을 띄운다. 얼마 전에 동기화했으면 건너뛴 응답(200)이다."""
        async with self.transaction() as conn:
            repo = self.repos(conn).lms
            connection = await repo.connection(user_id)
            if connection is None:
                raise ApiError(404, "LMS_NOT_CONNECTED", NOT_CONNECTED)
            # 한 문장으로 "내가 한다"고 못 박는다. 5분 안에 이미 했거나 다른 탭이 가져가면 False다
            claimed = await repo.claim_sync(user_id, now=now, before=now - SKIP_AFTER)
        if not claimed:
            last = connection.last_synced_at
            return SyncSkipped(last_synced_at=last.astimezone(KST) if last else None)
        try:
            token = self._token(connection.access_token)
        except StoredTokenUnreadable as exc:
            logger.warning("저장한 LMS 토큰을 읽지 못했어요: user %s", user_id)
            raise ApiError(422, "LMS_TOKEN_INVALID", TOKEN_UNREADABLE) from exc
        run_id = await start_run(self.log_connection, trigger="lms_sync", user_id=user_id)
        job = SyncJob(run_id=run_id, user_id=user_id, now=now, token=token)
        work = self.execute(job)
        try:
            await self.runner.start(work)
        except Exception:  # 일을 띄우지 못했다. 실행이 running으로 남지 않게 닫는다
            work.close()
            await self._close(run_id)
            raise ApiError(500, "INTERNAL_ERROR", STOPPED) from None
        return SyncStarted(run_id=run_id, status="running")

    async def execute(self, job: SyncJob) -> None:
        """뒤에서 도는 일. 실패해도 실행 기록에 남고 연결 상태를 바꾼다."""
        try:
            async with agent_run(
                self.log_connection, trigger="lms_sync", user_id=job.user_id, run_id=job.run_id
            ) as run:
                await self._sync(run, job)
        except Exception as exc:
            logger.warning("LMS 동기화 실패: user %s, run %s, %r", job.user_id, job.run_id, exc)
            await self._mark_error(job.user_id, exc)
            # 로그 연결을 얻지 못해 agent_run 밖에서 끝난 경우까지 닫는다(준비하기와 같다).
            # 닫지 않으면 GET /runs/{id}가 영원히 running이고 성공률 지표의 분모만 늘어난다
            await self._close(job.run_id)

    # ── 30분 배치 ───────────────────────────────────────────────────────────

    async def sync_all(self, *, now: datetime, limit: int = BATCH_USERS) -> BatchOutcome:
        """연결된 사용자를 차례로 동기화한다. 한 사람이 실패해도 다음 사람을 계속한다."""
        async with self.transaction() as conn:
            users = await self.repos(conn).lms.connected_users(before=now - SKIP_AFTER, limit=limit)
        result = BatchOutcome(users=len(users))
        for user_id in users:
            try:
                outcome = await self._run_for(user_id, now=now)
            except StoredTokenUnreadable:  # 우리 키 문제다. 사용자 연결은 건드리지 않는다
                logger.warning("저장한 LMS 토큰을 읽지 못했어요: user %s", user_id)
                result.failed += 1
                continue
            except Exception as exc:  # 토큰이 막혔거나 LearningX가 답하지 않았다
                logger.warning("LMS 배치 동기화 실패: user %s, %r", user_id, exc)
                result.failed += 1
                await self._mark_error(user_id, exc)
                continue
            if outcome is None:  # 그새 다른 쪽이 동기화를 시작했거나 연결이 사라졌다
                result.skipped += 1
                continue
            result.synced += 1
            result.new_assignments += outcome.created
            result.due_changed += outcome.due_changed
            result.submitted += outcome.submitted
        return result

    async def _run_for(self, user_id: str, *, now: datetime) -> SyncOutcome | None:
        """한 사람을 동기화한다. 그새 다른 쪽이 가져갔거나 연결이 사라졌으면 None이다."""
        async with self.transaction() as conn:
            repo = self.repos(conn).lms
            connection = await repo.connection(user_id)
            if connection is None:  # 그새 해제했다
                return None
            if not await repo.claim_sync(user_id, now=now, before=now - SKIP_AFTER):
                return None
        token = self._token(connection.access_token)
        async with agent_run(self.log_connection, trigger="lms_sync", user_id=user_id) as run:
            return await self._sync(run, SyncJob(run.id, user_id, now, token))

    # ── 동기화 본체 ─────────────────────────────────────────────────────────

    async def _sync(self, run: AgentRun, job: SyncJob) -> SyncOutcome:
        """과목 → 과제 → 저장. 외부 호출을 모두 마친 뒤에 쓰기 트랜잭션을 연다."""
        async with run.tool("fetch_lms_courses") as call:
            courses = student_courses(await self._fetch_courses(job.token))
            call.output = {"courses": len(courses)}
        async with self.transaction() as conn:
            repo = self.repos(conn).lms
            await repo.save_courses(job.user_id, courses, now=job.now)
            rows = await repo.active_courses(job.user_id)
        fetched, failed = await self._fetch_assignments(run, job, rows)
        if rows and failed and not fetched:
            # 과목이 있는데 한 과목도 받지 못했다. 저장할 것도 없고 성공으로 적으면 안 된다
            # (`touch_synced`가 오류 표시를 지워 버린다). 다음 배치에서 다시 시도한다
            raise ApiError(502, "LMS_API_ERROR", API_ERROR)
        outcome = await self._save(job, fetched, failed=failed)
        async with run.tool(SAVE_TOOL) as call:
            # `GET /runs/{id}`가 이 출력으로 결과를 만든다(repositories/runs.py)
            call.output = {
                "courses": outcome.courses,
                "new": outcome.created,
                "due_changed": outcome.due_changed,
                "submitted": outcome.submitted,
                "notices": outcome.notices,
                "failed_courses": outcome.failed_courses,
            }
        return outcome

    async def _fetch_assignments(
        self, run: AgentRun, job: SyncJob, rows: list[CourseRow]
    ) -> tuple[list[tuple[CourseRow, list[CanvasAssignment]]], int]:
        """과목마다 과제를 받는다. 한 과목이 실패하면 그 과목만 빼고 이어 간다(401은 멈춘다)."""
        fetched: list[tuple[CourseRow, list[CanvasAssignment]]] = []
        failed = 0
        async with run.tool("fetch_lms_assignments", {"courses": len(rows)}) as call:
            for course in rows:
                try:
                    raw = await self.client.assignments(job.token, course.canvas_course_id)
                except LearningXError as exc:
                    if exc.unauthorized:  # 토큰이 막혔다. 남은 과목도 못 받는다
                        raise ApiError(422, "LMS_TOKEN_INVALID", TOKEN_EXPIRED) from exc
                    logger.warning(
                        "과제 목록을 받지 못해 그 과목은 두고 넘어가요: course %s, status %s",
                        course.canvas_course_id,
                        exc.status,
                    )
                    failed += 1
                    continue
                fetched.append((course, assignments(raw)))
            call.output = {
                "courses": len(fetched),
                "assignments": sum(len(items) for _, items in fetched),
                "failed_courses": failed,
            }
        return fetched, failed

    async def _save(
        self,
        job: SyncJob,
        fetched: list[tuple[CourseRow, list[CanvasAssignment]]],
        *,
        failed: int,
    ) -> SyncOutcome:
        """받아 둔 과제를 한 트랜잭션에 쓰고, 플래너·알림을 맞춘다."""
        changes = AssignmentChanges()
        notices: list[AssignmentNotice] = []
        async with self.transaction() as conn:
            repos = self.repos(conn)
            repo, notes = repos.lms, repos.notes
            for course, items in fetched:
                one = await repo.save_assignments(job.user_id, course.id, items, now=job.now)
                changes = changes + one
                # 이미 낸 과제는 알리지 않는다(연결 첫 동기화에 지난 과제가 한꺼번에 들어온다)
                notices += [_notice(course, saved) for saved in one.created if not saved.submitted]
            await repo.sync_planner(job.user_id, changes, now=job.now)
            # 제출한 과제는 알림을 멈춘다(명세 10장). 새 과제 알림은 찾은 때 바로 보낸다
            await notes.drop_assignment_notices(job.user_id, changes.submitted)
            made = await notes.add_assignment_notices(job.user_id, notices, now=job.now)
            await repo.touch_synced(job.user_id, now=job.now)
        return SyncOutcome(
            courses=len(fetched),
            created=len(changes.created),
            due_changed=len(changes.due_changed),
            submitted=len(changes.submitted),
            notices=made,
            failed_courses=failed,
        )

    # ── 거들기 ──────────────────────────────────────────────────────────────

    def _token(self, encrypted: str) -> str:
        """저장한 토큰을 꺼낸다. 읽지 못하면 StoredTokenUnreadable이다(연결 상태는 건드리지 않는다)."""
        try:
            return decrypt(encrypted, self.key)
        except Exception as exc:
            raise StoredTokenUnreadable from exc

    async def _fetch_courses(self, token: str) -> list[dict[str, Any]]:
        try:
            return await self.client.courses(token)
        except LearningXError as exc:
            if exc.unauthorized:
                raise ApiError(422, "LMS_TOKEN_INVALID", TOKEN_EXPIRED) from exc
            logger.warning("LearningX 과목 목록 실패: status %s", exc.status)
            raise ApiError(502, "LMS_API_ERROR", API_ERROR) from exc

    async def _mark_error(self, user_id: str, exc: BaseException) -> None:
        """토큰이 막힌 경우만 연결을 error로 바꾼다. LearningX가 잠깐 답하지 않은 것은 두고 다시 시도한다."""
        if not (isinstance(exc, ApiError) and exc.code == "LMS_TOKEN_INVALID"):
            return
        try:
            async with self.transaction() as conn:
                await self.repos(conn).lms.mark_error(user_id, exc.message)
        except Exception:
            logger.exception("연결 상태를 바꾸지 못했어요: user %s", user_id)

    async def _close(self, run_id: str) -> None:
        try:
            await abandon_run(self.log_connection, run_id, ApiError(500, "INTERNAL_ERROR", STOPPED))
        except Exception:
            logger.exception("LMS 동기화 실행을 닫지 못했어요: run %s", run_id)


def _notice(course: CourseRow, saved: SavedAssignment) -> AssignmentNotice:
    """새 과제 알림 문구. 제목은 과목 이름, 본문은 과제와 마감(KST)이다."""
    body = saved.title
    if saved.due_at is not None:
        # %-m은 윈도에서 안 되는 서식이라 손으로 붙인다(테스트·CLI를 윈도에서도 돌린다)
        when = saved.due_at.astimezone(KST)
        body = f"{saved.title} · 마감 {when.month}/{when.day} {when:%H:%M}"
    return AssignmentNotice(
        assignment_id=saved.id, title=NEW_TITLE.format(course=course.short_name), body=body
    )


def get_lms_sync_service(
    request: Request,
    runner: RunnerDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> LmsSyncService:
    state = request.app.state
    pool, log_pool = getattr(state, "pool", None), getattr(state, "log_pool", None)
    if pool is None or log_pool is None:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    return LmsSyncService(
        transaction=pool.connection,
        log_connection=log_pool.connection,
        client=LearningXClient(api_base=settings.lms_api_base),
        encryption_key=settings.token_encryption_key,
        runner=runner,
    )


LmsSyncServiceDep = Annotated[LmsSyncService, Depends(get_lms_sync_service)]
```

### api (바뀌는 파일)

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
from typing import Any

BIGINT_MAX = 2**63 - 1  # Canvas 번호는 bigint 칸에 들어가야 한다


def is_canvas_id(value: Any) -> bool:
    """Canvas 번호로 쓸 수 있는 값인지. bool과 bigint를 넘는 수는 거른다(그대로 넣으면 DB가 터진다)."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= BIGINT_MAX


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

#### `api/app/lms/service.py`

```python
"""LearningX 연결 (F-50). 토큰을 확인하고 암호화해 저장한 뒤 수강 과목을 받아 둔다.

순서(명세 9장): `GET /api/v1/users/self`로 확인 → 과목 목록 → 저장. 두 호출 모두 실행 하나(`lms_sync`)
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
from app.lms.parse import is_canvas_id
from app.repositories.lms import LmsRepoDep, LmsRepository
from app.schemas.lms import ConnectResult

logger = logging.getLogger(__name__)

NOT_CONNECTED = (
    "LearningX를 연결해 주세요."  # 404 LMS_NOT_CONNECTED의 문구(라우터·동기화가 함께 쓴다)
)
TOKEN_INVALID = "토큰을 확인할 수 없어요. 복사할 때 앞뒤 공백이 들어갔는지 확인해 주세요."
TOKEN_EXPIRED = "토큰이 만료되었거나 삭제되었어요."
API_ERROR = "LearningX가 응답하지 않아요. 잠시 후 다시 시도해 주세요."
# 학생 등록인 과목만 본다(청강·조교 과목은 과제가 내 것이 아니다)
STUDENT = "student"
OPEN_STATES = ("available", "completed")  # 그 밖(unpublished 등)은 아직 열지 않은 과목이다


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
            and is_canvas_id(course.get("id"))
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

#### `api/app/repositories/lms.py`

```python
"""LearningX 연결과 과목 (F-50·F-14, ERD 3-2).

- 토큰은 암호화한 값만 저장하고(`lms_connections.access_token`), 화면에는 끝 4자리만 보낸다
- 과목은 `(user_id, canvas_course_id)`로 upsert하고, 이번 동기화에 없던 과목은 `is_active`를 내린다
  (수강을 뺀 과목이다 — 과제·공지 기록은 남겨 두고 목록에서만 뺀다). **목록이 비어 오면 내리지 않는다**
- 과목 목록의 숫자는 지금 저장된 것으로 센다. 주차 항목 동기화는 F-52라 `new_materials`는 그때까지 0이다
- 과제는 `(user_id, canvas_assignment_id)`로 upsert한다(제출 상태가 사람마다 달라 사용자별 표다, ERD 5장).
  이번 목록에 없던 과제는 `removed_at`을 찍고, 다시 나타나면 지운다. **목록이 비어 와도 찍는다** —
  과제는 과목과 달리 0건인 과목이 흔하고(녹화 6과목 중 2과목), 클라이언트가 끝까지 받지 못하면 예외라
  빈 목록은 "정말 없다"는 뜻이다
- 저장하면서 바뀐 것(새 과제·마감 변경·이번에 제출)을 모아 돌려준다. 플래너·알림·캘린더가 그걸 쓴다
- `last_synced_at`은 동기화를 **시작할 때** 찍는다(`claim_sync`). 같은 사용자를 두 번 동시에
  동기화하지 않고, 실패한 사람이 배치 앞자리를 계속 차지하지도 않는다
- 목록 순서는 `ordered()`·`by_due()`가 정한다. DB의 정렬 규칙은 환경마다 달라서 쓰지 않는다
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection

from app.db import get_conn
from app.eligibility import KST
from app.lms.assignments import SUBMITTED, CanvasAssignment
from app.lms.parse import course_name, is_canvas_id
from app.schemas.lms import (
    AssignmentCourse,
    AssignmentItem,
    ConnectionView,
    CourseItem,
    NextDue,
)


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


@dataclass(frozen=True)
class CourseRow:
    """동기화할 과목 하나. 화면 이름은 알림 문구에 쓴다."""

    id: str
    canvas_course_id: int
    short_name: str


@dataclass(frozen=True)
class SavedAssignment:
    """막 저장한 과제. 플래너 할 일과 알림 문구를 만들 만큼만 담는다."""

    id: str
    title: str
    due_at: datetime | None
    # 이미 낸 과제인지. 연결 첫 동기화에는 지난 학기분까지 한꺼번에 들어와서(녹화 17건 중 13건이
    # 제출·채점 완료였다), 낸 과제로 할 일을 만들거나 "새 과제" 알림을 보내면 안 된다
    submitted: bool = False


@dataclass(frozen=True)
class AssignmentChanges:
    """한 과목을 저장하고 바뀐 것. 수는 `POST /lms/sync` 결과에 그대로 들어간다(명세 9장)."""

    created: list[SavedAssignment] = field(default_factory=list)
    due_changed: list[SavedAssignment] = field(default_factory=list)
    # due_changed 중 **마감이 없다가 생긴** 과제. 이것만 할 일을 새로 만든다(아래 sync_planner)
    new_deadline: list[SavedAssignment] = field(default_factory=list)
    submitted: list[str] = field(default_factory=list)  # 이번에 제출로 바뀐 과제 id
    removed: int = 0

    def __add__(self, other: "AssignmentChanges") -> "AssignmentChanges":
        return AssignmentChanges(
            created=self.created + other.created,
            due_changed=self.due_changed + other.due_changed,
            new_deadline=self.new_deadline + other.new_deadline,
            submitted=self.submitted + other.submitted,
            removed=self.removed + other.removed,
        )


_FAR = datetime.max.replace(tzinfo=UTC)  # 마감 없는 과제를 뒤로 보낼 때 쓰는 비교값

_ASSIGNMENTS = (
    "select a.id, a.title, a.due_at, a.submission_state::text as submission_state, a.html_url,"
    " c.id as course_id, c.name as course_name,"
    # 할 일은 과제 하나에 한 줄이다(sync_planner의 not exists). 그래도 가장 먼저 만든 것을 쓴다
    " (select t.id from planner_tasks t where t.lms_assignment_id = a.id"
    "   and t.user_id = a.user_id order by t.created_at, t.id limit 1) as planner_task_id,"
    # 캘린더는 실제로 등록된 것만 true다(공고 상세와 같은 기준: external_event_id가 있는 행)
    " exists (select 1 from calendar_events e where e.lms_assignment_id = a.id"
    "   and e.user_id = a.user_id and e.external_event_id is not null) as calendar_registered"
    " from lms_assignments a"
    " join lms_courses c on c.id = a.lms_course_id and c.user_id = a.user_id"
    # 수강을 뺀 과목의 과제는 더 받지 않으니(active_courses) 사라진 표시도 안 붙는다. 여기서 뺀다
    " where a.user_id = %(uid)s and a.removed_at is null and coalesce(c.is_active, true)"
)
# `pending_review`(냈고 채점만 남은 상태)는 제출로 본다. 안 그러면 어느 state에도 안 들어간다
_STATE_FILTERS = {
    "open": " and a.submission_state = 'unsubmitted'",
    "submitted": " and a.submission_state <> 'unsubmitted'",
    "all": "",
}

_UPSERT_ASSIGNMENT = (
    "insert into lms_assignments (user_id, lms_course_id, canvas_assignment_id, title, due_at,"
    " html_url, submission_state, submitted_at, first_seen_at, removed_at)"
    " values (%(uid)s, %(course)s, %(canvas)s, %(title)s, %(due)s, %(url)s, %(state)s,"
    " %(submitted)s, %(now)s, null)"
    " on conflict (user_id, canvas_assignment_id) do update set"
    " lms_course_id = excluded.lms_course_id, title = excluded.title, due_at = excluded.due_at,"
    " html_url = excluded.html_url, submission_state = excluded.submission_state,"
    " submitted_at = excluded.submitted_at, removed_at = null"
    " returning id"
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
    # 가장 가까운 것 하나: 미제출 과제와 확정된 계획서 일정 중에서(명세 9장)
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
        """토큰을 즉시 지운다. 과목·과제 기록은 남기고 동기화만 멈춘다(명세 9장)."""
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
            if not is_canvas_id(canvas_id) or not name:
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

    async def active_courses(self, user_id: str) -> list[CourseRow]:
        """동기화할 과목. 수강을 뺀 과목(`is_active` false)은 더 받지 않는다."""
        rows = await self._rows(
            "select id, canvas_course_id, name from lms_courses"
            " where user_id = %s and coalesce(is_active, true)",
            (user_id,),
        )
        courses = [
            CourseRow(
                id=str(row["id"]),
                canvas_course_id=row["canvas_course_id"],
                short_name=course_name(row["name"]).short_name,
            )
            for row in rows
        ]
        return sorted(courses, key=lambda one: (one.short_name, one.canvas_course_id))

    async def save_assignments(
        self, user_id: str, course_id: str, items: list[CanvasAssignment], *, now: datetime
    ) -> AssignmentChanges:
        """한 과목의 과제를 저장하고 바뀐 것을 돌려준다.

        먼저 저장된 것을 한 번에 읽어 두고 비교한다. 새 과제·마감 변경·이번에 제출을 가려내려면
        예전 값이 필요한데, upsert의 `returning`은 바뀐 뒤 값만 준다.
        """
        before = {
            row["canvas_assignment_id"]: row
            for row in await self._rows(
                "select canvas_assignment_id, due_at, submission_state::text as submission_state,"
                " removed_at from lms_assignments where user_id = %s and lms_course_id = %s",
                (user_id, course_id),
            )
        }
        changes = AssignmentChanges()
        for item in items:
            row = await self._row(
                _UPSERT_ASSIGNMENT,
                {
                    "uid": user_id,
                    "course": course_id,
                    "canvas": item.canvas_assignment_id,
                    "title": item.title,
                    "due": item.due_at,
                    "url": item.html_url,
                    "state": item.submission_state,
                    "submitted": item.submitted_at,
                    "now": now,
                },
            )
            assert row is not None  # insert ... returning은 늘 한 행이다
            saved = SavedAssignment(
                id=str(row["id"]),
                title=item.title,
                due_at=item.due_at,
                submitted=item.submitted,
            )
            old = before.get(item.canvas_assignment_id)
            # 사라졌다 다시 나타난 과제도 "새 과제"다. 그 사이 할 일·알림이 없었다
            if old is None or old["removed_at"] is not None:
                changes.created.append(saved)
                continue
            if old["due_at"] != item.due_at:
                changes.due_changed.append(saved)
                if old["due_at"] is None:  # 마감이 없다가 생겼다 → 할 일이 있을 수 없다
                    changes.new_deadline.append(saved)
            if item.submitted and old["submission_state"] not in SUBMITTED:
                changes.submitted.append(saved.id)
        # 이번 목록에 없던 과제는 지운 것으로 본다(목록이 비어 와도 찍는다, 머리말)
        fetched = [item.canvas_assignment_id for item in items]
        cursor = await self.conn.execute(
            "update lms_assignments set removed_at = %(now)s"
            " where user_id = %(uid)s and lms_course_id = %(course)s and removed_at is null"
            " and not (canvas_assignment_id = any(%(ids)s::bigint[]))",
            {"uid": user_id, "course": course_id, "ids": fetched, "now": now},
        )
        return changes + AssignmentChanges(removed=max(cursor.rowcount, 0))

    async def sync_planner(self, user_id: str, changes: AssignmentChanges, *, now: datetime) -> int:
        """과제 할 일을 맞춘다(F-51·F-43). 만든 할 일 수를 돌려준다.

        - **이미 낸 과제는 할 일을 만들지 않는다**(SQL에서도 한 번 더 막는다). 연결하고 처음 받을 때
          지난 과제가 한꺼번에 들어온다
        - 새 과제와 **마감이 없다가 생긴 과제**는 할 일을 만든다(마감이 없으면 못 만든다 — `due_date`가
          not null). 마감이 값에서 값으로 바뀐 과제는 만들지 않는다 — PRD F-51은 "마감 변경 시 기존
          일정 수정"이고, 학생이 지운 할 일을 마감이 바뀔 때마다 되살리면 지울 수가 없다
        - 마감이 바뀌면 아직 끝내지 않은 할 일의 날짜만 고친다. 끝낸 할 일은 그대로 둔다
        - 제출한 과제의 할 일은 자동 완료다(PRD F-51)
        """
        # 거를 조건(마감 있음·아직 안 냄·사라지지 않음)은 아래 SQL 한 곳에만 둔다. 파이썬에서 한 번
        # 더 거르면 둘 중 하나가 틀려도 테스트가 알아채지 못한다
        fresh = [one.id for one in changes.created + changes.new_deadline]
        created = 0
        if fresh:
            cursor = await self.conn.execute(
                "insert into planner_tasks (user_id, source, lms_assignment_id, title, due_date)"
                " select a.user_id, 'lms_assignment', a.id, a.title,"
                " (a.due_at at time zone 'Asia/Seoul')::date from lms_assignments a"
                " where a.user_id = %(uid)s and a.id = any(%(ids)s::uuid[]) and a.due_at is not null"
                " and a.submission_state = 'unsubmitted' and a.removed_at is null"
                " and not exists (select 1 from planner_tasks t"
                "   where t.lms_assignment_id = a.id and t.user_id = a.user_id)",
                {"uid": user_id, "ids": fresh},
            )
            created = max(cursor.rowcount, 0)
        moved = [one.id for one in changes.due_changed if one.due_at is not None]
        if moved:
            await self.conn.execute(
                "update planner_tasks t set due_date = (a.due_at at time zone 'Asia/Seoul')::date,"
                " title = a.title from lms_assignments a"
                " where a.id = t.lms_assignment_id and a.user_id = t.user_id"
                " and t.user_id = %(uid)s"
                " and t.lms_assignment_id = any(%(ids)s::uuid[])"
                " and coalesce(t.is_done, false) = false and a.due_at is not null",
                {"uid": user_id, "ids": moved},
            )
        if changes.submitted:
            await self.conn.execute(
                "update planner_tasks set is_done = true, done_at = %(now)s"
                " where user_id = %(uid)s and lms_assignment_id = any(%(ids)s::uuid[])"
                " and coalesce(is_done, false) = false",
                {"uid": user_id, "ids": changes.submitted, "now": now},
            )
        return created

    async def claim_sync(self, user_id: str, *, now: datetime, before: datetime) -> bool:
        """동기화를 시작한다고 한 문장으로 못 박는다. 이미 누가 가져갔으면 False다.

        `last_synced_at`을 **시작할 때** 찍는다. 두 가지를 한꺼번에 막는다 —
        대시보드를 두 탭에서 열어 같은 사용자를 동시에 동기화하는 것(둘째는 False를 받는다),
        그리고 늘 실패하는 사용자가 배치 앞자리를 영구히 차지하는 것(실패해도 시각이 밀린다).
        성공·실패는 `status`·`last_error`로 본다(명세 9장).
        """
        cursor = await self.conn.execute(
            "update lms_connections set last_synced_at = %(now)s"
            " where user_id = %(uid)s and status <> 'disconnected'"
            " and (last_synced_at is null or last_synced_at <= %(before)s)",
            {"uid": user_id, "now": now, "before": before},
        )
        return cursor.rowcount > 0

    async def touch_synced(self, user_id: str, *, now: datetime) -> None:
        """잘 받았다고 적는다. 오류 표시를 지운다.

        시각을 **뒤로 돌리지 않는다** — 느린 동기화가 뒤에 시작한 동기화의 자리(`claim_sync`)를
        지워 버리면 같은 사용자를 또 동기화하게 되고, 그 사이 찍힌 오류 표시도 사라진다.
        해제한 연결은 건드리지 않는다.
        """
        await self.conn.execute(
            "update lms_connections set last_synced_at = %(now)s, status = 'active',"
            " last_error = null"
            " where user_id = %(uid)s and status <> 'disconnected'"
            " and (last_synced_at is null or last_synced_at <= %(now)s)",
            {"uid": user_id, "now": now},
        )

    async def connected_users(self, *, before: datetime, limit: int) -> list[str]:
        """동기화할 사용자(30분 배치). 오래 안 한 사람부터 본다.

        `before` 뒤에 이미 동기화한(또는 동기화를 시작한) 사람은 건너뛴다. 오류 상태도 넣는다 —
        토큰이 되살아나면 거기서 풀린다. 해제한 사람은 토큰이 없어 빠진다. 실패해도 `claim_sync`가
        시각을 밀어 두므로 한 사람이 앞자리를 계속 차지하지 않는다.
        """
        rows = await self._rows(
            "select user_id from lms_connections"
            " where status <> 'disconnected'"
            " and (last_synced_at is null or last_synced_at <= %(before)s)"
            " order by coalesce(last_synced_at, to_timestamp(0)), user_id limit %(limit)s",
            {"before": before, "limit": limit},
        )
        return [str(row["user_id"]) for row in rows]

    async def assignments(
        self, user_id: str, *, state: str = "open", course_id: str | None = None
    ) -> list[AssignmentItem]:
        """과제 목록(명세 9장). LMS에서 사라진 과제는 어느 state에도 넣지 않는다."""
        query = _ASSIGNMENTS + _STATE_FILTERS[state]
        params: dict[str, Any] = {"uid": user_id}
        if course_id is not None:
            query += " and a.lms_course_id = %(course)s"
            params["course"] = course_id
        return by_due([_assignment(row) for row in await self._rows(query, params)])

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


def by_due(items: list[AssignmentItem]) -> list[AssignmentItem]:
    """마감이 가까운 순. 마감이 없는 과제는 뒤로 보낸다.

    `ordered()`와 같은 이유로 DB에 맡기지 않는다(정렬 규칙이 환경마다 다르다).
    """
    return sorted(
        items, key=lambda one: (one.due_at is None, one.due_at or _FAR, one.title, one.id)
    )


def _assignment(row: dict[str, Any]) -> AssignmentItem:
    return AssignmentItem(
        id=str(row["id"]),
        course=AssignmentCourse(
            id=str(row["course_id"]), short_name=course_name(row["course_name"]).short_name
        ),
        title=row["title"],
        due_at=row["due_at"].astimezone(KST) if row["due_at"] else None,
        submission_state=row["submission_state"],
        html_url=row["html_url"],
        planner_task_id=str(row["planner_task_id"]) if row["planner_task_id"] else None,
        calendar_registered=row["calendar_registered"],
    )


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

#### `api/app/repositories/notifications.py`

```python
"""알림 예약·발송·알림함 SQL (F-33·F-35, API 명세 10장·12장, ERD v0.9 알림 중복 방지 표).

**예약**(하루 한 번): 공고에서 오는 알림 세 종류를 `(user_id, dedupe_key)`로 upsert한다. 사용자 ×
공고를 모두 보는 일이라 종류마다 한 문장(`insert … select`)으로 넣는다. 조건에서 빠진 pending 행은
지운다(준비 취소·숨김·마감 지남·이미 본 공고).

| 종류 | 키 | 누구에게 |
| --- | --- | --- |
| new_eligible | `new_eligible:opp:{id}` | 등록 7일 이내 + 적격 + 아직 상세를 열지 않음 |
| deadline_soon | `deadline_soon:opp:{id}:D-3`·`:D-1` | 적격이거나 준비한 공고. 마감일이 있어야 한다 |
| profile_needed | `profile_needed:opp:{id}` | 판정 불가 + 물어볼 항목이 있음 |

세 종류 모두 **숨긴 공고(관심 없음)와 설정에서 끈 종류는 만들지 않는다**(F-45, ERD). 알림 시각은
KST 09:00이고, **그 시점이 이미 지났으면 만들지 않는다** — 마감 이틀 전에 들어온 공고가 D-3·D-1을
한꺼번에 받으면 안 된다.

**발송**(5분마다): `scheduled_at`이 지난 pending 행을 닫는다. 보내기 전에 숨김을 다시 보고,
profile_needed는 사용자당 KST 하루 1건까지만 보낸다(ERD). 푸시 구독이 없거나 푸시를 끈 사용자는
푸시만 건너뛰고 행은 알림함에 남는다. 실제 푸시 발송은 F-33이다.

공고 공개 범위 조건은 `repositories/opportunities.py`의 VISIBLE과 같은 뜻이지만, 그 상수는 한 사용자
(`%(uid)s`)를 보는 문장용이라 여기서는 `p.id`로 다시 쓴다.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.db import get_conn
from app.eligibility import KST
from app.eligibility.catalog import INPUT_LABELS
from app.repositories.opportunities import Cursor, decode_cursor, encode_cursor
from app.schemas.notifications import (
    NotificationItem,
    NotificationLink,
    NotificationList,
    ScheduleResult,
    SendResult,
)

logger = logging.getLogger(__name__)
NOTIFY_HOUR = 9  # 알림을 보내는 시각(KST). 새벽에 깨우지 않는다
DEADLINE_DAYS = (3, 1)  # 마감 임박 알림을 보내는 날(D-3·D-1, PRD F-33)
NEW_DAYS = 7  # "새 공고"로 보는 등록 기간(ERD: 등록 7일 이내)
SEND_LIMIT = 500  # 한 번에 보내는 알림 수 상한
PROFILE_DAILY = 1  # profile_needed는 사용자당 KST 하루 이만큼만 보낸다(ERD)
LIST_LIMIT = 50

NEW_TITLE = "지원할 수 있는 공고가 있어요"
DEADLINE_TITLE = "마감이 가까워요"
PROFILE_TITLE = "프로필 정보가 필요해요"
ASSIGNMENT_TYPE = "new_assignment"  # notifications.type·user_settings.muted_notification_types
_NEEDED = " 입력하면 판정할 수 있어요"

# 공고 하나를 사용자 한 명에게 보일지 보는 조건. opportunities.VISIBLE과 같은 뜻이다
_VISIBLE = (
    " (o.source_type <> 'poster' or o.uploaded_by = p.id)"
    " and (o.visible_canvas_course_id is null or lc.id is not null)"
)
_JOINS = (
    " from profiles p"
    " cross join opportunities o"
    " left join lms_courses lc on o.visible_canvas_course_id is not null"
    " and lc.user_id = p.id and lc.canvas_course_id = o.visible_canvas_course_id and lc.is_active"
    " left join opportunity_marks m on m.user_id = p.id and m.opportunity_id = o.id"
    " left join eligibility_results e on e.user_id = p.id and e.opportunity_id = o.id"
    " left join prep_plans pl on pl.user_id = p.id and pl.opportunity_id = o.id"
    " left join user_settings s on s.user_id = p.id"
)
# 설정 행이 없는 사용자는 기본값(끈 종류 없음)이다
_NOT_MUTED = " not (%(type)s = any(coalesce(s.muted_notification_types, '{}')))"
_NOT_DISMISSED = " (m.mark is null or m.mark <> 'not_interested')"
_ACTIVE = " o.status = 'active'"
_UNEXPIRED = " (o.deadline_at is null or o.deadline_at >= %(now)s)"
# KST 날짜에 알림 시각을 붙여 timestamptz로 만든다
_AT_HOUR = f"((%s)::date + time '{NOTIFY_HOUR:02d}:00') at time zone 'Asia/Seoul'"
_DEADLINE_DAY = "(o.deadline_at at time zone 'Asia/Seoul')::date - d.days"
_NEXT_DAY = "%(next_day)s"


def needed_phrases() -> dict[str, str]:
    """물어볼 항목 이름 + 목적격 조사. SQL에서 문구를 만들 수 있게 미리 붙여 둔다."""
    return {field: f"{label}{_particle(label)}" for field, label in INPUT_LABELS.items()}


def _particle(word: str) -> str:
    """목적격 조사: 받침이 있으면 "을", 없으면 "를"."""
    last = word[-1]
    if "가" <= last <= "힣":
        return "을" if (ord(last) - 0xAC00) % 28 else "를"
    return "을"


@dataclass(frozen=True)
class AssignmentNotice:
    """새 과제 알림 하나. 문구는 과목 이름을 아는 쪽(app/lms/sync.py)에서 만든다."""

    assignment_id: str
    title: str
    body: str


@dataclass(frozen=True)
class Due:
    """보낼 알림 하나. dismissed는 그새 숨긴 공고다(보내지 않고 둔다)."""

    id: str
    user_id: str
    type: str
    dismissed: bool


class NotificationRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    # ── 예약 ────────────────────────────────────────────────────────────────

    async def schedule(self, *, now: datetime) -> ScheduleResult:
        """공고 알림 세 종류를 예약하고, 조건에서 빠진 pending 행을 지운다."""
        today = now.astimezone(KST).date()
        next_day = today if now.astimezone(KST).hour < NOTIFY_HOUR else today + timedelta(days=1)
        common = {"now": now, "next_day": next_day}
        result = ScheduleResult(created=0, rescheduled=0, removed=0, by_type={})
        for kind, query, params in (
            ("new_eligible", _NEW_ELIGIBLE, {}),
            ("deadline_soon", _DEADLINE_SOON, {"days": list(DEADLINE_DAYS)}),
            ("profile_needed", _PROFILE_NEEDED, {"needed": Jsonb(needed_phrases())}),
        ):
            rows = await self._rows(query, {**common, **params, "type": kind})
            created = sum(1 for row in rows if row["inserted"])
            result.created += created
            result.rescheduled += len(rows) - created
            result.by_type[kind] = len(rows)
        result.removed = await self._removed(now)
        return result

    async def _removed(self, now: datetime) -> int:
        """보낼 이유가 없어진 pending 행을 지운다. 보낸 행은 알림함에 남으므로 건드리지 않는다."""
        cursor = await self.conn.execute(_STALE, {"now": now, "types": list(_KINDS)})
        return cursor.rowcount

    # ── LMS 과제 알림 (F-51) ────────────────────────────────────────────────

    async def add_assignment_notices(
        self, user_id: str, notices: Sequence[AssignmentNotice], *, now: datetime
    ) -> int:
        """새 과제 알림을 만든다. 만든 수를 돌려준다.

        공고 알림과 달리 KST 09:00을 기다리지 않는다 — 과제는 마감이 코앞일 수 있어서 찾은 때
        바로 보낸다(명세 10장 예시의 `new_material`도 그 시각이다). 끈 종류는 만들지 않고(F-45),
        같은 과제의 알림은 `dedupe_key`로 한 번만 만든다.
        """
        created = 0
        for notice in notices:
            cursor = await self.conn.execute(
                "insert into notifications (user_id, type, lms_assignment_id, title, body,"
                " scheduled_at, dedupe_key)"
                " select %(uid)s, %(type)s, %(aid)s::uuid, %(title)s, %(body)s, %(now)s,"
                # 키 꼴은 ERD 5장 표 그대로다: new_assignment:asg:{lms_assignment_id}
                " %(type)s || ':asg:' || %(aid)s"
                " where not exists (select 1 from user_settings s where s.user_id = %(uid)s"
                "   and %(type)s = any(coalesce(s.muted_notification_types, '{}')))"
                " on conflict (user_id, dedupe_key) do nothing",
                {
                    "uid": user_id,
                    "type": ASSIGNMENT_TYPE,
                    "aid": notice.assignment_id,
                    "title": notice.title,
                    "body": notice.body,
                    "now": now,
                },
            )
            created += max(cursor.rowcount, 0)
        return created

    async def drop_assignment_notices(self, user_id: str, assignment_ids: Sequence[str]) -> int:
        """제출한 과제의 **아직 보내지 않은** 알림을 지운다(명세 10장). 보낸 알림은 알림함에 남는다."""
        if not assignment_ids:
            return 0
        cursor = await self.conn.execute(
            "delete from notifications where user_id = %(uid)s"
            " and lms_assignment_id = any(%(ids)s::uuid[])"
            " and status = 'pending' and sent_at is null",
            {"uid": user_id, "ids": list(assignment_ids)},
        )
        return max(cursor.rowcount, 0)

    # ── 발송 ────────────────────────────────────────────────────────────────

    async def due(self, *, now: datetime, limit: int = SEND_LIMIT) -> list[Due]:
        """보낼 때가 된 pending 알림. 오래된 것부터다."""
        rows = await self._rows(_DUE, {"now": now, "limit": limit})
        return [
            Due(
                id=str(row["id"]),
                user_id=str(row["user_id"]),
                type=row["type"],
                dismissed=row["dismissed"],
            )
            for row in rows
        ]

    async def sent_today(self, *, now: datetime, kind: str) -> dict[str, int]:
        """오늘(KST) 사용자별로 이미 보낸 그 종류의 알림 수. 하루 한도를 보는 데 쓴다."""
        rows = await self._rows(
            "select user_id::text as user_id, count(*) as count from notifications"
            " where type = %(type)s and sent_at is not null"
            " and (sent_at at time zone 'Asia/Seoul')::date = %(today)s group by 1",
            {"type": kind, "today": now.astimezone(KST).date()},
        )
        return {row["user_id"]: int(row["count"]) for row in rows}

    async def pushable(self, ids: Sequence[str]) -> int:
        """그중 푸시를 보낼 수 있는 알림 수(구독이 있고 푸시를 끄지 않았다). 실제 발송은 F-33."""
        if not ids:
            return 0
        row = await self._row(
            "select count(*) as count from notifications n"
            " left join user_settings s on s.user_id = n.user_id"
            " where n.id = any(%(ids)s::uuid[]) and coalesce(s.push_enabled, true)"
            " and exists (select 1 from push_subscriptions q where q.user_id = n.user_id)",
            {"ids": list(ids)},
        )
        return int(row["count"]) if row else 0

    async def mark_sent(self, ids: Sequence[str], *, now: datetime) -> int:
        """보낸 알림을 닫는다. 푸시를 못 보내도 알림함에는 남아야 하므로 succeeded다(ERD)."""
        if not ids:
            return 0
        cursor = await self.conn.execute(
            "update notifications set status = 'succeeded', sent_at = %(now)s"
            " where id = any(%(ids)s::uuid[]) and status = 'pending'",
            {"ids": list(ids), "now": now},
        )
        return cursor.rowcount

    async def send(self, *, now: datetime, limit: int = SEND_LIMIT) -> SendResult:
        """보낼 때가 된 알림을 닫는다. 숨긴 공고와 하루 한도를 넘는 알림은 보내지 않고 둔다."""
        due = await self.due(now=now, limit=limit)
        already = await self.sent_today(now=now, kind="profile_needed")
        sending: list[str] = []
        for item in due:
            if item.dismissed:
                continue
            if item.type == "profile_needed":
                if already.get(item.user_id, 0) >= PROFILE_DAILY:
                    continue
                already[item.user_id] = already.get(item.user_id, 0) + 1
            sending.append(item.id)
        count = await self.pushable(sending)
        return SendResult(
            due=len(due),
            sent=await self.mark_sent(sending, now=now),
            pushable=count,
            skipped=len(due) - len(sending),
        )

    # ── 알림함 ──────────────────────────────────────────────────────────────

    async def unread(self, user_id: str, *, now: datetime) -> int:
        row = await self._row(
            "select count(*) as count from notifications where user_id = %(uid)s"
            " and read_at is null and scheduled_at <= %(now)s",
            {"uid": user_id, "now": now},
        )
        return int(row["count"]) if row else 0

    async def listing(
        self,
        user_id: str,
        *,
        now: datetime,
        unread_only: bool = False,
        limit: int = 20,
        cursor: str | None = None,
    ) -> NotificationList:
        """지난 알림을 최신순으로. 안 읽은 수는 필터와 상관없이 전체 기준이다."""
        scope = f"unread={unread_only}"
        after = ""
        params: dict[str, Any] = {"uid": user_id, "now": now, "limit": limit + 1}
        if cursor:
            found = decode_cursor(cursor)
            if found.scope != scope or found.value is None:
                raise ValueError("조건이 다른 목록의 cursor")
            after = " and (n.scheduled_at, n.id) < (%(at)s, %(id)s::uuid)"
            params |= {"at": found.value, "id": found.id}
        rows = await self._rows(
            _LIST.format(unread=" and n.read_at is null" if unread_only else "", after=after),
            params,
        )
        items = [_item(row) for row in rows[:limit]]
        last = rows[limit - 1] if len(rows) > limit else None
        return NotificationList(
            items=items,
            unread_count=await self.unread(user_id, now=now),
            next_cursor=encode_cursor(
                Cursor(scope=scope, value=last["scheduled_at"], id=str(last["id"]))
            )
            if last
            else None,
        )

    async def read(self, user_id: str, *, now: datetime, ids: Sequence[UUID] | None = None) -> int:
        """읽음 처리. ids가 없으면 전체다. 아직 보낼 때가 안 된 알림은 건드리지 않는다."""
        where = "" if ids is None else " and id = any(%(ids)s::uuid[])"
        await self.conn.execute(
            "update notifications set read_at = %(now)s where user_id = %(uid)s"
            " and read_at is null and scheduled_at <= %(now)s" + where,
            {"uid": user_id, "now": now, "ids": [str(item) for item in ids or ()]},
        )
        return await self.unread(user_id, now=now)

    # ── 조회 ────────────────────────────────────────────────────────────────

    async def _rows(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return await (await self.conn.execute(query, params)).fetchall()

    async def _row(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        return await (await self.conn.execute(query, params)).fetchone()


def _item(row: dict[str, Any]) -> NotificationItem:
    return NotificationItem(
        id=str(row["id"]),
        type=row["type"],
        title=row["title"],
        body=row["body"],
        scheduled_at=row["scheduled_at"].astimezone(KST),
        read_at=row["read_at"].astimezone(KST) if row["read_at"] else None,
        link=_link(row),
    )


def _link(row: dict[str, Any]) -> NotificationLink | None:
    """누르면 갈 곳. 대상 id가 하나도 없으면 링크가 없다(명세 10장)."""
    for kind, column in _LINKS:
        if row[column] is not None:
            return NotificationLink(
                type=kind,
                id=str(row[column]),
                course_id=str(row["course_id"]) if row["course_id"] else None,
                focus="profile_input" if row["type"] == "profile_needed" else None,
            )
    return None


_LINKS: tuple[tuple[str, str], ...] = (
    ("opportunity", "opportunity_id"),
    ("planner_task", "planner_task_id"),
    ("lms_assignment", "lms_assignment_id"),
    ("lms_module_item", "lms_module_item_id"),
    ("lms_announcement", "lms_announcement_id"),
)
_KINDS: tuple[str, ...] = ("new_eligible", "deadline_soon", "profile_needed")

# xmax = 0이면 이번에 넣은 행이다(고친 행은 그렇지 않다). 만든 수와 고친 수를 가른다
_INSERTED = " returning (xmax = 0) as inserted"
_COLUMNS = (
    "insert into notifications"
    " (user_id, type, opportunity_id, title, body, scheduled_at, dedupe_key)"
)

# 새 공고: 등록 7일 이내 + 적격 + 아직 상세를 열지 않음. 공고당 1회라 이미 있으면 그대로 둔다
_NEW_ELIGIBLE = (
    f"{_COLUMNS} select p.id, %(type)s, o.id, '{NEW_TITLE}', o.title,"
    f" {_AT_HOUR % _NEXT_DAY}, 'new_eligible:opp:' || o.id"
    f"{_JOINS} where{_ACTIVE} and{_UNEXPIRED} and{_NOT_DISMISSED} and{_VISIBLE} and{_NOT_MUTED}"
    " and e.status = 'eligible' and o.created_at >= %(now)s - make_interval(days => "
    f"{NEW_DAYS})"
    " and not exists (select 1 from opportunity_views v"
    " where v.user_id = p.id and v.opportunity_id = o.id)"
    f" and {_AT_HOUR % _NEXT_DAY} > %(now)s"
    " on conflict (user_id, dedupe_key) do nothing" + _INSERTED
)

# 마감 임박: 적격이거나 준비한 공고. 마감이 바뀌면 아직 보내지 않은 행의 시각만 고친다
_DEADLINE_SOON = (
    f"{_COLUMNS} select p.id, %(type)s, o.id, '{DEADLINE_TITLE}',"
    " o.title || ' · D-' || d.days,"
    f" {_AT_HOUR % _DEADLINE_DAY}, 'deadline_soon:opp:' || o.id || ':D-' || d.days"
    f"{_JOINS} cross join unnest(%(days)s::int[]) as d(days)"
    f" where{_ACTIVE} and{_UNEXPIRED} and{_NOT_DISMISSED} and{_VISIBLE} and{_NOT_MUTED}"
    " and o.deadline_at is not null and (e.status = 'eligible' or pl.id is not null)"
    f" and {_AT_HOUR % _DEADLINE_DAY} > %(now)s"
    " on conflict (user_id, dedupe_key) do update set scheduled_at = excluded.scheduled_at"
    " where notifications.status = 'pending'"
    " and notifications.scheduled_at <> excluded.scheduled_at" + _INSERTED
)

# 정보 필요: 판정 불가 + 물어볼 항목이 있음. 문구의 항목 이름은 조사까지 붙여 넘긴다
_PROFILE_NEEDED = (
    f"{_COLUMNS} select p.id, %(type)s, o.id, '{PROFILE_TITLE}',"
    f" o.title || ' · ' || (%(needed)s::jsonb ->> e.missing_fields[1]) || '{_NEEDED}',"
    f" {_AT_HOUR % _NEXT_DAY}, 'profile_needed:opp:' || o.id"
    f"{_JOINS} where{_ACTIVE} and{_UNEXPIRED} and{_NOT_DISMISSED} and{_VISIBLE} and{_NOT_MUTED}"
    " and e.status = 'undetermined' and coalesce(array_length(e.missing_fields, 1), 0) > 0"
    " and %(needed)s::jsonb ? e.missing_fields[1]"
    f" and {_AT_HOUR % _NEXT_DAY} > %(now)s"
    " on conflict (user_id, dedupe_key) do nothing" + _INSERTED
)

# 보낼 이유가 없어진 pending 행: 숨김·준비 취소·마감 지남·숨겨진 공고·이미 본 새 공고
_STALE = (
    # 지우는 대상(n)은 USING의 조인 조건에서 볼 수 없다. 그래서 과목 공개 범위는 exists로 본다
    "delete from notifications n using opportunities o"
    " where n.opportunity_id = o.id and n.status = 'pending' and n.type = any(%(types)s)"
    " and ("
    "   o.status <> 'active'"
    "   or (o.deadline_at is not null and o.deadline_at < %(now)s)"
    "   or exists (select 1 from opportunity_marks m where m.user_id = n.user_id"
    "              and m.opportunity_id = o.id and m.mark = 'not_interested')"
    "   or (o.source_type = 'poster' and o.uploaded_by is distinct from n.user_id)"
    "   or (o.visible_canvas_course_id is not null and not exists ("
    "        select 1 from lms_courses lc where lc.user_id = n.user_id"
    "        and lc.canvas_course_id = o.visible_canvas_course_id and lc.is_active))"
    "   or (n.type = 'deadline_soon' and not exists ("
    "        select 1 from eligibility_results e where e.user_id = n.user_id"
    "        and e.opportunity_id = o.id and e.status = 'eligible')"
    "      and not exists (select 1 from prep_plans pl where pl.user_id = n.user_id"
    "        and pl.opportunity_id = o.id))"
    "   or (n.type = 'new_eligible' and (exists ("
    "        select 1 from opportunity_views v where v.user_id = n.user_id"
    "        and v.opportunity_id = o.id)"
    # 판정이 바뀌어 적격이 아니게 되면 "지원할 수 있는 공고"가 아니다
    "      or not exists (select 1 from eligibility_results e where e.user_id = n.user_id"
    "        and e.opportunity_id = o.id and e.status = 'eligible')))"
    "   or (n.type = 'profile_needed' and not exists ("
    "        select 1 from eligibility_results e where e.user_id = n.user_id"
    "        and e.opportunity_id = o.id and e.status = 'undetermined'"
    "        and coalesce(array_length(e.missing_fields, 1), 0) > 0))"
    " )"
)


# 보낼 때가 된 알림. 숨긴 공고는 함께 알려 주고(보내지 않고 둔다) 오래된 것부터 본다
_DUE = (
    "select n.id, n.user_id, n.type, coalesce(m.mark = 'not_interested', false) as dismissed"
    " from notifications n"
    " left join opportunity_marks m"
    " on n.opportunity_id is not null and m.user_id = n.user_id"
    " and m.opportunity_id = n.opportunity_id"
    " where n.status = 'pending' and n.scheduled_at <= %(now)s"
    " order by n.scheduled_at, n.id limit %(limit)s"
)

_LIST = (
    "select n.id, n.type, n.title, n.body, n.scheduled_at, n.read_at, n.opportunity_id,"
    " n.planner_task_id, n.lms_assignment_id, n.lms_module_item_id, n.lms_announcement_id,"
    # lms_* 링크에는 과목 id를 함께 내려준다(명세 10장). 과제는 과목을 바로 가리키고,
    # 자료·공지는 Canvas 과목 번호라서 내 과목 행을 찾아야 한다
    " coalesce("
    "   (select a.lms_course_id from lms_assignments a where a.id = n.lms_assignment_id"
    "    and a.user_id = n.user_id),"
    "   (select lc.id from lms_module_items mi join lms_courses lc on lc.user_id = n.user_id"
    "    and lc.canvas_course_id = mi.canvas_course_id where mi.id = n.lms_module_item_id),"
    "   (select lc.id from lms_announcements an join lms_courses lc on lc.user_id = n.user_id"
    "    and lc.canvas_course_id = an.canvas_course_id where an.id = n.lms_announcement_id)"
    " ) as course_id"
    " from notifications n"
    " where n.user_id = %(uid)s and n.scheduled_at <= %(now)s{unread}{after}"
    " order by n.scheduled_at desc, n.id desc limit %(limit)s"
)


def get_notification_repo(
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> NotificationRepository:
    return NotificationRepository(conn)


NotificationRepoDep = Annotated[NotificationRepository, Depends(get_notification_repo)]
```

#### `api/app/repositories/runs.py`

```python
"""실행 조회(GET /runs/{id}, API 명세 11장). 실행·단계(tool_calls)와 작업별 결과.

결과는 따로 저장하지 않고 실행이 만든 행에서 다시 읽는다. 준비하기는 그 실행의 계획(prep_plans)·서류·할 일이고,
포스터 추출과 LMS 동기화는 그 실행의 도구 출력(`tool_calls.output`)이다. 동기화 수는 그 실행만의 사실이라
다른 표에서 다시 셀 수 없다(과제 표에는 어느 실행이 넣었는지 적지 않는다).
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection
from pydantic import ValidationError

from app.db import get_conn
from app.eligibility import KST
from app.schemas.lms import SAVE_TOOL, LmsSyncResult, SyncCounts
from app.schemas.opportunities import DocumentItem, ProcessStep
from app.schemas.posters import (
    EXTRACT_LABEL,
    DuplicateCandidate,
    PosterDraft,
    PosterExtractResult,
)
from app.schemas.posters import (
    EXTRACT_TOOL as POSTER_TOOL,
)
from app.schemas.prepare import PrepareResult, PrepTask, RunError

# 준비하기 단계 이름(화면의 처리 과정). 정해진 순서로 도는 단계라 chosen_by는 pipeline이다.
# 마감일 캘린더 등록은 준비하기 단계가 아니라 따로 부르는 API다(POST /calendar/events, F-32)
PREPARE_LABELS = {
    "get_document_guide": "필요 서류 확인",
    "build_prep_plan": "마감일에서 거꾸로 일정 짜기",
}
# 포스터 추출 단계 이름. Vision 한 번이라 단계도 하나다(app/posters/service.py)
POSTER_LABELS = {POSTER_TOOL: EXTRACT_LABEL}
# LMS 동기화 단계 이름(F-50 연결·F-51 동기화, app/lms/sync.py)
LMS_LABELS = {
    "check_lms_token": "토큰 확인",
    "fetch_lms_courses": "수강 과목 받기",
    "fetch_lms_assignments": "과제·제출 받기",
    SAVE_TOOL: "바뀐 것 저장",
}
FAILED_MESSAGE = "준비 일정을 만들지 못했어요. 잠시 후 다시 눌러 주세요."
# 코드를 남기지 못한 실패에 보여 줄 문구. 작업마다 할 말이 다르다(api/CLAUDE.md: 무엇을 하면 되는지)
FAILED_MESSAGES = {
    "lms_sync": "LMS 자료를 가져오지 못했어요. 잠시 후 다시 시도해 주세요.",
}
_CODED = re.compile(r"^([A-Z][A-Z_]+): (.+)$", re.S)  # agent_log.error_text의 "코드: 문구"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunRow:
    id: str
    user_id: str | None
    trigger_type: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    latency_ms: int | None
    error_message: str | None

    def error(self) -> RunError | None:
        """학생에게 보여 줄 실패 이유. ApiError로 남긴 것만 그대로 보여 주고 나머지는 내부 기록이다."""
        if self.status != "failed":
            return None
        if self.error_message and (match := _CODED.match(self.error_message)):
            return RunError(code=match.group(1), message=match.group(2))
        message = FAILED_MESSAGES.get(self.trigger_type, FAILED_MESSAGE)
        return RunError(code="INTERNAL_ERROR", message=message)


def _label(tool_name: str) -> str:
    """화면에 보이는 단계 이름. 작업마다 표가 다르고, 표에 없으면 도구 이름 그대로다."""
    return (
        PREPARE_LABELS.get(tool_name)
        or POSTER_LABELS.get(tool_name)
        or LMS_LABELS.get(tool_name)
        or tool_name
    )


class RunRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def run(self, run_id: str) -> RunRow | None:
        row = await (
            await self.conn.execute(
                "select id, user_id, trigger_type, status::text as status, started_at, finished_at,"
                " latency_ms, error_message from agent_runs where id = %s",
                (run_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return RunRow(
            id=str(row["id"]),
            user_id=str(row["user_id"]) if row["user_id"] else None,
            trigger_type=row["trigger_type"],
            status=row["status"],
            started_at=_kst(row["started_at"]),
            finished_at=_kst(row["finished_at"]),
            latency_ms=row["latency_ms"],
            error_message=row["error_message"],
        )

    async def steps(self, run_id: str) -> list[ProcessStep]:
        rows = await (
            await self.conn.execute(
                "select seq, tool_name, status::text as status, latency_ms from tool_calls"
                " where run_id = %s order by seq, id",
                (run_id,),
            )
        ).fetchall()
        return [
            ProcessStep(
                seq=row["seq"],
                tool=row["tool_name"],
                label=_label(row["tool_name"]),
                status=row["status"],
                latency_ms=row["latency_ms"],
                chosen_by="pipeline",
                note=None,
            )
            for row in rows
        ]

    async def prepare_result(self, user_id: str, run_id: str) -> PrepareResult | None:
        """그 실행이 만든 내 계획. 없으면(지워짐) None."""
        plan = await (
            await self.conn.execute(
                "select id, opportunity_id from prep_plans where agent_run_id = %s and user_id = %s",
                (run_id, user_id),
            )
        ).fetchone()
        if plan is None:
            return None
        params: dict[str, Any] = {"plan": plan["id"], "oid": plan["opportunity_id"]}
        documents = await (
            await self.conn.execute(
                "select d.id::text as id, d.name, d.issuer, d.how_to, d.lead_days, d.effort_minutes,"
                " d.form_url, coalesce(d.is_required, true) as is_required,"
                " t.id::text as task_id, t.is_done"
                " from opportunity_documents d left join planner_tasks t"
                " on t.prep_plan_id = %(plan)s and t.document_id = d.id"
                " where d.opportunity_id = %(oid)s"
                " order by coalesce(d.is_required, true) desc, d.name, d.id",
                params,
            )
        ).fetchall()
        tasks = await (
            await self.conn.execute(
                "select id::text as id, title, due_date, document_id::text as document_id"
                " from planner_tasks where prep_plan_id = %(plan)s order by sort_order, due_date, id",
                params,
            )
        ).fetchall()
        return PrepareResult(
            prep_plan_id=str(plan["id"]),
            documents=[DocumentItem(**row) for row in documents],
            tasks=[PrepTask(**row) for row in tasks],
            # 마감일 캘린더는 따로 등록한다(POST /calendar/events). 준비하기 결과에는 담지 않는다
            calendar_event=None,
            calendar_error=None,
        )

    async def lms_sync_result(self, user_id: str, run_id: str) -> LmsSyncResult | None:
        """그 동기화가 바꾼 것(명세 8장). 저장 단계가 없으면(F-50 연결 실행 등) None이다."""
        row = await (
            await self.conn.execute(
                "select t.output from tool_calls t join agent_runs r on r.id = t.run_id"
                " where t.run_id = %s and r.user_id = %s and t.tool_name = %s"
                " order by t.seq desc, t.id desc limit 1",
                (run_id, user_id, SAVE_TOOL),
            )
        ).fetchone()
        output = row["output"] if row else None
        if not isinstance(output, dict):
            return None
        try:
            return LmsSyncResult(
                courses=int(output["courses"]),
                assignments=SyncCounts(
                    new=int(output["new"]),
                    due_changed=int(output["due_changed"]),
                    submitted=int(output["submitted"]),
                ),
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("동기화 결과 모양이 달라 읽지 못했어요: run %s", run_id)
            return None

    async def poster_result(self, user_id: str, run_id: str) -> PosterExtractResult | None:
        """그 실행이 만든 초안. 기록이 지워졌거나 모양이 달라졌으면 None이다."""
        row = await (
            await self.conn.execute(
                "select t.output from tool_calls t join agent_runs r on r.id = t.run_id"
                " where t.run_id = %s and r.user_id = %s and t.tool_name = %s"
                " order by t.seq desc, t.id desc limit 1",
                (run_id, user_id, POSTER_TOOL),
            )
        ).fetchone()
        output = row["output"] if row else None
        if not isinstance(output, dict) or "draft" not in output:
            return None
        try:
            draft = PosterDraft.model_validate(output["draft"])
        except ValidationError:
            logger.warning("포스터 초안 모양이 달라 읽지 못했어요: run %s", run_id)
            return None
        candidate = output.get("duplicate_candidate")
        duplicate = None
        if isinstance(candidate, dict):
            try:
                duplicate = DuplicateCandidate.model_validate(candidate)
            except ValidationError:
                duplicate = None
        return PosterExtractResult(draft=draft, duplicate_candidate=duplicate)


def _kst(value: datetime | None) -> datetime | None:
    return value.astimezone(KST) if value else None


def get_run_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> RunRepository:
    return RunRepository(conn)


RunRepoDep = Annotated[RunRepository, Depends(get_run_repo)]
```

#### `api/app/routers/lms.py`

```python
"""LearningX 연결·과목·과제 (F-50·F-51·F-14, API 명세 9장).

토큰 연결·상태·해제, 수강 과목 목록, 동기화(202 + `run_id`), 과제 목록이다.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.auth import CurrentUserDep
from app.clock import NowDep
from app.errors import ApiError
from app.lms.service import NOT_CONNECTED, LmsServiceDep
from app.lms.sync import LmsSyncServiceDep
from app.repositories.lms import LmsRepoDep
from app.schemas.lms import (
    AssignmentList,
    AssignmentState,
    ConnectionView,
    ConnectRequest,
    ConnectResult,
    CourseList,
    SyncResponse,
    SyncSkipped,
)

router = APIRouter(prefix="/lms", tags=["LMS"])


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


@router.post(
    "/sync",
    status_code=202,
    response_model=SyncResponse,
    # 건너뛴 응답도 계약에 있다(명세 9장). 생성되는 클라이언트가 두 모양을 다 보게 적어 둔다
    responses={200: {"model": SyncSkipped, "description": "마지막 동기화가 5분 안이라 건너뜀"}},
)
async def sync(
    user: CurrentUserDep, service: LmsSyncServiceDep, now: NowDep, response: Response
) -> SyncResponse:
    """과목·과제를 다시 받는다(F-51). 결과는 `GET /runs/{run_id}`로 본다.

    대시보드를 열 때 프론트가 부른다. 마지막 동기화가 5분 안이면 LearningX를 부르지 않고 200으로
    건너뛴 사실을 알려 준다. 연결이 없으면 404 LMS_NOT_CONNECTED다.
    """
    result = await service.start(user.id, now=now)
    if isinstance(result, SyncSkipped):
        response.status_code = 200
    return result


@router.get("/assignments", response_model=AssignmentList)
async def assignments(
    user: CurrentUserDep,
    repo: LmsRepoDep,
    state: AssignmentState = "open",
    lms_course_id: Annotated[UUID | None, Query(description="과목 하나만 볼 때")] = None,
) -> AssignmentList:
    """과제 목록(F-51). 마감이 가까운 순이고, 마감이 없는 과제는 뒤에 온다.

    `state`를 주지 않으면 아직 내지 않은 과제(`open`)만 준다. LMS에서 사라진 과제는 빠진다.
    """
    return AssignmentList(
        items=await repo.assignments(
            user.id,
            state=state,
            course_id=str(lms_course_id) if lms_course_id else None,
        )
    )
```

#### `api/app/routers/internal.py`

```python
"""내부·운영 API (API 명세 12장). 사용자 토큰이 아니라 서비스 키(`X-Internal-Key`)로만 부른다.

- `GET /internal/metrics` 기간별 성공률·응답시간·호출비용 + 판정 혼동행렬 + 제품 지표 5개(PRD 8장)
- `POST /internal/eval/run` 테스트 시나리오를 돌린다(CLI `python -m app.eval.cli`와 같은 함수)
- `POST /internal/jobs/lms-sync` LMS 연결된 사용자 동기화(30분마다)
- `POST /internal/jobs/schedule-notifications` 공고 알림 예약(하루 한 번)
- `POST /internal/jobs/send-notifications` 예약된 알림 발송(5분마다)

키가 틀렸을 때와 서버에 키가 없을 때 모두 403이다. 부른 쪽에 서버 설정 상태를 알려 주지 않는다.
키 값은 응답·로그에 남기지 않는다.
"""

import logging
import secrets
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query

from app.clock import NowDep
from app.config import Settings, get_settings
from app.eligibility import KST
from app.errors import ApiError
from app.lms.sync import LmsSyncServiceDep
from app.repositories.metrics import MetricsRepoDep
from app.repositories.notifications import NotificationRepoDep
from app.schemas.lms import SyncJobResult
from app.schemas.metrics import (
    EvalCheck,
    EvalRunRequest,
    EvalRunResult,
    EvalScenarioResult,
    Latency,
    Metrics,
)
from app.schemas.notifications import ScheduleResult, SendResult

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["내부"])

DEFAULT_DAYS = 30  # 기간을 주지 않으면 오늘까지 이만큼(KST)
FORBIDDEN = "이 API는 서비스 키로만 부를 수 있어요."


def internal_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_internal_key: Annotated[str | None, Header()] = None,
) -> None:
    """서비스 키 검증. 같은 길이의 틀린 키로 시간을 재지 못하게 compare_digest로 본다."""
    expected = settings.internal_api_key
    if not expected:
        # 서버에 키가 없으면 아무도 부를 수 없다. 부른 쪽에는 그 사실을 알려 주지 않는다
        logger.warning("내부 API 키가 비어 있어요(INTERNAL_API_KEY). /internal/*는 모두 403이에요")
        raise ApiError(403, "FORBIDDEN", FORBIDDEN)
    if not x_internal_key or not secrets.compare_digest(x_internal_key, expected):
        raise ApiError(403, "FORBIDDEN", FORBIDDEN)


InternalKeyDep = Annotated[None, Depends(internal_key)]


@router.get("/metrics", response_model=Metrics)
async def read_metrics(
    repo: MetricsRepoDep,
    now: NowDep,
    _: InternalKeyDep,
    from_: Annotated[str | None, Query(alias="from", description="YYYY-MM-DD(KST)")] = None,
    to: Annotated[str | None, Query(description="YYYY-MM-DD(KST)")] = None,
) -> Metrics:
    """기간 지표. 기간을 주지 않으면 오늘까지 30일이다(KST 날짜, 양 끝 포함).

    판정 불가 비율만 기간이 아니라 지금 저장된 판정 기준이다(저장소 머리말).
    """
    today = now.astimezone(KST).date()
    end = _day(to, "to") if to else today
    start = _day(from_, "from") if from_ else end - timedelta(days=DEFAULT_DAYS - 1)
    if end < start:
        raise _invalid({"to": "끝 날짜는 시작 날짜보다 뒤여야 해요."})
    return await repo.metrics((start, end))


@router.post("/jobs/lms-sync", response_model=SyncJobResult)
async def lms_sync(service: LmsSyncServiceDep, now: NowDep, _: InternalKeyDep) -> SyncJobResult:
    """연결된 사용자의 과목·과제를 동기화한다. 30분마다 도는 작업이다(F-51).

    한 사람이 실패해도 다음 사람을 계속한다(실패는 그 사람의 실행 기록에 남는다). 토큰이 막힌
    사람은 연결을 `error`로 바꿔 화면이 다시 연결을 안내한다. 최근에 동기화한 사람은 건너뛴다.
    """
    outcome = await service.sync_all(now=now)
    return SyncJobResult(
        users=outcome.users,
        synced=outcome.synced,
        failed=outcome.failed,
        skipped=outcome.skipped,
        new_assignments=outcome.new_assignments,
        due_changed=outcome.due_changed,
        submitted=outcome.submitted,
    )


@router.post("/jobs/schedule-notifications", response_model=ScheduleResult)
async def schedule_notifications(
    repo: NotificationRepoDep, now: NowDep, _: InternalKeyDep
) -> ScheduleResult:
    """공고 알림(새 적격·마감 임박·정보 필요)을 예약한다. 하루 한 번 도는 작업이다.

    같은 알림은 한 번만 만들고(사용자당 `dedupe_key` 1행), 마감이 바뀌면 아직 보내지 않은 행의
    시각만 고친다. 보낼 이유가 없어진 행은 지운다(저장소 머리말).
    """
    return await repo.schedule(now=now)


@router.post("/jobs/send-notifications", response_model=SendResult)
async def send_notifications(
    repo: NotificationRepoDep, now: NowDep, _: InternalKeyDep
) -> SendResult:
    """보낼 때가 된 알림을 보낸다. 5분마다 도는 작업이다.

    숨긴 공고의 알림과 하루 한도를 넘는 알림은 보내지 않고 둔다. 푸시 구독이 없거나 푸시를 끈
    사용자는 푸시만 건너뛰고 알림함에는 남는다. 실제 푸시 발송은 F-33이다.
    """
    return await repo.send(now=now)


@router.post("/eval/run", response_model=EvalRunResult)
async def run_eval(
    body: EvalRunRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    _: InternalKeyDep,
) -> EvalRunResult:
    """테스트 시나리오를 돌린다(PRD 8장). 돌린 기록은 `agent_runs`에 남고 지표 집계가 읽는다.

    DB 연결을 쥐지 않는다(저장소 의존이 없다). 시나리오는 자기 연결·풀을 따로 열고, 끝나면 만든
    사용자·공고를 지운다. 그래서 **시험용 DB**에서만 돌 수 있다.
    """
    # app.eval은 앱을 만들어 쓰므로(app.main) 모듈 맨 위에서 가져오면 순환 import가 된다
    from app.eval import pick, run_scenarios
    from app.eval.world import DEFAULT_NOW

    try:
        scenarios = pick(body.scenario_codes)
    except KeyError as exc:
        raise _invalid({"scenario_codes": str(exc).strip("'")}) from exc
    if not settings.database_url:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    try:
        report = await run_scenarios(settings.database_url, scenarios, now=body.now or DEFAULT_NOW)
    except RuntimeError as exc:  # 실제 Supabase DB면 돌리지 않는다(app/eval/world.py)
        logger.warning("시나리오를 돌리지 않았어요: %s", exc)
        raise ApiError(
            409, "EVAL_NOT_ALLOWED", "시나리오는 시험용 DB에서만 돌릴 수 있어요."
        ) from exc
    return EvalRunResult(
        now=report.now,
        priced_on=report.priced_on,
        scenarios=report.total,
        passed=report.passed,
        success_rate=report.success_rate,
        latency=Latency(p50_ms=report.p50, p95_ms=report.p95),
        cost_usd=float(report.cost_usd),
        llm_calls=report.llm_calls,
        results=[
            EvalScenarioResult(
                code=result.code,
                title=result.title,
                ok=result.ok,
                latency_ms=result.latency_ms,
                api_ms=result.api_ms,
                run_id=result.run_id,
                cost_usd=float(result.cost_usd),
                llm_calls=result.llm_calls,
                checks=[
                    EvalCheck(
                        what=check.what,
                        expected=check.expected,
                        actual=check.actual,
                        ok=check.ok,
                        kind=check.kind,
                    )
                    for check in result.checks
                ],
                error=result.error,
            )
            for result in report.results
        ],
    )


def _day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _invalid({field: "날짜를 YYYY-MM-DD로 적어 주세요."}) from None


def _invalid(fields: dict[str, str]) -> ApiError:
    return ApiError(422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": fields})
```

#### `api/app/routers/runs.py`

```python
from uuid import UUID

from fastapi import APIRouter

from app.auth import CurrentUserDep
from app.errors import ApiError
from app.repositories.runs import RunRepoDep
from app.schemas.prepare import RunResult, RunView

router = APIRouter(prefix="/runs", tags=["실행"])


@router.get("/{run_id}", response_model=RunView)
async def read_run(run_id: UUID, user: CurrentUserDep, repo: RunRepoDep) -> RunView:
    """실행 진행·결과(API 명세 11장). 본인 실행만 본다. 배치 실행은 403, 남의 실행·없는 실행은 404다.

    steps는 처리 과정(F-42)이고, 끝나면 result나 error(코드·문구)가 붙는다. result는 kind로 가린다:
    준비하기는 계획·서류·할 일(prepare), 포스터 추출은 공고 초안과 중복 후보(poster_extract),
    LMS 동기화는 과목·과제 수(lms_sync)다.
    """
    run = await repo.run(str(run_id))
    if run is not None and run.user_id is None:
        raise ApiError(403, "FORBIDDEN", "이 실행은 볼 수 없어요.")
    if run is None or run.user_id != user.id:
        raise ApiError(404, "NOT_FOUND", "실행을 찾을 수 없어요.")
    result: RunResult | None = None
    if run.status == "succeeded" and run.trigger_type == "prepare":
        result = await repo.prepare_result(user.id, run.id)
    elif run.status == "succeeded" and run.trigger_type == "poster_upload":
        result = await repo.poster_result(user.id, run.id)
    elif run.status == "succeeded" and run.trigger_type == "lms_sync":
        result = await repo.lms_sync_result(user.id, run.id)
    return RunView(
        id=run.id,
        trigger_type=run.trigger_type,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        latency_ms=run.latency_ms,
        steps=await repo.steps(run.id),
        result=result,
        error=run.error(),
    )
```

#### `api/app/schemas/lms.py`

```python
"""LearningX 연결·과목·과제 (F-50·F-51·F-14, API 명세 8장).

토큰은 요청으로만 받고 응답에는 끝 4자리만 넣는다(`token_last4`). 과목 이름은 LearningX가 준
`202620HY23525_데이터베이스`를 그대로 두고, 화면에 쓸 짧은 이름(`short_name`)과 포털 계획서 링크를
함께 내려준다. 계획서 링크는 사용자 브라우저에서만 연다(서버는 포털에 요청하지 않는다).

과제는 마감(`due_at`)이 없을 수 있다(녹화 17건 중 5건은 `due_at`이 null이고 `lock_at`만 있어서 그걸 쓴다).
`submission_state`는 LearningX가 준 값 그대로다(`unsubmitted`·`submitted`·`graded`·`pending_review`).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# DB enum(lms_connection_status)·GET /me의 lms.status·web 타입과 같은 세 가지
ConnectionStatus = Literal["active", "error", "disconnected"]
# DB enum(lms_submission_state)·web 타입과 같은 네 가지. LearningX가 준 값을 그대로 쓴다
SubmissionState = Literal["unsubmitted", "submitted", "graded", "pending_review"]
# `GET /lms/assignments?state=`. 주지 않으면 open이다(화면이 "할 일"로 먼저 보여 준다)
AssignmentState = Literal["open", "submitted", "all"]
# 동기화 결과를 남기는 도구 이름. app/lms/sync.py가 쓰고 GET /runs/{id}가 읽는다
SAVE_TOOL = "save_lms_sync"


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


class SyncStarted(BaseModel):
    """`POST /lms/sync` 202. 결과는 `GET /runs/{run_id}`로 본다."""

    run_id: str
    status: Literal["running"]


class SyncSkipped(BaseModel):
    """`POST /lms/sync` 200. 마지막 동기화가 얼마 안 돼 건너뛴 응답이다(명세 8장)."""

    skipped: Literal[True] = True
    last_synced_at: datetime | None  # KST 오프셋


# 같은 엔드포인트가 202·200으로 서로 다른 모양을 준다(명세 8장). 두 모양은 겹치는 칸이 없다
SyncResponse = SyncStarted | SyncSkipped


class SyncCounts(BaseModel):
    """이번 동기화에서 과제가 어떻게 바뀌었는지."""

    new: int
    due_changed: int
    submitted: int


class LmsSyncResult(BaseModel):
    """`GET /runs/{id}`의 동기화 결과(명세 8장). 주차 항목·공지는 F-52·F-53이라 아직 0이다."""

    kind: Literal["lms_sync"] = "lms_sync"
    courses: int
    assignments: SyncCounts
    new_module_items: int = 0
    new_announcements: int = 0


class AssignmentCourse(BaseModel):
    id: str
    short_name: str


class AssignmentItem(BaseModel):
    id: str
    course: AssignmentCourse
    title: str
    due_at: datetime | None  # KST 오프셋. 마감이 없는 과제는 null
    submission_state: SubmissionState
    html_url: str | None
    planner_task_id: str | None
    calendar_registered: bool


class AssignmentList(BaseModel):
    items: list[AssignmentItem]


class SyncJobResult(BaseModel):
    """`POST /internal/jobs/lms-sync`(30분 배치) 결과. 실패한 사용자는 다음 차례에 다시 본다."""

    users: int  # 이번에 본 사용자 수(최근에 동기화한 사람은 빼고 센다)
    synced: int
    failed: int
    skipped: int  # 그새 대시보드가 동기화를 시작했거나 연결이 사라진 사람
    new_assignments: int
    due_changed: int
    submitted: int
```

#### `api/app/schemas/prepare.py`

```python
"""준비하기(F-30·F-31)와 실행 조회(GET /runs/{id}). API 명세 7장·11장."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.calendar import CalendarEventView
from app.schemas.lms import LmsSyncResult
from app.schemas.opportunities import DocumentItem, ProcessStep, RunStatus
from app.schemas.posters import PosterExtractResult


class PrepareRequest(BaseModel):
    # 마감일 캘린더 등록은 준비하기와 따로 한다(POST /calendar/events, F-32)
    target_date: date | None = None  # 상시 공고(마감일 없음)는 꼭 준다. 오늘이나 그 뒤
    force: bool = False  # 지원 어려움 공고를 "그래도 준비하기"로 다시 보낼 때


class PrepareStarted(BaseModel):
    run_id: str | None  # 이미 준비한 공고는 그 준비 실행. 실행 기록이 지워졌으면 null
    status: RunStatus  # 처음이면 running(202), 이미 준비했으면 succeeded(200)


class PrepTask(BaseModel):
    id: str
    title: str  # "재학증명서 준비" · "신청 제출"
    due_date: date
    document_id: str | None


class PrepareResult(BaseModel):
    kind: Literal["prepare"] = "prepare"
    prep_plan_id: str
    documents: list[DocumentItem]  # 상세의 documents와 같은 모양(서류 할 일 id·완료 포함)
    tasks: list[PrepTask]  # 서류 순서대로, 마지막이 신청 제출
    # 마감일 캘린더는 따로 등록한다(F-32). 준비하기 결과에는 담지 않는다
    calendar_event: CalendarEventView | None
    calendar_error: str | None


class RunError(BaseModel):
    code: str
    message: str


RunResult = Annotated[
    PrepareResult | PosterExtractResult | LmsSyncResult, Field(discriminator="kind")
]


class RunView(BaseModel):
    id: str
    trigger_type: str
    status: RunStatus
    started_at: datetime | None  # KST 오프셋(+09:00)
    finished_at: datetime | None
    latency_ms: int | None
    steps: list[ProcessStep]
    # 작업별 결과. kind로 가린다(prepare 준비하기, poster_extract 포스터 추출, lms_sync 동기화)
    result: RunResult | None
    error: RunError | None
```

### api (새 테스트)

#### `api/tests/test_lms_assignments.py`

```python
"""Canvas 과제 응답 읽기(F-51). DB·네트워크 없이 돈다.

녹화(과제 17건)에서 확정한 규칙만 본다: 마감은 `due_at ?? lock_at`, 제출은 `submission.workflow_state`,
아직 열지 않은 과제는 건너뛴다.
"""

from datetime import UTC, datetime
from typing import Any

from app.lms.assignments import NO_TITLE, assignment, assignments, moment
from tests.lms_samples import DB_ASSIGNMENTS, DRAFT_ASSIGNMENT, HOMEWORK, LAB_REPORT, QUIZ


def test_it_reads_a_homework_with_a_due_date() -> None:
    one = assignment(HOMEWORK)
    assert one is not None
    assert one.canvas_assignment_id == 2811242
    assert one.title == "실습 2주차 결과 제출"
    assert one.due_at == datetime(2026, 10, 20, 14, 59, 59, tzinfo=UTC)  # 20일 23:59:59 KST
    assert one.html_url == "https://lms.test/courses/214023/assignments/2811242"
    assert one.submission_state == "unsubmitted"
    assert one.submitted_at is None
    assert not one.submitted


def test_the_deadline_falls_back_to_lock_at() -> None:
    """녹화 17건 중 5건은 due_at이 null이고 lock_at만 있었다(명세 9장)."""
    one = assignment(LAB_REPORT)
    assert one is not None
    assert LAB_REPORT["due_at"] is None
    assert one.due_at == datetime(2026, 10, 18, 14, 59, 59, tzinfo=UTC)


def test_a_submitted_assignment_keeps_the_time_it_was_submitted() -> None:
    one = assignment(LAB_REPORT)
    assert one is not None
    assert one.submission_state == "submitted"
    assert one.submitted_at == datetime(2026, 10, 15, 23, 2, 17, tzinfo=UTC)
    assert one.submitted


def test_a_quiz_comes_back_already_graded() -> None:
    """퀴즈는 자동 채점돼 graded로 온다. 그래도 '제출한 과제'다."""
    one = assignment(QUIZ)
    assert one is not None
    assert one.submission_state == "graded"
    assert one.submitted


def test_it_skips_an_assignment_that_is_not_published_yet() -> None:
    assert assignment(DRAFT_ASSIGNMENT) is None
    titles = [one.title for one in assignments(DB_ASSIGNMENTS)]
    assert titles == ["실습 2주차 결과 제출", "실습 3주차 결과 제출"]


def test_it_does_not_use_the_course_wide_submitted_flag() -> None:
    """has_submitted_submissions는 과목 전체 기준이라 내가 내지 않은 과제에도 true다(명세 9장)."""
    assert HOMEWORK["has_submitted_submissions"] is True
    one = assignment(HOMEWORK)
    assert one is not None and not one.submitted


def test_an_unknown_submission_state_is_treated_as_not_submitted() -> None:
    """DB enum에 없는 값을 그대로 넣으면 저장이 터진다. 모르는 값은 unsubmitted로 둔다."""
    raw: dict[str, Any] = {**HOMEWORK, "submission": {"workflow_state": "pending_upload"}}
    one = assignment(raw)
    assert one is not None
    assert one.submission_state == "unsubmitted"
    assert one.submitted_at is None


def test_a_submission_can_be_missing_altogether() -> None:
    raw = {key: value for key, value in HOMEWORK.items() if key != "submission"}
    one = assignment(raw)
    assert one is not None
    assert one.submission_state == "unsubmitted"


def test_pending_review_counts_as_submitted() -> None:
    """녹화에서는 못 봤지만 DB enum에 있는 값이다. 냈고 손 채점만 남은 상태라 제출로 센다 —
    제출로 보지 않으면 할 일이 끝나지 않고 알림도 멈추지 않는다."""
    raw: dict[str, Any] = {
        **HOMEWORK,
        "submission": {"workflow_state": "pending_review", "submitted_at": "2026-10-19T05:00:00Z"},
    }
    one = assignment(raw)
    assert one is not None
    assert one.submission_state == "pending_review"
    assert one.submitted
    assert one.submitted_at == datetime(2026, 10, 19, 5, 0, tzinfo=UTC)


def test_it_skips_items_without_a_usable_number() -> None:
    assert assignment({"name": "번호 없음"}) is None
    assert assignment({**HOMEWORK, "id": True}) is None  # bool은 int이지만 번호가 아니다
    assert assignment({**HOMEWORK, "id": 2**63}) is None  # bigint를 넘는 번호
    assert assignment("과제가 아니다") is None


def test_an_assignment_without_a_name_is_kept_with_a_placeholder() -> None:
    """이름이 빈 과제도 할 일이라 버리지 않는다. 화면에 (제목 없음)으로 보인다."""
    one = assignment({**HOMEWORK, "name": "   "})
    assert one is not None
    assert one.title == NO_TITLE


def test_it_reads_times_without_a_zone_as_utc() -> None:
    assert moment("2026-10-20T14:59:59Z") == datetime(2026, 10, 20, 14, 59, 59, tzinfo=UTC)
    assert moment("2026-10-20T14:59:59") == datetime(2026, 10, 20, 14, 59, 59, tzinfo=UTC)
    assert moment("2026-10-20T23:59:59+09:00") == datetime(2026, 10, 20, 14, 59, 59, tzinfo=UTC)


def test_a_broken_time_is_left_empty_instead_of_failing() -> None:
    assert moment("어제") is None
    assert moment("") is None
    assert moment(None) is None
    assert moment(1760000000) is None
    one = assignment({**HOMEWORK, "due_at": "곧", "lock_at": None})
    assert one is not None and one.due_at is None
```

#### `api/tests/test_lms_sync.py`

```python
"""LMS 동기화(F-51): `POST /lms/sync`·`GET /lms/assignments`·30분 배치.

LearningX 호출은 respx로 가로채고 저장소는 가짜로 바꿔 끼운다(DB·네트워크 없이 돈다).
SQL은 test_lms_db.py가 실제 스키마로 본다.
"""

from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.agent_log import using
from app.background import InlineRunner
from app.clock import current_time
from app.config import Settings, get_settings
from app.crypto import encrypt
from app.db import get_log_connect
from app.eligibility import KST
from app.lms.assignments import CanvasAssignment
from app.lms.client import LearningXClient
from app.lms.sync import LmsSyncService, Repos, SyncJob, get_lms_sync_service
from app.main import create_app
from app.repositories.lms import (
    AssignmentChanges,
    Connection,
    CourseRow,
    SavedAssignment,
    get_lms_repo,
)
from app.repositories.notifications import AssignmentNotice
from app.repositories.runs import get_run_repo
from app.schemas.lms import AssignmentCourse, AssignmentItem, LmsSyncResult, SyncCounts
from tests.conftest import USER_ID, make_token
from tests.fakes import FakeLogConnection
from tests.lms_samples import COURSES, DB_ASSIGNMENTS, ML_ASSIGNMENTS
from tests.prepare_fakes import FakeRunRepository, run_row

SYNC = "/api/v1/lms/sync"
ASSIGNMENTS = "/api/v1/lms/assignments"
BASE = "https://lms.test"
TOKEN = "18742~pAtB1g3TestTokenValue0000000000"
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)  # 2026-10-16 12:00 KST
INTERNAL_KEY = "test-internal-key"
JOB = "/api/v1/internal/jobs/lms-sync"
DB_COURSE = CourseRow(id="course-db", canvas_course_id=214023, short_name="데이터베이스")
ML_COURSE = CourseRow(id="course-ml", canvas_course_id=216515, short_name="기계학습")


@dataclass
class FakeLms:
    """과제·과목 저장을 기억하는 가짜 저장소. 실제 SQL은 test_lms_db.py가 본다."""

    connection_row: Connection | None = None
    courses: list[CourseRow] = field(default_factory=lambda: [DB_COURSE, ML_COURSE])
    changes: dict[str, AssignmentChanges] = field(default_factory=dict)  # course_id → 돌려줄 변화
    saved: list[tuple[str, list[CanvasAssignment]]] = field(default_factory=list)
    planned: list[AssignmentChanges] = field(default_factory=list)
    synced_at: datetime | None = None
    error: str | None = None
    claims: list[str] = field(default_factory=list)
    rows: dict[str, Connection] = field(default_factory=dict)
    users: list[str] = field(default_factory=list)
    before: datetime | None = None

    def _row(self, user_id: str) -> Connection | None:
        """사용자마다 따로 둔다. 배치에서 앞사람의 claim이 뒷사람을 막지 않게."""
        if user_id == USER_ID:
            return self.connection_row
        return self.rows.get(user_id, self.connection_row)

    def _put(self, user_id: str, row: Connection) -> None:
        if user_id == USER_ID:
            self.connection_row = row
        else:
            self.rows[user_id] = row

    async def connection(self, user_id: str) -> Connection | None:
        assert user_id == USER_ID or user_id in self.users
        return self._row(user_id)

    async def claim_sync(self, user_id: str, *, now: datetime, before: datetime) -> bool:
        """실제 SQL과 같은 뜻: 연결이 있고 before 뒤에 받지 않았으면 시각을 밀고 True."""
        row = self._row(user_id)
        if row is None or row.status == "disconnected":
            return False
        if row.last_synced_at is not None and row.last_synced_at > before:
            return False
        self.claims.append(user_id)
        self._put(user_id, Connection(**{**row.__dict__, "last_synced_at": now}))
        return True

    async def save_courses(
        self, user_id: str, courses: list[dict[str, Any]], *, now: datetime
    ) -> int:
        assert user_id == USER_ID or user_id in self.users
        return len(courses)

    async def active_courses(self, user_id: str) -> list[CourseRow]:
        return list(self.courses)

    async def save_assignments(
        self, user_id: str, course_id: str, items: list[CanvasAssignment], *, now: datetime
    ) -> AssignmentChanges:
        assert user_id == USER_ID or user_id in self.users
        self.saved.append((course_id, items))
        return self.changes.get(course_id, AssignmentChanges())

    async def sync_planner(self, user_id: str, changes: AssignmentChanges, *, now: datetime) -> int:
        self.planned.append(changes)
        return len(changes.created)

    async def touch_synced(self, user_id: str, *, now: datetime) -> None:
        self.synced_at = now

    async def mark_error(self, user_id: str, message: str) -> None:
        self.error = message

    async def connected_users(self, *, before: datetime, limit: int) -> list[str]:
        self.before = before
        return list(self.users)

    async def assignments(
        self, user_id: str, *, state: str = "open", course_id: str | None = None
    ) -> list[AssignmentItem]:
        assert user_id == USER_ID
        self.asked = (state, course_id)  # type: ignore[attr-defined]
        return [
            AssignmentItem(
                id="assignment-1",
                course=AssignmentCourse(id=DB_COURSE.id, short_name=DB_COURSE.short_name),
                title="실습 2주차 결과 제출",
                due_at=datetime(2026, 10, 20, 23, 59, 59, tzinfo=KST),
                submission_state="unsubmitted",
                html_url=f"{BASE}/courses/214023/assignments/2811242",
                planner_task_id="task-1",
                calendar_registered=False,
            )
        ]


@dataclass
class FakeNotes:
    added: list[AssignmentNotice] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    muted: bool = False

    async def add_assignment_notices(
        self, user_id: str, notices: Sequence[AssignmentNotice], *, now: datetime
    ) -> int:
        assert user_id
        if self.muted:
            return 0
        self.added += list(notices)
        return len(notices)

    async def drop_assignment_notices(self, user_id: str, assignment_ids: Sequence[str]) -> int:
        self.dropped += list(assignment_ids)
        return len(self.dropped)


@pytest.fixture
def lms(settings: Settings) -> FakeLms:
    return FakeLms(
        connection_row=Connection(
            status="active",
            token_last4=TOKEN[-4:],
            access_token=encrypt(TOKEN, settings.token_encryption_key),
            canvas_user_id=77001,
            last_synced_at=None,
            last_error=None,
        )
    )


@pytest.fixture
def notes() -> FakeNotes:
    return FakeNotes()


@pytest.fixture
def log() -> FakeLogConnection:
    return FakeLogConnection()


@pytest.fixture
def client(
    settings: Settings, lms: FakeLms, notes: FakeNotes, log: FakeLogConnection
) -> Iterator[TestClient]:
    # 배치(`/internal/jobs/lms-sync`)를 부르려면 서비스 키가 있어야 한다
    settings = Settings(**{**settings.model_dump(), "internal_api_key": INTERNAL_KEY})
    app = create_app(settings)

    @asynccontextmanager
    async def transaction() -> AsyncIterator[Any]:
        yield None  # 가짜 저장소는 연결을 쓰지 않는다

    service = LmsSyncService(
        transaction=transaction,
        log_connection=using(log),  # type: ignore[arg-type]
        client=LearningXClient(api_base=BASE),
        encryption_key=settings.token_encryption_key,
        runner=InlineRunner(),  # 응답 전에 동기화를 끝까지 돌린다
        repos=lambda conn: Repos(lms=lms, notes=notes),  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_lms_sync_service] = lambda: service
    app.dependency_overrides[get_lms_repo] = lambda: lms
    app.dependency_overrides[get_log_connect] = lambda: using(log)  # type: ignore[arg-type]
    app.dependency_overrides[current_time] = lambda: NOW
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {make_token()}"
        yield test_client


@pytest.fixture(autouse=True)
def canvas() -> Iterator[respx.MockRouter]:
    """기본 응답: 과목 3개, 데이터베이스 2건·기계학습 1건."""
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/api/v1/courses").mock(return_value=httpx.Response(200, json=COURSES))
        router.get(f"{BASE}/api/v1/courses/214023/assignments").mock(
            return_value=httpx.Response(200, json=DB_ASSIGNMENTS)
        )
        router.get(f"{BASE}/api/v1/courses/216515/assignments").mock(
            return_value=httpx.Response(200, json=ML_ASSIGNMENTS)
        )
        yield router


def test_it_starts_a_sync_and_gives_back_the_run(client: TestClient, lms: FakeLms) -> None:
    response = client.post(SYNC)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "running"
    assert body["run_id"]
    assert lms.synced_at == NOW  # 끝나면 마지막 동기화 시각을 찍는다


def test_it_saves_only_published_assignments(client: TestClient, lms: FakeLms) -> None:
    client.post(SYNC)
    saved = {course: [one.title for one in items] for course, items in lms.saved}
    assert saved == {
        "course-db": ["실습 2주차 결과 제출", "실습 3주차 결과 제출"],  # 준비 중 과제는 빠진다
        "course-ml": ["3주차 퀴즈"],
    }


def test_the_run_records_every_outside_call_as_a_tool(
    client: TestClient, log: FakeLogConnection
) -> None:
    """외부 호출은 모두 실행 안의 도구로 남는다(api/CLAUDE.md). 토큰은 입력에 넣지 않는다."""
    client.post(SYNC)
    assert log.tools() == ["fetch_lms_courses", "fetch_lms_assignments", "save_lms_sync"]
    assert TOKEN not in str(log.statements)  # 입력·출력에 토큰이 남지 않는다


def test_the_result_is_in_the_save_step(
    client: TestClient, lms: FakeLms, log: FakeLogConnection
) -> None:
    """`GET /runs/{id}`는 save_lms_sync의 출력으로 결과를 만든다(repositories/runs.py)."""
    lms.changes["course-db"] = AssignmentChanges(
        created=[SavedAssignment("a1", "실습 2주차 결과 제출", NOW + timedelta(days=4))],
        due_changed=[SavedAssignment("a2", "실습 3주차 결과 제출", NOW + timedelta(days=2))],
        submitted=["a3"],
    )
    client.post(SYNC)
    output = log.outputs()["save_lms_sync"]
    assert output["courses"] == 2
    assert (output["new"], output["due_changed"], output["submitted"]) == (1, 1, 1)


def test_a_new_assignment_becomes_a_task_and_a_notice(
    client: TestClient, lms: FakeLms, notes: FakeNotes
) -> None:
    lms.changes["course-ml"] = AssignmentChanges(
        created=[SavedAssignment("a9", "3주차 퀴즈", datetime(2026, 10, 11, 14, 59, tzinfo=UTC))]
    )
    client.post(SYNC)
    assert [one.created for one in lms.planned] == [lms.changes["course-ml"].created]
    assert len(notes.added) == 1
    notice = notes.added[0]
    assert notice.assignment_id == "a9"
    assert notice.title == "기계학습 새 과제가 올라왔어요"
    assert notice.body == "3주차 퀴즈 · 마감 10/11 23:59"  # KST로 보여 준다


def test_an_assignment_already_submitted_gets_no_notice(
    client: TestClient, lms: FakeLms, notes: FakeNotes
) -> None:
    """연결 첫 동기화에는 지난 학기 과제까지 들어온다. 이미 낸 과제로 알림을 보내면 안 된다."""
    lms.changes["course-db"] = AssignmentChanges(
        created=[
            SavedAssignment("a1", "지난 과제", NOW - timedelta(days=9), submitted=True),
            SavedAssignment("a2", "이번 과제", NOW + timedelta(days=2)),
        ]
    )
    client.post(SYNC)
    assert [one.assignment_id for one in notes.added] == ["a2"]


def test_an_assignment_without_a_deadline_still_gets_a_notice(
    client: TestClient, lms: FakeLms, notes: FakeNotes
) -> None:
    lms.changes["course-db"] = AssignmentChanges(
        created=[SavedAssignment("a8", "기말 보고서", None)]
    )
    client.post(SYNC)
    assert notes.added[0].body == "기말 보고서"


def test_submitting_stops_the_pending_notice(
    client: TestClient, lms: FakeLms, notes: FakeNotes
) -> None:
    """제출하면 아직 보내지 않은 알림을 지운다(명세 10장)."""
    lms.changes["course-db"] = AssignmentChanges(submitted=["a3", "a4"])
    client.post(SYNC)
    assert notes.dropped == ["a3", "a4"]


def test_it_skips_a_sync_that_just_happened(client: TestClient, lms: FakeLms) -> None:
    """5분 안에 또 부르면 LearningX를 부르지 않는다(명세 8장)."""
    assert lms.connection_row is not None
    lms.connection_row = Connection(
        **{**lms.connection_row.__dict__, "last_synced_at": NOW - timedelta(minutes=2)}
    )
    response = client.post(SYNC)
    assert response.status_code == 200
    assert response.json() == {"skipped": True, "last_synced_at": "2026-10-16T11:58:00+09:00"}
    assert lms.saved == []  # 아무것도 받지 않았다


def test_a_second_call_does_not_start_a_second_sync(client: TestClient, lms: FakeLms) -> None:
    """대시보드를 두 탭에서 열어도 한 번만 받는다. claim이 한 문장으로 자리를 잡는다."""
    assert client.post(SYNC).status_code == 202
    first = len(lms.saved)
    again = client.post(SYNC)
    assert again.status_code == 200
    assert again.json()["skipped"] is True
    assert len(lms.saved) == first  # 두 번째는 LearningX를 부르지 않았다
    assert lms.claims == [USER_ID]


def test_it_syncs_again_after_five_minutes(client: TestClient, lms: FakeLms) -> None:
    assert lms.connection_row is not None
    lms.connection_row = Connection(
        **{**lms.connection_row.__dict__, "last_synced_at": NOW - timedelta(minutes=6)}
    )
    assert client.post(SYNC).status_code == 202
    assert lms.saved != []


def test_it_asks_to_connect_first(client: TestClient, lms: FakeLms) -> None:
    lms.connection_row = None
    response = client.post(SYNC)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LMS_NOT_CONNECTED"


def test_a_dead_token_marks_the_connection(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """401이면 연결을 error로 바꿔 화면이 다시 연결을 안내한다. 실행은 실패로 남는다."""
    canvas.get(f"{BASE}/api/v1/courses").mock(return_value=httpx.Response(401, json={}))
    response = client.post(SYNC)
    assert response.status_code == 202  # 동기화는 뒤에서 돌아서 시작 응답은 202다
    assert lms.error == "토큰이 만료되었거나 삭제되었어요."
    assert lms.synced_at is None


def test_a_broken_stored_token_asks_to_connect_again(client: TestClient, lms: FakeLms) -> None:
    """키를 바꿨거나 값이 깨졌다. 500으로 끝내지 않고 다시 연결하게 한다."""
    assert lms.connection_row is not None
    lms.connection_row = Connection(
        **{**lms.connection_row.__dict__, "access_token": "암호문이 아니다"}
    )
    response = client.post(SYNC)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LMS_TOKEN_INVALID"


def test_learningx_being_down_does_not_mark_the_token(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """503은 토큰 문제가 아니다. 연결 상태를 바꾸지 않고 다음 동기화에서 다시 시도한다."""
    canvas.get(f"{BASE}/api/v1/courses").mock(return_value=httpx.Response(503, json={}))
    client.post(SYNC)
    assert lms.error is None
    assert lms.synced_at is None


def test_one_broken_course_does_not_stop_the_others(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter, log: FakeLogConnection
) -> None:
    """한 과목이 403이면 그 과목만 두고 넘어간다. 부분 목록으로 저장하면 과제가 사라진 것이 된다."""
    canvas.get(f"{BASE}/api/v1/courses/214023/assignments").mock(
        return_value=httpx.Response(403, json={})
    )
    client.post(SYNC)
    assert [course for course, _ in lms.saved] == ["course-ml"]
    assert log.outputs()["save_lms_sync"]["failed_courses"] == 1
    assert lms.synced_at == NOW  # 나머지는 받았으니 동기화는 성공이다


def test_a_dead_token_in_the_middle_stops_the_sync(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    canvas.get(f"{BASE}/api/v1/courses/214023/assignments").mock(
        return_value=httpx.Response(401, json={})
    )
    client.post(SYNC)
    assert lms.saved == []  # 쓰기 트랜잭션에 들어가지 않았다
    assert lms.error == "토큰이 만료되었거나 삭제되었어요."


def test_a_course_with_no_assignments_is_fine(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """녹화 6과목 중 2과목이 과제 0건이었다. 빈 목록은 오류가 아니다(명세 9장)."""
    canvas.get(f"{BASE}/api/v1/courses/216515/assignments").mock(
        return_value=httpx.Response(200, json=[])
    )
    assert client.post(SYNC).status_code == 202
    saved = dict(lms.saved)
    assert saved["course-ml"] == []
    assert lms.synced_at == NOW


def test_it_sends_the_token_only_in_the_header(
    client: TestClient, canvas: respx.MockRouter
) -> None:
    client.post(SYNC)
    for call in canvas.calls:
        assert call.request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in str(call.request.url)


def test_the_sync_needs_a_login(settings: Settings, lms: FakeLms) -> None:
    app = create_app(settings)
    app.dependency_overrides[get_lms_repo] = lambda: lms
    with TestClient(app) as anonymous:
        assert anonymous.post(SYNC).status_code == 401
        assert anonymous.get(ASSIGNMENTS).status_code == 401


def test_the_run_shows_the_sync_result(client: TestClient) -> None:
    """`GET /runs/{id}`가 동기화 결과를 보여 준다(명세 8장·11장). 단계 이름도 한글로 나온다."""
    runs = FakeRunRepository()
    client.app.dependency_overrides[get_run_repo] = lambda: runs  # type: ignore[attr-defined]
    run = run_row(
        id="00000000-0000-4000-8000-0000000000b1",
        user_id=USER_ID,
        trigger_type="lms_sync",
        status="succeeded",
    )
    runs.runs[run.id] = run
    runs.lms_results[run.id] = LmsSyncResult(
        courses=2, assignments=SyncCounts(new=1, due_changed=0, submitted=2)
    )

    body = client.get(f"/api/v1/runs/{run.id}").json()
    assert body["result"] == {
        "kind": "lms_sync",
        "courses": 2,
        "assignments": {"new": 1, "due_changed": 0, "submitted": 2},
        "new_module_items": 0,
        "new_announcements": 0,
    }


def test_a_sync_where_every_course_fails_is_not_a_success(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """한 과목도 받지 못하면 성공으로 적지 않는다. 적으면 오류 표시가 지워지고 학생은 받았다고 믿는다."""
    for course in (214023, 216515):
        canvas.get(f"{BASE}/api/v1/courses/{course}/assignments").mock(
            return_value=httpx.Response(403, json={})
        )
    client.post(SYNC)
    assert lms.saved == []
    assert lms.synced_at is None  # touch_synced를 부르지 않았다
    assert lms.error is None  # 토큰 문제가 아니라 학교 쪽 문제다


def test_a_failed_sync_closes_its_run(
    client: TestClient, lms: FakeLms, log: FakeLogConnection, canvas: respx.MockRouter
) -> None:
    """실행이 running으로 남으면 GET /runs/{id}가 끝나지 않고 성공률 지표의 분모만 늘어난다."""
    canvas.get(f"{BASE}/api/v1/courses").mock(return_value=httpx.Response(503, json={}))
    client.post(SYNC)
    closed = [
        query for query, _ in log.statements if "update agent_runs" in query and "'failed'" in query
    ]
    assert closed, "실패한 실행을 닫지 않았다"


def test_a_token_we_cannot_decrypt_does_not_blame_the_student(
    client: TestClient, lms: FakeLms
) -> None:
    """암호화 키 문제다. 연결을 error로 바꾸면 멀쩡한 토큰을 다시 받게 만든다(app/crypto.py 키 교체)."""
    assert lms.connection_row is not None
    lms.connection_row = Connection(
        **{**lms.connection_row.__dict__, "access_token": "암호문이 아니다"}
    )
    lms.users = ["user-a"]
    body = client.post(JOB, headers={"X-Internal-Key": INTERNAL_KEY}).json()
    assert (body["synced"], body["failed"]) == (0, 1)
    assert lms.error is None


def test_the_batch_counts_the_ones_someone_else_took(client: TestClient, lms: FakeLms) -> None:
    """대시보드가 방금 동기화를 시작한 사람은 배치에서 건너뛴다(claim이 막는다)."""
    lms.users = ["user-a"]
    assert lms.connection_row is not None
    lms.connection_row = Connection(
        **{**lms.connection_row.__dict__, "last_synced_at": NOW - timedelta(minutes=1)}
    )
    body = client.post(JOB, headers={"X-Internal-Key": INTERNAL_KEY}).json()
    assert (body["users"], body["synced"], body["failed"], body["skipped"]) == (1, 0, 0, 1)


def test_the_job_does_not_print_the_token() -> None:
    """실수로 로그에 찍어도 토큰이 나오지 않게 repr에서 뺀다(Connection.access_token과 같다)."""
    job = SyncJob(run_id="run-1", user_id=USER_ID, now=NOW, token=TOKEN)
    assert TOKEN not in repr(job)
    assert job.token == TOKEN


def test_a_failed_sync_tells_the_student_about_the_sync() -> None:
    """실패 문구가 준비하기 것("준비 일정을 만들지 못했어요")으로 나가면 안 된다."""
    run = run_row(trigger_type="lms_sync", status="failed", error_message="RuntimeError()")
    error = run.error()
    assert error is not None
    assert error.code == "INTERNAL_ERROR"
    assert "LMS" in error.message and "준비" not in error.message


# ── 과제 목록 ───────────────────────────────────────────────────────────────


def test_it_lists_open_assignments_by_default(client: TestClient, lms: FakeLms) -> None:
    response = client.get(ASSIGNMENTS)
    assert response.status_code == 200
    assert lms.asked == ("open", None)  # type: ignore[attr-defined]
    item = response.json()["items"][0]
    assert item["course"] == {"id": "course-db", "short_name": "데이터베이스"}
    assert item["due_at"] == "2026-10-20T23:59:59+09:00"  # KST로 내려준다
    assert item["planner_task_id"] == "task-1"
    assert item["calendar_registered"] is False


def test_it_passes_the_filters_through(client: TestClient, lms: FakeLms) -> None:
    client.get(
        ASSIGNMENTS,
        params={"state": "all", "lms_course_id": "11111111-1111-4111-8111-111111111111"},
    )
    assert lms.asked == ("all", "11111111-1111-4111-8111-111111111111")  # type: ignore[attr-defined]


def test_it_refuses_an_unknown_state(client: TestClient) -> None:
    response = client.get(ASSIGNMENTS, params={"state": "done"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_it_refuses_a_course_id_that_is_not_a_uuid(client: TestClient) -> None:
    response = client.get(ASSIGNMENTS, params={"lms_course_id": "214023"})
    assert response.status_code == 422


# ── 30분 배치 ───────────────────────────────────────────────────────────────


def test_the_batch_syncs_every_connected_user(client: TestClient, lms: FakeLms) -> None:
    lms.users = ["user-a", "user-b"]
    response = client.post(JOB, headers={"X-Internal-Key": INTERNAL_KEY})
    assert response.status_code == 200
    body = response.json()
    assert (body["users"], body["synced"], body["failed"]) == (2, 2, 0)
    assert lms.before == NOW - timedelta(minutes=5)  # 방금 받은 사람은 건너뛴다


def test_the_batch_goes_on_after_one_user_fails(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """앞사람이 실패해도 뒷사람은 받는다. 첫 호출만 401로 막아 둘을 가른다."""
    lms.users = ["user-a", "user-b"]
    calls = {"n": 0}

    def answer(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(401, json={})
        return httpx.Response(200, json=COURSES)

    canvas.get(f"{BASE}/api/v1/courses").mock(side_effect=answer)
    body = client.post(JOB, headers={"X-Internal-Key": INTERNAL_KEY}).json()
    assert (body["users"], body["synced"], body["failed"]) == (2, 1, 1)
    assert lms.error == "토큰이 만료되었거나 삭제되었어요."  # 실패한 사람만 표시된다
    assert lms.saved  # 뒷사람 과제는 저장됐다


def test_the_batch_needs_the_service_key(client: TestClient) -> None:
    assert client.post(JOB).status_code == 403
    assert client.post(JOB, headers={"X-Internal-Key": "not-the-key"}).status_code == 403
```

### api (바뀌는 테스트)

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

과제 샘플에서 확인한 것(F-51, 과제 17건 녹화):

- `due_at`이 null이고 `lock_at`만 있는 과제가 있다(17건 중 5건) → 마감은 `due_at ?? lock_at`이다
- `has_submitted_submissions`는 과목 전체 기준이라 내가 내지 않은 과제에도 true다 → 쓰지 않는다
- 퀴즈(`submission_types: ["online_quiz"]`)는 자동 채점돼 `graded`로 온다(17건 중 4건)
- 제출한 과제의 `submission.submitted_at`이 제출 시각이다. 점수는 null일 수 있다(0점 과제)
- 시각은 모두 `...Z`(UTC)로 온다

주차 항목·공지 샘플은 F-52·F-53에서 더한다(그 기능이 쓸 때 함께 넣는다).
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


# ── 과제 (F-51) ─────────────────────────────────────────────────────────────
# 마감이 있고 아직 내지 않은 과제. 가장 흔한 모양이다
HOMEWORK: dict[str, Any] = {
    "id": 2811242,
    "due_at": "2026-10-20T14:59:59Z",  # 2026-10-20 23:59:59 KST
    "unlock_at": "2026-10-13T00:00:00Z",
    "lock_at": "2026-10-22T14:59:59Z",
    "points_possible": 0.0,
    "grading_type": "points",
    "assignment_group_id": 579630,
    "position": 1,
    "allowed_attempts": -1,
    "course_id": 214023,
    "name": "실습 2주차 결과 제출",
    "submission_types": ["online_upload"],
    "has_submitted_submissions": True,  # 과목 전체 기준이라 내 제출과 무관하다
    "is_quiz_assignment": False,
    "workflow_state": "published",
    "html_url": "https://lms.test/courses/214023/assignments/2811242",
    "published": True,
    "submission": {
        "id": 106325980,
        "assignment_id": 2811242,
        "user_id": CANVAS_USER_ID,
        "submitted_at": None,
        "workflow_state": "unsubmitted",
        "attempt": None,
        "score": None,
        "grade": None,
        "graded_at": None,
        "late": False,
        "missing": False,
        "submission_type": None,
        "excused": None,
        "seconds_late": 0,
        "cached_due_date": "2026-10-20T14:59:59Z",
    },
}

# `due_at`이 null이고 `lock_at`만 있는 과제(녹화 17건 중 5건). 마감은 lock_at으로 본다
LAB_REPORT: dict[str, Any] = {
    "id": 2811588,
    "due_at": None,
    "unlock_at": None,
    "lock_at": "2026-10-18T14:59:59Z",
    "points_possible": 0.0,
    "grading_type": "points",
    "assignment_group_id": 579630,
    "position": 2,
    "allowed_attempts": -1,
    "course_id": 214023,
    "name": "실습 3주차 결과 제출",
    "submission_types": ["online_upload"],
    "has_submitted_submissions": True,
    "is_quiz_assignment": False,
    "workflow_state": "published",
    "html_url": "https://lms.test/courses/214023/assignments/2811588",
    "published": True,
    "lock_info": {
        "lock_at": "2026-10-18T14:59:59Z",
        "can_view": True,
        "asset_string": "assignment_2811588",
    },
    "submission": {
        "id": 106325981,
        "assignment_id": 2811588,
        "user_id": CANVAS_USER_ID,
        "submitted_at": "2026-10-15T23:02:17Z",
        "workflow_state": "submitted",
        "attempt": 1,
        "score": None,
        "grade": None,
        "graded_at": None,
        "late": False,
        "missing": False,
        "submission_type": "online_upload",
        "excused": None,
        "seconds_late": 0,
        "cached_due_date": None,
    },
}

# 퀴즈는 자동 채점돼 바로 graded로 온다(녹화 17건 중 4건)
QUIZ: dict[str, Any] = {
    "id": 2799146,
    "quiz_id": 85791,
    "is_quiz_assignment": True,
    "due_at": "2026-10-11T14:59:00Z",
    "unlock_at": None,
    "lock_at": "2026-10-11T14:59:00Z",
    "points_possible": 3.0,
    "grading_type": "points",
    "assignment_group_id": 579631,
    "position": 3,
    "course_id": 216515,
    "name": "3주차 퀴즈",
    "submission_types": ["online_quiz"],
    "has_submitted_submissions": True,
    "workflow_state": "published",
    "html_url": "https://lms.test/courses/216515/assignments/2799146",
    "published": True,
    "submission": {
        "id": 106325982,
        "assignment_id": 2799146,
        "user_id": CANVAS_USER_ID,
        "submitted_at": "2026-10-09T08:40:14Z",
        "workflow_state": "graded",
        "attempt": 1,
        "score": None,
        "grade": None,
        "graded_at": "2026-10-09T08:40:20Z",
        "submission_type": "online_quiz",
        "late": False,
        "missing": False,
        "excused": None,
        "seconds_late": 0,
    },
}

# 아직 열지 않은 과제. 학생 화면에는 안 보이니 저장하지 않는다(녹화에는 없었다 — 과목에서 본 모양을 옮겼다)
DRAFT_ASSIGNMENT: dict[str, Any] = {
    "id": 2820001,
    "due_at": "2026-12-01T14:59:59Z",
    "lock_at": None,
    "points_possible": 10.0,
    "course_id": 214023,
    "name": "기말 과제(준비 중)",
    "submission_types": ["online_upload"],
    "is_quiz_assignment": False,
    "workflow_state": "unpublished",
    "html_url": "https://lms.test/courses/214023/assignments/2820001",
    "published": False,
    "submission": {
        "id": 106325983,
        "assignment_id": 2820001,
        "user_id": CANVAS_USER_ID,
        "submitted_at": None,
        "workflow_state": "unsubmitted",
    },
}

# 데이터베이스 과목(214023)의 과제 목록 응답
DB_ASSIGNMENTS: list[dict[str, Any]] = [HOMEWORK, LAB_REPORT, DRAFT_ASSIGNMENT]
# 기계학습 과목(216515)의 과제 목록 응답
ML_ASSIGNMENTS: list[dict[str, Any]] = [QUIZ]
```

#### `api/tests/test_lms_db.py`

```python
"""LearningX 연결·과목·과제 SQL(F-50·F-51)을 실제 스키마에 대고 확인한다: 토큰 저장·교체·삭제,
과목 upsert와 수강 뺀 과목 내리기, 과목 목록의 숫자와 격리, 과제 저장과 플래너·알림 맞추기.

트랜잭션을 되돌려 지운다. DATABASE_URL이 있을 때만 돈다.
"""

from datetime import timedelta
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from app.eligibility import KST
from app.lms.assignments import CanvasAssignment, assignments
from app.repositories.lms import AssignmentChanges, LmsRepository, SavedAssignment
from app.repositories.notifications import AssignmentNotice, NotificationRepository
from app.repositories.runs import RunRepository
from app.schemas.lms import SAVE_TOOL
from tests.db_world import DATABASE_URL, connect, make_user
from tests.lms_samples import (
    DATABASE,
    DB_ASSIGNMENTS,
    MACHINE_LEARNING,
    MINE,
    SEMINAR,
)

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


# ── 과제 저장 (F-51) ────────────────────────────────────────────────────────


def _one(
    canvas_id: int = 11,
    *,
    title: str = "실습 2주차 결과 제출",
    due: Any = None,
    state: str = "unsubmitted",
    submitted_at: Any = None,
) -> CanvasAssignment:
    return CanvasAssignment(
        canvas_assignment_id=canvas_id,
        title=title,
        due_at=due,
        html_url=f"https://lms.test/courses/214023/assignments/{canvas_id}",
        submission_state=state,
        submitted_at=submitted_at,
    )


async def _course_id(world: dict[str, Any], canvas_course_id: int = DATABASE["id"]) -> str:
    row = await (
        await world["conn"].execute(
            "select id from lms_courses where user_id = %s and canvas_course_id = %s",
            (world["me"], canvas_course_id),
        )
    ).fetchone()
    return str(row["id"])


async def test_it_saves_the_assignments_of_a_course(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)

    changes = await repo.save_assignments(me, course, assignments(DB_ASSIGNMENTS), now=now)
    assert [one.title for one in changes.created] == [
        "실습 2주차 결과 제출",
        "실습 3주차 결과 제출",
    ]
    assert (changes.due_changed, changes.submitted, changes.removed) == ([], [], 0)

    items = await repo.assignments(me, state="all")
    assert [(one.title, one.submission_state) for one in items] == [
        ("실습 3주차 결과 제출", "submitted"),  # 마감이 더 이르다(lock_at 10/18)
        ("실습 2주차 결과 제출", "unsubmitted"),
    ]
    assert items[0].course.short_name == "데이터베이스"
    # 마감은 샘플 그대로 저장되고 KST로 나간다(실습 3주차는 lock_at, 2주차는 due_at)
    assert [one.due_at.isoformat() for one in items] == [
        "2026-10-18T23:59:59+09:00",
        "2026-10-20T23:59:59+09:00",
    ]
    assert items[1].html_url == "https://lms.test/courses/214023/assignments/2811242"


async def test_saving_again_changes_nothing_new(world: dict[str, Any]) -> None:
    """같은 목록을 다시 받으면 새 과제도, 마감 변경도, 제출도 없다(알림이 두 번 가지 않는다)."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    items = [_one(due=now + timedelta(days=3))]
    await repo.save_assignments(me, course, items, now=now)

    again = await repo.save_assignments(me, course, items, now=now + timedelta(minutes=30))
    assert (again.created, again.due_changed, again.submitted, again.removed) == ([], [], [], 0)


async def test_a_changed_deadline_is_reported_once(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(me, course, [_one(due=now + timedelta(days=3))], now=now)

    moved = now + timedelta(days=5)
    changes = await repo.save_assignments(me, course, [_one(due=moved)], now=now)
    assert [one.id for one in changes.due_changed] and changes.created == []
    assert (await repo.assignments(me))[0].due_at == moved.astimezone(KST)

    nothing = await repo.save_assignments(me, course, [_one(due=moved)], now=now)
    assert nothing.due_changed == []


async def test_submitting_is_reported_once(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(me, course, [_one(due=now + timedelta(days=3))], now=now)

    handed_in = _one(due=now + timedelta(days=3), state="submitted", submitted_at=now)
    changes = await repo.save_assignments(me, course, [handed_in], now=now)
    assert len(changes.submitted) == 1

    graded = _one(due=now + timedelta(days=3), state="graded", submitted_at=now)
    again = await repo.save_assignments(me, course, [graded], now=now)
    assert again.submitted == []  # submitted → graded는 새 제출이 아니다
    assert (await repo.assignments(me, state="submitted"))[0].submission_state == "graded"


async def test_an_assignment_that_disappeared_is_marked_removed(world: dict[str, Any]) -> None:
    """LMS에서 지운 과제는 기록만 남기고 목록·숫자에서 뺀다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(me, course, [_one(11), _one(12, title="실습 3주차")], now=now)

    changes = await repo.save_assignments(me, course, [_one(11)], now=now)
    assert changes.removed == 1
    assert [one.title for one in await repo.assignments(me, state="all")] == [
        "실습 2주차 결과 제출"
    ]
    assert (await repo.courses(me, now=now))[0].open_assignments == 1


async def test_an_empty_list_removes_the_assignments(world: dict[str, Any]) -> None:
    """과제는 0건인 과목이 흔하다(녹화 6과목 중 2과목). 과목 목록과 달리 빈 목록을 믿는다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(me, course, [_one(11)], now=now)

    changes = await repo.save_assignments(me, course, [], now=now)
    assert changes.removed == 1
    assert await repo.assignments(me, state="all") == []


async def test_an_assignment_that_comes_back_counts_as_new(world: dict[str, Any]) -> None:
    """사라졌다 다시 나타나면 새 과제다. 그 사이 할 일·알림이 없었다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(me, course, [_one(11)], now=now)
    await repo.save_assignments(me, course, [], now=now)

    changes = await repo.save_assignments(me, course, [_one(11)], now=now)
    assert len(changes.created) == 1
    assert len(await repo.assignments(me, state="all")) == 1  # 줄은 하나다(upsert)


async def test_assignments_of_another_user_are_not_mine(world: dict[str, Any]) -> None:
    repo, me, other, now = world["repo"], world["me"], world["other"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    await repo.save_courses(other, [DATABASE], now=now)
    mine = await _course_id(world)
    row = await (
        await world["conn"].execute(
            "select id from lms_courses where user_id = %s and canvas_course_id = %s",
            (other, DATABASE["id"]),
        )
    ).fetchone()
    await repo.save_assignments(me, mine, [_one(11)], now=now)
    await repo.save_assignments(other, str(row["id"]), [_one(11), _one(12)], now=now)

    assert len(await repo.assignments(me, state="all")) == 1
    assert len(await repo.assignments(other, state="all")) == 2
    # 남의 동기화가 내 과제를 지우지 않는다
    await repo.save_assignments(other, str(row["id"]), [], now=now)
    assert len(await repo.assignments(me, state="all")) == 1


async def test_an_assignment_already_submitted_when_first_seen_is_quiet(
    world: dict[str, Any],
) -> None:
    """연결 첫 동기화에는 지난 과제가 한꺼번에 들어온다(녹화 17건 중 13건이 제출·채점 완료).
    낸 과제로 할 일을 만들거나 "새 과제" 알림을 보내면 안 된다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    old = _one(11, title="지난 과제", due=now - timedelta(days=9), state="graded", submitted_at=now)

    changes = await repo.save_assignments(me, course, [old], now=now)
    assert [one.title for one in changes.created] == ["지난 과제"]
    assert changes.created[0].submitted is True
    assert await repo.sync_planner(me, changes, now=now) == 0
    assert await _tasks(world) == []


async def test_a_dropped_courses_assignments_leave_the_list(world: dict[str, Any]) -> None:
    """수강을 빼면 그 과목의 과제는 더 받지 않는다(사라진 표시도 안 붙는다). 목록에서 뺀다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE, MACHINE_LEARNING], now=now)
    db = await _course_id(world)
    await repo.save_assignments(me, db, [_one(11, due=now + timedelta(days=3))], now=now)
    assert len(await repo.assignments(me)) == 1

    await repo.save_courses(me, [MACHINE_LEARNING], now=now)  # 데이터베이스를 뺐다
    assert await repo.assignments(me) == []
    assert await repo.assignments(me, state="all") == []


async def test_sweeping_twice_removes_nothing_the_second_time(world: dict[str, Any]) -> None:
    """사라진 표시는 한 번만 찍는다. 매번 다시 찍으면 동기화 결과가 거짓말을 한다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(me, course, [_one(11)], now=now)
    assert (await repo.save_assignments(me, course, [], now=now)).removed == 1
    assert (await repo.save_assignments(me, course, [], now=now)).removed == 0


async def test_the_first_time_we_saw_an_assignment_is_kept(world: dict[str, Any]) -> None:
    """`first_seen_at`은 처음 본 때다. 다시 받을 때마다 밀리면 "새 자료" 기준이 무너진다."""
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(me, course, [_one(11)], now=now)
    later = now + timedelta(days=1)
    await repo.save_assignments(me, course, [_one(11, title="이름이 바뀌었다")], now=later)

    row = await (
        await conn.execute(
            "select first_seen_at, title from lms_assignments where user_id = %s", (me,)
        )
    ).fetchone()
    assert row["first_seen_at"] == now  # 처음 본 때 그대로
    assert row["title"] == "이름이 바뀌었다"  # 제목은 갱신된다


async def test_the_list_does_not_borrow_another_users_task_or_event(
    world: dict[str, Any],
) -> None:
    """같은 과제 id를 가리키는 남의 할 일·캘린더 행이 내 목록에 붙지 않는다."""
    repo, me, other, now, conn = (
        world["repo"],
        world["me"],
        world["other"],
        world["now"],
        world["conn"],
    )
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=3))], now=now
    )
    assignment_id = changes.created[0].id
    # 남이 내 과제를 가리키는 행을 가졌다(실제로는 생기지 않지만, 조건이 빠지면 섞인다)
    await conn.execute(
        "insert into planner_tasks (user_id, source, lms_assignment_id, title, due_date)"
        " values (%s, 'lms_assignment', %s, '남의 할 일', %s)",
        (other, assignment_id, now.date()),
    )
    await conn.execute(
        "insert into calendar_events (user_id, provider, lms_assignment_id, title, starts_at,"
        " external_event_id) values (%s, 'google', %s, '남의 일정', %s, 'ev-9')",
        (other, assignment_id, now),
    )

    item = (await repo.assignments(me))[0]
    assert item.planner_task_id is None
    assert item.calendar_registered is False


# ── 과제 목록 (F-51) ────────────────────────────────────────────────────────


async def test_the_assignment_list_filters_and_sorts(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE, MACHINE_LEARNING], now=now)
    db, ml = await _course_id(world), await _course_id(world, MACHINE_LEARNING["id"])
    await repo.save_assignments(
        me,
        db,
        [
            _one(11, title="마감 없는 과제"),
            _one(12, title="늦은 과제", due=now + timedelta(days=9)),
            _one(13, title="낸 과제", due=now + timedelta(days=1), state="graded"),
        ],
        now=now,
    )
    await repo.save_assignments(
        me, ml, [_one(21, title="이른 과제", due=now + timedelta(days=2))], now=now
    )

    assert [one.title for one in await repo.assignments(me)] == [
        "이른 과제",
        "늦은 과제",
        "마감 없는 과제",  # 마감이 없는 과제는 뒤로 간다
    ]
    assert [one.title for one in await repo.assignments(me, state="submitted")] == ["낸 과제"]
    # pending_review(냈고 채점만 남음)도 제출 쪽이다. 어느 state에도 안 들어가면 안 된다
    await repo.save_assignments(
        me,
        ml,
        [
            _one(
                21, title="이른 과제", due=now + timedelta(days=2)
            ),  # 목록에서 빠지지 않게 함께 보낸다
            _one(22, title="검토 중 과제", due=now + timedelta(days=3), state="pending_review"),
        ],
        now=now,
    )
    assert "검토 중 과제" in [one.title for one in await repo.assignments(me, state="submitted")]
    assert "검토 중 과제" not in [one.title for one in await repo.assignments(me)]
    assert len(await repo.assignments(me, state="all")) == 5
    assert [one.title for one in await repo.assignments(me, course_id=ml)] == ["이른 과제"]


async def test_the_list_shows_the_task_and_calendar_links(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=3))], now=now
    )
    await repo.sync_planner(me, changes, now=now)
    assignment_id = changes.created[0].id
    await conn.execute(
        "insert into calendar_events (user_id, provider, lms_assignment_id, title, starts_at,"
        " external_event_id) values (%s, 'google', %s, '마감', %s, 'ev-1')",
        (me, assignment_id, now + timedelta(days=3)),
    )

    item = (await repo.assignments(me))[0]
    assert item.planner_task_id is not None
    assert item.calendar_registered is True


async def test_a_calendar_row_without_an_event_is_not_registered(world: dict[str, Any]) -> None:
    """등록을 시작했다 못 끝낸 행이다(F-32의 reserve). 등록됐다고 보여 주면 안 된다."""
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(me, course, [_one(11)], now=now)
    await conn.execute(
        "insert into calendar_events (user_id, provider, lms_assignment_id, title, starts_at)"
        " values (%s, 'google', %s, '마감', %s)",
        (me, changes.created[0].id, now),
    )
    assert (await repo.assignments(me))[0].calendar_registered is False


# ── 플래너 (F-51·F-43) ──────────────────────────────────────────────────────


async def _tasks(world: dict[str, Any]) -> list[dict[str, Any]]:
    return await (
        await world["conn"].execute(
            "select title, due_date, coalesce(is_done, false) as is_done, done_at,"
            " source::text as source, lms_assignment_id from planner_tasks"
            " where user_id = %s order by due_date, title",
            (world["me"],),
        )
    ).fetchall()


async def test_a_new_assignment_becomes_a_planner_task(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    due = now + timedelta(days=3)
    changes = await repo.save_assignments(me, course, [_one(11, due=due)], now=now)

    assert await repo.sync_planner(me, changes, now=now) == 1
    rows = await _tasks(world)
    assert len(rows) == 1
    assert rows[0]["title"] == "실습 2주차 결과 제출"
    assert rows[0]["due_date"] == due.astimezone(KST).date()  # 마감은 KST 날짜다
    assert rows[0]["source"] == "lms_assignment"
    assert not rows[0]["is_done"]


async def test_an_assignment_without_a_deadline_gets_no_task(world: dict[str, Any]) -> None:
    """할 일에는 날짜가 있어야 한다(planner_tasks.due_date). 마감이 생기면 그때 만든다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(me, course, [_one(11)], now=now)
    assert await repo.sync_planner(me, changes, now=now) == 0
    assert await _tasks(world) == []

    later = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=2))], now=now
    )
    assert await repo.sync_planner(me, later, now=now) == 1


async def test_a_moved_deadline_moves_the_task(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    first = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=3))], now=now
    )
    await repo.sync_planner(me, first, now=now)

    moved = now + timedelta(days=6)
    changes = await repo.save_assignments(me, course, [_one(11, due=moved)], now=now)
    assert await repo.sync_planner(me, changes, now=now) == 0  # 새로 만들지 않는다
    rows = await _tasks(world)
    assert len(rows) == 1 and rows[0]["due_date"] == moved.astimezone(KST).date()


async def test_submitting_finishes_the_task(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    first = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=3))], now=now
    )
    await repo.sync_planner(me, first, now=now)

    handed_in = _one(11, due=now + timedelta(days=3), state="submitted", submitted_at=now)
    changes = await repo.save_assignments(me, course, [handed_in], now=now)
    await repo.sync_planner(me, changes, now=now)
    rows = await _tasks(world)
    assert rows[0]["is_done"] and rows[0]["done_at"] == now


async def test_a_task_the_student_deleted_is_not_made_again(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    first = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=3))], now=now
    )
    await repo.sync_planner(me, first, now=now)
    await conn.execute("delete from planner_tasks where user_id = %s", (me,))

    moved = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=5))], now=now
    )
    await repo.sync_planner(me, moved, now=now)
    assert await _tasks(world) == []  # 지운 할 일을 되살리지 않는다


async def test_a_finished_task_is_left_alone_when_the_deadline_moves(
    world: dict[str, Any],
) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    first = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=3))], now=now
    )
    await repo.sync_planner(me, first, now=now)
    await conn.execute(
        "update planner_tasks set is_done = true, done_at = %s where user_id = %s", (now, me)
    )

    moved = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=9))], now=now
    )
    await repo.sync_planner(me, moved, now=now)
    rows = await _tasks(world)
    assert rows[0]["due_date"] == (now + timedelta(days=3)).astimezone(KST).date()


async def test_the_planner_does_not_touch_another_users_task(world: dict[str, Any]) -> None:
    repo, me, other, now = world["repo"], world["me"], world["other"], world["now"]
    await repo.save_courses(other, [DATABASE], now=now)
    row = await (
        await world["conn"].execute("select id from lms_courses where user_id = %s", (other,))
    ).fetchone()
    changes = await repo.save_assignments(
        other, str(row["id"]), [_one(11, due=now + timedelta(days=3))], now=now
    )
    assert await repo.sync_planner(me, changes, now=now) == 0  # 내 할 일이 아니다
    assert await _tasks(world) == []


# ── 알림 (F-51·F-33) ────────────────────────────────────────────────────────


async def test_a_new_assignment_makes_one_notice(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    notes = NotificationRepository(conn)
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(me, course, [_one(11)], now=now)
    notice = AssignmentNotice(changes.created[0].id, "데이터베이스 새 과제가 올라왔어요", "실습")

    assert await notes.add_assignment_notices(me, [notice], now=now) == 1
    assert await notes.add_assignment_notices(me, [notice], now=now) == 0  # 같은 과제는 한 번만
    row = await (
        await conn.execute(
            "select type, title, body, scheduled_at, dedupe_key, lms_assignment_id, status::text"
            " as status from notifications where user_id = %s",
            (me,),
        )
    ).fetchone()
    assert row["type"] == "new_assignment"
    assert row["dedupe_key"] == f"new_assignment:asg:{changes.created[0].id}"  # ERD 5장 표
    assert row["scheduled_at"] == now  # 찾은 때 바로 보낸다(09:00을 기다리지 않는다)
    assert row["status"] == "pending"


async def test_someone_elses_mute_does_not_silence_me(world: dict[str, Any]) -> None:
    """남이 끈 종류 때문에 내 알림이 사라지면 안 된다(끈 설정은 사용자별이다)."""
    repo, me, other, now, conn = (
        world["repo"],
        world["me"],
        world["other"],
        world["now"],
        world["conn"],
    )
    notes = NotificationRepository(conn)
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(me, course, [_one(11)], now=now)
    await conn.execute(
        "insert into user_settings (user_id, muted_notification_types)"
        " values (%s, array['new_assignment'])",
        (other,),
    )
    notice = AssignmentNotice(changes.created[0].id, "제목", "본문")
    assert await notes.add_assignment_notices(me, [notice], now=now) == 1


async def test_a_muted_type_makes_no_notice(world: dict[str, Any]) -> None:
    """설정에서 끈 종류는 만들지 않는다(F-45, ERD)."""
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    notes = NotificationRepository(conn)
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(me, course, [_one(11)], now=now)
    await conn.execute(
        "insert into user_settings (user_id, muted_notification_types)"
        " values (%s, array['new_assignment']) on conflict (user_id) do update"
        " set muted_notification_types = array['new_assignment']",
        (me,),
    )
    notice = AssignmentNotice(changes.created[0].id, "제목", "본문")
    assert await notes.add_assignment_notices(me, [notice], now=now) == 0


async def test_submitting_drops_the_notice_that_was_not_sent(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    notes = NotificationRepository(conn)
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(me, course, [_one(11), _one(12)], now=now)
    waiting, sent = (one.id for one in changes.created)
    await notes.add_assignment_notices(
        me,
        [AssignmentNotice(waiting, "가", "나"), AssignmentNotice(sent, "다", "라")],
        now=now,
    )
    await conn.execute(
        "update notifications set status = 'succeeded', sent_at = %s where lms_assignment_id = %s",
        (now, sent),
    )

    assert await notes.drop_assignment_notices(me, [waiting, sent]) == 1
    rows = await (
        await conn.execute("select lms_assignment_id from notifications where user_id = %s", (me,))
    ).fetchall()
    assert [str(row["lms_assignment_id"]) for row in rows] == [sent]  # 보낸 알림은 남는다


async def test_dropping_nothing_is_fine(world: dict[str, Any]) -> None:
    notes = NotificationRepository(world["conn"])
    assert await notes.drop_assignment_notices(world["me"], []) == 0


# ── 동기화 시각·배치 대상 (F-51) ────────────────────────────────────────────


async def test_touching_the_sync_time_clears_the_error(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await repo.mark_error(me, "토큰이 만료되었거나 삭제되었어요.")

    later = now + timedelta(hours=1)
    await repo.touch_synced(me, now=later)
    found = await repo.connection(me)
    assert found is not None
    assert (found.status, found.last_error) == ("active", None)
    assert found.last_synced_at == later


async def test_a_sync_can_be_claimed_only_once_in_the_window(world: dict[str, Any]) -> None:
    """같은 사용자를 두 번 동시에 동기화하지 않는다. 한 문장으로 자리를 잡는다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    window = timedelta(minutes=5)

    # 방금 연결해서 last_synced_at이 now다 → 5분 안에는 못 가져간다
    assert await repo.claim_sync(me, now=now, before=now - window) is False

    later = now + timedelta(minutes=6)
    assert await repo.claim_sync(me, now=later, before=later - window) is True
    found = await repo.connection(me)
    assert found is not None and found.last_synced_at == later
    # 바로 다음 요청은 막힌다(앞의 claim이 시각을 밀어 뒀다)
    assert await repo.claim_sync(me, now=later, before=later - window) is False


async def test_a_claim_is_refused_when_there_is_no_connection(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    assert await repo.claim_sync(me, now=now, before=now) is False

    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await world["conn"].execute(
        "update lms_connections set status = 'disconnected' where user_id = %s", (me,)
    )
    assert await repo.claim_sync(me, now=now, before=now + timedelta(days=1)) is False


async def test_a_claim_does_not_touch_the_error_message(world: dict[str, Any]) -> None:
    """가져가는 것만으로 "잘 됐다"고 적지 않는다. 성공은 touch_synced가 적는다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await repo.mark_error(me, "토큰이 만료되었거나 삭제되었어요.")
    later = now + timedelta(hours=1)

    assert await repo.claim_sync(me, now=later, before=later - timedelta(minutes=5)) is True
    found = await repo.connection(me)
    assert found is not None
    assert (found.status, found.last_error) == ("error", "토큰이 만료되었거나 삭제되었어요.")


async def test_a_user_whose_sync_keeps_failing_does_not_block_the_queue(
    world: dict[str, Any],
) -> None:
    """실패해도 claim이 시각을 밀어 둔다. 안 그러면 그 사람이 영원히 배치 앞자리를 차지한다."""
    repo, me, other, now = world["repo"], world["me"], world["other"], world["now"]
    await repo.save_connection(
        me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now - timedelta(hours=3)
    )
    await repo.save_connection(
        other, token="enc-2", last4="b8e1", canvas_user_id=2, now=now - timedelta(hours=2)
    )
    before = now - timedelta(minutes=5)
    assert await repo.connected_users(before=before, limit=10) == [me, other]

    # me를 가져가 동기화했지만 실패해서 touch_synced는 못 불렀다
    assert await repo.claim_sync(me, now=now, before=before) is True
    assert await repo.connected_users(before=before, limit=10) == [other]


async def test_a_slow_sync_does_not_turn_the_clock_back(world: dict[str, Any]) -> None:
    """느린 동기화가 뒤에 시작한 동기화의 자리를 지워 버리면, 같은 사용자를 또 동기화하게 된다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    started = now + timedelta(minutes=10)  # 느린 동기화가 시작한 시각
    later = started + timedelta(minutes=6)  # 그 사이 배치가 가져갔다
    assert await repo.claim_sync(me, now=later, before=later - timedelta(minutes=5)) is True

    await repo.touch_synced(me, now=started)  # 느린 쪽이 뒤늦게 끝났다
    found = await repo.connection(me)
    assert found is not None and found.last_synced_at == later


async def test_finishing_a_sync_does_not_revive_a_disconnected_one(world: dict[str, Any]) -> None:
    """해제한 뒤에 끝난 동기화가 연결을 되살리면 안 된다."""
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await conn.execute(
        "update lms_connections set status = 'disconnected' where user_id = %s", (me,)
    )
    await repo.touch_synced(me, now=now + timedelta(minutes=1))
    found = await repo.connection(me)
    assert found is not None and found.status == "disconnected"


async def test_an_already_finished_task_keeps_its_done_time(world: dict[str, Any]) -> None:
    """제출 상태가 그대로인데 동기화마다 완료 시각을 다시 찍으면, 플래너가 오늘 끝낸 일로 보인다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    first = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=3))], now=now
    )
    await repo.sync_planner(me, first, now=now)
    handed_in = _one(11, due=now + timedelta(days=3), state="submitted", submitted_at=now)
    changes = await repo.save_assignments(me, course, [handed_in], now=now)
    await repo.sync_planner(me, changes, now=now)

    # 같은 과제를 그대로 다시 받아도(제출 변화 없음) 완료 시각은 그대로다
    later = now + timedelta(hours=2)
    again = await repo.save_assignments(me, course, [handed_in], now=later)
    await repo.sync_planner(me, AssignmentChanges(submitted=[first.created[0].id]), now=later)
    assert again.submitted == []
    rows = await _tasks(world)
    assert rows[0]["done_at"] == now


async def test_the_batch_takes_the_ones_waiting_longest(world: dict[str, Any]) -> None:
    repo, me, other, now = world["repo"], world["me"], world["other"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await repo.save_connection(
        other, token="enc-2", last4="b8e1", canvas_user_id=2, now=now - timedelta(hours=2)
    )

    waiting = await repo.connected_users(before=now - timedelta(minutes=5), limit=10)
    assert waiting == [other]  # 방금 받은 me는 건너뛴다

    assert await repo.connected_users(before=now + timedelta(minutes=1), limit=10) == [other, me]
    assert await repo.connected_users(before=now + timedelta(minutes=1), limit=1) == [other]


async def test_a_disconnected_user_is_not_synced(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await conn.execute(
        "update lms_connections set status = 'disconnected' where user_id = %s", (me,)
    )
    assert await repo.connected_users(before=now + timedelta(days=1), limit=10) == []


async def test_a_broken_token_is_still_tried_again(world: dict[str, Any]) -> None:
    """error 상태도 배치에 넣는다. 사용자가 LMS에서 토큰을 되살리면 거기서 풀린다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await repo.mark_error(me, "토큰이 만료되었거나 삭제되었어요.")
    assert await repo.connected_users(before=now + timedelta(minutes=1), limit=10) == [me]


async def test_the_changes_add_up(world: dict[str, Any]) -> None:
    """과목마다 센 것을 더해 한 동기화 결과로 만든다(app/lms/sync.py)."""
    first = AssignmentChanges(
        created=[SavedAssignment("a", "가", None)], submitted=["s1"], removed=1
    )
    second = AssignmentChanges(due_changed=[SavedAssignment("b", "나", None)], removed=2)
    total = first + second
    assert (len(total.created), len(total.due_changed), total.submitted, total.removed) == (
        1,
        1,
        ["s1"],
        3,
    )


# ── 실행 결과 (F-51, GET /runs/{id}) ───────────────────────────────────────


async def _run_with(world: dict[str, Any], tool: str, output: Any) -> str:
    """도구 하나를 남긴 동기화 실행. 결과는 저장하지 않고 이 출력에서 다시 읽는다."""
    conn, me = world["conn"], world["me"]
    row = await (
        await conn.execute(
            "insert into agent_runs (user_id, trigger_type, status) values (%s, 'lms_sync',"
            " 'succeeded') returning id",
            (me,),
        )
    ).fetchone()
    run_id = str(row["id"])
    await conn.execute(
        "insert into tool_calls (run_id, seq, tool_name, input, output, status)"
        " values (%s, 1, %s, '{}'::jsonb, %s, 'succeeded')",
        (run_id, tool, Jsonb(output) if output is not None else None),
    )
    return run_id


async def test_the_run_result_comes_from_the_save_step(world: dict[str, Any]) -> None:
    conn, me = world["conn"], world["me"]
    run_id = await _run_with(
        world,
        SAVE_TOOL,
        {"courses": 2, "new": 1, "due_changed": 0, "submitted": 2, "notices": 1},
    )
    found = await RunRepository(conn).lms_sync_result(me, run_id)
    assert found is not None
    assert found.kind == "lms_sync"
    assert found.courses == 2
    assert (found.assignments.new, found.assignments.due_changed) == (1, 0)
    assert found.assignments.submitted == 2
    assert (found.new_module_items, found.new_announcements) == (0, 0)  # F-52·F-53


async def test_a_connect_run_has_no_sync_result(world: dict[str, Any]) -> None:
    """F-50 연결 실행도 trigger가 lms_sync다. 저장 단계가 없으면 결과는 없다."""
    run_id = await _run_with(world, "fetch_lms_courses", {"courses": 8})
    assert await RunRepository(world["conn"]).lms_sync_result(world["me"], run_id) is None


async def test_a_broken_output_is_read_as_no_result(world: dict[str, Any]) -> None:
    run_id = await _run_with(world, SAVE_TOOL, {"courses": "둘"})
    assert await RunRepository(world["conn"]).lms_sync_result(world["me"], run_id) is None
    empty = await _run_with(world, SAVE_TOOL, None)
    assert await RunRepository(world["conn"]).lms_sync_result(world["me"], empty) is None


async def test_another_users_run_result_is_not_mine(world: dict[str, Any]) -> None:
    run_id = await _run_with(
        world, SAVE_TOOL, {"courses": 1, "new": 0, "due_changed": 0, "submitted": 0}
    )
    assert await RunRepository(world["conn"]).lms_sync_result(world["other"], run_id) is None


async def test_the_steps_have_korean_labels(world: dict[str, Any]) -> None:
    """처리 과정(F-42)에 도구 이름이 그대로 나오지 않게 한다."""
    run_id = await _run_with(world, "fetch_lms_assignments", {"courses": 2})
    steps = await RunRepository(world["conn"]).steps(run_id)
    assert [(one.tool, one.label) for one in steps] == [("fetch_lms_assignments", "과제·제출 받기")]
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

    def outputs(self) -> dict[str, Any]:
        """도구 이름 → 그 도구가 남긴 출력. 도구는 겹치지 않으니 넣은 순서로 짝지어 읽는다."""
        open_names: list[str] = []
        found: dict[str, Any] = {}
        for query, params in self.statements:
            if not isinstance(params, tuple):
                continue
            if "insert into tool_calls" in query:
                open_names.append(params[2])
            elif "update tool_calls set output" in query and open_names:
                value = params[0]
                found[open_names.pop()] = getattr(value, "obj", value)
        return found

    def tools(self) -> list[str]:
        """기록된 도구 이름(tool_calls에 넣은 순서대로)."""
        return [
            params[2]
            for query, params in self.statements
            if "insert into tool_calls" in query and isinstance(params, tuple)
        ]
```

#### `api/tests/prepare_fakes.py`

```python
"""준비하기 API 단위 테스트용 가짜 서비스·실행 저장소. 실제 실행·SQL은 test_prepare_db.py가 본다."""

import itertools
from datetime import date, datetime
from typing import Any

from app.prepare.service import Started
from app.repositories.prepare import PlanState
from app.repositories.runs import RunRow
from app.schemas.lms import LmsSyncResult
from app.schemas.opportunities import OpportunityDetail, ProcessStep
from app.schemas.posters import PosterExtractResult
from app.schemas.prepare import PrepareResult

_ids = itertools.count(1)


def new_id() -> str:
    return f"00000000-0000-4000-8000-{next(_ids):012d}"


class FakePrepareService:
    def __init__(self) -> None:
        self.details: dict[str, OpportunityDetail] = {}  # 공고 id → 지금 판정한 상세. 없으면 404
        self.plans: dict[tuple[str, str], PlanState] = {}
        self.judge_calls: list[tuple[str, str, str | None]] = []
        self.resets: list[str] = []
        self.begins: list[tuple[str, str, date, date]] = []  # (user, 공고, 마감, 오늘)
        self.conflict: Started | None = None  # begin 사이에 다른 요청이 계획을 만든 경우

    async def judge(
        self, user_id: str, opportunity_id: str, *, now: datetime, display_name: str | None
    ) -> OpportunityDetail | None:
        self.judge_calls.append((user_id, opportunity_id, display_name))
        return self.details.get(opportunity_id)

    async def plan(self, user_id: str, opportunity_id: str) -> PlanState | None:
        return self.plans.get((user_id, opportunity_id))

    async def reset(self, plan: PlanState) -> None:
        self.resets.append(plan.id)
        self.plans = {key: value for key, value in self.plans.items() if value.id != plan.id}

    async def begin(
        self, user_id: str, opportunity_id: str, *, deadline: date, today: date
    ) -> Started:
        self.begins.append((user_id, opportunity_id, deadline, today))
        if self.conflict is not None:
            return self.conflict
        run_id = new_id()
        self.plans[(user_id, opportunity_id)] = PlanState(new_id(), run_id, "running", False)
        return Started(run_id, "running", created=True)


class FakeRunRepository:
    def __init__(self) -> None:
        self.runs: dict[str, RunRow] = {}
        self.steps_by_run: dict[str, list[ProcessStep]] = {}
        self.results: dict[str, PrepareResult] = {}
        self.poster_results: dict[str, PosterExtractResult] = {}
        self.lms_results: dict[str, LmsSyncResult] = {}
        self.result_calls: list[tuple[str, str]] = []

    async def run(self, run_id: str) -> RunRow | None:
        return self.runs.get(run_id)

    async def steps(self, run_id: str) -> list[ProcessStep]:
        return list(self.steps_by_run.get(run_id, []))

    async def prepare_result(self, user_id: str, run_id: str) -> PrepareResult | None:
        self.result_calls.append((user_id, run_id))
        return self.results.get(run_id)

    async def poster_result(self, user_id: str, run_id: str) -> PosterExtractResult | None:
        self.result_calls.append((user_id, run_id))
        return self.poster_results.get(run_id)

    async def lms_sync_result(self, user_id: str, run_id: str) -> LmsSyncResult | None:
        self.result_calls.append((user_id, run_id))
        return self.lms_results.get(run_id)


def run_row(**values: Any) -> RunRow:
    base: dict[str, Any] = {
        "id": new_id(),
        "user_id": None,
        "trigger_type": "prepare",
        "status": "running",
        "started_at": None,
        "finished_at": None,
        "latency_ms": None,
        "error_message": None,
    }
    return RunRow(**{**base, **values})
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

// GET /runs/{id}의 result (kind: "lms_sync"). 주차 항목·공지는 F-52·F-53이라 아직 0이다
export interface LmsSyncResult {
  kind: "lms_sync";
  courses: number;
  assignments: { new: number; due_changed: number; submitted: number };
  new_module_items: number;
  new_announcements: number;
}

// GET /lms/assignments?state=open|submitted|all&lms_course_id= (주지 않으면 open)
export type AssignmentState = "open" | "submitted" | "all";
export interface Assignment {
  id: string;
  course: { id: string; short_name: string };
  title: string;
  due_at: string | null;        // 마감이 없는 과제도 있다(due_at·lock_at 둘 다 없음)
  submission_state: SubmissionState;
  html_url: string | null;
  planner_task_id: string | null;
  calendar_registered: boolean;
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

