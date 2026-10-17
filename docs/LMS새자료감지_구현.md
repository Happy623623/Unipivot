# LMS 주차학습 새 자료 감지 — 새 항목은 수강생 모두에게 한 번, 피드로 모아 보기

> 📝 기준: PRD v0.9 F-52 · API 명세 v0.4 9장(LMS)·10장(알림) · ERD v0.9 LMS·알림 · 2026-10-17
>
> **먼저 합쳐야 한다**: `LMS과제동기화_구현.md`(F-51). 이 PR은 그 위에 쌓는다 — 같은 동기화 흐름에 주차 항목을 더하고, 같은 파일 여러 개를 이어서 고친다.

F-51은 과제를, 이 PR은 **주차학습 항목**을 받는다. 10/16 녹화(모듈 84개·항목 87건)를 테스트 샘플로 옮겼다.

- `POST /lms/sync`에 주차 모듈·항목 받기가 붙는다(결과의 `new_module_items`가 실제 수가 된다)
- 새 항목은 `new_material` 알림이 되고, **그 과목을 듣는 수강생 모두에게** 간다(항목은 과목 공통이다)
- `GET /lms/updates` — 새 주차 항목과 과제를 한 피드로(커서 쪽 넘김)
- `GET /lms/courses`의 `new_materials`가 실제 수가 된다

**DB 변경이 있다**: `lms_courses.modules_synced_at` 한 칸(아래 "정한 것" 2번). 마이그레이션 파일이 함께 들어 있고, `npx supabase db push`는 네가 터미널에서 돌려야 한다.

## 정한 것

1. **같은 항목인지는 `canvas_item_id`로만 가린다.** 녹화 87건 중 15쌍이 한 모듈 안에서 제목이 같았다(영상·슬라이드로 추정). 제목으로 가리면 한쪽이 사라진다.
2. **그 과목의 첫 수집에는 알림을 보내지 않는다.** 연결 직후에는 한 학기 분량이 한꺼번에 들어온다. 첫 수집인지는 새 칸 `lms_courses.modules_synced_at`으로 가린다 — "표에 그 과목 행이 있는지"로 가리면 **항목이 0건인 과목**(녹화 6과목 중 2과목)에 나중에 올라온 첫 자료가 영원히 첫 수집으로 묶인다. 첫 수집 때 `last_viewed_at`도 지금으로 올려서, 연결 전부터 있던 항목이 "새 자료" 수에 들어가지 않게 한다.
3. **새 항목 알림은 과목 단위 팬아웃이다.** 항목은 과목 공통 표라 누가 먼저 동기화하든 그 과목 수강생 모두가 한 번씩 받는다(ERD 3-2). **연결을 끊은 사람과 수강을 뺀 과목, 설정에서 끈 사람은 뺀다.**
4. **주차 모듈을 못 받아도 동기화는 성공이다.** 과제와 다르다 — 과제는 못 받으면 "사라진 과제"가 되지만, 주차 항목은 안 받으면 새 자료 수가 잠깐 비어 있을 뿐이다. 401(토큰 막힘)만 전체를 멈춘다.
5. **사라진 항목은 지우지 않는다.** `lms_module_items`에 `removed_at`이 없다(ERD). 교수가 항목을 지워도 기록은 남는다.
6. **피드(`GET /lms/updates`)는 처음 본 순이고 한 쪽 50개다.** `since`를 주지 않으면 최근 14일이고, **다음 쪽은 커서에 적힌 `since`를 쓴다** — 기본값이 요청마다 달라서 그대로 두면 둘째 쪽이 늘 422가 된다(검토에서 잡혔다). 마감 D-3 이내 미제출 과제는 `since`보다 오래됐어도 넣는다(명세 9장).
7. **공지는 아직 없다**(F-53). `?type=announcement`는 받아 두고 빈 목록을 준다.
8. **바로가기는 `html_url`이다.** `url`은 API 주소라 학생이 열면 JSON이 뜬다.
9. **`content_id`는 저장하지 않는다.** 명세 9장이 "Assignment 항목의 `content_id`로 주차와 과제를 이을 수 있다"고 적어 뒀지만 `lms_module_items`에 칸이 없다. 칸을 늘리는 대신 F-53 이후로 미룬다("남은 것").

## 레포에 넣는 법

**F-51(`LMS과제동기화_구현.md`)을 먼저 합친 다음에** 아래 블록을 Claude Code에 붙여.

````text
main에 F-51이 합쳐진 것을 확인하고, 새 브랜치 feat/F-52-lms-materials를 main에서 따 줘.
docs/LMS새자료감지_구현.md(방금 받은 파일)를 docs/에 넣고 아래를 해 줘.

[1] 문서 맨 아래 "코드" 절의 파일 14개를 그대로 만들거나 덮어써 줘. `#### `경로`` 아래 코드 블록이 그 파일의 전체 내용이다.
    새 파일: api/app/lms/modules.py · api/tests/test_lms_modules.py · supabase/migrations/20261017000000_lms_modules_synced_at.sql
    바뀌는 파일: api/app/lms/sync.py · api/app/repositories/lms.py · api/app/repositories/notifications.py · api/app/repositories/runs.py · api/app/routers/lms.py · api/app/schemas/lms.py · api/tests/lms_samples.py · api/tests/test_lms_db.py · api/tests/test_lms_sync.py · web/src/types/lms.ts · web/src/mocks/lms.ts
    (바뀌는 파일 안에는 F-51 내용이 이미 들어 있다. F-51을 합친 뒤라면 그대로 덮어쓰면 된다. 혹시 F-51과 다른 점이 보이면 덮어쓰지 말고 나한테 알려 줘.)

[2] "문서에 반영하기" 절의 블록대로 기준 문서를 고쳐 줘(API 명세 2곳 · ERD 4곳).

[3] DB 변경이 있다. 마이그레이션 파일을 새로 넣었으니 `npx supabase db push`는 **네가 직접** 터미널에서 돌려 줘(나는 돌리지 않는다). 이미 적용한 마이그레이션 파일은 고치지 마.

[4] 검사:
    api> uv run ruff check . && uv run ruff format --check . && uv run pytest
    web> npm run typecheck && npm run build
    로컬은 DATABASE_URL이 없어서 DB 테스트를 건너뛴다(`834 passed, 234 skipped`면 맞다). CI에서는 `1068 passed`다.

[5] 통과하면 "feat(F-52): 주차학습 새 자료 감지와 LMS 업데이트 피드" 커밋으로 PR을 올려 줘. 본문에 새 엔드포인트(GET /lms/updates)와 **DB 변경 있음(lms_courses.modules_synced_at)**을 적어 줘.
````


## 합친 뒤 확인

```bash
# 0) 마이그레이션 적용 (네가 터미널에서)
npx supabase db push

# 1) 동기화 — 주차 항목까지 받는다
curl -X POST localhost:8000/api/v1/lms/sync -H "Authorization: Bearer $TOKEN"
curl localhost:8000/api/v1/runs/<run_id> -H "Authorization: Bearer $TOKEN"
# → steps에 "주차 자료 받기"가 생기고, result.new_module_items가 채워진다(첫 수집은 알림 없이 수만)

# 2) 피드
curl "localhost:8000/api/v1/lms/updates" -H "Authorization: Bearer $TOKEN"
curl "localhost:8000/api/v1/lms/updates?type=module_item&lms_course_id=<uuid>" -H "Authorization: Bearer $TOKEN"
# next_cursor가 오면 그대로 다시 부른다(since는 커서가 가지고 있다)
curl "localhost:8000/api/v1/lms/updates?cursor=<next_cursor>" -H "Authorization: Bearer $TOKEN"

# 3) 과목 카드의 새 자료 수
curl localhost:8000/api/v1/lms/courses -H "Authorization: Bearer $TOKEN"

# 4) 두 번째 동기화에서 새 항목이 생기면 알림함에 "…자료가 올라왔어요"
curl localhost:8000/api/v1/notifications -H "Authorization: Bearer $TOKEN"
```

## 구조

```text
api/app/lms/modules.py     모듈·항목 응답 → 저장할 값 (ID로 가리기, 빈 모듈, 따로 받아야 하는 모듈)
api/app/lms/sync.py        fetch_lms_modules 단계와 저장·알림(과목 단위 팬아웃)
api/app/repositories/lms.py            save_module_items(첫 수집 가리기)·updates(피드 + 커서)
api/app/repositories/notifications.py  add_material_notices(수강생 전체, 끊은 사람 제외)
api/app/routers/lms.py                 GET /lms/updates (종류 검사, 커서 지문)
supabase/migrations/20261017000000_lms_modules_synced_at.sql   lms_courses.modules_synced_at
```

동기화 한 번(F-51 + F-52):

```text
POST /lms/sync
  └ agent_run(lms_sync)
      ├ fetch_lms_courses      수강 과목
      ├ fetch_lms_assignments  과목마다 과제 (F-51)
      ├ fetch_lms_modules      과목마다 주차 모듈·항목 (F-52)
      │                          항목이 함께 안 오면 modules/{id}/items로 보충
      │                          한 과목이 실패하면 그 과목만 건너뛴다(401은 멈춤)
      └ save_lms_sync          한 트랜잭션:
          ├ (F-51) 과제 저장 → 플래너 → 과제 알림
          ├ save_module_items   과목 공통 표에 upsert, 첫 수집이면 modules_synced_at·last_viewed_at 올림
          ├ add_material_notices  첫 수집이 아니면 수강생 모두에게 new_material
          └ touch_synced
```

## 확인한 것

| 확인 | 결과 |
| --- | --- |
| api 테스트 | DB 없이 `834 passed, 234 skipped`, DB를 붙이면 `1068 passed`. F-52로 더한 테스트 41개(항목 읽기 7 · 동기화·피드 15 · DB 19) |
| 항목 읽기(녹화 모양) | 모듈마다 항목 뽑기 · **제목이 같은 항목 둘 다 남음** · 빈 모듈 정상 · 모듈 이름 그대로(`Week 3 : …`, 빈 이름은 "주차 미정") · 따로 받아 온 항목 합치기 · 번호 없는·bool·bigint 초과·항목 아닌 값 거르기 · 종류·링크가 문자열이 아니면 비우기 |
| 동기화 | 과목마다 항목 저장 · 새 항목 → 수강생 알림 문구(명세 10장 꼴) · **첫 수집은 조용히**(수는 셈) · 결과의 `new_module_items` · 주차 모듈 실패는 과제 저장을 막지 않음 · 401은 멈춤 · 보충 경로로 따로 받기 · 도구 기록 네 개(`fetch_lms_courses`·`fetch_lms_assignments`·`fetch_lms_modules`·`save_lms_sync`) |
| 피드 API | 기본 14일·기본 종류 두 개 · 응답 모양(판별 union) · 필터 전달(KST→UTC) · **`since` 없이도 다음 쪽이 됨**(요청마다 시계가 가는 상황으로 시험) · 다른 목록 커서 422 · 깨진 커서 422 · 모르는 종류 422(빈 값·대문자·섞인 값) · 공지는 받아 두고 빈 목록 · 로그인 필요 |
| DB(실제 스키마) | 과목 공통 저장(두 사람이 같은 행) · 둘째 동기화에서 새 항목만 보고 · 제목 같은 둘 다 저장 · 처음 본 시각 유지(이름·종류·링크는 갱신) · **빈 과목에 나중에 올라온 첫 자료는 알림 대상** · 연결 전 항목은 새 자료로 안 셈 · 수강생 전체 알림(한 번만) · 끈 사람·끊은 사람·수강 뺀 과목 제외 · 피드: 항목+과제 함께, 종류·과목 필터, 오래된 것 제외, 마감 D-3 포함, 커서(같은 시각 8행도 빠짐·겹침 없음), 올린 파일 잇기, 남의 항목·남의 파일 안 보임, 수강 뺀 과목 제외 |
| 되돌림 시험 23가지 | 아래 "되돌림 시험" — **모두 잡혔다** |
| 빌드·검사 | api `ruff check`·`ruff format --check` 통과(197 파일). web `npm run typecheck`·`npm run build` 통과. 마이그레이션은 시험용 DB에 적용해 돌렸다. 실제 LearningX에는 접속하지 않았다 |

### 검토에서 고친 것

| 지적 | 고친 것 |
| --- | --- |
| **`since` 없이 부르면 둘째 쪽이 늘 422다.** 기본값이 "지금 − 14일"이라 커서 지문이 요청마다 달라진다 → 50개가 넘는 학생은 피드를 끝까지 볼 수 없다 | 지문을 조건(종류·과목)과 `since`로 나누고, 다음 쪽은 **커서에 적힌 `since`**를 쓴다. `since`는 UTC로 적어서 같은 시각을 다른 오프셋으로 보내도 같은 목록이다. 요청마다 시계가 가는 테스트로 못 박았다 |
| **항목이 0건이던 과목의 첫 자료가 영원히 안 알려진다.** "표에 행이 있는지"로 첫 수집을 가렸는데, 녹화 6과목 중 2과목이 과제·항목 0건이었다 | `lms_courses.modules_synced_at`을 더해 "이 과목 항목을 받은 적이 있는지"로 가린다(마이그레이션 포함). 그 테스트를 더했다 |
| **연결 직후 과목 카드에 "새 자료 87"이 뜬다.** F-50 연결은 과목까지만 받고 항목은 그 뒤 동기화에 들어와서, 전부 `last_viewed_at` 뒤가 된다 | 첫 수집 때 `last_viewed_at`을 지금으로 올린다(ERD 규칙 그대로). 그 테스트를 더했다 |
| **연결을 끊은 사람에게도 새 자료 알림이 간다.** 같이 듣는 사람이 동기화하면 팬아웃에 섞인다 | 연결이 남아 있는 사람에게만 만든다. 그 테스트를 더했다 |
| `GET /lms/updates`에 엔드포인트 테스트가 하나도 없다(저장소만 직접 불렀다) | 성공·401·모르는 종류 422·다른 목록 커서 422·깨진 커서 422·다음 쪽 이어 읽기까지 더했다(api/CLAUDE.md 규칙) |
| 피드 순서 테스트가 "둘 중 아무 순서나" 통과한다. 커서 테스트는 시각을 일부러 다르게 만들어서 **한 동기화에서 들어온 같은 시각 행**을 안 본다 | 순서 단정을 고치고, 같은 시각 8행을 2개씩 끊어 읽어 빠짐·겹침이 없는지 보는 테스트를 더했다 |
| 명세에 없는 필드(`item_type`)와 규칙(14일 기본·50개·커서 지문)을 코드가 먼저 갖고 있다 | 명세 9장 `GET /lms/updates`에 적었다(이 PR의 "문서에 반영하기") |
| 같은 항목이 다른 과목으로 옮겨지면 동기화마다 새 항목으로 센다 | upsert에서 `canvas_course_id`도 갱신한다 |
| 쓰지 않는 `UpdateType`이 라우터의 목록과 다르다 | 하나로 합쳐 라우터가 그 값을 쓴다 |

### 되돌림 시험 23가지

항목을 제목으로 가리기 · 첫 수집도 알리기 · 첫 수집 표시 안 남기기 · 첫 수집에 본 시각 안 올리기 · 처음 본 시각 다시 찍기 · 피드에서 수강 뺀 과목 안 걸러내기 · 피드가 남의 항목 보기 · 피드가 남이 올린 파일 보여 주기 · 피드가 마감 임박 과제 빼기 · 다음 쪽 판단용 한 개 더 안 받기 · 피드 종류 필터 빼기 · 새 자료 수가 본 시각 무시 · 자료 알림이 끊은 사람에게 가기 · 수강 뺀 과목에 가기 · 끈 종류도 만들기 · 알림 키를 과제 꼴로 쓰기 · 모듈 실패가 동기화 멈추기 · 보충 경로 안 받기 · 커서의 `since` 무시하고 다시 계산하기 · 모르는 종류 그대로 넘기기 · 다른 목록 커서 받아 주기 · 바로가기로 API 주소 주기 · 따로 온 항목 안 합치기 → **모두 잡혔다.**

## 남은 것

- **공지(F-53)가 비어 있다.** `GET /lms/updates`의 `announcement`와 동기화 결과의 `new_announcements`는 F-53이 채운다. 녹화 샘플은 `out2` 폴더에 그대로 있다 — **지우지 마.**
- **`GET /lms/courses/{id}`(과목 상세)가 아직 없다.** 명세 9장은 이 엔드포인트가 `last_viewed_at`을 갱신한다고 적어 뒀는데, 그걸 만들기 전까지는 **새 자료 수가 줄어들지 않는다**(동기화가 첫 수집 때 한 번 올릴 뿐이다). 과목 상세 PR에서 같이 넣는다.
- **`content_id`로 주차와 과제를 잇지 않는다**(정한 것 9번). 잇고 싶으면 `lms_module_items`에 칸을 더해야 한다.
- **사라진 항목을 지우지 않는다.** 교수가 지운 항목도 피드·수에 남는다. 표에 `removed_at`이 없어서 그대로 뒀다.
- **web 학업 화면은 아직 목이다.** 이 PR은 타입과 목 자료만 맞췄다(`web/src/types/lms.ts`·`src/mocks/lms.ts`).
- 캘린더 등록(F-51의 남은 것)은 그대로 열려 있다. 네가 셋 중 하나를 고르면 그 PR을 만든다.

## 문서에 반영하기

````text
문서 두 개를 고쳐 줘. 같은 브랜치에서 해. 아래 "찾을 줄"은 각 파일에 한 번만 나온다.

[1] docs/API_명세_v0.4.md — 9장 `POST /lms/sync` 결과 설명의 마지막 줄
찾을 줄:
- 마감 날짜를 캘린더에 넣는 일은 이 동기화에서 하지 않는다(사용자 캘린더에 쓰는 일이라 따로 정한다). `new_module_items`·`new_announcements`는 F-52·F-53이 채운다
이 줄을 아래 세 줄로 바꿔:
- 마감 날짜를 캘린더에 넣는 일은 이 동기화에서 하지 않는다(사용자 캘린더에 쓰는 일이라 따로 정한다). `new_announcements`는 F-53이 채운다
- `new_module_items`는 이번에 **처음 본 주차 항목** 수다. 그 과목의 항목을 처음 받는 동기화에서는 수만 세고 알림을 만들지 않는다 — 연결 직후에는 한 학기 분량이 한꺼번에 들어온다(녹화 87건). 그때 `lms_courses.last_viewed_at`도 지금으로 올려서 "새 자료" 수에도 들어가지 않게 한다
- 새 주차 항목 알림(`new_material`)은 그 과목을 듣는 **수강생 모두에게** 간다(항목은 과목 공통이다, ERD 3-2). 연결을 끊은 사람과 설정에서 끈 사람은 뺀다

[2] docs/API_명세_v0.4.md — 9장 `GET /lms/updates` 설명의 첫 줄
찾을 줄:
- `uploaded_file_id`: 사용자가 이 항목 알림에서 넘어가 PDF를 올렸으면 해당 파일. 프론트는 "업로드하기" 버튼 대신 "요약 보기"를 띄운다
이 줄 **앞에** 아래 네 줄을 넣어:
- `since`를 주지 않으면 최근 14일이다. 한 쪽은 50개이고, 더 있으면 `next_cursor`를 준다
- `cursor`는 **종류·과목이 같은 목록**에서만 쓸 수 있다(다르면 422 `VALIDATION_FAILED`, `details.fields.cursor`). 다음 쪽은 커서에 적힌 `since`를 쓴다 — 기본값(지금 − 14일)은 요청마다 달라서 그대로 두면 다음 쪽을 부를 수 없다
- 항목은 **처음 본 순**(최신 먼저)이다. `module_item`에는 `item_type`(`ExternalTool`·`Page`·`Quiz`·`Assignment`, 녹화에 `File`은 없었다)이 함께 간다. `module_name`·`html_url`·`item_type`은 null일 수 있다
- `assignment` 항목은 `{type, id, course, title, due_at, submission_state, html_url, first_seen_at}`이다. 새로 본 과제이거나 **마감 D-3 이내 미제출** 과제가 들어온다(마감 임박은 `since`보다 오래된 것도 넣는다)

[3] docs/ERD_v0.9.md — lms_courses 표(머메이드 그림)
찾을 줄:
        timestamptz last_viewed_at "새 자료 기준"
이 줄 뒤에 아래 한 줄을 넣어:
        timestamptz modules_synced_at "주차 항목 첫 수집"

[4] docs/ERD_v0.9.md — "과목 새 자료" 설명
찾을 줄:
- **과목 새 자료**: `first_seen_at`이 `lms_courses.last_viewed_at`보다 뒤인 주차 항목 수다. 과목 행이 생길 때 기본값이 첫 동기화 시각이라 연결 전부터 있던 항목은 세지 않고, 과목 상세를 열면 갱신한다.
이 줄을 아래 두 줄로 바꿔:
- **과목 새 자료**: `first_seen_at`이 `lms_courses.last_viewed_at`보다 뒤인 주차 항목 수다. 과목 행이 생길 때 기본값이 첫 동기화 시각이고, **주차 항목을 그 과목에서 처음 받을 때 다시 지금으로 올린다**(F-50 연결은 과목 목록까지만 받아서, 항목은 그 뒤 동기화에 들어온다 — 올리지 않으면 연결 전부터 있던 항목이 모두 "새 자료"가 된다). 과목 상세를 열면 또 갱신한다.
- **첫 수집 가리기**: 주차 항목을 그 과목에서 처음 받았는지는 `lms_courses.modules_synced_at`으로 본다. 표에 행이 있는지로 가리면 안 된다 — 항목이 0건인 과목이 흔해서(녹화 6과목 중 2과목) 나중에 올라온 첫 자료가 영원히 "첫 수집"으로 묶인다.

[5] docs/ERD_v0.9.md — "새 자료 감지" 설명의 앞부분
찾을 조각:
- **새 자료 감지**: 동기화 때 `canvas_item_id`가 처음 보이면 `lms_module_items`에 넣고, 그 과목 수강생에게 `new_material` 알림을 만든다.
이 조각을 아래로 바꿔:
- **새 자료 감지**: 동기화 때 `canvas_item_id`가 처음 보이면 `lms_module_items`에 넣고, 그 과목 수강생에게 `new_material` 알림을 만든다(**연결을 끊은 사람과 수강을 뺀 과목은 뺀다** — 해제하면 동기화를 멈춘다). 그 과목의 첫 수집에는 만들지 않는다.

[6] docs/ERD_v0.9.md — 7장 마이그레이션 표의 마지막 줄
찾을 줄:
| 8 | `supabase/migrations/20261013000000_opportunity_marks.sql` | opportunity_marks(관심·관심 없음 표시, F-45), opportunity_id 인덱스, RLS 본인 행 읽기 |
이 줄 뒤에 아래 세 줄을 넣어(9·10번은 이미 레포에 있는데 표에 빠져 있던 것이다):
| 9 | `supabase/migrations/20261014090000_region_merge_jeonnam_gwangju.sql` | 지역 코드 정리(전남·광주 병합) |
| 10 | `supabase/migrations/20261014091000_tool_calls_input_comment.sql` | tool_calls.input 주석(프로필 값을 넣지 않는다) |
| 11 | `supabase/migrations/20261017000000_lms_modules_synced_at.sql` | lms_courses.modules_synced_at(주차 항목 첫 수집, F-52) |

문서 머리의 보강 이력 줄이 있으면 "v0.9 보강 (2026-10-17): 주차 항목 첫 수집 표시(F-52)"를 같은 꼴로 한 줄 더해 줘.
````

## 코드

아래 파일 14개를 그대로 만들거나 바꾼다. **F-51을 합친 뒤**에 옮겨야 한다(바뀌는 파일에 F-51 내용이 들어 있다). 샌드박스에서 마이그레이션을 적용한 DB로 `pytest`를 돌리고, `ruff`·web `typecheck`·`build`를 통과하고 되돌림 시험 23가지를 모두 잡은 코드다. 실제 LearningX에는 접속하지 않았다.

### DB (새 마이그레이션)

#### `supabase/migrations/20261017000000_lms_modules_synced_at.sql`

```sql
-- F-52: 주차 항목을 그 과목에서 처음 받았는지 기록한다.
-- 연결하고 처음 받으면 한 학기 분량(녹화 87건)이 모두 "새 항목"이라 알림을 보내지 않는다.
-- 항목이 0건인 과목이 흔해서(녹화 6과목 중 2과목) "표에 행이 있는지"로는 가릴 수 없다.
alter table lms_courses add column modules_synced_at timestamptz;

comment on column lms_courses.modules_synced_at is
  '주차 항목을 처음 받은 시각. null이면 아직 안 받았다 — 그 첫 수집은 새 자료 알림을 보내지 않는다';
```

### api (새 파일)

#### `api/app/lms/modules.py`

```python
"""Canvas 모듈(주차)·항목 응답 → 저장할 값 (F-52, API 명세 9장의 10/16 녹화 규칙).

녹화(6과목·모듈 84개·항목 87건)에서 확정한 것만 따른다:

- 같은 항목인지는 **`canvas_item_id`로만** 가린다. 한 모듈에 제목이 같은 항목이 둘씩 있다(15쌍)
- 항목 `type`은 `ExternalTool`(LearningX 출석·영상 LTI) 75 · `Assignment` 7 · `Quiz` 4 · `Page` 1이었고
  **`File`은 한 건도 없었다**. 자료 파일은 Canvas에 없고 LearningX 안에서만 열린다(PRD 5-6)
- 바로가기는 `html_url`이다(`url`은 API 주소라 학생이 열 수 없다)
- 모듈 이름은 `1주차`·`5주차 (개천절 대체휴일)`·`Week 3 : …`가 섞인다. 그대로 저장하고 주차 번호를
  따로 뽑지 않는다. `position`은 연속이 아니라(1주차가 position 17인 과목이 있다) 저장하지 않는다
- 항목이 없는 모듈이 흔하다(84개 중 47개가 `items: []`). 빈 모듈은 오류가 아니다
- `include[]=items`로 항목이 함께 오지만, 항목이 많으면 `items` 키가 빠질 수 있다(Canvas 문서).
  그때는 `items_url` 경로로 따로 받는다 — `needs_items`가 그 모듈을 가린다
"""

import logging
from dataclasses import dataclass
from typing import Any

from app.lms.parse import is_canvas_id

logger = logging.getLogger(__name__)

NO_NAME = "주차 미정"  # 이름이 빈 모듈. 알림 문구에 그대로 쓴다
NO_TITLE = "(제목 없음)"


@dataclass(frozen=True)
class CanvasModuleItem:
    """저장 직전의 주차 항목 하나. `lms_module_items` 칸과 같은 이름이다."""

    canvas_item_id: int
    module_name: str
    title: str
    item_type: str | None
    html_url: str | None


def needs_items(module: Any) -> int | None:
    """항목이 함께 오지 않은 모듈의 번호. 따로 받아야 한다(없으면 None)."""
    if not isinstance(module, dict) or "items" in module:
        return None
    number = module.get("id")
    return number if is_canvas_id(number) else None


def module_items(
    modules: list[Any], *, extra: dict[int, list[Any]] | None = None
) -> list[CanvasModuleItem]:
    """모듈 목록 응답을 저장할 값으로. `extra`는 따로 받아 온 모듈별 항목이다."""
    items: list[CanvasModuleItem] = []
    for module in modules:
        if not isinstance(module, dict):
            continue
        name = (module.get("name") or "").strip() or NO_NAME
        raw = module.get("items")
        if raw is None and extra is not None and is_canvas_id(module.get("id")):
            raw = extra.get(module["id"])
        for one in raw or []:
            parsed = item(one, module_name=name)
            if parsed is not None:
                items.append(parsed)
    return items


def item(raw: Any, *, module_name: str) -> CanvasModuleItem | None:
    """항목 하나. 번호가 없으면 None이다(번호가 같은 항목인지 가리는 유일한 기준이다)."""
    if not isinstance(raw, dict) or not is_canvas_id(raw.get("id")):
        return None
    kind = raw.get("type")
    return CanvasModuleItem(
        canvas_item_id=raw["id"],
        module_name=module_name,
        title=(raw.get("title") or "").strip() or NO_TITLE,
        item_type=kind if isinstance(kind, str) and kind else None,
        html_url=raw.get("html_url") if isinstance(raw.get("html_url"), str) else None,
    )
```

### api (바뀌는 파일)

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

캘린더 등록은 아직 하지 않는다(사용자 구글 캘린더에 쓰는 일이라 따로 정한다). 과목 공지는 F-53이다.

주차 항목(F-52)은 과목 공통이라 저장도 알림도 과목 단위다. 그 과목의 항목을 **이번에 처음** 받으면
한 학기 분량이 모두 "새 항목"이라 알림을 보내지 않고 저장만 한다.
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
from app.lms.modules import CanvasModuleItem, module_items, needs_items
from app.lms.service import API_ERROR, NOT_CONNECTED, TOKEN_EXPIRED, student_courses
from app.repositories.lms import (
    AssignmentChanges,
    CourseRow,
    LmsRepository,
    ModuleChanges,
    SavedAssignment,
    SavedItem,
)
from app.repositories.notifications import (
    AssignmentNotice,
    MaterialNotice,
    NotificationRepository,
)
from app.schemas.lms import SAVE_TOOL, SyncCounts, SyncResponse, SyncSkipped, SyncStarted

logger = logging.getLogger(__name__)
Connect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]

SKIP_AFTER = timedelta(minutes=5)  # 이 안에 동기화했으면 건너뛴다(명세 9장)
BATCH_USERS = 50  # 배치 한 번에 보는 사용자 수 상한. 넘으면 다음 차례에 간다
STOPPED = "동기화를 시작하지 못했어요. 잠시 후 다시 시도해 주세요."
TOKEN_UNREADABLE = "저장한 토큰을 읽을 수 없어요. 다시 연결해 주세요."
NEW_TITLE = "{course} 새 과제가 올라왔어요"
MATERIAL_TITLE = "{course} {module} 자료가 올라왔어요"


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
    new_items: int = 0  # 처음 본 주차 항목(F-52)
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
        modules = await self._fetch_modules(run, job, rows)
        if rows and failed and not fetched:
            # 과목이 있는데 한 과목도 받지 못했다. 저장할 것도 없고 성공으로 적으면 안 된다
            # (`touch_synced`가 오류 표시를 지워 버린다). 다음 배치에서 다시 시도한다
            raise ApiError(502, "LMS_API_ERROR", API_ERROR)
        outcome = await self._save(job, fetched, modules, failed=failed)
        async with run.tool(SAVE_TOOL) as call:
            # `GET /runs/{id}`가 이 출력으로 결과를 만든다(repositories/runs.py)
            call.output = {
                "courses": outcome.courses,
                "new": outcome.created,
                "due_changed": outcome.due_changed,
                "submitted": outcome.submitted,
                "new_module_items": outcome.new_items,
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
                    failed += self._skip(exc, course, what="과제 목록")
                    continue
                fetched.append((course, assignments(raw)))
            call.output = {
                "courses": len(fetched),
                "assignments": sum(len(items) for _, items in fetched),
                "failed_courses": failed,
            }
        return fetched, failed

    async def _fetch_modules(
        self, run: AgentRun, job: SyncJob, rows: list[CourseRow]
    ) -> list[tuple[CourseRow, list[CanvasModuleItem]]]:
        """과목마다 주차 모듈·항목을 받는다(F-52). 실패한 과목은 그냥 두고 넘어간다.

        과제와 달리 실패를 세지 않는다 — 과제는 받았는데 주차 항목만 못 받았다고 동기화 전체를
        실패로 적을 이유가 없다(새 자료 수가 잠깐 비어 있을 뿐이다).
        """
        fetched: list[tuple[CourseRow, list[CanvasModuleItem]]] = []
        async with run.tool("fetch_lms_modules", {"courses": len(rows)}) as call:
            for course in rows:
                try:
                    modules = await self.client.modules(job.token, course.canvas_course_id)
                    extra = await self._missing_items(job, course, modules)
                except LearningXError as exc:
                    self._skip(exc, course, what="주차 모듈")
                    continue
                fetched.append((course, module_items(modules, extra=extra)))
            call.output = {
                "courses": len(fetched),
                "items": sum(len(items) for _, items in fetched),
            }
        return fetched

    async def _missing_items(
        self, job: SyncJob, course: CourseRow, modules: list[Any]
    ) -> dict[int, list[Any]]:
        """`include[]=items`로 항목이 오지 않은 모듈만 따로 받는다(녹화에서는 없었다)."""
        extra: dict[int, list[Any]] = {}
        for module in modules:
            number = needs_items(module)
            if number is None:
                continue
            extra[number] = await self.client.module_items(
                job.token, course.canvas_course_id, number
            )
        return extra

    def _skip(self, exc: LearningXError, course: CourseRow, *, what: str) -> int:
        """한 과목을 건너뛴다. 토큰이 막힌 경우(401)는 남은 과목도 못 받으니 멈춘다."""
        if exc.unauthorized:
            raise ApiError(422, "LMS_TOKEN_INVALID", TOKEN_EXPIRED) from exc
        logger.warning(
            "%s을 받지 못해 그 과목은 두고 넘어가요: course %s, status %s",
            what,
            course.canvas_course_id,
            exc.status,
        )
        return 1

    async def _save(
        self,
        job: SyncJob,
        fetched: list[tuple[CourseRow, list[CanvasAssignment]]],
        modules: list[tuple[CourseRow, list[CanvasModuleItem]]],
        *,
        failed: int,
    ) -> SyncOutcome:
        """받아 둔 과제·주차 항목을 한 트랜잭션에 쓰고, 플래너·알림을 맞춘다."""
        changes = AssignmentChanges()
        notices: list[AssignmentNotice] = []
        items = ModuleChanges()
        made = 0
        async with self.transaction() as conn:
            repos = self.repos(conn)
            repo, notes = repos.lms, repos.notes
            for course, assignment_items in fetched:
                one = await repo.save_assignments(
                    job.user_id, course.id, assignment_items, now=job.now
                )
                changes = changes + one
                # 이미 낸 과제는 알리지 않는다(연결 첫 동기화에 지난 과제가 한꺼번에 들어온다)
                notices += [_notice(course, saved) for saved in one.created if not saved.submitted]
            await repo.sync_planner(job.user_id, changes, now=job.now)
            # 제출한 과제는 알림을 멈춘다(명세 10장). 새 과제 알림은 찾은 때 바로 보낸다
            await notes.drop_assignment_notices(job.user_id, changes.submitted)
            made += await notes.add_assignment_notices(job.user_id, notices, now=job.now)
            for course, module_list in modules:
                one_course = await repo.save_module_items(
                    job.user_id, course.canvas_course_id, module_list, now=job.now
                )
                items = items + one_course
                # 주차 항목은 과목 공통이라 그 과목 수강생 모두에게 간다(첫 수집이면 보내지 않는다)
                made += await notes.add_material_notices(
                    course.canvas_course_id,
                    [_material(course, saved) for saved in one_course.notifiable],
                    now=job.now,
                )
            await repo.touch_synced(job.user_id, now=job.now)
        return SyncOutcome(
            courses=len(fetched),
            created=len(changes.created),
            due_changed=len(changes.due_changed),
            submitted=len(changes.submitted),
            new_items=len(items.created),
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


def _material(course: CourseRow, saved: SavedItem) -> MaterialNotice:
    """새 주차 항목 알림 문구(명세 10장 예시와 같은 꼴): "기계학습 8주차 자료가 올라왔어요"."""
    return MaterialNotice(
        item_id=saved.id,
        title=MATERIAL_TITLE.format(course=course.short_name, module=saved.module_name),
        body=saved.title,
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

#### `api/app/repositories/lms.py`

```python
"""LearningX 연결과 과목 (F-50·F-14, ERD 3-2).

- 토큰은 암호화한 값만 저장하고(`lms_connections.access_token`), 화면에는 끝 4자리만 보낸다
- 과목은 `(user_id, canvas_course_id)`로 upsert하고, 이번 동기화에 없던 과목은 `is_active`를 내린다
  (수강을 뺀 과목이다 — 과제·공지 기록은 남겨 두고 목록에서만 뺀다). **목록이 비어 오면 내리지 않는다**
- 과목 목록의 숫자는 지금 저장된 것으로 센다. 주차 항목 동기화는 F-52라 `new_materials`는 그때까지 0이다
- 주차 항목(`lms_module_items`)은 **과목 공통**이라 `user_id`가 없다(ERD 3-2). `canvas_item_id`로만
  같은 항목인지 가리고, 사라진 항목은 지우지 않는다
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
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection

from app.db import get_conn
from app.eligibility import KST
from app.lms.assignments import SUBMITTED, CanvasAssignment
from app.lms.modules import CanvasModuleItem
from app.lms.parse import course_name, is_canvas_id
from app.repositories.opportunities import Cursor
from app.schemas.lms import (
    AssignmentCourse,
    AssignmentItem,
    AssignmentUpdate,
    ConnectionView,
    CourseItem,
    ModuleItemUpdate,
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
class SavedItem:
    """막 저장한 주차 항목. 알림 문구를 만들 만큼만 담는다."""

    id: str
    module_name: str
    title: str


@dataclass(frozen=True)
class ModuleChanges:
    """한 과목의 주차 항목을 저장하고 바뀐 것.

    `first_load`는 그 과목의 항목을 **이번에 처음** 받았다는 뜻이다. 연결하고 처음 받으면 한 학기
    분량(녹화 87건)이 모두 "새 항목"이라 알림을 보내지 않는다(저장만 한다).
    """

    created: list[SavedItem] = field(default_factory=list)
    first_load: bool = False

    # 과목을 더해 합칠 때 first_load는 OR다(수를 세는 데만 쓴다). 알림은 과목마다 `notifiable`로
    # 가려야 한다 — 합친 값으로 가리면 첫 수집 과목 하나가 다른 과목 알림까지 막는다
    def __add__(self, other: "ModuleChanges") -> "ModuleChanges":
        return ModuleChanges(
            created=self.created + other.created,
            first_load=self.first_load or other.first_load,
        )

    @property
    def notifiable(self) -> list[SavedItem]:
        """알림을 만들 항목. 첫 수집이면 없다."""
        return [] if self.first_load else self.created


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
UPDATE_LIMIT = 50  # `GET /lms/updates` 한 쪽
DEADLINE_SOON = timedelta(days=3)  # 피드에 넣는 "마감 임박"(명세 9장: D-3 이내 미제출)

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

# 새 주차 항목과 과제를 한 피드로(명세 9장 `GET /lms/updates`). 둘을 같은 모양으로 맞춰 union한다.
# 주차 항목은 과목 공통 표라 과목 번호로 내 수강 과목에 잇는다(그래서 남의 과목 항목은 안 나온다)
_UPDATES = (
    "select * from ("
    "  select 'module_item' as kind, i.id, i.first_seen_at as at, c.id as course_id,"
    "    c.name as course_name, i.module_name, i.title, i.item_type, i.html_url,"
    "    null::timestamptz as due_at, null as submission_state,"
    "    (select f.id from files f where f.lms_module_item_id = i.id and f.user_id = c.user_id"
    "      order by f.created_at, f.id limit 1) as uploaded_file_id"
    "  from lms_module_items i"
    "  join lms_courses c on c.canvas_course_id = i.canvas_course_id and c.user_id = %(uid)s"
    "    and coalesce(c.is_active, true)"
    "  where i.first_seen_at >= %(since)s"
    "  union all"
    "  select 'assignment', a.id, a.first_seen_at, c.id, c.name, null, a.title, null, a.html_url,"
    "    a.due_at, a.submission_state::text, null"
    "  from lms_assignments a"
    "  join lms_courses c on c.id = a.lms_course_id and c.user_id = a.user_id"
    "  where a.user_id = %(uid)s and a.removed_at is null and coalesce(c.is_active, true)"
    # 새 과제이거나, 마감이 가까운 미제출 과제다(명세 9장)
    "    and (a.first_seen_at >= %(since)s or (a.submission_state = 'unsubmitted'"
    "      and a.due_at >= %(now)s and a.due_at < %(soon)s))"
    ") as feed where kind = any(%(kinds)s::text[])"
)

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
    # (연결 전부터 있던 항목은 첫 수집 때 last_viewed_at을 올려서 빼고 센다, save_module_items)
    " (select count(*) from lms_module_items i where i.canvas_course_id = c.canvas_course_id"
    "   and i.first_seen_at > coalesce(c.last_viewed_at, to_timestamp(0))) as new_materials,"
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

_UPSERT_ITEM = (
    "insert into lms_module_items (canvas_course_id, canvas_item_id, module_name, title,"
    " item_type, html_url, first_seen_at)"
    " values (%(canvas)s, %(item)s, %(module)s, %(title)s, %(kind)s, %(url)s, %(now)s)"
    # 처음 본 때(`first_seen_at`)는 그대로 둔다. 새 자료 수(`GET /lms/courses`)가 그 시각을 본다
    # 과목이 바뀐 항목(과목 복제 등)은 새 과목으로 다시 붙인다. 안 그러면 동기화마다 새 항목이 된다
    " on conflict (canvas_item_id) do update set canvas_course_id = excluded.canvas_course_id,"
    " module_name = excluded.module_name, title = excluded.title,"
    " item_type = excluded.item_type, html_url = excluded.html_url"
    " returning id"
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

    async def updates(
        self,
        user_id: str,
        *,
        since: datetime,
        now: datetime,
        kinds: list[str],
        course_id: str | None = None,
        cursor: Cursor | None = None,
        limit: int = UPDATE_LIMIT,
    ) -> tuple[list[Any], Cursor | None]:
        """새 주차 항목·과제 피드(F-52·F-51). 처음 본 순(최신 먼저)이고 한 쪽은 `limit`개다.

        `cursor`는 같은 조건(지문)에서만 쓸 수 있다. 마지막 행의 (처음 본 시각, id) 뒤를 이어 읽는다.
        """
        query = _UPDATES
        params: dict[str, Any] = {
            "uid": user_id,
            "since": since,
            "now": now,
            "soon": now + DEADLINE_SOON,
            "kinds": kinds,
        }
        if course_id is not None:
            query += " and course_id = %(course)s"
            params["course"] = course_id
        if cursor is not None:
            query += " and (at, id) < (%(at)s, %(last)s)"
            params["at"], params["last"] = cursor.value, cursor.id
        query += " order by at desc, id desc limit %(limit)s"
        params["limit"] = limit + 1  # 한 개 더 받아 다음 쪽이 있는지 본다
        rows = await self._rows(query, params)
        more = len(rows) > limit
        rows = rows[:limit]
        items = [_update(row) for row in rows]
        if not more or not rows:
            return items, None
        last = rows[-1]
        return items, Cursor(
            scope=update_scope(kinds, course_id, since), value=last["at"], id=str(last["id"])
        )

    async def save_module_items(
        self, user_id: str, canvas_course_id: int, items: list[CanvasModuleItem], *, now: datetime
    ) -> ModuleChanges:
        """주차 항목을 저장하고 처음 본 것을 돌려준다.

        `lms_module_items`는 **과목 공통 표**라 `user_id`가 없다(ERD 3-2: 주차 항목은 수강생 모두에게
        같다). 그래서 다른 수강생이 먼저 동기화했으면 나에게는 "처음 본 항목"이 아니다 — 알림은
        그때 그 과목 수강생 모두에게 한 번 만든다(`add_material_notices`).

        **첫 수집인지는 내 과목 행의 `modules_synced_at`으로 가린다.** 표에 행이 있는지로 가리면
        안 된다 — 항목이 0건인 과목이 흔해서(녹화 6과목 중 2과목) 그 과목에 나중에 올라온 첫 자료가
        영원히 "첫 수집"으로 묶인다. 첫 수집에는 `last_viewed_at`도 지금으로 올려서, 연결 전부터
        있던 항목이 "새 자료" 수에 들어가지 않게 한다(ERD 알림함·조회 기록).

        사라진 항목은 지우지 않는다(표에 `removed_at`이 없다). 교수가 항목을 지워도 기록은 남는다.
        """
        row = await self._row(
            "select modules_synced_at from lms_courses"
            " where user_id = %s and canvas_course_id = %s",
            (user_id, canvas_course_id),
        )
        first_load = row is None or row["modules_synced_at"] is None
        before = {
            row["canvas_item_id"]
            for row in await self._rows(
                "select canvas_item_id from lms_module_items where canvas_course_id = %s",
                (canvas_course_id,),
            )
        }
        created: list[SavedItem] = []
        for one in items:
            row = await self._row(
                _UPSERT_ITEM,
                {
                    "canvas": canvas_course_id,
                    "item": one.canvas_item_id,
                    "module": one.module_name,
                    "title": one.title,
                    "kind": one.item_type,
                    "url": one.html_url,
                    "now": now,
                },
            )
            assert row is not None  # insert ... returning은 늘 한 행이다
            if one.canvas_item_id not in before:
                created.append(
                    SavedItem(
                        id=str(row["id"]),
                        module_name=one.module_name,
                        title=one.title,
                    )
                )
        # 첫 수집 표시와 "여기까지 봤다"를 함께 올린다(둘 다 그 사용자 과목 행이다)
        await self.conn.execute(
            "update lms_courses set modules_synced_at = %(now)s,"
            " last_viewed_at = greatest(coalesce(last_viewed_at, %(now)s), %(now)s)"
            " where user_id = %(uid)s and canvas_course_id = %(canvas)s"
            " and modules_synced_at is null",
            {"uid": user_id, "canvas": canvas_course_id, "now": now},
        )
        return ModuleChanges(created=created, first_load=first_load)

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


def update_scope(kinds: list[str], course_id: str | None, since: datetime) -> str:
    """피드 조건의 지문. 조건이 다른 목록에는 그 커서를 쓸 수 없다(명세 9장).

    `since`는 UTC로 적는다 — 같은 시각을 다른 오프셋으로 보내도 같은 목록이다. 조건 부분과 `since`를
    `|`로 나눠 두므로, 다음 쪽을 부를 때 커서에서 `since`를 되읽을 수 있다(기본값이 매 요청 달라지는
    문제를 막는다).
    """
    return f"{update_filter(kinds, course_id)}|{since.astimezone(UTC).isoformat()}"


def update_filter(kinds: list[str], course_id: str | None) -> str:
    """지문에서 `since`를 뺀 부분(종류·과목)."""
    return f"{','.join(sorted(kinds))}|{course_id or ''}"


def update_since(scope: str) -> datetime | None:
    """커서 지문에 적힌 `since`. 모양이 틀리면 None이다."""
    try:
        return datetime.fromisoformat(scope.rsplit("|", 1)[1])
    except (IndexError, ValueError):
        return None


def _update(row: dict[str, Any]) -> ModuleItemUpdate | AssignmentUpdate:
    course = AssignmentCourse(
        id=str(row["course_id"]), short_name=course_name(row["course_name"]).short_name
    )
    if row["kind"] == "module_item":
        return ModuleItemUpdate(
            id=str(row["id"]),
            course=course,
            module_name=row["module_name"],
            title=row["title"],
            item_type=row["item_type"],
            html_url=row["html_url"],
            first_seen_at=row["at"].astimezone(KST),
            uploaded_file_id=str(row["uploaded_file_id"]) if row["uploaded_file_id"] else None,
        )
    return AssignmentUpdate(
        id=str(row["id"]),
        course=course,
        title=row["title"],
        due_at=row["due_at"].astimezone(KST) if row["due_at"] else None,
        submission_state=row["submission_state"],
        html_url=row["html_url"],
        first_seen_at=row["at"].astimezone(KST),
    )


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
MATERIAL_TYPE = "new_material"  # 새 주차 항목(F-52). 과목 수강생 모두에게 간다
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
class MaterialNotice:
    """새 주차 항목 알림 하나. 문구는 과목 이름을 아는 쪽(app/lms/sync.py)에서 만든다."""

    item_id: str
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

    async def add_material_notices(
        self, canvas_course_id: int, notices: Sequence[MaterialNotice], *, now: datetime
    ) -> int:
        """새 주차 항목 알림을 **그 과목 수강생 모두에게** 만든다(ERD 3-2: 항목은 과목 공통이다).

        과제 알림과 달리 사용자를 받지 않는다 — 항목을 처음 본 쪽이 누구든 수강생 전체가 받는다.
        연결을 끊은 사람과 끈 종류는 만들지 않고, 같은 항목은 `dedupe_key`로 한 번만 만든다.
        """
        created = 0
        for notice in notices:
            cursor = await self.conn.execute(
                "insert into notifications (user_id, type, lms_module_item_id, title, body,"
                " scheduled_at, dedupe_key)"
                " select c.user_id, %(type)s, %(item)s::uuid, %(title)s, %(body)s, %(now)s,"
                # 키 꼴은 ERD 5장 표 그대로다: new_material:mod:{lms_module_item_id}
                " %(type)s || ':mod:' || %(item)s"
                " from lms_courses c"
                # 연결을 끊은 사람에게는 보내지 않는다(명세 9장: 해제하면 동기화를 멈춘다).
                # 해제하면 연결 행이 지워지므로 inner join이다
                " join lms_connections n on n.user_id = c.user_id and n.status <> 'disconnected'"
                " left join user_settings s on s.user_id = c.user_id"
                " where c.canvas_course_id = %(canvas)s and coalesce(c.is_active, true)"
                "   and not (%(type)s = any(coalesce(s.muted_notification_types, '{}')))"
                " on conflict (user_id, dedupe_key) do nothing",
                {
                    "canvas": canvas_course_id,
                    "type": MATERIAL_TYPE,
                    "item": notice.item_id,
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
    "fetch_lms_modules": "주차 자료 받기",
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
                # F-52 전 실행에는 이 칸이 없다(그때는 주차 항목을 받지 않았다)
                new_module_items=int(output.get("new_module_items", 0)),
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

from datetime import datetime, timedelta
from typing import Annotated, get_args
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.auth import CurrentUserDep
from app.clock import NowDep
from app.errors import ApiError
from app.lms.service import NOT_CONNECTED, LmsServiceDep
from app.lms.sync import LmsSyncServiceDep
from app.repositories.lms import LmsRepoDep, update_filter, update_since
from app.repositories.opportunities import decode_cursor, encode_cursor
from app.schemas.lms import (
    AssignmentList,
    AssignmentState,
    ConnectionView,
    ConnectRequest,
    ConnectResult,
    CourseList,
    LmsUpdateList,
    SyncResponse,
    SyncSkipped,
    UpdateType,
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


UPDATE_KINDS = get_args(UpdateType)  # 쓸 수 있는 종류(schemas/lms.py와 한 곳에서 본다)
SINCE_DAYS = 14  # since를 주지 않으면 최근 이만큼


@router.get("/updates", response_model=LmsUpdateList)
async def updates(
    user: CurrentUserDep,
    repo: LmsRepoDep,
    now: NowDep,
    since: Annotated[datetime | None, Query(description="이 시각 뒤에 처음 본 것")] = None,
    type: Annotated[str, Query(description="쉼표로 나눈 종류")] = "module_item,assignment",
    lms_course_id: Annotated[UUID | None, Query(description="과목 하나만 볼 때")] = None,
    cursor: Annotated[str | None, Query(description="다음 쪽")] = None,
) -> LmsUpdateList:
    """새 주차 항목·과제 피드(F-52·F-51). 처음 본 순이고, 마감 D-3 이내 미제출 과제도 넣는다.

    `since`를 주지 않으면 최근 14일이다. `cursor`를 주면 그 커서에 적힌 `since`를 쓴다(기본값은 요청마다
    달라서 그대로 두면 다음 쪽을 부를 수 없다). 종류·과목이 다른 목록의 커서는 422다.
    한 쪽은 50개이고, 공지(`announcement`)는 F-53이 채운다.
    """
    kinds = [one.strip() for one in type.split(",") if one.strip()]
    unknown = [one for one in kinds if one not in UPDATE_KINDS]
    if not kinds or unknown:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "볼 종류를 확인해 주세요.",
            {"fields": {"type": f"{', '.join(UPDATE_KINDS)} 중에서 골라 주세요."}},
        )
    course = str(lms_course_id) if lms_course_id else None
    start = since or now - timedelta(days=SINCE_DAYS)
    last = None
    if cursor is not None:
        try:
            last = decode_cursor(cursor)
        except ValueError:
            last = None
        # `since`는 커서에 적힌 값을 쓴다. 기본값(지금 - 14일)은 요청마다 달라서, 지문에 넣고 그대로
        # 비교하면 둘째 쪽이 늘 422가 된다
        from_cursor = update_since(last.scope) if last else None
        if (
            last is None
            or from_cursor is None
            or not last.scope.startswith(f"{update_filter(kinds, course)}|")
        ):
            raise ApiError(
                422,
                "VALIDATION_FAILED",
                "목록 조건이 바뀌었어요. 처음부터 다시 불러 주세요.",
                {"fields": {"cursor": "조건이 다른 목록의 커서예요."}},
            )
        start = from_cursor
    items, next_cursor = await repo.updates(
        user.id, since=start, now=now, kinds=kinds, course_id=course, cursor=last
    )
    return LmsUpdateList(
        items=items, next_cursor=encode_cursor(next_cursor) if next_cursor else None
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
from typing import Annotated, Literal

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


# `GET /lms/updates?type=`에 쓸 수 있는 값. 공지(`announcement`)는 F-53이 채운다(그때까지 결과가 빈다)
UpdateType = Literal["module_item", "assignment", "announcement"]


class ModuleItemUpdate(BaseModel):
    """새 주차 항목 하나(F-52)."""

    type: Literal["module_item"] = "module_item"
    id: str
    course: AssignmentCourse
    module_name: str | None
    title: str
    item_type: str | None  # ExternalTool · Assignment · Quiz · Page (녹화에 File은 없었다)
    html_url: str | None
    first_seen_at: datetime  # KST 오프셋
    uploaded_file_id: str | None  # 이 항목 알림에서 올린 PDF가 있으면 그 파일


class AssignmentUpdate(BaseModel):
    """새 과제나 마감이 가까운 미제출 과제 하나(F-51)."""

    type: Literal["assignment"] = "assignment"
    id: str
    course: AssignmentCourse
    title: str
    due_at: datetime | None
    submission_state: SubmissionState
    html_url: str | None
    first_seen_at: datetime


LmsUpdateItem = Annotated[ModuleItemUpdate | AssignmentUpdate, Field(discriminator="type")]


class LmsUpdateList(BaseModel):
    items: list[LmsUpdateItem]
    next_cursor: str | None


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

### api (새 테스트)

#### `api/tests/test_lms_modules.py`

```python
"""Canvas 모듈(주차)·항목 읽기(F-52). DB·네트워크 없이 돈다.

녹화(모듈 84개·항목 87건)에서 확정한 규칙만 본다: 같은 항목은 `canvas_item_id`로만 가린다,
바로가기는 `html_url`, 빈 모듈은 오류가 아니다.
"""

from typing import Any

from app.lms.modules import NO_NAME, NO_TITLE, item, module_items, needs_items
from tests.lms_samples import DB_MODULES, ML_MODULES, MODULE_WITHOUT_ITEMS


def test_it_reads_the_items_of_every_module() -> None:
    items = module_items(DB_MODULES)
    assert [(one.canvas_item_id, one.module_name, one.title, one.item_type) for one in items] == [
        (8569302, "3주차", "3주차 강의", "ExternalTool"),
        (8569303, "3주차", "3주차 강의", "ExternalTool"),  # 제목이 같아도 둘 다 남는다
        (8569304, "3주차", "3주차 퀴즈", "Quiz"),
    ]
    assert items[0].html_url == "https://lms.test/courses/214023/modules/items/8569302"


def test_two_items_with_the_same_title_are_different_items() -> None:
    """녹화 87건 중 15쌍이 한 모듈 안에서 제목이 같았다. 제목으로 가리면 하나가 사라진다."""
    items = module_items(DB_MODULES)
    same = [one for one in items if one.title == "3주차 강의"]
    assert len(same) == 2
    assert {one.canvas_item_id for one in same} == {8569302, 8569303}


def test_an_empty_module_is_fine() -> None:
    """녹화 84개 모듈 중 47개가 `items: []`였다."""
    empty = [one for one in DB_MODULES if one["name"].startswith("4주차")]
    assert module_items(empty) == []


def test_the_module_name_is_kept_as_it_comes() -> None:
    """`1주차`·`5주차 (개천절 대체휴일)`·`Week 3 : …`가 섞인다. 주차 번호를 뽑지 않는다."""
    assert module_items(ML_MODULES)[0].module_name == "Week 3 : Trees"
    weird = [{"name": "  ", "items": [{"id": 1, "title": "가", "type": "Page"}]}]
    assert module_items(weird)[0].module_name == NO_NAME


def test_items_that_come_separately_are_merged() -> None:
    """`include[]=items`로 항목이 오지 않은 모듈은 따로 받아 합친다."""
    assert needs_items(MODULE_WITHOUT_ITEMS) == 2871999
    assert needs_items(DB_MODULES[0]) is None  # 빈 목록이어도 함께 온 것이다
    assert needs_items(DB_MODULES[1]) is None
    assert needs_items({"name": "번호 없음"}) is None

    extra = {2871999: [{"id": 999, "title": "5주차 강의", "type": "ExternalTool"}]}
    items = module_items([MODULE_WITHOUT_ITEMS], extra=extra)
    assert [(one.canvas_item_id, one.module_name) for one in items] == [(999, "5주차")]
    # 따로 받아 오지 못했으면 그 모듈은 비어 있는 것으로 둔다
    assert module_items([MODULE_WITHOUT_ITEMS]) == []


def test_it_skips_items_without_a_usable_number() -> None:
    assert item({"title": "번호 없음"}, module_name="1주차") is None
    assert item({"id": True, "title": "참"}, module_name="1주차") is None
    assert item({"id": 2**63, "title": "큰 수"}, module_name="1주차") is None
    assert item("항목이 아니다", module_name="1주차") is None
    assert module_items(["모듈이 아니다", None]) == []


def test_missing_fields_are_left_empty() -> None:
    one = item({"id": 7, "title": "  "}, module_name="1주차")
    assert one is not None
    assert one.title == NO_TITLE
    assert one.item_type is None  # 종류를 모르면 비워 둔다
    assert one.html_url is None

    numbered: dict[str, Any] = {"id": 8, "title": "가", "type": 3, "html_url": 5}
    other = item(numbered, module_name="1주차")
    assert other is not None
    assert (other.item_type, other.html_url) == (None, None)
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

주차 모듈 샘플에서 확인한 것(F-52, 모듈 84개·항목 87건 녹화):

- 한 모듈에 **제목이 같은 항목이 둘씩** 있다(15쌍) → 같은 항목인지는 `canvas_item_id`로만 가린다
- 항목 `type`은 `ExternalTool` 75 · `Assignment` 7 · `Quiz` 4 · `Page` 1이고 `File`은 0건이다
- 모듈 `position`은 연속이 아니다(1주차가 position 17인 과목이 있다) → 저장하지 않는다
- 항목이 없는 모듈이 흔하다(84개 중 47개가 `items: []`)
- 학생이 여는 주소는 `html_url`이다. `url`은 API 주소라 열어도 JSON이다

공지 샘플은 F-53에서 더한다(그 기능이 쓸 때 함께 넣는다).
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


# ── 주차 모듈·항목 (F-52) ───────────────────────────────────────────────────
def _item(
    item_id: int,
    title: str,
    kind: str = "ExternalTool",
    *,
    course: int = 214023,
    module: int = 2871837,
    content: int | None = None,
) -> dict[str, Any]:
    """녹화한 항목 모양 그대로. `url`은 API 주소라 학생이 열 수 없다(`html_url`을 쓴다)."""
    return {
        "id": item_id,
        "title": title,
        "position": 2,
        "indent": 0,
        "type": kind,
        "module_id": module,
        "html_url": f"https://lms.test/courses/{course}/modules/items/{item_id}",
        "url": f"https://lms.test/api/v1/courses/{course}/external_tools/sessionless_launch?id=138",
        "page_url": None,
        "external_url": f"https://lms.test/learningx/lti/lecture_attendance/items/view/{item_id}",
        "content_id": content,
        "new_tab": None,
        "published": None,
    }


def _module(
    module_id: int, name: str, items: list[dict[str, Any]], *, position: int = 17
) -> dict[str, Any]:
    return {
        "id": module_id,
        "name": name,
        "position": position,  # 연속이 아니다(1주차가 17인 과목이 있었다)
        "unlock_at": None,
        "require_sequential_progress": False,
        "published": None,
        "items_count": len(items),
        "items_url": f"https://lms.test/api/v1/courses/214023/modules/{module_id}/items",
        "state": "started",
        "completed_at": None,
        "items": items,
    }


# 데이터베이스 과목: 3주차에 제목이 같은 항목 둘(녹화 15쌍과 같은 모양), 4주차는 빈 모듈
DB_MODULES: list[dict[str, Any]] = [
    _module(
        2871837,
        "3주차",
        [
            _item(8569302, "3주차 강의", content=138),
            _item(8569303, "3주차 강의"),  # 제목이 같다 — ID로만 가린다
            _item(8569304, "3주차 퀴즈", "Quiz", content=85791),
        ],
    ),
    _module(2871840, "4주차 (개천절 대체휴일)", [], position=21),
]

# 기계학습 과목: 모듈 하나에 과제 항목 하나
ML_MODULES: list[dict[str, Any]] = [
    _module(
        2756894,
        "Week 3 : Trees",
        [
            _item(
                8631787,
                "3주차 과제 안내",
                "Assignment",
                course=216515,
                module=2756894,
                content=2799146,
            )
        ],
        position=1,
    )
]

# `include[]=items`로 항목이 오지 않은 모듈(녹화에는 없었지만 Canvas 문서에 있는 경우)
MODULE_WITHOUT_ITEMS: dict[str, Any] = {
    "id": 2871999,
    "name": "5주차",
    "position": 25,
    "items_count": 1,
    "items_url": "https://lms.test/api/v1/courses/214023/modules/2871999/items",
    "state": "locked",
}
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
from itertools import count
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
    ModuleChanges,
    SavedAssignment,
    SavedItem,
    get_lms_repo,
    update_scope,
)
from app.repositories.notifications import AssignmentNotice, MaterialNotice
from app.repositories.opportunities import Cursor
from app.repositories.runs import get_run_repo
from app.schemas.lms import (
    AssignmentCourse,
    AssignmentItem,
    LmsSyncResult,
    ModuleItemUpdate,
    SyncCounts,
)
from tests.conftest import USER_ID, make_token
from tests.fakes import FakeLogConnection
from tests.lms_samples import (
    COURSES,
    DB_ASSIGNMENTS,
    DB_MODULES,
    ML_ASSIGNMENTS,
    ML_MODULES,
    MODULE_WITHOUT_ITEMS,
)
from tests.prepare_fakes import FakeRunRepository, run_row

SYNC = "/api/v1/lms/sync"
ASSIGNMENTS = "/api/v1/lms/assignments"
BASE = "https://lms.test"
TOKEN = "18742~pAtB1g3TestTokenValue0000000000"
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)  # 2026-10-16 12:00 KST
INTERNAL_KEY = "test-internal-key"
FEED_ITEM = "22222222-2222-4222-8222-222222222222"  # 커서는 uuid만 받는다(decode_cursor)
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
    items: list[tuple[int, list[Any]]] = field(default_factory=list)
    feed_calls: list[tuple[datetime, tuple[str, ...], str | None, Any]] = field(
        default_factory=list
    )
    module_changes: dict[int, ModuleChanges] = field(default_factory=dict)
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

    async def save_module_items(
        self, user_id: str, canvas_course_id: int, items: list[Any], *, now: datetime
    ) -> ModuleChanges:
        assert user_id == USER_ID or user_id in self.users
        self.items.append((canvas_course_id, items))
        return self.module_changes.get(canvas_course_id, ModuleChanges())

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

    async def updates(
        self,
        user_id: str,
        *,
        since: datetime,
        now: datetime,
        kinds: list[str],
        course_id: str | None = None,
        cursor: Any = None,
        limit: int = 50,
    ) -> tuple[list[Any], Any]:
        assert user_id == USER_ID
        self.feed_calls.append((since, tuple(kinds), course_id, cursor))
        item = ModuleItemUpdate(
            id=FEED_ITEM,
            course=AssignmentCourse(id=DB_COURSE.id, short_name=DB_COURSE.short_name),
            module_name="3주차",
            title="3주차 강의",
            item_type="ExternalTool",
            html_url=f"{BASE}/courses/214023/modules/items/8569302",
            first_seen_at=NOW.astimezone(KST),
            uploaded_file_id=None,
        )
        if cursor is not None:  # 둘째 쪽은 한 줄만 주고 끝낸다
            return [item], None
        return [item], Cursor(scope=update_scope(kinds, course_id, since), value=NOW, id=FEED_ITEM)

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
    materials: list[MaterialNotice] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    muted: bool = False

    async def add_material_notices(
        self, canvas_course_id: int, notices: Sequence[MaterialNotice], *, now: datetime
    ) -> int:
        assert canvas_course_id
        self.materials += list(notices)
        return len(notices)

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
        router.get(f"{BASE}/api/v1/courses/214023/modules").mock(
            return_value=httpx.Response(200, json=DB_MODULES)
        )
        router.get(f"{BASE}/api/v1/courses/216515/modules").mock(
            return_value=httpx.Response(200, json=ML_MODULES)
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
    assert log.tools() == [
        "fetch_lms_courses",
        "fetch_lms_assignments",
        "fetch_lms_modules",
        "save_lms_sync",
    ]
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


def test_it_saves_the_module_items_of_every_course(client: TestClient, lms: FakeLms) -> None:
    client.post(SYNC)
    saved = {course: [one.title for one in items] for course, items in lms.items}
    assert saved == {
        214023: ["3주차 강의", "3주차 강의", "3주차 퀴즈"],  # 제목이 같은 둘도 따로 저장된다
        216515: ["3주차 과제 안내"],
    }


def test_a_new_module_item_becomes_a_notice(
    client: TestClient, lms: FakeLms, notes: FakeNotes
) -> None:
    """명세 10장 예시와 같은 꼴: "기계학습 8주차 자료가 올라왔어요" + 항목 제목."""
    lms.module_changes[216515] = ModuleChanges(
        created=[SavedItem("item-1", "8주차", "08 - Ensemble Methods")]
    )
    client.post(SYNC)
    assert len(notes.materials) == 1
    notice = notes.materials[0]
    assert notice.item_id == "item-1"
    assert notice.title == "기계학습 8주차 자료가 올라왔어요"
    assert notice.body == "08 - Ensemble Methods"


def test_the_first_load_of_a_course_is_silent(
    client: TestClient, lms: FakeLms, notes: FakeNotes
) -> None:
    """연결하고 처음 받으면 한 학기 분량(녹화 87건)이 모두 새 항목이다. 알림을 보내지 않는다."""
    lms.module_changes[214023] = ModuleChanges(
        created=[SavedItem("item-1", "1주차", "01 - 소개"), SavedItem("item-2", "2주차", "02")],
        first_load=True,
    )
    client.post(SYNC)
    assert notes.materials == []
    assert [course for course, _ in lms.items] == [214023, 216515]  # 저장은 했다


def test_the_result_counts_new_module_items(
    client: TestClient, lms: FakeLms, log: FakeLogConnection
) -> None:
    lms.module_changes[214023] = ModuleChanges(
        created=[SavedItem("item-1", "1주차", "01"), SavedItem("item-2", "1주차", "02")],
        first_load=True,  # 첫 수집이어도 수는 센다(알림만 안 보낸다)
    )
    client.post(SYNC)
    assert log.outputs()["save_lms_sync"]["new_module_items"] == 2


def test_a_course_whose_modules_fail_does_not_fail_the_sync(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """과제는 받았는데 주차 항목만 못 받았다고 동기화를 실패로 적지 않는다."""
    canvas.get(f"{BASE}/api/v1/courses/214023/modules").mock(
        return_value=httpx.Response(500, json={})
    )
    client.post(SYNC)
    assert [course for course, _ in lms.items] == [216515]
    assert [course for course, _ in lms.saved] == ["course-db", "course-ml"]  # 과제는 둘 다
    assert lms.synced_at == NOW


def test_a_dead_token_while_reading_modules_stops_the_sync(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    canvas.get(f"{BASE}/api/v1/courses/214023/modules").mock(
        return_value=httpx.Response(401, json={})
    )
    client.post(SYNC)
    assert lms.error == "토큰이 만료되었거나 삭제되었어요."
    assert lms.synced_at is None  # 저장까지 가지 않았다


def test_items_that_did_not_come_inline_are_fetched(
    client: TestClient, lms: FakeLms, canvas: respx.MockRouter
) -> None:
    """`include[]=items`로 항목이 오지 않은 모듈은 허용된 보충 경로로 따로 받는다(명세 9장)."""
    canvas.get(f"{BASE}/api/v1/courses/214023/modules").mock(
        return_value=httpx.Response(200, json=[MODULE_WITHOUT_ITEMS])
    )
    separate = canvas.get(f"{BASE}/api/v1/courses/214023/modules/2871999/items").mock(
        return_value=httpx.Response(
            200, json=[{"id": 999, "title": "5주차 강의", "type": "ExternalTool"}]
        )
    )
    client.post(SYNC)
    assert separate.called
    saved = dict(lms.items)
    assert [one.title for one in saved[214023]] == ["5주차 강의"]


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


# ── 새 자료·과제 피드 (F-52) ────────────────────────────────────────────────

UPDATES = "/api/v1/lms/updates"


def test_the_feed_defaults_to_the_last_two_weeks(client: TestClient, lms: FakeLms) -> None:
    response = client.get(UPDATES)
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0] == {
        "type": "module_item",
        "id": FEED_ITEM,
        "course": {"id": "course-db", "short_name": "데이터베이스"},
        "module_name": "3주차",
        "title": "3주차 강의",
        "item_type": "ExternalTool",
        "html_url": f"{BASE}/courses/214023/modules/items/8569302",
        "first_seen_at": "2026-10-16T12:00:00+09:00",
        "uploaded_file_id": None,
    }
    since, kinds, course, cursor = lms.feed_calls[0]
    assert since == NOW - timedelta(days=14)
    assert kinds == ("module_item", "assignment") and course is None and cursor is None


def test_the_feed_passes_the_filters_through(client: TestClient, lms: FakeLms) -> None:
    client.get(
        UPDATES,
        params={
            "since": "2026-10-01T00:00:00+09:00",
            "type": "module_item",
            "lms_course_id": "11111111-1111-4111-8111-111111111111",
        },
    )
    since, kinds, course, _ = lms.feed_calls[0]
    assert since == datetime(2026, 9, 30, 15, 0, tzinfo=UTC)  # KST → UTC
    assert kinds == ("module_item",)
    assert course == "11111111-1111-4111-8111-111111111111"


def test_the_feed_reads_the_next_page_without_since(client: TestClient, lms: FakeLms) -> None:
    """`since`를 안 주면 기본값이 요청마다 달라진다. 그래도 다음 쪽을 부를 수 있어야 한다.

    실제 시계는 요청마다 다르다(`datetime.now`). 테스트의 고정 시계로는 이 문제가 안 보여서,
    이 테스트만 요청마다 1마이크로초씩 가는 시계를 쓴다.
    """
    ticking = count()
    client.app.dependency_overrides[current_time] = (  # type: ignore[attr-defined]
        lambda: NOW + timedelta(microseconds=next(ticking))
    )
    first = client.get(UPDATES).json()
    assert first["next_cursor"]

    second = client.get(UPDATES, params={"cursor": first["next_cursor"]})
    assert second.status_code == 200
    assert second.json()["next_cursor"] is None
    # 둘째 쪽은 커서에 적힌 since를 그대로 쓴다(지금 - 14일을 다시 계산하지 않는다)
    assert lms.feed_calls[1][0] == lms.feed_calls[0][0]
    assert lms.feed_calls[1][3] is not None  # 커서를 그대로 저장소에 넘겼다


def test_the_feed_refuses_a_cursor_from_another_list(client: TestClient) -> None:
    first = client.get(UPDATES).json()
    response = client.get(UPDATES, params={"cursor": first["next_cursor"], "type": "module_item"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_FAILED"
    assert "cursor" in error["details"]["fields"]


def test_the_feed_refuses_a_broken_cursor(client: TestClient) -> None:
    assert client.get(UPDATES, params={"cursor": "커서가 아니다"}).status_code == 422


def test_the_feed_refuses_an_unknown_kind(client: TestClient) -> None:
    for value in ("", "nope", "module_item,nope", "MODULE_ITEM"):
        response = client.get(UPDATES, params={"type": value})
        assert response.status_code == 422, value
        assert "type" in response.json()["error"]["details"]["fields"]


def test_the_feed_accepts_announcements_but_has_none_yet(client: TestClient, lms: FakeLms) -> None:
    """공지는 F-53이 채운다. 그때까지는 조건만 받아 두고 빈 목록이다."""
    assert client.get(UPDATES, params={"type": "announcement"}).status_code == 200
    assert lms.feed_calls[0][1] == ("announcement",)


def test_the_feed_needs_a_login(settings: Settings, lms: FakeLms) -> None:
    app = create_app(settings)
    app.dependency_overrides[get_lms_repo] = lambda: lms
    with TestClient(app) as anonymous:
        assert anonymous.get(UPDATES).status_code == 401
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
from app.lms.modules import CanvasModuleItem, module_items
from app.repositories.lms import AssignmentChanges, LmsRepository, SavedAssignment
from app.repositories.notifications import (
    AssignmentNotice,
    MaterialNotice,
    NotificationRepository,
)
from app.repositories.runs import RunRepository
from app.schemas.lms import SAVE_TOOL
from tests.db_world import DATABASE_URL, connect, make_user
from tests.lms_samples import (
    DATABASE,
    DB_ASSIGNMENTS,
    DB_MODULES,
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


# ── 주차 항목 (F-52) ────────────────────────────────────────────────────────


async def test_it_saves_module_items_as_a_shared_table(world: dict[str, Any]) -> None:
    """주차 항목은 과목 공통이다(ERD 3-2). 같은 과목을 듣는 두 사람이 같은 행을 본다."""
    repo, me, other, now = world["repo"], world["me"], world["other"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    await repo.save_courses(other, [DATABASE], now=now)
    items = module_items(DB_MODULES)

    first = await repo.save_module_items(me, DATABASE["id"], items, now=now)
    assert [one.title for one in first.created] == ["3주차 강의", "3주차 강의", "3주차 퀴즈"]
    assert first.first_load is True  # 이 과목 항목을 처음 받았다
    assert first.notifiable == []  # 첫 수집은 알리지 않는다

    rows = await (
        await world["conn"].execute(
            "select count(*) as n from lms_module_items where canvas_course_id = %s",
            (DATABASE["id"],),
        )
    ).fetchone()
    assert rows["n"] == 3  # 사람마다 따로 쌓이지 않는다
    # 연결하면서 받은 항목은 "새 자료"가 아니다(과목 행의 last_viewed_at이 그때로 찍힌다)
    assert (await repo.courses(me, now=now))[0].new_materials == 0

    later = now + timedelta(days=1)
    await repo.save_module_items(
        me,
        DATABASE["id"],
        [*items, CanvasModuleItem(8569999, "4주차", "04", "Page", None)],
        now=later,
    )
    assert (await repo.courses(me, now=later))[0].new_materials == 1
    assert (await repo.courses(other, now=later))[0].new_materials == 1  # 같이 듣는 사람도 센다


async def test_the_second_sync_only_reports_the_new_item(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    items = module_items(DB_MODULES)
    await repo.save_module_items(me, DATABASE["id"], items, now=now)

    extra = [*items, CanvasModuleItem(8569999, "4주차", "04 - 정규화", "Page", None)]
    later = await repo.save_module_items(me, DATABASE["id"], extra, now=now + timedelta(days=1))
    assert [one.title for one in later.created] == ["04 - 정규화"]
    assert later.first_load is False
    assert later.notifiable == later.created  # 이제는 알린다


async def test_items_with_the_same_title_are_stored_twice(world: dict[str, Any]) -> None:
    """녹화 15쌍처럼 제목이 같은 항목이 둘이면 둘 다 남아야 한다(ID로만 가린다)."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    await repo.save_module_items(me, DATABASE["id"], module_items(DB_MODULES), now=now)
    rows = await (
        await world["conn"].execute(
            "select canvas_item_id from lms_module_items where title = '3주차 강의'"
            " order by canvas_item_id",
            (),
        )
    ).fetchall()
    assert [row["canvas_item_id"] for row in rows] == [8569302, 8569303]


async def test_an_item_keeps_the_time_it_was_first_seen(world: dict[str, Any]) -> None:
    """새 자료 수가 이 시각을 본다(`GET /lms/courses`). 다시 받을 때 밀면 계속 "새 자료"가 된다."""
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    one = CanvasModuleItem(8569302, "3주차", "3주차 강의", "ExternalTool", "https://lms.test/a")
    await repo.save_module_items(me, DATABASE["id"], [one], now=now)

    later = now + timedelta(days=2)
    renamed = CanvasModuleItem(8569302, "3주차 (보강)", "3주차 강의(수정)", "Page", None)
    again = await repo.save_module_items(me, DATABASE["id"], [renamed], now=later)
    assert again.created == []  # 같은 항목이다
    row = await (
        await conn.execute(
            "select first_seen_at, module_name, title, item_type, html_url from lms_module_items"
            " where canvas_item_id = 8569302",
            (),
        )
    ).fetchone()
    assert row["first_seen_at"] == now
    assert (row["module_name"], row["title"]) == ("3주차 (보강)", "3주차 강의(수정)")
    assert (row["item_type"], row["html_url"]) == ("Page", None)  # 바뀐 값으로 갱신된다


async def test_a_new_item_notifies_everyone_taking_the_course(world: dict[str, Any]) -> None:
    """항목은 과목 공통이라 그 과목 수강생 모두가 알림을 받는다(ERD 3-2)."""
    repo, me, other, now, conn = (
        world["repo"],
        world["me"],
        world["other"],
        world["now"],
        world["conn"],
    )
    notes = NotificationRepository(conn)
    for user in (me, other):
        await repo.save_connection(user, token="enc", last4="a9f2", canvas_user_id=1, now=now)
        await repo.save_courses(user, [DATABASE], now=now)
    await repo.save_module_items(me, DATABASE["id"], module_items(DB_MODULES), now=now)
    fresh = await repo.save_module_items(
        me,
        DATABASE["id"],
        [
            *module_items(DB_MODULES),
            CanvasModuleItem(8569999, "4주차", "04 - 정규화", "Page", None),
        ],
        now=now,
    )
    notice = MaterialNotice(
        fresh.created[0].id, "데이터베이스 4주차 자료가 올라왔어요", "04 - 정규화"
    )

    assert await notes.add_material_notices(DATABASE["id"], [notice], now=now) == 2
    rows = await (
        await conn.execute(
            "select user_id, type, title, body, dedupe_key, lms_module_item_id from notifications"
            " order by user_id",
            (),
        )
    ).fetchall()
    assert {str(row["user_id"]) for row in rows} == {me, other}
    assert rows[0]["type"] == "new_material"
    assert rows[0]["dedupe_key"] == f"new_material:mod:{fresh.created[0].id}"  # ERD 5장 표
    # 같은 항목은 한 번만(다음 동기화에서 또 보내지 않는다)
    assert await notes.add_material_notices(DATABASE["id"], [notice], now=now) == 0


async def test_a_muted_student_gets_no_material_notice(world: dict[str, Any]) -> None:
    repo, me, other, now, conn = (
        world["repo"],
        world["me"],
        world["other"],
        world["now"],
        world["conn"],
    )
    notes = NotificationRepository(conn)
    for user in (me, other):
        await repo.save_connection(user, token="enc", last4="a9f2", canvas_user_id=1, now=now)
        await repo.save_courses(user, [DATABASE], now=now)
    saved = await repo.save_module_items(
        me, DATABASE["id"], [CanvasModuleItem(8569302, "3주차", "강의", "Page", None)], now=now
    )
    await conn.execute(
        "insert into user_settings (user_id, muted_notification_types)"
        " values (%s, array['new_material'])",
        (other,),
    )
    notice = MaterialNotice(saved.created[0].id, "제목", "본문")

    assert await notes.add_material_notices(DATABASE["id"], [notice], now=now) == 1
    row = await (await conn.execute("select user_id from notifications", ())).fetchone()
    assert str(row["user_id"]) == me


async def test_a_student_who_disconnected_gets_no_material_notice(world: dict[str, Any]) -> None:
    """연결을 끊으면 동기화가 멈춘다(명세 9장). 같이 듣는 사람이 동기화해도 알림이 가면 안 된다."""
    repo, me, other, now, conn = (
        world["repo"],
        world["me"],
        world["other"],
        world["now"],
        world["conn"],
    )
    notes = NotificationRepository(conn)
    for user in (me, other):
        await repo.save_connection(user, token="enc", last4="a9f2", canvas_user_id=1, now=now)
        await repo.save_courses(user, [DATABASE], now=now)
    saved = await repo.save_module_items(
        me, DATABASE["id"], [CanvasModuleItem(8569302, "3주차", "강의", "Page", None)], now=now
    )
    assert await repo.delete_connection(other) is True  # other가 연결을 끊었다

    notice = MaterialNotice(saved.created[0].id, "제목", "본문")
    assert await notes.add_material_notices(DATABASE["id"], [notice], now=now) == 1
    row = await (await conn.execute("select user_id from notifications", ())).fetchone()
    assert str(row["user_id"]) == me


async def test_the_first_item_of_an_empty_course_is_notified(world: dict[str, Any]) -> None:
    """항목이 0건인 과목이 흔하다(녹화 6과목 중 2과목). 그 과목에 나중에 올라온 첫 자료는 알려야 한다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)

    empty = await repo.save_module_items(me, DATABASE["id"], [], now=now)
    assert (empty.created, empty.first_load) == ([], True)

    later = now + timedelta(days=7)
    first = await repo.save_module_items(
        me, DATABASE["id"], [CanvasModuleItem(1, "1주차", "01 - 소개", "Page", None)], now=later
    )
    assert [one.title for one in first.created] == ["01 - 소개"]
    assert first.first_load is False  # 첫 수집은 이미 지났다
    assert first.notifiable == first.created  # 그래서 알린다
    assert (await repo.courses(me, now=later))[0].new_materials == 1


async def test_the_back_catalogue_is_not_counted_as_new(world: dict[str, Any]) -> None:
    """연결은 과목까지만 받고(F-50), 주차 항목은 그 뒤 동기화에서 온다. 그때 있던 항목은 새 자료가 아니다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    later = now + timedelta(minutes=30)  # 대시보드를 열어 동기화한 때

    await repo.save_module_items(me, DATABASE["id"], module_items(DB_MODULES), now=later)
    assert (await repo.courses(me, now=later))[0].new_materials == 0

    newer = later + timedelta(days=1)
    await repo.save_module_items(
        me,
        DATABASE["id"],
        [*module_items(DB_MODULES), CanvasModuleItem(8569999, "4주차", "04", "Page", None)],
        now=newer,
    )
    assert (await repo.courses(me, now=newer))[0].new_materials == 1


async def test_a_dropped_course_gets_no_material_notice(world: dict[str, Any]) -> None:
    """수강을 뺀 과목의 새 자료는 알리지 않는다."""
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    notes = NotificationRepository(conn)
    await repo.save_connection(me, token="enc", last4="a9f2", canvas_user_id=1, now=now)
    await repo.save_courses(me, [DATABASE], now=now)
    saved = await repo.save_module_items(
        me, DATABASE["id"], [CanvasModuleItem(8569302, "3주차", "강의", "Page", None)], now=now
    )
    await conn.execute("update lms_courses set is_active = false where user_id = %s", (me,))
    notice = MaterialNotice(saved.created[0].id, "제목", "본문")
    assert await notes.add_material_notices(DATABASE["id"], [notice], now=now) == 0


# ── 새 자료·과제 피드 (F-52, GET /lms/updates) ──────────────────────────────


async def test_the_feed_shows_new_items_and_new_assignments(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_module_items(
        me,
        DATABASE["id"],
        [CanvasModuleItem(8569302, "3주차", "3주차 강의", "ExternalTool", "https://lms.test/i")],
        now=now,
    )
    await repo.save_assignments(me, course, [_one(11, due=now + timedelta(days=9))], now=now)

    items, cursor = await repo.updates(
        me, since=now - timedelta(days=1), now=now, kinds=["module_item", "assignment"]
    )
    assert cursor is None
    assert {one.type for one in items} == {"assignment", "module_item"}
    assert len(items) == 2
    item = next(one for one in items if one.type == "module_item")
    assert (item.module_name, item.title) == ("3주차", "3주차 강의")
    assert item.item_type == "ExternalTool"
    assert item.course.short_name == "데이터베이스"
    assert item.uploaded_file_id is None
    assert item.first_seen_at == now.astimezone(KST)


async def test_the_feed_filters_by_kind_and_course(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE, MACHINE_LEARNING], now=now)
    db = await _course_id(world)
    await repo.save_module_items(
        me, DATABASE["id"], [CanvasModuleItem(1, "3주차", "DB 강의", "Page", None)], now=now
    )
    await repo.save_module_items(
        me, MACHINE_LEARNING["id"], [CanvasModuleItem(2, "3주차", "ML 강의", "Page", None)], now=now
    )
    await repo.save_assignments(me, db, [_one(11, due=now + timedelta(days=9))], now=now)
    since = now - timedelta(days=1)

    only_items, _ = await repo.updates(me, since=since, now=now, kinds=["module_item"])
    assert {one.title for one in only_items} == {"DB 강의", "ML 강의"}
    only_db, _ = await repo.updates(
        me, since=since, now=now, kinds=["module_item", "assignment"], course_id=db
    )
    assert {one.title for one in only_db} == {"DB 강의", "실습 2주차 결과 제출"}
    nothing, _ = await repo.updates(me, since=since, now=now, kinds=["announcement"])
    assert nothing == []  # 공지는 F-53이 채운다


async def test_the_feed_leaves_out_old_things(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_module_items(
        me, DATABASE["id"], [CanvasModuleItem(1, "1주차", "지난 강의", "Page", None)], now=now
    )
    await repo.save_assignments(me, course, [_one(11, due=now + timedelta(days=30))], now=now)
    await conn.execute(
        "update lms_module_items set first_seen_at = %s", (now - timedelta(days=30),)
    )
    await conn.execute("update lms_assignments set first_seen_at = %s", (now - timedelta(days=30),))

    items, _ = await repo.updates(
        me, since=now - timedelta(days=7), now=now, kinds=["module_item", "assignment"]
    )
    assert items == []


async def test_an_assignment_due_soon_comes_back_even_if_it_is_old(
    world: dict[str, Any],
) -> None:
    """마감 D-3 이내 미제출 과제는 since보다 오래된 것도 넣는다(명세 9장)."""
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(
        me,
        course,
        [
            _one(11, title="곧 마감", due=now + timedelta(days=2)),
            _one(12, title="먼 마감", due=now + timedelta(days=9)),
            _one(13, title="낸 과제", due=now + timedelta(days=1), state="submitted"),
        ],
        now=now,
    )
    await conn.execute("update lms_assignments set first_seen_at = %s", (now - timedelta(days=30),))

    items, _ = await repo.updates(me, since=now - timedelta(days=7), now=now, kinds=["assignment"])
    assert [one.title for one in items] == ["곧 마감"]


async def test_the_feed_reads_on_with_a_cursor(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    await repo.save_module_items(
        me,
        DATABASE["id"],
        [CanvasModuleItem(number, "3주차", f"강의 {number}", "Page", None) for number in (1, 2, 3)],
        now=now,
    )
    # 처음 본 시각을 달리해 순서를 못 박는다
    for number, minutes in ((1, 0), (2, 5), (3, 10)):
        await conn.execute(
            "update lms_module_items set first_seen_at = %s where canvas_item_id = %s",
            (now + timedelta(minutes=minutes), number),
        )
    since = now - timedelta(days=1)

    first, cursor = await repo.updates(me, since=since, now=now, kinds=["module_item"], limit=2)
    assert [one.title for one in first] == ["강의 3", "강의 2"]  # 최신 먼저
    assert cursor is not None
    rest, last = await repo.updates(
        me, since=since, now=now, kinds=["module_item"], limit=2, cursor=cursor
    )
    assert [one.title for one in rest] == ["강의 1"]
    assert last is None


async def test_the_feed_pages_through_rows_seen_at_the_same_moment(
    world: dict[str, Any],
) -> None:
    """한 동기화에서 들어온 행은 `first_seen_at`이 모두 같다. 그때도 빠지거나 겹치지 않아야 한다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_module_items(
        me,
        DATABASE["id"],
        [
            CanvasModuleItem(number, "3주차", f"강의 {number}", "Page", None)
            for number in range(1, 6)
        ],
        now=now,
    )
    await repo.save_assignments(
        me,
        course,
        [
            _one(20 + number, title=f"과제 {number}", due=now + timedelta(days=9))
            for number in range(3)
        ],
        now=now,
    )
    since = now - timedelta(days=1)

    seen: list[str] = []
    cursor = None
    for _ in range(10):  # 넉넉히 돌려 본다(8행이면 네 쪽이다)
        page, cursor = await repo.updates(
            me, since=since, now=now, kinds=["module_item", "assignment"], limit=2, cursor=cursor
        )
        seen += [one.id for one in page]
        if cursor is None:
            break
    assert len(seen) == 8
    assert len(set(seen)) == 8  # 겹치지 않는다


async def test_the_feed_shows_the_file_i_uploaded_for_an_item(world: dict[str, Any]) -> None:
    """항목 알림에서 올린 PDF가 있으면 화면이 "요약 보기"를 띄운다(명세 9장)."""
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    saved = await repo.save_module_items(
        me, DATABASE["id"], [CanvasModuleItem(1, "3주차", "강의", "Page", None)], now=now
    )
    row = await (
        await conn.execute(
            "insert into files (user_id, kind, origin, storage_path, sha256,"
            " lms_module_item_id) values (%s, 'lecture_material', 'upload', 'p/1', 'abc', %s)"
            " returning id",
            (me, saved.created[0].id),
        )
    ).fetchone()

    items, _ = await repo.updates(me, since=now - timedelta(days=1), now=now, kinds=["module_item"])
    assert items[0].uploaded_file_id == str(row["id"])


async def test_the_feed_is_not_someone_elses(world: dict[str, Any]) -> None:
    """항목은 과목 공통이지만, 그 과목을 듣지 않는 사람에게는 보이지 않는다."""
    repo, me, other, now, conn = (
        world["repo"],
        world["me"],
        world["other"],
        world["now"],
        world["conn"],
    )
    await repo.save_courses(me, [DATABASE], now=now)
    await repo.save_module_items(
        me, DATABASE["id"], [CanvasModuleItem(1, "3주차", "강의", "Page", None)], now=now
    )
    since = now - timedelta(days=1)
    mine, _ = await repo.updates(me, since=since, now=now, kinds=["module_item"])
    assert len(mine) == 1
    theirs, _ = await repo.updates(other, since=since, now=now, kinds=["module_item"])
    assert theirs == []

    # 남이 올린 파일은 내 피드에 붙지 않는다
    await repo.save_courses(other, [DATABASE], now=now)
    saved_id = mine[0].id
    await conn.execute(
        "insert into files (user_id, kind, origin, storage_path, sha256, lms_module_item_id)"
        " values (%s, 'lecture_material', 'upload', 'p/2', 'def', %s)",
        (other, saved_id),
    )
    again, _ = await repo.updates(me, since=since, now=now, kinds=["module_item"])
    assert again[0].uploaded_file_id is None


async def test_a_dropped_course_leaves_the_feed(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    await repo.save_module_items(
        me, DATABASE["id"], [CanvasModuleItem(1, "3주차", "강의", "Page", None)], now=now
    )
    await conn.execute("update lms_courses set is_active = false where user_id = %s", (me,))
    items, _ = await repo.updates(me, since=now - timedelta(days=1), now=now, kinds=["module_item"])
    assert items == []
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

// GET /lms/updates?since=&type=module_item,assignment&lms_course_id=&cursor=
// since를 주지 않으면 최근 14일. announcement는 F-53이 채운다(그때까지 비어 있다)
export type LmsUpdateType = "module_item" | "assignment" | "announcement";
export type LmsUpdate =
  | { type: "module_item"; id: string; course: { id: string; short_name: string }; module_name: string | null; title: string; item_type: string | null; html_url: string | null; first_seen_at: string; uploaded_file_id: string | null }
  | { type: "announcement"; id: string; course: { id: string; short_name: string }; title: string; summary: string | null; posted_at: string; category: AnnouncementCategory | null; attachment_count: number; opportunity_id: string | null; planner_task_id: string | null }
  | { type: "assignment"; id: string; course: { id: string; short_name: string }; title: string; due_at: string | null; submission_state: SubmissionState; html_url: string | null; first_seen_at: string };
export interface LmsUpdateList {
  items: LmsUpdate[];
  next_cursor: string | null;
}
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
  { type: "module_item", id: "analysis-m4", course: { id: "analysis", short_name: "해석학" }, module_name: "8주차", title: "Decision Trees", item_type: "ExternalTool", html_url: "https://lms.example.edu/analysis/modules/4", first_seen_at: "2026-10-05T09:20:00+09:00", uploaded_file_id: "analysis-material" },
  { type: "assignment", id: "capstone-a1", course: { id: "capstone", short_name: "DS창업캡스톤디자인1" }, title: "창업아이템 정의", due_at: "2026-10-06T23:59:00+09:00", submission_state: "unsubmitted", html_url: "https://lms.example.edu/capstone/assignments/1", first_seen_at: "2026-10-02T09:00:00+09:00" },
  { type: "announcement", id: "database-n1", course: { id: "database", short_name: "데이터베이스" }, title: "다음 주 강의실 변경", summary: "제2공학관 301호에서 수업해요.", posted_at: "2026-10-05T08:00:00+09:00", category: "schedule_change", attachment_count: 0, opportunity_id: null, planner_task_id: "task-db-notice" },
];
```

