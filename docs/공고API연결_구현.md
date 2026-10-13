# 공고 피드·상세 실제 API 연결 — S1-5·S1-6 웹 (홈·공고 상세·정보 입력)

> 📝 기준: PRD v0.9 F-03·F-40·F-41·F-42 · API 명세 v0.4 4·5·11·13장 · `피드판정_구현.md` · `공고상세_구현.md` · `원문확인이유_구현.md` · `계정API연결_구현.md` · 스킬 `mock-to-api` · 2026-10-12
>
> 함께 보는 파일: `계정API연결_구현.md`(실제 모드 환경과 로그인), `Nextjs_이식_가이드.md` W4. 모두 레포에 들어가 있어야 한다

웹의 홈 피드와 공고 상세를 목데이터에서 실제 FastAPI로 바꿨다. 목 모드(`NEXT_PUBLIC_USE_MOCKS=true`)는 전처럼 돈다.
- **홈:** 공고 목록, 요약 숫자, 카테고리 칩, 정렬을 `GET /opportunities`로 받는다. 50개씩 끝까지 받아 화면에서 지원 어려움을 맨 아래로 묶는다.
- **공고 상세:** `GET /opportunities/{id}`로 다음을 보인다.
  - 판정표: "다음 중 하나" 묶음, 판정 기준일, 판정하지 못한 이유
  - 필요 서류와 공고 첨부파일
  - AI 처리 과정: 모델이 고른 단계와 이유, 원문 확인이 필요한 이유
- **정보 입력:**
  - 빠진 항목만 묻고 `PATCH /me/profile`로 저장한 뒤 공고를 다시 불러온다. 서버가 그 자리에서 다시 판정한다.
  - 창을 띄우면 `profile_prompt_shown`을 남긴다.
  - 소득 항목은 창 안에서 선택 동의를 받는다.
- **오늘 날짜:** 실제 모드의 D-day와 상대 시간을 진짜 오늘(KST)로 계산한다. 전에는 10월 5일로 고정이었다.
- **타입:** 공고 피드·상세 타입을 API 명세 v0.4에 맞췄다.

상세가 실제 공고를 보여 주게 되어, 준비하기·서류 체크·포스터 등록은 실제 모드에서 준비 중 안내로 바꿨다. 목으로 흉내 내면 실제 공고와 맞지 않기 때문이다.
- **아직 목인 곳:** 플래너.
- **바뀌지 않은 곳:** API, DB 마이그레이션.
- **덤:** `next dev`가 `web/AGENTS.md`를 만들지 않게 했다.

**규모와 확인:**
- 새 파일 5개, 바꾸는 파일 23개다.
- 웹은 `tsc`와 `next build`를 목 모드, 실제 모드, 환경 변수 없이 세 번 통과했다.
- Playwright로 실제 모드 88단계, 목 모드 26단계를 눌렀다. 실제 모드는 실제 FastAPI, 마이그레이션을 모두 적용한 Postgres(공고 70개 시드), 가짜 Supabase Auth로 돌렸다.
- 검토 에이전트 1개가 따로 봤고, 지적 8가지를 받아들였다.

## 정한 것

| 항목 | 정한 것 | 이유 |
| --- | --- | --- |
| 홈 피드 호출 | `eligibility` 없이 판정 결과를 모두 받는다. 50개씩 `next_cursor`가 없을 때까지, 최대 1,000개다.<br>카테고리 칩은 `category`로 서버가 거른다(기타 칩 = `research,exam,etc`).<br>화면에서 나누는 것: 요약 카드 필터(지원 가능·확인 필요·마감 임박), 지원 어려움 묶음 | 요약 숫자(`counts`)는 필터와 상관없는 전체 기준이다. 지원 어려움을 펼칠 때 따로 부르면, 칩을 고른 상태에서 묶음 개수가 맞지 않는다.<br>공고는 수백 개 수준이라 한 번에 받아도 된다. `피드판정_구현.md`의 처음 계획(두 번 부르기)을 바꿨다 |
| 요약 숫자·빈 피드 | 요약 카드는 서버 `counts`를 그대로 쓴다. 피드가 비었는지는 `counts`(지원 가능 + 확인 필요 + 지원 어려움)로 본다 | 전체 피드를 한 번 더 부르지 않는다 |
| D-day·오늘 | 카드의 D-day는 서버 `d_day`를 쓴다.<br>`client.ts`의 `todayKst()`·`nowIso()`로 계산하는 것: 상세의 "마감까지 N일", 목표일 최솟값, 알림·LMS의 상대 시간, 플래너의 처음 달.<br>목 모드는 목데이터 기준일(2026-10-05)을 쓴다 | `MOCK_TODAY`·`MOCK_NOW` 상수는 실제 모드에서도 10월 5일로 고정이었다. 함수로 바꿔 화면을 그릴 때 계산한다 |
| 판정표 | 같은 `clause_no` 조건이 2개 이상이면 "다음 중 하나" 상자에 묶고, 묶음 결과 배지를 단다.<br>행은 "라벨 + 조건"과 내 값을 보인다. 예: 직전학기 이수학점 12학점 이상 · 10학점.<br>지원 어려움이면 불충족 묶음을 위로 올린다. 판정 기준일은 표 위에 적는다 | API 5장. v0.4의 `condition_text`에는 라벨이 없다 |
| 판정하지 못한 이유 | 내 값 자리에 쓰는 말(서버가 내 값을 주면 그 값):<br>· `missing_profile`: "미입력"<br>· `ambiguous`·`unsupported_field`: "원문 확인"<br>· `basis_mismatch`: "기준 다름"<br>행을 펼치면 원문 근거와 이유별 안내가 보인다.<br>비어 있어도 정보 입력에서 묻지 않는 항목에는 "지금은 묻지 않아요"라고 안내한다. 같은 묶음의 다른 조건을 이미 충족한 경우 등이다 | `unknown_reason`(v0.4) |
| 정보 입력 | 판정에 빠진 항목만 묻는다. 요건 항목은 프로필 항목으로 바꿔 묻는다:<br>· 나이 → 생년월일(이미 있으면 병역 복무 개월)<br>· 거주지역 → 시·도와 시·군·구<br>· 나머지 → 같은 이름<br>입력란은 온보딩·설정과 같은 정의(`profileFields`)와 같은 검사를 쓴다.<br>`PATCH /me/profile`(프로필 전체)로 저장한 뒤 공고를 다시 부른다. 새로 입력한 값이 없으면 저장하지 않는다 | 서버 판정 엔진의 "입력 필요" 문구와 같은 규칙이다.<br>빈칸으로 저장하면 결과는 그대로인데 "다시 판정했어요"가 뜬다 |
| 정보 입력의 소득 항목 | 선택 동의 전이면 창 안에 동의 안내와 "동의하고 입력하기"를 보인다. 누르면 `PATCH /me/consents` 뒤 입력란이 열린다 | API 13장 `CONSENT_REQUIRED`(`income_info`) "소득 동의 안내"와 같은 API다. 동의 없이 소득 값은 보내지 않는다(PRD F-02) |
| 병역 복무 개월 | 정보 입력에서 물을 때는 "복무하지 않았으면 0을 입력해 주세요."라고 안내한다 | 설정의 안내("해당자만 입력해요")대로 비워 두면 판정이 끝나지 않는다 |
| `profile_prompt_shown` | 정보 입력창을 띄울 때 공고 id와 함께 한 번 보낸다. 창을 다시 열면 다시 보낸다.<br>알림에서 `focus=profile_input`으로 들어와도 빠진 항목이 없으면 창을 열지 않고 보내지도 않는다 | API 4장. 지표가 부풀지 않게 한다 |
| 처리 과정 | 단계마다 보이는 것:<br>· 라벨, 소요 시간, 상태(완료·실패·진행 중·대기)<br>· 모델이 고른 단계에는 "AI가 고름"과 고른 이유(`note`)<br>원문 확인이 필요한 이유(`review_reasons`)는 맨 위 목록이다. 둘 다 일반 텍스트로만 보인다(링크·마크다운 없이).<br>판정 시각이 없으면(요건 추출 실패) "내 프로필과 비교" 줄을 숨긴다 | API 5·11장 |
| 첨부·원문 링크 | 필요 서류 카드 아래 "공고 첨부파일"에 학교 다운로드 링크를 건다. AI가 읽지 못한 첨부(`failed`)에는 "AI가 읽지 못한 파일이에요"를 붙인다.<br>원문·첨부·양식 주소는 http·https일 때만 링크로 건다(`webUrl`).<br>원문 보기는 새 탭 링크다(`window.open`을 쓰지 않는다) | 학생이 양식을 내려받는 곳이다.<br>공고에서 온 주소라 `javascript:` 같은 주소를 막는다 |
| 포스터 표시 | 카드는 주최 옆에, 상세는 부제에 "내가 올린 포스터"를 쓴다. 업로더 이름은 쓰지 않는다.<br>신고 버튼(P1)은 없앤다. 출처 이름은 "공유 포스터"에서 "포스터"로 바꾼다 | API v0.4 부록, 멘토 피드백(포스터는 올린 사람에게만 보인다).<br>명세의 "주최 자리에"를 "주최 옆에"로 고친다(아래 반영하기) |
| 공고 상태 | 준비한 공고가 마감·숨김·병합이 되면 상세 위에 안내를 띄운다:<br>· 마감: "마감된 공고예요."<br>· 숨김: "지금은 목록에서 내린 공고예요."<br>· 병합: "같은 내용의 다른 공고와 합쳐진 공고예요."<br>모두 뒤에 "준비한 서류와 일정은 그대로 볼 수 있어요."를 붙인다 | API 5장 `status` |
| 불러오기 오류 | 홈·상세를 불러오지 못하면 `errorMessage`로 화면 문구를 쓴다. 서버 5xx면 "공고를 불러오지 못했어요. …"다.<br>없는 공고(404)와 형식이 틀린 id(422, 예: 목 모드 주소)는 "공고를 찾을 수 없어요."와 "홈으로" 버튼을 보인다 | `web/CLAUDE.md` 문구 규칙 |
| 실제 모드의 준비 중 기능 | 막는 장치:<br>· 준비하기(F-30)와 서류 체크: `PREPARE_READY`<br>· 포스터 등록(W6): `POSTER_READY`<br>막았을 때 화면:<br>· "준비 일정 만들기"·"그래도 준비하기": 목표일·확인 창 없이 바로 준비 중 안내<br>· 서류 체크: 꺼 두고 이유를 적는다<br>· 포스터 등록: 준비 중 안내와 "홈으로"<br>· 빈 피드: 포스터 대신 "다시 불러오기" | 목 준비하기·목 포스터는 실제 공고와 맞지 않는다. 예: 목 포스터를 등록하면 "공고를 찾을 수 없어요"로 끝났다.<br>PR A의 LMS·탈퇴와 같은 방식이다 |
| 목 모드 | 공고 목데이터를 v0.4 모양으로 바꿨다.<br>정보 입력을 저장하면 목 저장소의 프로필로 빈 항목이 채워졌는지 보고 "모든 조건 충족"으로 바꾼다(실제 판정은 서버).<br>목의 요약 숫자도 카테고리와 상관없는 전체 기준이다 | 목 모드 시연이 그대로 돈다. 화면이 하던 가짜 재판정은 목 쪽(`mocks/rejudge.ts`)으로 옮겼다 |
| 파일 나누기 | 필요 서류·첨부는 `OpportunityDocuments.tsx`로, 목 포스터 등록은 `mocks/posterStore.ts`로 나눴다 | 300줄 규칙. `mocks/store.ts`는 310줄이었다 |
| AGENTS.md | `next.config.ts`에 `agentRules: false`를 넣었다 | `next dev`가 AI 도구를 알아채면 `web/AGENTS.md`를 만든다. 규칙 파일은 `web/CLAUDE.md` 하나로 둔다.<br>이미 생긴 파일은 다음 `next dev`가 지운다(Next가 넣은 내용만 있을 때) |

### 실제 모드에서 화면별로

| 화면 | 실제 API | 아직 목이거나 준비 중 |
| --- | --- | --- |
| 홈 | 공고 목록·요약 숫자·칩·정렬(`GET /opportunities`), 이름(`GET /me`) | — |
| 공고 상세 | 상세·판정표·첨부·처리 과정(`GET /opportunities/{id}`).<br>정보 입력(`GET`·`PATCH /me/profile`, `PATCH /me/consents`, `GET /meta/departments`, `POST /events`) | 준비하기·서류 체크는 준비 중 안내. 대체 공고(P1)는 꺼짐 |
| 플래너 | 캘린더 연결 줄, 처음 달(오늘 기준) | 할 일은 목이다. 그 안의 공고 링크는 실제 공고가 아니라 "공고를 찾을 수 없어요"로 열린다 |
| 포스터 등록 | — | 준비 중 안내 |
| 그 밖 | PR A와 같다 | PR A와 같다 |

### 바뀐 문구

| 곳 | 문구 |
| --- | --- |
| 홈 빈 피드(실제 모드) | 아직 볼 수 있는 공고가 없어요. 새 공고가 올라오면 여기에 보여요 · 버튼 "다시 불러오기" |
| 홈·상세 불러오기 실패 | 공고를 불러오지 못했어요. 잠시 후 새로 고쳐 주세요. (상세) 공고를 불러오지 못했어요. 잠시 후 다시 열어 주세요. · 버튼 "홈으로" |
| 포스터 카드 | 내가 올린 포스터 · 출처 "포스터"(전: 김\*지님 공유, 공유 포스터) |
| 상세 위 안내 | 마감된 공고예요. · 지금은 목록에서 내린 공고예요. · 같은 내용의 다른 공고와 합쳐진 공고예요. (준비했으면) 준비한 서류와 일정은 그대로 볼 수 있어요. |
| 판정표 | 판정 기준일 2026.10.15 · 만 나이·학년·학적은 이날 기준으로 따져요 · 다음 중 하나 · 내 값 자리 "미입력"·"원문 확인"·"기준 다름" |
| 판정표 펼침 | 정보를 입력하면 바로 다시 판정해요. · 조건이 모호해서 판정하지 않았어요. 원문을 확인해 주세요. · 프로필로는 판정할 수 없는 조건이에요. 원문을 확인해 주세요. · 공고와 내 정보의 기준(실거주·출신 고교 주소, 평점 만점 등)이 달라 직접 확인해야 해요. · 입력하지 않은 정보예요. 다른 조건으로 결과가 정해져서 지금은 묻지 않아요. |
| 판정표가 빌 때 | 공고에서 지원 자격을 정리하지 못했어요. 원문을 확인해 주세요. · 공고에 적힌 지원 자격이 없어요. |
| 필요 서류 | 공고에서 정리한 제출 서류가 없어요. 원문을 확인해 주세요. · 서류 체크는 아직 준비 중이에요 · 공고 첨부파일 · AI가 읽지 못한 파일이에요 |
| 처리 과정 | 원문 확인이 필요한 이유 · AI가 고름 · 실패 · 대기 · 아직 AI 처리 기록이 없어요. |
| 정보 입력 | 이 공고를 판정하는 데 필요한 정보예요. 저장하면 바로 다시 판정해요. · 내 정보를 불러오고 있어요. · 내 정보를 불러오지 못했어요. 창을 닫고 다시 열어 주세요. · 새로 입력한 값이 없어요. 빈칸을 채운 뒤 저장해 주세요. · 저장하지 못했어요. 잠시 후 다시 눌러 주세요. · 여기서 입력할 수 있는 항목이 없어요. 원문을 확인해 주세요. |
| 정보 입력(소득) | 소득·수급 정보는 선택 동의를 하면 입력할 수 있어요. 자격 판정에만 쓰고, 탈퇴하면 바로 지워요. · 버튼 "동의하고 입력하기"("동의하는 중") · 소득·수급 정보는 선택 동의를 해야 저장할 수 있어요. · 동의하지 못했어요. 잠시 후 다시 눌러 주세요. |
| 정보 입력(병역) | 복무 기간만큼 나이 상한을 늘려 주는 공고예요. 복무하지 않았으면 0을 입력해 주세요. |
| 정보 입력 뒤 토스트 | 다시 판정했어요 · (다시 불러오지 못하면) 저장했어요. 화면을 새로 고치면 다시 판정한 결과가 보여요. |
| 준비하기(실제 모드) | 준비 일정 만들기는 아직 준비 중이에요. 지금은 필요 서류와 마감일을 이 화면에서 확인해 주세요. |
| 포스터 등록(실제 모드) | 포스터 등록은 아직 준비 중이에요 · 준비되면 이 화면에서 포스터를 올려 공고로 등록할 수 있어요. 지금은 홈에서 학교 공지를 확인해 주세요. · 버튼 "홈으로" |

## 레포에 넣는 법

마이그레이션이 없어서 `supabase db push`는 하지 않는다. API도 바뀌지 않는다.

```text
공고 피드·상세 실제 API 연결(S1-5·S1-6 웹)을 넣자. docs/공고API연결_구현.md를 docs/에 넣었어.
1. main을 최신으로 받고 feat/F-40-feed-detail-web 브랜치를 만들어. 아래 2번의 바꾸는 파일 중에 97819a1 뒤로 main에서 바뀐 것이 있으면(git log --oneline 97819a1..main -- <파일>) 바꾸기 전에 멈추고 알려줘.
2. 문서 "코드"의 파일 28개를 문서 내용으로 통째로 만들거나 바꿔. 파일 경로는 "코드" 아래 #### 제목 그대로고, 내용은 고치지 마.
   새 파일 5개: web/src/components/OpportunityDocuments.tsx, web/src/components/PosterNotReady.tsx, web/src/lib/webUrl.ts, web/src/mocks/posterStore.ts, web/src/mocks/rejudge.ts
   바꾸는 파일 23개: web/src/api/client.ts, web/src/api/mockClient.ts, web/src/types/api.ts, web/src/lib/format.ts, web/src/screens/Home.tsx, web/src/screens/OpportunityDetail.tsx, web/src/components/OpportunityPreparation.tsx, web/src/components/OpportunityConditions.tsx, web/src/components/ProfileInputModal.tsx, web/src/components/AiProcessPanel.tsx, web/src/components/Button.tsx, web/src/screens/PosterUpload.tsx, web/src/components/Header.tsx, web/src/components/ConnectedServices.tsx, web/src/components/CourseAssignments.tsx, web/src/screens/Academics.tsx, web/src/screens/Planner.tsx, web/src/mocks/account.ts, web/src/mocks/opportunities.ts, web/src/mocks/opportunityDetails.ts, web/src/mocks/store.ts, web/next.config.ts, web/CLAUDE.md
   .env와 .env.local은 읽거나 고치지 마.
3. 문서 "PRD·ERD·API에 반영하기"의 요청도 이 브랜치에서 해.
4. web에서 npm ci, npm run typecheck, npm run build를 돌려.
5. api는 바뀌지 않지만 uv run ruff check ., uv run pytest를 돌려. 320 passed, 35 skipped가 나와야 해.
6. 통과하면 커밋하고 PR을 열어. 제목은 "feat(F-40·F-41): 홈 피드와 공고 상세를 실제 API에 연결 (S1-5·S1-6 웹)"이고, 설명에 새로 만든·바꾼 파일, 검사 결과, 문서에서 건너뛴 항목을 적어.
7. gh pr checks --watch로 CI를 기다려. web·api 작업이 모두 통과하고 api 로그에 "355 passed"가 있으면 squash로 합치고 브랜치를 지워. 다르면 합치지 말고 무엇이 다른지 알려줘.
```

- [ ] api: 바뀌지 않아 그대로 Windows·macOS `320 passed, 35 skipped`(Linux `321 passed, 34 skipped`)다. CI는 DB를 붙여 `355 passed`다
- [ ] web: typecheck·build 통과. 환경 변수 없이 빌드해도 된다(CI와 같은 조건으로 확인함)

## 합친 뒤 실제로 눌러 보기

PR A 때처럼 `api`는 `uv run uvicorn app.main:app --reload`, `web`은 `npm run dev`로 띄운다. `api/.env`를 고쳤으면 uvicorn을 껐다 켠다.

- [ ] **홈:** 1번(공지 가져오기)으로 넣은 공고가 보인다.
  - 요약 숫자, 칩(장학금·기타 등), 마감 임박순·최신순이 맞는지 본다.
  - 요건 추출을 아직 돌리지 않은 공고는 "원문 확인 필요: 자격 요건을 정리하지 못함"으로 보이는 게 정상이다.
- [ ] **공고 상세:** 하나를 연다.
  - 판정표, 판정 기준일, 필요 서류, 공고 첨부파일, AI 처리 과정이 보인다.
  - "원문 보기"는 새 탭으로 학교 공지를 연다.
- [ ] **정보 입력:** "정보 필요" 공고가 있으면 정보 입력 → 저장한다. "다시 판정했어요"와 바뀐 결과가 보이면 된다. 없으면 건너뛴다.
- [ ] **준비 중 기능:** "준비 일정 만들기"와 포스터 등록 화면은 준비 중 안내가 뜬다.
- [ ] **DB 확인:** 레포 루트 PowerShell에서 아래를 돌려 결과를 붙여 준다. 개수만 나온다(이름·이메일 없음).

```powershell
[Console]::OutputEncoding = [Text.Encoding]::UTF8
npx supabase db query --linked --output-format json "select (select count(*) from opportunities o where o.status = 'active') as active_notices, (select count(*) from eligibility_results r where r.user_id = p.id) as judged, (select count(*) from opportunity_views v where v.user_id = p.id) as viewed, (select count(*) from usage_events e where e.user_id = p.id and e.event = 'profile_prompt_shown') as prompts_shown from profiles p order by p.created_at desc limit 1" | Set-Clipboard
```

결과 읽는 법(가장 최근에 가입한 사용자 기준):
- `judged`: 0보다 크면 홈을 열 때 판정이 저장된 것이다.
- `viewed`: 연 상세 수다.
- `prompts_shown`: 정보 입력창을 띄운 수다.

## 구조

```text
web/src/api/client.ts         getFeed(50개씩 끝까지)·getOpportunity(422 → 없는 공고) 실제 API, todayKst·nowIso,
                              PREPARE_READY·POSTER_READY. 준비하기·플래너·포스터 함수는 아직 목
web/src/api/mockClient.ts     목 getFeed(counts는 전체 기준)·getOpportunity(목 다시 판정)
web/src/types/api.ts          공고 피드·상세 v0.4: uploaded_by_me, status, attachments, review_reasons, clauses,
                              unknown_reason, basis_date, ProcessStep(tool·chosen_by·note), Run.steps
web/src/lib/format.ts         formatDdayValue(서버 d_day), getKstDateKey 공개, 출처 이름 "포스터"
web/src/lib/webUrl.ts         (새) http·https 주소만 링크로
web/src/screens/
  Home.tsx                    피드 한 번 부르기, counts로 빈 피드, 서버 d_day, 내가 올린 포스터, 실제 모드 빈 피드
  OpportunityDetail.tsx       상태 안내, 부제(내가 올린 포스터·수강생 대상), 원문 새 탭 링크, 신고 숨김,
                              정보 입력 뒤 다시 불러오기, 불러오기 오류 문구
  PosterUpload.tsx            실제 모드는 준비 중 안내
  Planner.tsx, Academics.tsx  오늘·지금 함수
web/src/components/
  OpportunityConditions.tsx   묶음("다음 중 하나"), 라벨+조건, 판정하지 못한 이유, 판정 기준일
  OpportunityDocuments.tsx    (새) 필요 서류와 공고 첨부파일, 실제 모드 서류 체크 막기
  OpportunityPreparation.tsx  사유(reason_text), 오늘 기준 마감, 준비 중 안내, 원문 링크 버튼
  ProfileInputModal.tsx       정보 입력: 항목 바꾸기·검사·저장·소득 동의·profile_prompt_shown
  AiProcessPanel.tsx          단계 상태·AI가 고름·고른 이유, 원문 확인 이유
  PosterNotReady.tsx          (새) 포스터 등록 준비 중 화면
  Button.tsx                  ButtonLink(새 탭 링크 버튼)
  Header.tsx, ConnectedServices.tsx, CourseAssignments.tsx   오늘·지금 함수
web/src/mocks/
  opportunities.ts, opportunityDetails.ts   v0.4 모양(묶음·첨부·처리 과정·원문 확인 이유)
  account.ts                  목 프로필: 시·군·구·학자금 지원구간 비움(목 "정보 필요" 공고와 맞춤)
  rejudge.ts                  (새) 목 다시 판정
  posterStore.ts              (새) 목 포스터 등록(store.ts에서 나눔)
  store.ts                    addStoredOpportunity
web/next.config.ts            agentRules: false
web/CLAUDE.md                 오늘·지금 함수, 카드 D-day, 준비 중 기능
```

## 확인한 것

| 검사 | 결과 |
| --- | --- |
| web `tsc --noEmit` | 통과 |
| web `next build` | 목 모드, 실제 모드, 환경 변수 없이(CI) 모두 통과. 11개 라우트 |
| `next dev` | AI 도구 환경(`CLAUDECODE=1`)에서 띄워도 `web/AGENTS.md`가 생기지 않는다 |
| 바꾼 파일 줄 수 | 모두 300줄 이하. 가장 긴 파일은 `PosterUpload.tsx` 299줄, `types/api.ts` 279줄 |
| api | 바꾸지 않음. Linux `321 passed, 34 skipped`, `ruff check` 통과 |

**실제 모드 환경:**
- DB: 빈 Postgres 16에 마이그레이션을 모두 적용하고 공고 70개를 넣었다.
  - 판정 상태: 지원 가능, 정보 필요(학점·거주지역·나이·소득·병역), 원문 확인 필요(추출 실패·프로필로 판정할 수 없는 조건), 지원 어려움.
  - 특수한 경우: "다음 중 하나" 묶음 2개, 내 포스터·남의 포스터, 준비한 마감 공고, 숨김 공고, 대외활동 55개(두 쪽).
  - 첨부·서류·처리 과정(도구 호출 기록)도 넣었다.
- API: uvicorn(HS256 검증).
- 웹: 실제 모드로 빌드해 `next start`로 띄웠다. 로그인은 세션 쿠키로 대신했다.

| 묶음 | 본 것 |
| --- | --- |
| 홈 | 요약 숫자가 서버 `counts`와 같다. 50개 넘는 피드를 두 쪽 받는다(66장, 대외활동 55장). 칩 3종, 요약 필터, 지원 어려움 묶음, 정렬이 된다. 내 포스터 표시, 남의 포스터 없음, 서버 `d_day`. 빈 피드(실제 모드) → 다시 불러오기. 상세를 열면 새 공고 수가 준다 |
| 상세 | 사유, 마감까지 N일, 원문 새 탭 링크. 판정표의 라벨+조건·내 값·기준일. "다음 중 하나" 묶음. 묻지 않는 빈 항목 안내, 판정할 수 없는 조건 안내, 지원 어려움 사유 |
| 상세: 추출 실패 | 판정표 대신 안내, 읽지 못한 첨부 표시. 원문 확인 이유는 일반 텍스트이고 주소가 지워진다. "내 프로필과 비교" 줄이 숨는다. 주 버튼 "원문 보기"는 새 탭으로 열린다 |
| 상세: 링크·처리 과정 | 양식·첨부 링크가 걸리고 `javascript:` 주소는 링크가 아니다. 처리 과정에 첨부 이름, 고른 이유, "AI가 고름" 3개가 보인다 |
| 상세: 상태·오류 | 내 포스터에 신고 버튼이 없다. 준비한 마감 공고 안내가 뜨고 서류 체크가 막힌다. 숨김·남의 포스터·목 주소는 "공고를 찾을 수 없어요."다. 서버 500 → 화면 문구 |
| 정보 입력: 기본 | 빠진 항목만 묻는다(학점 1칸). `profile_prompt_shown`이 1건 남는다. 빈칸 저장을 막는다. 범위 밖 값에 오류가 뜬다. 저장 → 다시 판정, DB에 저장, 창 닫힘 |
| 정보 입력: 항목별 | 거주지역은 두 칸이고 서버 422 문구가 입력란 아래 뜬다. `focus=profile_input`이면 창이 바로 열린다(나이 → 생년월일). 병역 복무 개월은 0 안내 → 저장 → 지원 어려움. 소득은 창 안에서 동의 → 입력 → 충족 |
| 정보 입력: 열지 않을 때 | 지원 가능 공고는 `focus`가 있어도 창을 열지 않고 기록도 남기지 않는다 |
| 준비 중 기능 | "준비 일정 만들기"(상시 공고도 목표일 없이)와 "그래도 준비하기"(확인 창 없이)는 바로 안내한다. 포스터 등록 → 안내 → 홈으로 |
| 마무리 | 정보 입력 뒤 홈 숫자가 바뀐다(지원 가능 63, 정보 입력 0, 지원 어려움 2). 플래너가 이번 달로 열리고 설정이 열린다. 콘솔 오류가 없다 |

**목 모드 26단계:**
- 요약 숫자(전체 기준), 칩, 포스터 표시
- 정보 입력 저장 → 목 다시 판정(홈 숫자에도 반영), 소득 입력
- 과목 공지 부제, 읽지 못한 첨부, 처리 과정의 실패 단계
- 준비하기 흐름(진행 단계 → 결과 → 완료), 그래도 준비하기, 포스터 원문 창, 서류 체크
- 포스터 등록 화면, 빈 피드, 플래너 10월, 콘솔 오류 없음

검토 에이전트 1개가 따로 봤다. 막을 문제는 없었고 아래를 받아들였다.

| 제안 | 고친 것 |
| --- | --- |
| 생년월일이 있는 사람에게 병역 복무 개월만 물을 때, 설정의 안내("해당자만 입력")대로 빈칸으로 저장하게 된다. 결과는 그대로인데 "다시 판정했어요"가 뜬다 | 창에서 "복무하지 않았으면 0" 안내. 새로 입력한 값이 없으면 저장하지 않는다 |
| 실제 모드 빈 피드의 "포스터 등록"을 누르면 준비 중 화면 → 홈으로 돌아 제자리다 | 실제 모드 빈 피드는 "다시 불러오기" |
| 알림의 `focus=profile_input`이 빠진 항목 없는 공고에서도 창을 열고 기록을 남긴다 | 빠진 항목이 있을 때만 연다 |
| 같은 묶음의 다른 조건을 충족해 묻지 않는 빈 항목에도 "입력하면 다시 판정" 안내가 뜬다 | "지금은 묻지 않아요" 안내 |
| 학과 목록을 못 불러오면 정보 입력창 전체가 실패한다 | 학과 칸에만 안내를 띄우고 나머지는 입력받는다 |
| 홈·상세 불러오기 오류가 서버 문구 그대로다("잠시 후 다시 시도해 주세요.") | `errorMessage`로 화면 문구. 없는 공고에 "홈으로" |
| `web/CLAUDE.md`의 포스터 설명이 코드와 다르다 | 고침 |
| 실제 모드의 준비 중 기능이 늦게 알린다:<br>· 상시 공고는 목표일을 고른 뒤에야 안내<br>· 그래도 준비하기는 확인 창 뒤에야 안내<br>· 준비한 공고의 서류 체크는 눌러야 실패<br>· 포스터 카드는 "공유 포스터"<br>· 상세가 `window.open`을 쓴다 | 미리 막고 바로 안내한다. 서류 체크는 꺼 두고 이유를 적는다. 출처 이름은 "포스터", 원문은 새 탭 링크 |

그대로 둔 것:
- **1,000개 상한:** 피드가 1,000개를 넘으면 그 뒤는 홈에 보이지 않는다(`next_cursor`가 남음). 공고가 그만큼 쌓이면 "더 보기"를 붙인다.
- **서류 체크 박스:** 응답을 받은 뒤에 체크 상태가 바뀐다(전과 같음). 준비하기 API 작업 때 바로 바뀌게 한다.
- **설정 프로필 폼:** 범위를 넘는 값에 브라우저 기본 말풍선이 뜬다(전과 같음). 정보 입력창은 입력란 아래 문구로 보인다.

## Windows에서

- 새 코드에 플랫폼별 코드는 없다.
- `api` 테스트는 로컬 Postgres로만 돌린다. `DATABASE_URL`에 실제 Supabase 주소를 넣고 `pytest`를 돌리지 않는다.

## 남은 것과 다음 단계

- **`profile_prompt_submitted`(정할 것):**
  - 무엇: 정보 입력창에서 저장했다는 기록이다. 서버가 `PATCH /me/profile` 안에서 남긴다(API 4장).
  - 막힌 점: 어느 공고의 입력창인지 넘길 방법이 명세에 없다. 지표(정보 입력 완료율)에 필요하다.
  - 선택지: (가) `PATCH /me/profile`이 `?opportunity_id=`를 받는다. (나) 이 이벤트만 `POST /events`로 받는다(서버가 기록한다는 원칙을 바꾼다).
  - API 14장에 올린다(아래 반영하기).
- **API가 생기면 지울 것:**
  - `PREPARE_READY`: 준비하기·서류 체크(F-30·F-31)
  - `POSTER_READY`: 포스터 등록(W6)
  - 플래너는 아직 목이라 실제 모드의 할 일과 그 안의 공고 링크가 가짜다. 플래너 API 작업 때 바꾼다.
- **다음 PR(학위과정, B안):** 프로필과 요건에 학위과정(학부·석사·박사)을 더해 대학원생 대상 공고를 판정한다. 공지 가져오기 결과(1번 출력)를 보고 범위를 정한다. → 10/12 docs/학위과정_구현.md.
- **작은 PR(로그인 진단):** API가 토큰을 거절한 이유를 로그에 남기고(토큰은 빼고), 몇 초의 시계 차이를 허용한다. 환경 점검 스크립트를 레포에 넣을지도 같이 정한다. → 10/13 docs/로그인진단_구현.md. 환경 점검 스크립트는 넣지 않고 API가 켤 때 점검한다.
- **Google 테스트 모드:** 캘린더 연결은 7일 뒤 끊긴다. 데모 전에 앱 게시 상태를 정한다.

## PRD·ERD·API에 반영하기

"레포에 넣는 법" 3번에서 같은 브랜치에 적용한다. ERD·PRD는 바꿀 것이 없다.

```text
docs/공고API연결_구현.md의 결정을 기준 문서에 반영해줘. 문서 파일만 고치고 코드·마이그레이션은 건드리지 마. 아래 자리를 찾지 못하면 지어내지 말고 가장 가까운 자리에 넣은 뒤, 어디에 넣었는지 알려줘. 가까운 자리도 없으면 건너뛰고 알려줘.
1. docs/API_명세_v0.4.md
   - 머리말의 마지막 "v0.4 보강" 줄 아래에 더해: "v0.4 보강(10/12, 공고 화면 실제 연결): 홈 피드 호출 방식, 포스터 카드 표시, profile_prompt_submitted 미결"
   - 5장 GET /opportunities 목록에서 "홈은 기본 목록을 `eligibility=eligible,undetermined`로 부르고, "지원 어려움 N개" 묶음을 펼칠 때 `eligibility=ineligible`로 따로 부른다"를 "홈은 eligibility 없이 50개씩 next_cursor가 없을 때까지(최대 1,000개) 받아 화면에서 지원 어려움을 맨 아래 묶음으로 나눈다. 묶음 개수가 칩(category)과 맞아야 해서 따로 부르지 않는다"로 바꿔. 그 문장의 앞부분("`eligibility`는 쉼표로 여러 값을 받는다.")은 그대로 둬.
   - 같은 절의 "포스터 카드는 주최 자리에 "내가 올린 포스터"를 쓴다."를 "포스터 카드는 주최 옆에 "내가 올린 포스터"를 붙이고, 상세는 부제에 쓴다."로 바꿔.
   - 14장 "결정이 필요한 것" 목록 끝에 더해: "- [ ] profile_prompt_submitted에 어느 공고의 정보 입력창인지 남기는 방법 — PATCH /me/profile이 opportunity_id를 받을지, 이 이벤트만 POST /events로 받을지 (10/12)"
   - 부록 "프론트 반영 목록" 끝의 "> 10/11 반영…" 줄 아래에 더해: "> 10/12 반영(docs/공고API연결_구현.md): OpportunityItem·OpportunityDetail·Condition·ProcessStep·Run.steps 타입, 판정표 묶음·판정 기준일, 카드·상세의 업로더 표시와 신고 버튼 숨김."
2. docs/Nextjs_이식_가이드.md "## W4: 목데이터를 실제 API로 바꾸기" 표
   - getFeed 행 비고를 "판정 결과를 eligibility 없이 50개씩 끝까지 받아 화면에서 묶는다(칩은 category, 기타 = research·exam·etc). 정렬 `deadline`·`recent`. 실제 API 연결(10/12)"로 바꿔.
   - getOpportunity 행 비고를 "서버가 다시 판정하고 조회 기록을 남긴다. 형식이 틀린 id(422)는 없는 공고로 안내. 실제 API 연결(10/12)"로 바꿔.
   - prepareOpportunity 행 비고 끝에 " · API 전까지 실제 모드는 누르면 준비 중 안내(PREPARE_READY)"를 더해.
   - setDocumentDone · setPlannerTaskDone 행 비고 끝에 " · API 전까지 실제 모드는 서류 체크를 막는다(PREPARE_READY)"를 더해.
   - extractPoster 행과 registerPosterOpportunity 행 비고 끝에 각각 " · API 전까지 실제 모드는 포스터 등록 화면에 준비 중 안내(POSTER_READY)"를 더해.
   - 표 바로 아래에 한 줄 더해: "화면의 오늘·지금은 client.ts의 todayKst()·nowIso()다. 목 모드는 목데이터 기준일(2026-10-05)을 돌려준다(10/12)."
3. docs/피드판정_구현.md의 "화면 연결(mock-to-api): `getFeed`를 실제 API로 바꾼다." 항목 끝에 더해: " → 10/12 docs/공고API연결_구현.md에서 바꿨다. 지원 어려움을 따로 부르지 않고 한 번에 받아 화면에서 묶는다(이유는 그 문서 '정한 것')."
4. docs/공고상세_구현.md의 "화면 연결(mock-to-api): `getOpportunity`를 실제 API로 바꾼다." 항목 끝에 더해: " → 10/12 docs/공고API연결_구현.md에서 바꿨다."
5. docs/원문확인이유_구현.md의 "화면(mock-to-api): `types/api.ts`의 `OpportunityDetail`에 `review_reasons: string[]`를 더하고" 항목 끝에 더해: " → 10/12 넣었다(처리 과정 맨 위 '원문 확인이 필요한 이유', docs/공고API연결_구현.md)."
6. docs/계정API연결_구현.md "남은 것과 다음 단계"의 "다음 PR(S1-5·S1-6 웹)" 항목 끝에 더해: " → 10/12 docs/공고API연결_구현.md."
끝나면 바뀐 곳을 알려줘.
```

## 코드

경로는 레포 루트 기준이다. 새 파일 5개와 바뀐 파일 23개의 전체 내용을 싣는다.

### 데이터 함수와 타입

#### `web/src/api/client.ts`

```ts
import { ApiError, apiFetch, notReady, USE_MOCKS } from "@/api/http";
import * as mock from "@/api/mockClient";
import { MockApiError, rejectAfter, respond } from "@/api/mockClient";
import { getDevScenario } from "@/dev/scenarios";
import { getKstDateKey } from "@/lib/format";
import { duplicatePosterExtractResult, mockNow, mockToday, posterExtractResult } from "@/mocks";
import { registerStoredPoster } from "@/mocks/posterStore";
import {
  getStoredPlanner,
  addStoredManualTask,
  deleteStoredManualTask,
  prepareStoredOpportunity,
  setStoredPlannerTaskDone,
  setStoredDocumentDone,
  updateStoredManualTask,
} from "@/mocks/store";
import type {
  Category,
  FeedResponse,
  OpportunityDetail,
  OpportunityItem,
  PlannerResponse,
  PlannerTask,
  PosterExtractResult,
  PrepareResult,
  ReportReason,
} from "@/types/api";

// 화면이 쓰는 데이터 함수는 모두 이 파일에서 가져간다 (web/CLAUDE.md, 스킬 mock-to-api).
// 계정·LMS 함수는 accountClient.ts·lmsClient.ts에 두고 여기서 다시 내보낸다.
// 공고 피드·상세는 실제 API를 부르고, 아래 준비하기·플래너·포스터 함수는 아직 목이다
export * from "@/api/accountClient";
export * from "@/api/lmsClient";
export { ApiError, consentRequired, errorMessage, fieldErrors } from "@/api/http";
export { MockApiError };

export interface FeedParams {
  category?: Category | "all"; // "etc"는 기타 칩(연구·시험·기타)
  sort?: "deadline" | "recent";
}

// 화면의 오늘(KST "YYYY-MM-DD")과 지금. 목 모드는 목데이터의 기준 시각(2026-10-05)을 쓴다
export function todayKst(): string {
  return USE_MOCKS ? mockToday : getKstDateKey(new Date());
}

export function nowIso(): string {
  return USE_MOCKS ? mockNow : new Date().toISOString();
}

export type PosterPreviewState =
  | { status: "idle"; result: null }
  | { status: "failure"; result: null }
  | { status: "limit"; result: null }
  | { status: "duplicate"; result: PosterExtractResult };

// "기타" 칩은 연구·시험·기타 세 카테고리를 함께 고른다
function feedCategories(category: FeedParams["category"]): Category[] | null {
  if (!category || category === "all") return null;
  return category === "etc" ? ["research", "exam", "etc"] : [category];
}

const FEED_PAGE_SIZE = 50; // API 최대값
const FEED_MAX_PAGES = 20; // 1,000개까지 받는다. 더 있으면 next_cursor가 남는다

// GET /opportunities. 홈은 판정 결과를 모두 받아 화면에서 묶는다(지원 어려움은 맨 아래 묶음).
// 다음 쪽(next_cursor)이 없을 때까지 50개씩 이어 받는다. counts는 필터와 상관없는 전체 기준이다
export async function getFeed(params: FeedParams = {}): Promise<FeedResponse> {
  const categories = feedCategories(params.category);
  const sort = params.sort ?? "deadline";
  if (USE_MOCKS) return mock.getFeed(categories, sort);
  const query = new URLSearchParams({ sort, limit: String(FEED_PAGE_SIZE) });
  if (categories) query.set("category", categories.join(","));
  let page = await apiFetch<FeedResponse>(`/opportunities?${query}`);
  const items: OpportunityItem[] = [...page.items];
  for (let pages = 1; page.next_cursor && pages < FEED_MAX_PAGES; pages += 1) {
    query.set("cursor", page.next_cursor);
    page = await apiFetch<FeedResponse>(`/opportunities?${query}`);
    items.push(...page.items);
  }
  return { items, next_cursor: page.next_cursor, counts: page.counts };
}

// GET /opportunities/{id}. 서버가 지금 프로필로 다시 판정하고 조회 기록을 남긴다.
// 형식이 틀린 id(422, 예: 목 모드에서 쓰던 주소)도 없는 공고처럼 알린다
export async function getOpportunity(id: string): Promise<OpportunityDetail> {
  if (USE_MOCKS) return mock.getOpportunity(id);
  try {
    return await apiFetch<OpportunityDetail>(`/opportunities/${encodeURIComponent(id)}`);
  } catch (error) {
    if (error instanceof ApiError && error.code === "VALIDATION_FAILED") {
      throw new ApiError("NOT_FOUND", "공고를 찾을 수 없어요.", 404);
    }
    throw error;
  }
}

// 준비하기·서류 체크를 받을지. TODO(api): POST /opportunities/{id}/prepare·PATCH /planner/tasks가 생기면
// 아래 함수를 바꾸고 지운다. 그 전까지 실제 모드는 "준비 일정 만들기"를 누르면 준비 중이라고 알린다
export const PREPARE_READY = USE_MOCKS;
export const PREPARE_NOT_READY = "준비 일정 만들기는 아직 준비 중이에요. 지금은 필요 서류와 마감일을 이 화면에서 확인해 주세요.";

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

export function prepareOpportunity(
  id: string,
  includeCalendar: boolean,
  targetDate?: string,
): Promise<PrepareResult> {
  if (!PREPARE_READY) return notReady(PREPARE_NOT_READY);
  return respond(prepareStoredOpportunity(id, includeCalendar, targetDate));
}

// 서류 체크 = 플래너 할 일 완료 (PATCH /planner/tasks/{task_id})
export function setDocumentDone(
  opportunityId: string,
  documentId: string,
  isDone: boolean,
): Promise<OpportunityDetail> {
  if (!PREPARE_READY) return notReady("서류 체크는 아직 준비 중이에요.");
  return respond(setStoredDocumentDone(opportunityId, documentId, isDone));
}

// TODO(api): POST /opportunities/{id}/reports { reason, detail } — 신고(P1). 그 전까지 화면에 신고 버튼이 없다
export function reportOpportunity(
  _id: string,
  _reason: ReportReason,
  _detail: string,
): Promise<{ reported: boolean; hidden: boolean }> {
  return respond({ reported: true, hidden: false });
}

// 포스터 등록을 받을지. TODO(api): POST /files·/posters/extract·/posters/confirm(W6)이 생기면 아래 포스터 함수를
// 바꾸고 지운다. 그 전까지 실제 모드는 포스터 등록 화면에서 준비 중이라고 알린다(목 공고는 실제 상세에서 열리지 않는다)
export const POSTER_READY = USE_MOCKS;

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

#### `web/src/api/mockClient.ts`

```ts
import { getDevScenario } from "@/dev/scenarios";
import { courseDetails, courses, lmsUpdates, materials, opportunities } from "@/mocks";
import { mockDepartments, mockNow } from "@/mocks/account";
import { rejudgeStoredOpportunity } from "@/mocks/rejudge";
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
  Category,
  ConsentResult,
  Course,
  CourseDetail,
  Department,
  FeedCounts,
  FeedResponse,
  IncomeConsentResult,
  LmsConnection,
  LmsUpdate,
  MaterialDetail,
  Me,
  OpportunityDetail,
  OpportunityItem,
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

// 공고 피드·상세 (client.ts)

// 홈 요약 카드 숫자. 실제 API처럼 카테고리 필터와 상관없이 전체 공고 기준이다
function feedCounts(items: OpportunityItem[]): FeedCounts {
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

export function getFeed(categories: Category[] | null, sort: "deadline" | "recent"): Promise<FeedResponse> {
  if (getDevScenario() === "empty_feed") {
    return respond({ items: [], next_cursor: null, counts: feedCounts([]) });
  }
  const items = opportunities.filter((item) => !categories || categories.includes(item.category));
  items.sort((a, b) =>
    sort === "deadline"
      ? (a.d_day ?? Number.MAX_SAFE_INTEGER) - (b.d_day ?? Number.MAX_SAFE_INTEGER)
      : // 실제 API는 등록 최신순이다. 목데이터에는 등록 시각이 없어 새 공고만 앞으로 보낸다
        Number(b.is_new) - Number(a.is_new),
  );
  return respond({ items, next_cursor: null, counts: feedCounts(opportunities) });
}

// 정보 입력으로 프로필(목 저장소)이 채워졌으면 그 자리에서 다시 판정한 것처럼 바꿔서 준다
export function getOpportunity(id: string): Promise<OpportunityDetail> {
  const detail = rejudgeStoredOpportunity(id, getStoredProfile());
  if (!detail) return Promise.reject(new Error("공고를 찾을 수 없어요."));
  return respond(detail);
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
// 내 정보·프로필·동의·학과·사용 기록·공고 피드·상세는 v0.4에 맞췄다.
// 준비하기·플래너·포스터는 아직 v0.3 모양이다(TODO(api): 그 화면을 실제 API에 붙일 때 명세 부록대로 맞춘다)
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
  missing_fields: string[];              // 정보 입력창(F-03)에 띄울 요건 항목
}
export interface OpportunityItem {
  id: string;
  title: string;
  organizer: string | null;
  category: Category;
  source_type: SourceType;
  deadline_at: string | null;
  d_day: number | null;                  // 마감일(KST) - 오늘(KST). 마감일이 없으면 null(상시)
  easy_summary: string | null;
  eligibility: FeedEligibility;
  recommend_reason: string | null;       // P1
  needs_review: boolean;
  uploaded_by_me: boolean;               // 내가 올린 포스터. 업로더 이름은 보여주지 않는다
  course_name: string | null;            // 과목 공지에서 온 공고만
  prepared: boolean;
  is_new: boolean;
}
// 홈 요약 카드. 카테고리·판정 필터와 상관없이 지금 보이는 활성 공고 전체 기준이다
export interface FeedCounts {
  eligible: number; new_eligible: number;
  undetermined: number; missing_info: number; needs_review: number;
  ineligible: number; deadline_soon: number;
}
export interface FeedResponse { items: OpportunityItem[]; next_cursor: string | null; counts: FeedCounts; }

// GET /opportunities/{id}
export type Outcome = "pass" | "fail" | "unknown";
export type UnknownReason = "missing_profile" | "ambiguous" | "unsupported_field" | "basis_mismatch";
export type OpportunityStatus = "active" | "hidden" | "merged" | "expired";
export interface Condition {
  requirement_id: string;
  clause_no: number;                     // 같은 번호끼리 한 묶음("다음 중 하나")
  field: string;                         // 요건 항목. 나이(age)·거주지역(region)은 프로필 항목 이름과 다르다
  label: string;                         // "직전학기 이수학점"
  operator: string;
  value: unknown;
  user_value: unknown;
  condition_text: string;                // "12학점 이상" (label은 빼고)
  user_value_text: string | null;        // "10학점", 미입력이면 null
  outcome: Outcome;
  unknown_reason: UnknownReason | null;  // 결과가 충족·불충족이면 null
  evidence_text: string | null;          // 근거 원문 문장
  is_ambiguous: boolean;
}
export interface Clause {
  clause_no: number;
  outcome: Outcome;
  condition_count: number;               // 2 이상이면 "다음 중 하나" 상자로 그린다
}
export interface DetailEligibility {
  status: EligibilityStatus;
  display_status: DisplayStatus;
  reason_text: string | null;            // 상태 사유 한 줄(피드 카드의 summary와 같다)
  basis_date: string | null;             // 판정 기준일. 요건 추출에 실패한 공고는 null
  requirements_version: number;
  missing_fields: string[];
  clauses: Clause[];
  conditions: Condition[];               // 묶음 순서, 묶음 안에서는 원문 순서
  evaluated_at: string | null;
}
export interface AttachmentItem {
  id: string;
  file_name: string;
  source_url: string;                    // 학교 다운로드 주소
  extract_status: "succeeded" | "failed" | "skipped"; // skipped: 에이전트가 읽지 않음
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
// 처리 과정 한 줄 (공고 상세의 process.extraction, GET /runs/{id}의 steps)
export interface ProcessStep {
  seq: number;
  tool: string;
  label: string;                         // "첨부 '2026-2 장학 안내.hwp' 읽기"
  status: RunStatus;
  latency_ms: number | null;
  chosen_by: "agent" | "pipeline";       // 모델이 고른 도구인지, 정해진 순서인지
  note: string | null;                   // 모델이 고른 이유 한 줄. 일반 텍스트로만 보여 준다
}
export interface OpportunityDetail {
  id: string;
  title: string;
  organizer: string | null;
  category: Category;
  source_type: SourceType;
  status: OpportunityStatus;             // 준비한 공고가 마감·숨김이 되어도 보인다. 화면 위에 안내를 띄운다
  original_url: string | null;
  poster_url: string | null;             // 포스터 원본 이미지(서명 URL 5분). 포스터 업로드(W6)부터 채운다
  easy_summary: string | null;
  apply_start_at: string | null;
  deadline_at: string | null;
  needs_review: boolean;
  review_reasons: string[];              // 원문 확인이 필요한 이유. 일반 텍스트로만 보여 준다
  extraction_confidence: number | null;
  uploaded_by_me: boolean;
  course_name: string | null;
  attachments: AttachmentItem[];
  eligibility: DetailEligibility;
  documents: DocumentItem[];
  prep: {
    prepared: boolean;
    prep_plan_id: string | null;
    tasks_total: number;
    tasks_done: number;
    calendar_events: { id: string; provider: "google" | "ics" }[];
  };
  process: { extraction: ProcessStep[]; evaluated_at: string | null; prepare_run_id: string | null };
  reported_by_me: boolean;               // 신고(P1) 전에는 늘 false
}

// GET /runs/{id}: 포스터 추출·준비하기 진행 표시
export interface Run<R = unknown> {
  id: string;
  status: RunStatus;
  steps: ProcessStep[];
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

#### `web/src/lib/format.ts`

```ts
import type { Category, SourceType } from "@/types/api";

const KST_TIME_ZONE = "Asia/Seoul";

function parseDate(value: string | Date): Date {
  if (value instanceof Date) return value;
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00+09:00`) : new Date(value);
}

// KST 날짜 "YYYY-MM-DD"
export function getKstDateKey(value: string | Date): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: KST_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(parseDate(value));
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function formatKstLongDate(value: string | Date): string {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: KST_TIME_ZONE,
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(parseDate(value));
}

export function formatKstShortDate(value: string | Date): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: KST_TIME_ZONE,
    month: "numeric",
    day: "numeric",
  }).format(parseDate(value));
}

export function formatKstDate(value: string | Date): string {
  return getKstDateKey(value).replace(/-/g, ".");
}

export function getDdayValue(
  deadlineAt: string | null,
  now: string | Date = new Date(),
): number | null {
  if (!deadlineAt) return null;
  const deadline = new Date(`${getKstDateKey(deadlineAt)}T00:00:00Z`);
  const today = new Date(`${getKstDateKey(now)}T00:00:00Z`);
  return Math.round((deadline.getTime() - today.getTime()) / 86_400_000);
}

export function formatDday(deadlineAt: string | null, now: string | Date = new Date()): string {
  return formatDdayValue(getDdayValue(deadlineAt, now));
}

// 서버가 계산한 d_day(마감일 - 오늘, KST)를 그대로 표시한다. null은 마감일 없음
export function formatDdayValue(days: number | null): string {
  if (days === null) return "상시";
  if (days === 0) return "D-day";
  return days > 0 ? `D-${days}` : `D+${Math.abs(days)}`;
}

export function isDeadlineSoon(deadlineAt: string | null, now: string | Date = new Date()): boolean {
  const days = getDdayValue(deadlineAt, now);
  return days !== null && days >= 0 && days <= 3;
}

export function getCategoryLabel(category: Category, context: "feed" | "detail" = "feed"): string {
  if (context === "detail" && category === "research") return "연구 참여";
  if (context === "detail" && category === "exam") return "시험·자격";
  const labels: Record<Category, string> = {
    scholarship: "장학금",
    school_program: "교내 프로그램",
    youth_policy: "청년정책",
    contest: "공모전",
    activity: "대외활동",
    research: "연구",
    exam: "시험",
    etc: "기타",
  };
  return labels[category];
}

export function getSourceLabel(sourceType: SourceType): string {
  const labels: Record<SourceType, string> = {
    school_notice: "교내 공지",
    youth_policy: "청년정책",
    contest: "공모전",
    poster: "포스터", // 공유는 P1이라 올린 사람에게만 보인다
    lms_announcement: "과목 공지",
  };
  return labels[sourceType];
}

export function formatRelativeTime(
  value: string | Date,
  now: string | Date = new Date(),
): string {
  const elapsed = Math.max(
    0,
    parseDate(now).getTime() - parseDate(value).getTime(),
  );
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return "방금 전";
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  return `${Math.floor(hours / 24)}일 전`;
}
```

#### `web/src/lib/webUrl.ts`

```ts
// 공고에서 온 바깥 주소(원문·첨부·양식)는 http·https만 링크로 건다. 그 밖이면 null
export function webUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}
```

### 홈

#### `web/src/screens/Home.tsx`

```tsx
import { useState } from "react";
import { errorMessage, getFeed, getMe, POSTER_READY, type FeedParams } from "@/api/client";
import Badge from "@/components/Badge";
import Header from "@/components/Header";
import Skeleton from "@/components/Skeleton";
import StatusBadge from "@/components/StatusBadge";
import { formatDdayValue, getCategoryLabel, getSourceLabel } from "@/lib/format";
import useAsyncData from "@/lib/useAsyncData";
import type { Category, DisplayStatus, OpportunityItem } from "@/types/api";
import type { Route } from "@/types/route";

interface HomeProps {
  navigate: (route: Route) => void;
}

type SummaryFilter = "eligible" | "undetermined" | "deadline_soon";

const categoryFilters: { label: string; value: Category | "all" }[] = [
  { label: "전체", value: "all" },
  { label: "장학금", value: "scholarship" },
  { label: "교내 프로그램", value: "school_program" },
  { label: "청년정책", value: "youth_policy" },
  { label: "공모전", value: "contest" },
  { label: "대외활동", value: "activity" },
  { label: "기타", value: "etc" },
];

const statusMarks: Record<DisplayStatus, string> = {
  eligible: "✓",
  missing_info: "!",
  needs_review: "□",
  ineligible: "×",
};

function HomeSkeleton() {
  return (
    <>
      <Skeleton className="h-[70px] w-[360px]" />
      <div className="grid max-w-[786px] grid-cols-3 gap-4">
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
      </div>
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-44 w-full rounded-2xl" />
      <Skeleton className="h-44 w-full rounded-2xl" />
    </>
  );
}

function OpportunityCard({ item, navigate }: { item: OpportunityItem; navigate: (route: Route) => void }) {
  const displayStatus = item.eligibility.display_status;
  const reasonTone =
    displayStatus === "eligible"
      ? "bg-[#ecfdf3] text-[#15803d]"
      : displayStatus === "missing_info"
        ? "bg-[#fff8e1] text-[#b7791f]"
        : displayStatus === "needs_review"
          ? "bg-[#f2f4f7] text-[#475467]"
          : "bg-[#fef2f2] text-[#c53030]";
  const deadlineSoon = item.d_day !== null && item.d_day >= 0 && item.d_day <= 3;
  // 포스터는 올린 사람에게만 보인다. 업로더 이름 대신 "내가 올린 포스터"라고 쓴다
  const context =
    item.source_type === "poster" && item.uploaded_by_me
      ? "내가 올린 포스터"
      : item.source_type === "lms_announcement" && item.course_name
        ? `${item.course_name} 수강생 대상`
        : null;
  const sourceAction = item.source_type === "poster" ? "포스터 보기" : "원문 보기";

  return (
    <button
      type="button"
      onClick={() => navigate({ name: "opportunity", id: item.id })}
      className="opportunity-card group w-full rounded-2xl border border-[#e5e7eb] bg-white p-[22px] text-left transition-all duration-300 hover:-translate-y-1 hover:border-[#cfd7ff] hover:shadow-[0_14px_36px_rgba(79,110,247,0.11)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4f6ef7]"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge>{getCategoryLabel(item.category)}</Badge>
          <span className="text-[12px] font-medium text-[#667085]">{item.organizer}</span>
          {context && <span className="text-[12px] text-[#667085]">· {context}</span>}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <StatusBadge displayStatus={displayStatus} />
          {item.eligibility.display_status === "eligible" && item.needs_review && (
            <Badge tone="gray">원문 확인 필요</Badge>
          )}
          <span className={`text-[12px] font-semibold ${deadlineSoon ? "text-[#c53030]" : "text-[#667085]"}`}>
            {deadlineSoon && "마감 임박 "}
            {formatDdayValue(item.d_day)}
          </span>
        </div>
      </div>
      <h3 className="mt-3 flex items-center gap-2 text-[18px] font-semibold leading-[1.45]">
        {item.is_new && <span className="size-2 shrink-0 rounded-full bg-[#4f6ef7]" />}
        {item.title}
      </h3>
      <p className="mt-2 text-[13px] text-[#667085]">{item.easy_summary}</p>
      <div className={`mt-3 inline-flex items-center gap-2 rounded-[10px] px-3 py-[9px] text-[13px] font-medium ${reasonTone}`}>
        <b>{statusMarks[displayStatus]}</b>
        <span className="truncate">{item.eligibility.summary}</span>
      </div>
      <div className="mt-3 flex items-center justify-between text-[12px] text-[#667085]">
        <span>{getSourceLabel(item.source_type)} · {sourceAction}</span>
        <span className="translate-x-1 text-[18px] text-[#4f6ef7] opacity-0 transition-all duration-300 group-hover:translate-x-0 group-hover:opacity-100">→</span>
      </div>
    </button>
  );
}

export default function Home({ navigate }: HomeProps) {
  const [category, setCategory] = useState<Category | "all">("all");
  const [summaryFilter, setSummaryFilter] = useState<SummaryFilter | null>(null);
  const [sort, setSort] = useState<FeedParams["sort"]>("deadline");
  const [showIneligible, setShowIneligible] = useState(false);
  const [reload, setReload] = useState(0);
  // 판정 결과를 모두 받아 화면에서 묶는다. 요약 카드 숫자(counts)는 카테고리와 상관없는 전체 기준이다
  const request = useAsyncData(
    () =>
      Promise.all([getMe(), getFeed({ category, sort })]).catch((error: unknown) => {
        throw new Error(errorMessage(error, "공고를 불러오지 못했어요. 잠시 후 새로 고쳐 주세요."));
      }),
    [category, sort, reload],
  );

  if (request.loading) return <HomeSkeleton />;
  if (request.error || !request.data) {
    return <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">{request.error ?? "홈 데이터를 불러오지 못했어요."}</p>;
  }

  const [me, feed] = request.data;
  const summaryFilteredItems = feed.items.filter((item) => {
    if (summaryFilter === "eligible") return item.eligibility.display_status === "eligible";
    if (summaryFilter === "undetermined") return item.eligibility.status === "undetermined";
    if (summaryFilter === "deadline_soon") {
      return item.eligibility.status !== "ineligible" && item.d_day !== null && item.d_day >= 0 && item.d_day <= 3;
    }
    return true;
  });
  const visibleItems = summaryFilteredItems.filter((item) => item.eligibility.display_status !== "ineligible");
  const ineligibleItems = summaryFilteredItems.filter((item) => item.eligibility.display_status === "ineligible");
  const counts = feed.counts;
  const hasFilteredResults = visibleItems.length + ineligibleItems.length > 0;
  const isEmptyFeed = counts.eligible + counts.undetermined + counts.ineligible === 0;

  const toggleSummary = (filter: SummaryFilter) => {
    setSummaryFilter((current) => (current === filter ? null : filter));
    setShowIneligible(false);
  };

  const resetFilters = () => {
    setCategory("all");
    setSummaryFilter(null);
    setSort("deadline");
    setShowIneligible(false);
  };

  return (
    <>
      <Header title={`안녕하세요, ${me.display_name}님`} subtitle="나에게 맞는 기회와 이번 주 할 일을 한눈에 확인하세요." />
      <section className="grid max-w-[786px] grid-cols-3 gap-4 max-[760px]:grid-cols-1">
        <button
          type="button"
          onClick={() => toggleSummary("eligible")}
          aria-pressed={summaryFilter === "eligible"}
          className={`h-28 rounded-2xl border bg-white p-5 text-left ${
            summaryFilter === "eligible" ? "border-[#4f6ef7]" : "border-[#e5e7eb]"
          }`}
        >
          <p className="text-[13px] font-medium text-[#667085]">지원 가능</p>
          <p className="text-[28px] font-bold leading-9 text-[#15803d]">{counts.eligible}</p>
          <p className="text-[12px] text-[#667085]">새 공고 {counts.new_eligible}개</p>
        </button>
        <button
          type="button"
          onClick={() => toggleSummary("undetermined")}
          aria-pressed={summaryFilter === "undetermined"}
          className={`h-28 rounded-2xl border bg-white p-5 text-left ${
            summaryFilter === "undetermined" ? "border-[#4f6ef7]" : "border-[#e5e7eb]"
          }`}
        >
          <p className="text-[13px] font-medium text-[#667085]">확인 필요</p>
          <p className="text-[28px] font-bold leading-9 text-[#b7791f]">{counts.undetermined}</p>
          <p className="text-[12px] text-[#667085]">정보 입력 {counts.missing_info} · 원문 확인 {counts.needs_review}</p>
        </button>
        <button
          type="button"
          onClick={() => toggleSummary("deadline_soon")}
          aria-pressed={summaryFilter === "deadline_soon"}
          className={`h-28 rounded-2xl border bg-white p-5 text-left ${
            summaryFilter === "deadline_soon" ? "border-[#4f6ef7]" : "border-[#e5e7eb]"
          }`}
        >
          <p className="text-[13px] font-medium text-[#667085]">마감 임박</p>
          <p className="text-[28px] font-bold leading-9 text-[#c53030]">{counts.deadline_soon}</p>
          <p className="text-[12px] text-[#667085]">3일 이내</p>
        </button>
      </section>
      <section>
        <div className="flex items-center justify-between">
          <h2 className="text-[20px] font-semibold">추천 공고</h2>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as NonNullable<FeedParams["sort"]>)}
            className="bg-transparent text-[13px] font-medium text-[#667085] outline-none"
          >
            <option value="deadline">마감 임박순</option>
            <option value="recent">최신순</option>
          </select>
        </div>
        <div className="mt-5 flex flex-wrap gap-2">
          {categoryFilters.map((filter) => (
            <button
              key={filter.value}
              type="button"
              onClick={() => setCategory(filter.value)}
              className={`filter-chip rounded-full transition-all duration-300 ${
                category === filter.value
                  ? "-translate-y-0.5 scale-105 shadow-[0_6px_16px_rgba(79,110,247,0.18)]"
                  : "opacity-55 hover:-translate-y-0.5 hover:scale-105 hover:opacity-100"
              }`}
              aria-pressed={category === filter.value}
            >
              <Badge>{filter.label}</Badge>
            </button>
          ))}
        </div>
        {isEmptyFeed ? (
          // 실제 모드는 포스터 등록(W6) 전이라 다시 불러오기를 안내한다
          <div className="mt-7 rounded-2xl border border-dashed border-[#e5e7eb] bg-white p-10 text-center">
            <p className="text-[16px] font-semibold">
              {POSTER_READY ? "포스터를 올리면 공고로 등록하고 자격을 판정해요" : "아직 볼 수 있는 공고가 없어요. 새 공고가 올라오면 여기에 보여요"}
            </p>
            <button
              type="button"
              onClick={() => (POSTER_READY ? navigate({ name: "upload" }) : setReload((value) => value + 1))}
              className="mt-3 text-[13px] font-semibold text-[#4f6ef7]"
            >
              {POSTER_READY ? "포스터 등록" : "다시 불러오기"}
            </button>
          </div>
        ) : !hasFilteredResults ? (
          <div className="mt-7 rounded-2xl border border-dashed border-[#e5e7eb] bg-white p-10 text-center">
            <p className="text-[16px] font-semibold">조건에 맞는 공고가 없어요</p>
            <button type="button" onClick={resetFilters} className="mt-3 text-[13px] font-semibold text-[#4f6ef7]">
              필터 초기화
            </button>
          </div>
        ) : (
          <>
            <div key={`${category}-${summaryFilter}-${sort}`} className="opportunity-list mt-7 flex flex-col gap-7">
              {visibleItems.map((item) => <OpportunityCard key={item.id} item={item} navigate={navigate} />)}
            </div>
            {ineligibleItems.length > 0 && (
              <div className="mt-7">
                <button
                  type="button"
                  onClick={() => setShowIneligible((value) => !value)}
                  className="flex w-full items-center justify-between rounded-[14px] border border-[#e5e7eb] bg-white p-4 text-[14px] font-semibold"
                >
                  지원 어려움 {ineligibleItems.length}개
                  <span className="text-[#667085]">{showIneligible ? "⌃" : "⌄"}</span>
                </button>
                {showIneligible && (
                  <div className="mt-3 flex flex-col gap-3">
                    {ineligibleItems.map((item) => <OpportunityCard key={item.id} item={item} navigate={navigate} />)}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </section>
    </>
  );
}
```

### 공고 상세

#### `web/src/screens/OpportunityDetail.tsx`

```tsx
import { useEffect, useState } from "react";
import { errorMessage, getOpportunity } from "@/api/client";
import Button from "@/components/Button";
import AiProcessPanel from "@/components/AiProcessPanel";
import Header from "@/components/Header";
import Modal from "@/components/Modal";
import OpportunityConditions from "@/components/OpportunityConditions";
import OpportunityDocuments from "@/components/OpportunityDocuments";
import OpportunityPreparation from "@/components/OpportunityPreparation";
import ProfileInputModal from "@/components/ProfileInputModal";
import Skeleton from "@/components/Skeleton";
import { getCategoryLabel } from "@/lib/format";
import useAsyncData from "@/lib/useAsyncData";
import { webUrl } from "@/lib/webUrl";
import type { OpportunityDetail as OpportunityDetailData, OpportunityStatus } from "@/types/api";
import type { Route } from "@/types/route";

interface OpportunityDetailProps {
  id: string;
  focus?: "profile_input";
  calendarConnected: boolean;
  navigate: (route: Route) => void;
}

// 준비한 공고는 마감·숨김·병합이 되어도 본인에게 보인다. 그때 화면 위에 띄우는 안내 (API 명세 5장 status)
const STATUS_NOTICE: Record<Exclude<OpportunityStatus, "active">, string> = {
  expired: "마감된 공고예요.",
  hidden: "지금은 목록에서 내린 공고예요.",
  merged: "같은 내용의 다른 공고와 합쳐진 공고예요.",
};

function DetailSkeleton() {
  return (
    <>
      <Skeleton className="h-[70px] w-[480px]" />
      <Skeleton className="h-[150px] w-full rounded-2xl" />
      <div className="grid grid-cols-[1.3fr_1fr] gap-5">
        <Skeleton className="h-[400px] rounded-2xl" />
        <Skeleton className="h-[400px] rounded-2xl" />
      </div>
    </>
  );
}

export default function OpportunityDetail({
  id,
  focus,
  calendarConnected,
  navigate,
}: OpportunityDetailProps) {
  const request = useAsyncData(
    () =>
      getOpportunity(id).catch((error: unknown) => {
        throw new Error(errorMessage(error, "공고를 불러오지 못했어요. 잠시 후 다시 열어 주세요."));
      }),
    [id],
  );
  const [override, setOverride] = useState<OpportunityDetailData | null>(null);
  const [profileOpen, setProfileOpen] = useState(focus === "profile_input");
  const [posterOpen, setPosterOpen] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    setOverride(null);
    setProfileOpen(focus === "profile_input");
  }, [id, focus]);

  if (request.loading) return <DetailSkeleton />;
  if (request.error || !request.data) {
    return (
      <div className="flex items-center justify-between gap-4 rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">
        <p>{request.error ?? "공고를 불러오지 못했어요."}</p>
        <Button secondary onClick={() => navigate({ name: "home" })}>홈으로</Button>
      </div>
    );
  }

  const detail = override ?? request.data;
  const isPoster = detail.source_type === "poster";
  // 포스터는 원본 이미지(포스터 업로드 W6부터)를 창으로, 나머지는 원문 주소를 새 탭으로 연다. 둘 다 없으면 원문 보기가 없다
  const originalHref = isPoster ? null : webUrl(detail.original_url);
  const openPoster = isPoster && detail.poster_url ? () => setPosterOpen(true) : null;
  const showToast = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(""), 2200);
  };

  // 정보 입력을 저장한 뒤: 서버가 상세를 줄 때 지금 프로필로 다시 판정한다
  const reloadAfterProfile = async () => {
    try {
      const updated = await getOpportunity(id);
      setOverride(updated);
      setProfileOpen(false);
      showToast("다시 판정했어요");
    } catch {
      setProfileOpen(false);
      showToast("저장했어요. 화면을 새로 고치면 다시 판정한 결과가 보여요.");
    }
  };

  const subtitle = [
    getCategoryLabel(detail.category, "detail"),
    detail.organizer ?? "주최 미정",
    ...(isPoster && detail.uploaded_by_me ? ["내가 올린 포스터"] : []),
    ...(detail.course_name ? [`${detail.course_name} 수강생 대상`] : []),
  ].join(" · ");

  return (
    <>
      <Header
        title={detail.title}
        subtitle={subtitle}
        action={
          originalHref ? (
            <a href={originalHref} target="_blank" rel="noopener noreferrer" className="text-[13px] font-semibold text-[#4f6ef7]">원문 보기</a>
          ) : openPoster ? (
            <button type="button" onClick={openPoster} className="text-[13px] font-semibold text-[#4f6ef7]">원문 보기</button>
          ) : null
        }
      />
      {detail.status !== "active" && (
        <p role="status" className="rounded-[14px] border border-[#e5e7eb] bg-[#f2f4f7] px-[18px] py-3 text-[13px] font-semibold text-[#475467]">
          {STATUS_NOTICE[detail.status]}
          {detail.prep.prepared && " 준비한 서류와 일정은 그대로 볼 수 있어요."}
        </p>
      )}
      <OpportunityPreparation
        detail={detail}
        calendarConnected={calendarConnected}
        navigate={navigate}
        onOpenProfile={() => setProfileOpen(true)}
        originalHref={originalHref}
        onOpenPoster={openPoster}
        onDetailChange={setOverride}
      />
      <section className="grid grid-cols-[1.3fr_1fr] gap-5 max-[900px]:grid-cols-1">
        <div className="min-h-[400px] rounded-2xl border border-[#e5e7eb] bg-white p-[22px]">
          <h2 className="text-[18px] font-semibold">AI 자격 판정</h2>
          <p className="mt-2 text-[13px] text-[#667085]">행을 누르면 판정에 사용한 공고 원문을 확인할 수 있어요.</p>
          <OpportunityConditions eligibility={detail.eligibility} />
        </div>
        <OpportunityDocuments detail={detail} onChange={setOverride} onError={showToast} />
      </section>
      <AiProcessPanel detail={detail} />
      <ProfileInputModal
        open={profileOpen && detail.eligibility.missing_fields.length > 0}
        opportunityId={detail.id}
        missingFields={detail.eligibility.missing_fields}
        onClose={() => setProfileOpen(false)}
        onSaved={reloadAfterProfile}
      />
      <Modal open={posterOpen} title="포스터 원문" onClose={() => setPosterOpen(false)}>
        {detail.poster_url && <img src={detail.poster_url} alt={`${detail.title} 포스터`} className="mx-auto max-h-[70dvh] rounded-[14px]" />}
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

#### `web/src/components/OpportunityPreparation.tsx`

```tsx
import { useState } from "react";
import {
  errorMessage,
  getOpportunity,
  prepareOpportunity,
  PREPARE_NOT_READY,
  PREPARE_READY,
  todayKst,
} from "@/api/client";
import Badge from "@/components/Badge";
import Button, { ButtonLink } from "@/components/Button";
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
  originalHref: string | null; // 공고 원문 주소(http·https만)
  onOpenPoster: (() => void) | null; // 포스터 원본 이미지가 있으면 창으로 연다
  onDetailChange: (detail: OpportunityDetail) => void;
}

type StepStatus = "idle" | "running" | "done";

const wait = (milliseconds: number) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

function deadlineCopy(detail: OpportunityDetail): string {
  const days = getDdayValue(detail.deadline_at, todayKst());
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
  originalHref,
  onOpenPoster,
  onDetailChange,
}: OpportunityPreparationProps) {
  const [steps, setSteps] = useState<[StepStatus, StepStatus]>(["idle", "idle"]);
  const [result, setResult] = useState<PrepareResult | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [includeCalendar, setIncludeCalendar] = useState(true);
  const [finishing, setFinishing] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [targetDate, setTargetDate] = useState(""); // 상시 공고의 준비 목표일
  const [message, setMessage] = useState<string | null>(null); // 준비하기를 하지 못한 이유
  const today = todayKst();
  const deadlineSoon = isDeadlineSoon(detail.deadline_at, today);
  const applicationPeriod = `${detail.apply_start_at ? formatKstDate(detail.apply_start_at) : "시작일 미정"} ~ ${
    detail.deadline_at ? formatKstDate(detail.deadline_at) : "상시"
  }`;

  // 실제 모드는 아직 준비하기 API가 없어 누르면 바로 준비 중이라고 알린다(목표일·확인 창 없이)
  const notReady = () => setMessage(PREPARE_NOT_READY);

  // 목 모드: 단계 진행을 흉내 낸다. TODO(api): 준비하기 API가 생기면 waitForRun의 steps로 바꾼다
  const startPreparation = async () => {
    setConfirmOpen(false);
    setCompleted(false);
    setResult(null);
    setMessage(null);
    setSteps(["running", "idle"]);
    try {
      await wait(600);
      setSteps(["done", "running"]);
      const [prepared] = await Promise.all([
        prepareOpportunity(detail.id, false, targetDate || undefined),
        wait(600),
      ]);
      setSteps(["done", "done"]);
      setResult(prepared);
      onDetailChange(await getOpportunity(detail.id));
    } catch (error) {
      setSteps(["idle", "idle"]);
      setMessage(errorMessage(error, "준비 일정을 만들지 못했어요. 잠시 후 다시 눌러 주세요."));
    }
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
      if (!PREPARE_READY) return <Button onClick={notReady}>준비 일정 만들기</Button>;
      if (!detail.deadline_at) {
        return (
          <div className="flex items-end gap-2">
            <label className="text-[12px] font-semibold text-[#667085]">
              목표일
              <input
                type="date"
                value={targetDate}
                min={today}
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
      if (originalHref) return <ButtonLink href={originalHref}>원문 보기</ButtonLink>;
      return (
        <Button onClick={onOpenPoster ?? undefined} disabled={!onOpenPoster} title={onOpenPoster ? undefined : "원문 주소가 없어요"}>
          원문 보기
        </Button>
      );
    }
    return (
      <div className="flex gap-2">
        <span title="대체 공고 추천은 준비 중이에요">
          <Button disabled>대체 공고 보기</Button>
        </span>
        <Button secondary onClick={PREPARE_READY ? () => setConfirmOpen(true) : notReady}>그래도 준비하기</Button>
      </div>
    );
  })();

  return (
    <>
      <section className="flex items-center justify-between gap-5 rounded-2xl border border-[#e5e7eb] bg-white p-[22px] max-[760px]:flex-col max-[760px]:items-start">
        <div>
          <div className="flex gap-2">
            <StatusBadge displayStatus={detail.eligibility.display_status} />
            {detail.needs_review && detail.eligibility.display_status === "eligible" && (
              <Badge tone="gray">원문 확인 필요</Badge>
            )}
          </div>
          <p className="mt-2 text-[16px] font-semibold">{detail.eligibility.reason_text}</p>
          <p className={`mt-2 text-[13px] ${deadlineSoon ? "font-semibold text-[#c53030]" : "text-[#667085]"}`}>
            {deadlineCopy(detail)}
          </p>
          <p className="mt-1 text-[12px] text-[#667085]">신청 기간 {applicationPeriod}</p>
        </div>
        {action}
      </section>
      {message && (
        <p role="status" className="rounded-[10px] bg-[#f2f4f7] px-4 py-3 text-[13px] text-[#475467]">{message}</p>
      )}
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

#### `web/src/components/OpportunityConditions.tsx`

```tsx
import { useState } from "react";
import Badge from "@/components/Badge";
import { formatKstDate } from "@/lib/format";
import type { Condition, DetailEligibility, Outcome, UnknownReason } from "@/types/api";
import type { Tone } from "@/types/route";

interface OpportunityConditionsProps {
  eligibility: DetailEligibility;
}

const OUTCOMES: Record<Outcome, { label: string; tone: Tone; mark: string; color: string }> = {
  pass: { label: "충족", tone: "green", mark: "✓", color: "text-[#15803d]" },
  fail: { label: "불충족", tone: "red", mark: "×", color: "text-[#c53030]" },
  unknown: { label: "확인 필요", tone: "yellow", mark: "!", color: "text-[#b7791f]" },
};

// 판정하지 못한 이유별 내 값 자리 문구와, 행을 펼쳤을 때의 안내 (API 명세 5장 unknown_reason)
const UNKNOWN: Record<UnknownReason, { value: string; hint: string }> = {
  missing_profile: { value: "미입력", hint: "정보를 입력하면 바로 다시 판정해요." },
  ambiguous: { value: "원문 확인", hint: "조건이 모호해서 판정하지 않았어요. 원문을 확인해 주세요." },
  unsupported_field: { value: "원문 확인", hint: "프로필로는 판정할 수 없는 조건이에요. 원문을 확인해 주세요." },
  basis_mismatch: { value: "기준 다름", hint: "공고와 내 정보의 기준(실거주·출신 고교 주소, 평점 만점 등)이 달라 직접 확인해야 해요." },
};

// 비어 있어도 같은 묶음의 다른 조건이 충족됐거나 다른 묶음이 불충족이면 정보 입력에서 묻지 않는다
const NOT_ASKED = "입력하지 않은 정보예요. 다른 조건으로 결과가 정해져서 지금은 묻지 않아요.";

function ConditionRow({ condition, asked, open, highlightFailure, onToggle }: {
  condition: Condition;
  asked: boolean; // 정보 입력에서 묻는 항목인지(eligibility.missing_fields)
  open: boolean;
  highlightFailure: boolean;
  onToggle: () => void;
}) {
  const result = OUTCOMES[condition.outcome];
  const unknown = condition.unknown_reason ? UNKNOWN[condition.unknown_reason] : null;
  const hint = condition.unknown_reason === "missing_profile" && !asked ? NOT_ASKED : unknown?.hint;
  const value = condition.user_value_text ?? unknown?.value ?? "미입력";

  return (
    <div className="overflow-hidden rounded-[10px]">
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-center justify-between gap-4 px-1 py-2 text-left">
        <span className="text-[14px] font-medium">
          <b className={`mr-2 ${result.color}`}>{result.mark}</b>
          {condition.label && <span className="mr-1 text-[#667085]">{condition.label}</span>}
          {condition.condition_text}
        </span>
        <span className="flex shrink-0 items-center gap-2 text-[13px] font-semibold">
          <span className={highlightFailure && condition.outcome === "fail" ? "text-[#c53030]" : ""}>{value}</span>
          <Badge tone={result.tone}>{result.label}</Badge>
          <span className="text-[#667085]">{open ? "⌃" : "⌄"}</span>
        </span>
      </button>
      {open && (
        <div className="bg-[#f7f8fa] px-4 py-3 text-[12px] leading-5 text-[#667085]">
          <p>공고 원문: {condition.evidence_text ?? "원문 근거를 확인할 수 없어요."}</p>
          {hint && <p className="mt-1 font-semibold text-[#b7791f]">{hint}</p>}
        </div>
      )}
    </div>
  );
}

// 조건별 판정표. 같은 묶음(clause_no)의 조건은 "다음 중 하나"이고, 묶음끼리는 모두 맞아야 한다
export default function OpportunityConditions({ eligibility }: OpportunityConditionsProps) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const ineligible = eligibility.display_status === "ineligible";
  const groups = eligibility.clauses.map((clause) => ({
    clause,
    rows: eligibility.conditions.filter((condition) => condition.clause_no === clause.clause_no),
  }));
  // 지원 어려움이면 불충족 묶음을 맨 위로 올린다
  const ordered = ineligible
    ? [...groups].sort((a, b) => Number(b.clause.outcome === "fail") - Number(a.clause.outcome === "fail"))
    : groups;

  if (eligibility.conditions.length === 0) {
    return (
      <p className="mt-4 rounded-[10px] bg-[#f7f8fa] px-4 py-3 text-[13px] text-[#344054]">
        {eligibility.display_status === "needs_review"
          ? "공고에서 지원 자격을 정리하지 못했어요. 원문을 확인해 주세요."
          : "공고에 적힌 지원 자격이 없어요."}
      </p>
    );
  }

  const row = (condition: Condition) => (
    <ConditionRow
      key={condition.requirement_id}
      condition={condition}
      asked={eligibility.missing_fields.includes(condition.field)}
      open={expanded === condition.requirement_id}
      highlightFailure={ineligible}
      onToggle={() => setExpanded(expanded === condition.requirement_id ? null : condition.requirement_id)}
    />
  );

  return (
    <div className="mt-4 flex flex-col gap-2">
      {eligibility.basis_date && (
        <p className="text-[12px] text-[#667085]">
          판정 기준일 {formatKstDate(eligibility.basis_date)} · 만 나이·학년·학적은 이날 기준으로 따져요
        </p>
      )}
      {ordered.map(({ clause, rows }) =>
        rows.length < 2 ? (
          rows.map(row)
        ) : (
          <div key={`clause-${clause.clause_no}`} className="rounded-[12px] border border-[#e5e7eb] p-2">
            <div className="flex items-center justify-between px-1 pb-1">
              <span className="text-[12px] font-semibold text-[#667085]">다음 중 하나</span>
              <Badge tone={OUTCOMES[clause.outcome].tone}>{OUTCOMES[clause.outcome].label}</Badge>
            </div>
            {rows.map(row)}
          </div>
        ),
      )}
    </div>
  );
}
```

#### `web/src/components/OpportunityDocuments.tsx`

```tsx
import { errorMessage, PREPARE_READY, setDocumentDone } from "@/api/client";
import { webUrl } from "@/lib/webUrl";
import type { DocumentItem, OpportunityDetail } from "@/types/api";

interface OpportunityDocumentsProps {
  detail: OpportunityDetail;
  onChange: (detail: OpportunityDetail) => void;
  onError: (message: string) => void;
}

function documentInfo(document: DocumentItem): string {
  const issuer = document.issuer ?? "발급처 확인";
  let info =
    document.lead_days === 0
      ? `${issuer} · 즉시 발급`
      : document.lead_days
        ? `${issuer} · 발급 ${document.lead_days}일`
        : issuer;
  if (document.effort_minutes) info += ` · 작성 약 ${document.effort_minutes}분`;
  return info;
}

// 공고 상세의 필요 서류(준비하면 플래너 할 일과 같이 체크)와 공고 첨부파일
export default function OpportunityDocuments({ detail, onChange, onError }: OpportunityDocumentsProps) {
  // 서류 체크는 준비 일정을 만든 뒤에 한다. 실제 모드는 플래너 API 전까지 체크를 막는다
  const checkable = detail.prep.prepared && PREPARE_READY;
  const lockedHint = detail.prep.prepared ? "서류 체크는 아직 준비 중이에요" : "준비 일정을 만들면 체크할 수 있어요";

  return (
    <div className="min-h-[400px] rounded-2xl border border-[#e5e7eb] bg-white p-[22px]">
      <h2 className="text-[18px] font-semibold">필요 서류</h2>
      <p className="mt-2 text-[13px] text-[#667085]">발급 방법과 예상 시간을 확인하세요.</p>
      <div className="mt-4 flex flex-col gap-[14px]">
        {detail.documents.length === 0 && (
          <p className="text-[13px] text-[#667085]">공고에서 정리한 제출 서류가 없어요. 원문을 확인해 주세요.</p>
        )}
        {detail.documents.map((document) => {
          const formUrl = webUrl(document.form_url);
          return (
            <div key={document.id}>
              <label
                title={checkable ? undefined : lockedHint}
                className={`text-[14px] font-semibold ${checkable ? "cursor-pointer" : "cursor-not-allowed"}`}
              >
                <input
                  type="checkbox"
                  checked={document.is_done === true}
                  disabled={!checkable}
                  onChange={async (event) => {
                    try {
                      onChange(await setDocumentDone(detail.id, document.id, event.target.checked));
                    } catch (caught) {
                      onError(errorMessage(caught, "서류를 체크하지 못했어요. 잠시 후 다시 눌러 주세요."));
                    }
                  }}
                  className="mr-2 accent-[#4f6ef7]"
                />
                {document.name}
              </label>
              <p className="ml-5 text-[12px] text-[#667085]">
                {documentInfo(document)}
                {formUrl && (
                  <a href={formUrl} target="_blank" rel="noopener noreferrer" className="ml-2 font-semibold text-[#4f6ef7]">양식 내려받기</a>
                )}
              </p>
              {!checkable && <p className="ml-5 mt-1 text-[11px] text-[#a0a4ab]">{lockedHint}</p>}
            </div>
          );
        })}
      </div>
      {detail.attachments.length > 0 && (
        <div className="mt-6 border-t border-[#e5e7eb] pt-4">
          <h3 className="text-[14px] font-semibold">공고 첨부파일</h3>
          <ul className="mt-2 flex flex-col gap-2">
            {detail.attachments.map((attachment) => {
              const url = webUrl(attachment.source_url);
              return (
                <li key={attachment.id} className="text-[13px]">
                  {url ? (
                    <a href={url} target="_blank" rel="noopener noreferrer" className="font-semibold text-[#4f6ef7]">{attachment.file_name}</a>
                  ) : (
                    <span className="font-semibold">{attachment.file_name}</span>
                  )}
                  {attachment.extract_status === "failed" && (
                    <span className="ml-2 text-[12px] text-[#667085]">AI가 읽지 못한 파일이에요</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
```

#### `web/src/components/AiProcessPanel.tsx`

```tsx
import { useState } from "react";
import Badge from "@/components/Badge";
import { formatKstDate } from "@/lib/format";
import type { OpportunityDetail, RunStatus } from "@/types/api";
import type { Tone } from "@/types/route";

interface AiProcessPanelProps {
  detail: OpportunityDetail;
}

const STEP_STATUS: Record<RunStatus, { label: string; tone: Tone }> = {
  succeeded: { label: "완료", tone: "green" },
  failed: { label: "실패", tone: "red" },
  running: { label: "진행 중", tone: "blue" },
  pending: { label: "대기", tone: "gray" },
};

// AI 처리 과정(F-42): 요건 추출 단계, 원문 확인이 필요한 이유, 프로필 비교, 준비 단계.
// 단계의 고른 이유(note)와 원문 확인 이유는 모델이 쓴 글이라 일반 텍스트로만 보여 준다(링크·마크다운 없이)
export default function AiProcessPanel({ detail }: AiProcessPanelProps) {
  const [open, setOpen] = useState(false);
  const steps = detail.process.extraction;
  const evaluatedAt = detail.eligibility.evaluated_at;
  const empty = steps.length === 0 && detail.review_reasons.length === 0 && !evaluatedAt && !detail.prep.prepared;

  return (
    <section className="rounded-[14px] bg-[#eef2ff] p-[18px]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between text-[14px] font-semibold text-[#4f6ef7]"
      >
        AI 처리 과정
        <span>{open ? "⌃" : "⌄"}</span>
      </button>
      {open && (
        <div className="mt-4 flex flex-col gap-2">
          {detail.review_reasons.length > 0 && (
            <div className="rounded-[10px] bg-white/70 px-4 py-3 text-[13px] text-[#344054]">
              <p className="font-semibold">원문 확인이 필요한 이유</p>
              <ul className="mt-1 list-disc pl-5 leading-6">
                {detail.review_reasons.map((reason, index) => <li key={index}>{reason}</li>)}
              </ul>
            </div>
          )}
          {steps.map((step) => {
            const status = STEP_STATUS[step.status];
            return (
              <div key={step.seq} className="rounded-[10px] bg-white/70 px-4 py-3 text-[13px]">
                <div className="flex items-center justify-between gap-3">
                  <span className="flex flex-wrap items-center gap-2">
                    {step.label}
                    {step.chosen_by === "agent" && <Badge tone="blue">AI가 고름</Badge>}
                  </span>
                  <span className="flex shrink-0 items-center gap-2 text-[#667085]">
                    {step.latency_ms !== null && `${step.latency_ms}ms`}
                    <Badge tone={status.tone}>{status.label}</Badge>
                  </span>
                </div>
                {step.note && <p className="mt-1 text-[12px] leading-5 text-[#667085]">{step.note}</p>}
              </div>
            );
          })}
          {evaluatedAt && (
            <div className="rounded-[10px] bg-white/70 px-4 py-3 text-[13px] text-[#344054]">
              내 프로필과 비교 · {formatKstDate(evaluatedAt)}
            </div>
          )}
          {detail.prep.prepared && (
            <>
              <div className="flex justify-between rounded-[10px] bg-white/70 px-4 py-3 text-[13px]">
                <span>필요 서류 확인</span><Badge tone="green">완료</Badge>
              </div>
              <div className="flex justify-between rounded-[10px] bg-white/70 px-4 py-3 text-[13px]">
                <span>마감일에서 거꾸로 일정 짜기</span><Badge tone="green">완료</Badge>
              </div>
            </>
          )}
          {empty && <p className="px-1 text-[13px] text-[#667085]">아직 AI 처리 기록이 없어요.</p>}
        </div>
      )}
    </section>
  );
}
```

#### `web/src/components/ProfileInputModal.tsx`

```tsx
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  consentRequired,
  errorMessage,
  fieldErrors,
  getDepartments,
  getMe,
  getProfile,
  recordEvent,
  saveProfile,
  updateIncomeConsent,
} from "@/api/client";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import ProfileFieldInput from "@/components/profile/ProfileFieldInput";
import {
  buildProfileSteps,
  fromFormValues,
  toFormValues,
  validateProfile,
  withoutIncome,
  type ProfileErrors,
  type ProfileFieldConfig,
  type ProfileFormValues,
  type ProfileKey,
} from "@/lib/profileFields";
import type { Department, Profile } from "@/types/api";

interface ProfileInputModalProps {
  open: boolean;
  opportunityId: string;
  missingFields: string[]; // eligibility.missing_fields (요건 항목)
  onClose: () => void;
  onSaved: () => Promise<void>; // 공고를 다시 불러온다(서버가 그 자리에서 다시 판정한다)
}

interface Loaded {
  profile: Profile;
  departments: Department[];
  incomeConsented: boolean;
}

const INCOME_KEYS = new Set<ProfileKey>(["income_bracket", "median_income_pct", "welfare_status"]);

// 나이 조건에서 생년월일이 이미 있으면 병역 복무 개월을 묻는다. 복무하지 않았으면 0을 넣어야 판정이 끝난다
const MILITARY_HINT = "복무 기간만큼 나이 상한을 늘려 주는 공고예요. 복무하지 않았으면 0을 입력해 주세요.";

function withContextHint(field: ProfileFieldConfig): ProfileFieldConfig {
  return field.key === "military_service_months" ? { ...field, hint: MILITARY_HINT } : field;
}

// 요건 항목 → 입력받을 프로필 항목. 나이는 생년월일(이미 있으면 병역 복무 개월)을,
// 거주지역은 시·도와 시·군·구를 묻는다(서버 판정 엔진의 "입력 필요" 문구와 같다)
function inputKeys(field: string, profile: Profile): ProfileKey[] {
  if (field === "age") return [profile.birth_date ? "military_service_months" : "birth_date"];
  if (field === "region") return ["region_sido", "region_sigungu"];
  return field in profile ? [field as ProfileKey] : [];
}

// 정보 입력(F-03): 판정에 빠진 항목만 받아 PATCH /me/profile로 저장한다. 창을 띄우면 profile_prompt_shown을 남긴다
export default function ProfileInputModal({ open, opportunityId, missingFields, onClose, onSaved }: ProfileInputModalProps) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [values, setValues] = useState<ProfileFormValues | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [errors, setErrors] = useState<ProfileErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [agreeing, setAgreeing] = useState(false);
  const shown = useRef(false);
  const fieldsKey = missingFields.join(",");

  useEffect(() => {
    if (!open) {
      shown.current = false;
      return;
    }
    if (!shown.current) {
      shown.current = true;
      recordEvent("profile_prompt_shown", opportunityId);
    }
    let active = true;
    setLoaded(null);
    setLoadError(null);
    setErrors({});
    setError(null);
    const fields = fieldsKey.split(",");
    // 학과 목록을 못 불러와도 다른 항목은 입력받는다(학과 칸에 안내가 뜬다)
    const departments = fields.includes("department") ? getDepartments().catch(() => []) : Promise.resolve([]);
    Promise.all([getProfile(), getMe(), departments])
      .then(([profile, me, departments]) => {
        if (!active) return;
        setLoaded({ profile, departments, incomeConsented: me.income_info_consented });
        setValues(toFormValues(profile));
      })
      .catch((caught: unknown) => {
        if (active) setLoadError(errorMessage(caught, "내 정보를 불러오지 못했어요. 창을 닫고 다시 열어 주세요."));
      });
    return () => {
      active = false;
    };
  }, [open, opportunityId, fieldsKey]);

  const fields = useMemo(() => {
    if (!loaded) return [];
    const configs = buildProfileSteps(loaded.departments).flatMap((step) => step.fields);
    const keys = [...new Set(fieldsKey.split(",").flatMap((field) => inputKeys(field, loaded.profile)))];
    return keys.flatMap((key) => configs.filter((config) => config.key === key).map(withContextHint));
  }, [loaded, fieldsKey]);
  const needsIncome = fields.some((field) => INCOME_KEYS.has(field.key));
  const editable = loaded?.incomeConsented ? fields : fields.filter((field) => !INCOME_KEYS.has(field.key));

  const agreeIncome = async () => {
    setAgreeing(true);
    setError(null);
    try {
      await updateIncomeConsent(true);
      setLoaded((current) => current && { ...current, incomeConsented: true });
    } catch (caught) {
      setError(errorMessage(caught, "동의하지 못했어요. 잠시 후 다시 눌러 주세요."));
    } finally {
      setAgreeing(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!loaded || !values) return;
    const nextErrors = validateProfile(values, editable);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    const before = toFormValues(loaded.profile);
    if (editable.every((field) => values[field.key].trim() === before[field.key].trim())) {
      setError("새로 입력한 값이 없어요. 빈칸을 채운 뒤 저장해 주세요.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const next = fromFormValues(values, loaded.profile);
      await saveProfile(loaded.incomeConsented ? next : withoutIncome(next));
    } catch (caught) {
      setSaving(false);
      if (consentRequired(caught) === "income_info") {
        setLoaded({ ...loaded, incomeConsented: false });
        setError("소득·수급 정보는 선택 동의를 해야 저장할 수 있어요.");
        return;
      }
      setErrors(fieldErrors(caught));
      setError(errorMessage(caught, "저장하지 못했어요. 잠시 후 다시 눌러 주세요."));
      return;
    }
    await onSaved();
    setSaving(false);
  };

  return (
    <Modal open={open} title="정보 입력" onClose={onClose}>
      {loadError ? (
        <p role="alert" className="text-[13px] text-[#c53030]">{loadError}</p>
      ) : !loaded || !values ? (
        <p className="text-[13px] text-[#667085]">내 정보를 불러오고 있어요.</p>
      ) : (
        <form noValidate onSubmit={submit}>
          <p className="mb-4 text-[13px] text-[#667085]">이 공고를 판정하는 데 필요한 정보예요. 저장하면 바로 다시 판정해요.</p>
          {needsIncome && (
            <div className="mb-4 rounded-[10px] bg-[#fff8e1] p-3 text-[12px] text-[#b7791f]">
              {loaded.incomeConsented ? (
                <p>자격 판정에만 쓰고, 탈퇴하면 바로 지워요</p>
              ) : (
                <>
                  <p>소득·수급 정보는 선택 동의를 하면 입력할 수 있어요. 자격 판정에만 쓰고, 탈퇴하면 바로 지워요.</p>
                  <div className="mt-2">
                    <Button secondary onClick={agreeIncome} disabled={agreeing}>
                      {agreeing ? "동의하는 중" : "동의하고 입력하기"}
                    </Button>
                  </div>
                </>
              )}
            </div>
          )}
          <div className="flex flex-col gap-4">
            {editable.map((field) => (
              <ProfileFieldInput
                key={field.key}
                field={field}
                value={values[field.key]}
                error={errors[field.key]}
                onChange={(value) => setValues((current) => current && { ...current, [field.key]: value })}
              />
            ))}
          </div>
          {fields.length === 0 && (
            <p className="text-[13px] text-[#667085]">여기서 입력할 수 있는 항목이 없어요. 원문을 확인해 주세요.</p>
          )}
          {error && <p role="alert" className="mt-4 text-[13px] text-[#c53030]">{error}</p>}
          <div className="mt-6 flex justify-end gap-2">
            <Button secondary onClick={onClose}>취소</Button>
            <Button type="submit" disabled={saving || editable.length === 0}>
              {saving ? "다시 판정 중" : "저장하고 다시 판정"}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
```

#### `web/src/components/Button.tsx`

```tsx
import type { ReactNode } from "react";

interface ButtonProps {
  children: ReactNode;
  type?: "button" | "submit";
  secondary?: boolean;
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
}

const BASE = "h-[42px] rounded-[10px] border px-[18px] text-[14px] font-semibold transition active:scale-[0.98]";
const PRIMARY = "border-[#4f6ef7] bg-[#4f6ef7] text-white hover:bg-[#425fe0]";

// 바깥 주소(공고 원문 등)를 새 탭으로 여는 버튼 모양 링크
export function ButtonLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={`inline-flex items-center ${BASE} ${PRIMARY}`}>
      {children}
    </a>
  );
}

export default function Button({
  children,
  type = "button",
  secondary = false,
  onClick,
  disabled = false,
  title,
}: ButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`${BASE} disabled:cursor-not-allowed disabled:opacity-45 ${
        secondary ? "border-[#e5e7eb] bg-white text-[#181a20] hover:bg-[#f7f8fa]" : PRIMARY
      }`}
    >
      {children}
    </button>
  );
}
```

### 포스터 등록(실제 모드는 준비 중)

#### `web/src/screens/PosterUpload.tsx`

```tsx
import { useEffect, useRef, useState } from "react";
import {
  extractPoster,
  getPosterPreviewState,
  MockApiError,
  POSTER_READY,
  registerPosterOpportunity,
} from "@/api/client";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import Header from "@/components/Header";
import PosterExtractForm from "@/components/PosterExtractForm";
import PosterNotReady from "@/components/PosterNotReady";
import Skeleton from "@/components/Skeleton";
import { validatePosterFile } from "@/lib/posterFile";
import useAsyncData from "@/lib/useAsyncData";
import type { PosterExtractResult } from "@/types/api";
import type { Route } from "@/types/route";

interface PosterUploadProps {
  navigate: (route: Route) => void;
}

type UploadStatus =
  | "idle"
  | "analyzing"
  | "complete"
  | "duplicate"
  | "failure"
  | "limit";
type StepStatus = "idle" | "running" | "done";

const wait = (milliseconds: number) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

function SourcePreview({
  previewUrl,
  fileName,
  isPdf,
}: {
  previewUrl: string;
  fileName: string;
  isPdf: boolean;
}) {
  return (
    <section className="flex min-h-[520px] items-center justify-center overflow-hidden rounded-[18px] border border-[#e5e7eb] bg-white p-5">
      {isPdf ? (
        <div className="text-center">
          <div className="mx-auto flex size-20 items-center justify-center rounded-[14px] bg-[#fef2f2] text-[18px] font-bold text-[#c53030]">PDF</div>
          <p className="mt-3 text-[13px] text-[#667085]">{fileName}</p>
        </div>
      ) : (
        <img src={previewUrl || "/assets/mock-opportunity-poster.svg"} alt="업로드한 포스터 미리보기" className="max-h-[640px] rounded-[14px] object-contain" />
      )}
    </section>
  );
}

export default function PosterUpload({ navigate }: PosterUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const objectUrlRef = useRef<string | null>(null);
  const scenario = useAsyncData(getPosterPreviewState, []);
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [steps, setSteps] = useState<[StepStatus, StepStatus, StepStatus]>([
    "idle",
    "idle",
    "idle",
  ]);
  const [result, setResult] = useState<PosterExtractResult | null>(null);
  const [draft, setDraft] = useState<PosterExtractResult["draft"] | null>(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [fileName, setFileName] = useState("");
  const [isPdf, setIsPdf] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [toast, setToast] = useState("");
  const [failureMessage, setFailureMessage] = useState(
    "글자를 읽지 못했어요. 포스터 전체가 보이게 밝은 곳에서 다시 찍어 주세요",
  );

  useEffect(() => {
    if (!scenario.data) return;
    if (scenario.data.status === "duplicate") {
      setStatus("duplicate");
      setResult(scenario.data.result);
      setDraft(scenario.data.result.draft);
      setPreviewUrl("/assets/mock-opportunity-poster.svg");
    } else {
      setStatus(scenario.data.status);
    }
  }, [scenario.data]);

  useEffect(
    () => () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    },
    [],
  );

  const reset = () => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = null;
    setStatus("idle");
    setSteps(["idle", "idle", "idle"]);
    setResult(null);
    setDraft(null);
    setPreviewUrl("");
    setFileName("");
    setIsPdf(false);
    setFailureMessage(
      "글자를 읽지 못했어요. 포스터 전체가 보이게 밝은 곳에서 다시 찍어 주세요",
    );
  };

  const analyze = async (file?: File) => {
    if (!file) return;
    const validationError = await validatePosterFile(file);
    if (validationError) {
      setFailureMessage(validationError);
      setStatus("failure");
      return;
    }

    const pdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
    setIsPdf(pdf);
    setFileName(file.name);
    if (!pdf) {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = URL.createObjectURL(file);
      setPreviewUrl(objectUrlRef.current);
    }
    setStatus("analyzing");
    const extraction = extractPoster(file)
      .then((value) => ({ value, error: null }))
      .catch((error: unknown) => ({ value: null, error }));

    for (let index = 0; index < 3; index += 1) {
      setSteps((current) => current.map((step, stepIndex) => (
        stepIndex < index ? "done" : stepIndex === index ? "running" : step
      )) as [StepStatus, StepStatus, StepStatus]);
      await wait(600);
      setSteps((current) => current.map((step, stepIndex) => (
        stepIndex === index ? "done" : step
      )) as [StepStatus, StepStatus, StepStatus]);
    }

    const extracted = await extraction;
    if (extracted.error) {
      setFailureMessage(
        "글자를 읽지 못했어요. 포스터 전체가 보이게 밝은 곳에서 다시 찍어 주세요",
      );
      setStatus(
        extracted.error instanceof MockApiError && extracted.error.code === "upload_limit"
          ? "limit"
          : "failure",
      );
      return;
    }
    if (!extracted.value) return;
    setResult(extracted.value);
    setDraft(extracted.value.draft);
    setStatus(extracted.value.duplicate_candidate ? "duplicate" : "complete");
  };

  const register = async () => {
    if (!draft) return;
    setRegistering(true);
    const detail = await registerPosterOpportunity(draft);
    setToast("공고를 등록했어요");
    setTimeout(() => navigate({ name: "opportunity", id: detail.id }), 700);
  };

  if (!POSTER_READY) return <PosterNotReady navigate={navigate} />;
  if (scenario.loading) {
    return (
      <>
        <Skeleton className="h-[70px] w-[430px]" />
        <Skeleton className="h-[310px] w-full rounded-[18px]" />
      </>
    );
  }

  const uploadInputs = (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept=".jpg,.jpeg,.png,.webp,.heic,.pdf"
        className="hidden"
        onChange={(event) => analyze(event.target.files?.[0])}
      />
      <input
        ref={cameraInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(event) => analyze(event.target.files?.[0])}
      />
    </>
  );

  return (
    <>
      <Header title="포스터로 공고 등록" subtitle="포스터를 올리면 AI가 제목, 마감일, 지원 조건을 자동으로 정리해요." />
      {uploadInputs}
      {status === "idle" && (
        <section
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            analyze(event.dataTransfer.files[0]);
          }}
          className="flex h-[310px] flex-col items-center justify-center gap-3 rounded-[18px] border border-dashed border-[#e5e7eb] bg-white"
        >
          <span className="text-[34px] font-bold text-[#4f6ef7]">↑</span>
          <p className="text-[18px] font-semibold">이미지 또는 PDF를 업로드해주세요</p>
          <p className="text-[13px] text-[#667085]">JPG · PNG · WEBP · HEIC 또는 2쪽 이하 PDF · 20MB 이하</p>
          <div className="flex gap-2">
            <Button onClick={() => fileInputRef.current?.click()}>파일 선택</Button>
            <span className="hidden max-[760px]:inline-flex">
              <Button secondary onClick={() => cameraInputRef.current?.click()}>사진 찍기</Button>
            </span>
          </div>
        </section>
      )}
      {status === "analyzing" && (
        <div className="grid grid-cols-[1fr_1fr] gap-5 max-[900px]:grid-cols-1">
          <SourcePreview previewUrl={previewUrl} fileName={fileName} isPdf={isPdf} />
          <section className="rounded-[18px] border border-[#e5e7eb] bg-white p-6">
            <h2 className="text-[20px] font-bold">포스터를 분석하고 있어요</h2>
            <div className="mt-5 flex flex-col gap-3">
              {["포스터에서 글자·날짜 읽기", "지원 자격 정리", "내 프로필과 비교"].map((label, index) => (
                <div key={label} className="flex items-center justify-between rounded-[12px] bg-[#f7f8fa] p-4 text-[14px]">
                  <span>{label}</span>
                  <Badge tone={steps[index] === "done" ? "green" : "blue"}>
                    {steps[index] === "done" ? "완료" : steps[index] === "running" ? "진행 중" : "대기"}
                  </Badge>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
      {status === "complete" && result && draft && (
        <div className="grid grid-cols-[0.85fr_1.15fr] gap-5 max-[900px]:grid-cols-1">
          <SourcePreview previewUrl={previewUrl} fileName={fileName} isPdf={isPdf} />
          <PosterExtractForm
            result={result}
            draft={draft}
            registering={registering}
            onDraftChange={setDraft}
            onRegister={register}
          />
        </div>
      )}
      {status === "duplicate" && result?.duplicate_candidate && (
        <div className="grid grid-cols-[1fr_1fr] gap-5 max-[900px]:grid-cols-1">
          <SourcePreview previewUrl={previewUrl} fileName={fileName} isPdf={isPdf} />
          <section className="flex min-h-[300px] flex-col items-center justify-center rounded-[18px] border border-[#e5e7eb] bg-white p-8 text-center">
            <Badge tone="yellow">중복 공고</Badge>
            <h2 className="mt-4 text-[22px] font-bold">이미 등록된 공고예요</h2>
            <p className="mt-2 text-[14px] text-[#667085]">{result.duplicate_candidate.title}</p>
            <div className="mt-5">
              <Button onClick={() => navigate({ name: "opportunity", id: result.duplicate_candidate!.opportunity_id })}>
                기존 공고 보기
              </Button>
            </div>
          </section>
        </div>
      )}
      {(status === "failure" || status === "limit") && (
        <section className="flex min-h-[310px] flex-col items-center justify-center rounded-[18px] border border-[#e5e7eb] bg-white p-8 text-center">
          <Badge tone="red">{status === "limit" ? "업로드 한도 초과" : "분석 실패"}</Badge>
          <h2 className="mt-4 text-[20px] font-bold">
            {status === "limit"
              ? "오늘은 더 올릴 수 없어요. 내일 0시부터 다시 올릴 수 있어요"
              : failureMessage}
          </h2>
          {status === "failure" && (
            <div className="mt-5">
              <Button onClick={() => {
                reset();
                setTimeout(() => fileInputRef.current?.click());
              }}>
                다시 올리기
              </Button>
            </div>
          )}
        </section>
      )}
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white">
          {toast}
        </div>
      )}
    </>
  );
}
```

#### `web/src/components/PosterNotReady.tsx`

```tsx
import Button from "@/components/Button";
import Header from "@/components/Header";
import type { Route } from "@/types/route";

// 실제 모드에서 포스터 등록(W6) API가 생기기 전까지 포스터 등록 화면 대신 보여 준다
export default function PosterNotReady({ navigate }: { navigate: (route: Route) => void }) {
  return (
    <>
      <Header title="포스터로 공고 등록" subtitle="포스터를 올리면 AI가 제목, 마감일, 지원 조건을 자동으로 정리해요." />
      <section className="flex min-h-[310px] flex-col items-center justify-center gap-3 rounded-[18px] border border-dashed border-[#e5e7eb] bg-white p-6 text-center">
        <p className="text-[18px] font-semibold">포스터 등록은 아직 준비 중이에요</p>
        <p className="text-[13px] text-[#667085]">준비되면 이 화면에서 포스터를 올려 공고로 등록할 수 있어요. 지금은 홈에서 학교 공지를 확인해 주세요.</p>
        <Button onClick={() => navigate({ name: "home" })}>홈으로</Button>
      </section>
    </>
  );
}
```

### 오늘·지금을 쓰는 화면

#### `web/src/components/Header.tsx`

```tsx
import { useState, type ReactNode } from "react";
import { nowIso } from "@/api/client";
import { useAppShell } from "@/components/AppShell";
import { formatRelativeTime } from "@/lib/format";
import type { AppNotification, NotificationType } from "@/types/api";
import type { Route } from "@/types/route";

interface HeaderProps {
  title: string;
  subtitle: string;
  action?: ReactNode;
}

function getNotificationRoute(notification: AppNotification): Route {
  if (notification.link.type === "opportunity") {
    return {
      name: "opportunity",
      id: notification.link.id,
      focus: notification.link.focus,
    };
  }
  if (notification.link.type === "planner_task") return { name: "planner" };
  // lms_* 알림의 link.id는 과제·자료·공지 ID라서 과목 이동에는 course_id를 쓴다
  const courseId = notification.link.course_id;
  if (!courseId) return { name: "academics" };
  if (notification.link.type === "lms_module_item") {
    return { name: "course", id: courseId, tab: "materials" };
  }
  if (notification.link.type === "lms_announcement") {
    return { name: "course", id: courseId, tab: "announcements" };
  }
  return { name: "course", id: courseId, tab: "assignments" };
}

function getNotificationDot(type: NotificationType): string {
  if (type === "deadline_soon" || type === "task_due") return "bg-[#c53030]";
  if (type === "profile_needed") return "bg-[#b7791f]";
  if (type === "schedule_change") return "bg-[#a0a4ab]";
  return "bg-[#4f6ef7]";
}

export default function Header({ title, subtitle, action }: HeaderProps) {
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const {
    notifications,
    unreadNotifications,
    markNotificationRead,
    markAllNotificationsRead,
    navigate,
  } = useAppShell();

  const openNotification = async (notification: AppNotification) => {
    if (notification.read_at === null) {
      await markNotificationRead(notification.id);
    }
    navigate(getNotificationRoute(notification));
    setNotificationsOpen(false);
  };

  return (
    <>
      <header className="flex items-center justify-between gap-6">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h1 className="truncate text-[28px] font-bold leading-[1.45] text-[#181a20]">{title}</h1>
            {action}
          </div>
          <p className="mt-[2px] text-[14px] leading-[1.45] text-[#667085]">{subtitle}</p>
        </div>
        <button
          type="button"
          onClick={() => setNotificationsOpen(true)}
          className="relative flex size-10 shrink-0 items-center justify-center rounded-full bg-[#4f6ef7] text-white transition hover:-translate-y-0.5 hover:bg-[#425fe0] hover:shadow-[0_6px_16px_rgba(79,110,247,0.24)] active:scale-95"
          aria-label={`읽지 않은 알림 ${unreadNotifications}개 열기`}
        >
          <svg
            aria-hidden="true"
            width="19"
            height="19"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
            <path d="M10 21h4" />
          </svg>
          {unreadNotifications > 0 && (
            <span className="absolute -right-1 -top-1 flex min-w-5 items-center justify-center rounded-full bg-[#c53030] px-1.5 py-0.5 text-[10px] font-bold leading-4 text-white">
              {unreadNotifications}
            </span>
          )}
        </button>
      </header>
      <div
        className={`fixed inset-0 z-40 bg-[#181a20]/20 transition-opacity duration-300 ${
          notificationsOpen
            ? "pointer-events-auto opacity-100"
            : "pointer-events-none opacity-0"
        }`}
        onClick={() => setNotificationsOpen(false)}
        aria-hidden="true"
      />
      <aside
        className={`fixed inset-y-0 right-0 z-50 flex w-[380px] max-w-[92vw] flex-col bg-white p-6 shadow-[-16px_0_50px_rgba(24,26,32,0.12)] transition-transform duration-300 ease-out ${
          notificationsOpen ? "translate-x-0" : "translate-x-full"
        }`}
        aria-label="알림 패널"
        aria-hidden={!notificationsOpen}
      >
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-[20px] font-bold">알림</h2>
            <p className="mt-1 text-[12px] text-[#667085]">
              읽지 않은 알림 {unreadNotifications}개
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={markAllNotificationsRead}
              disabled={unreadNotifications === 0}
              className="text-[12px] font-semibold text-[#4f6ef7] disabled:cursor-default disabled:text-[#a0a4ab]"
            >
              모두 읽음
            </button>
            <button
              type="button"
              onClick={() => setNotificationsOpen(false)}
              className="flex size-9 items-center justify-center rounded-[10px] bg-[#f7f8fa] text-[20px] text-[#667085]"
              aria-label="알림 닫기"
            >
              ×
            </button>
          </div>
        </div>
        <div className="mt-6 flex flex-col gap-2">
          {notifications.map((notification, index) => (
            <button
              type="button"
              key={notification.id}
              onClick={() => openNotification(notification)}
              className={`${notificationsOpen ? "notification-item" : ""} rounded-[14px] border border-transparent p-4 text-left transition hover:border-[#cfd7ff] ${
                notification.read_at === null ? "bg-[#eef2ff]" : "bg-white"
              }`}
              style={{ animationDelay: `${index * 70}ms` }}
            >
              <span className="flex items-start gap-3">
                <span
                  className={`mt-1.5 size-2 shrink-0 rounded-full ${getNotificationDot(notification.type)}`}
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-start justify-between gap-3">
                    <b className="text-[14px] font-semibold">{notification.title}</b>
                    <span className="shrink-0 text-[11px] text-[#a0a4ab]">
                      {formatRelativeTime(notification.scheduled_at, nowIso())}
                    </span>
                  </span>
                  {notification.body && (
                    <span className="mt-1 block text-[12px] leading-5 text-[#667085]">
                      {notification.body}
                    </span>
                  )}
                </span>
              </span>
            </button>
          ))}
          {notifications.length === 0 && (
            <div className="flex min-h-52 items-center justify-center rounded-[14px] border border-dashed border-[#e5e7eb] text-[14px] font-semibold text-[#667085]">
              새 알림이 없어요
            </div>
          )}
        </div>
      </aside>
    </>
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

#### `web/src/components/CourseAssignments.tsx`

```tsx
import Badge from "@/components/Badge";
import { formatDday } from "@/lib/format";
import { todayKst } from "@/api/client";
import type { CourseDetail, SubmissionState } from "@/types/api";
import type { Tone } from "@/types/route";

interface CourseAssignmentsProps {
  assignments: CourseDetail["assignments"];
}

const submissionMeta: Record<SubmissionState, { label: string; tone: Tone }> = {
  unsubmitted: { label: "미제출", tone: "red" },
  submitted: { label: "제출", tone: "green" },
  graded: { label: "채점 완료", tone: "gray" },
  pending_review: { label: "제출", tone: "green" },
};

export default function CourseAssignments({
  assignments,
}: CourseAssignmentsProps) {
  const sorted = [...assignments].sort((a, b) => {
    const aSubmitted = a.submission_state === "unsubmitted" ? 0 : 1;
    const bSubmitted = b.submission_state === "unsubmitted" ? 0 : 1;
    if (aSubmitted !== bSubmitted) return aSubmitted - bSubmitted;
    return (a.due_at ?? "9999").localeCompare(b.due_at ?? "9999");
  });

  return (
    <div className="flex flex-col gap-3">
      {sorted.map((assignment) => {
        const status = submissionMeta[assignment.submission_state];
        return (
          <article
            key={assignment.id}
            className="flex items-center justify-between gap-4 rounded-[12px] bg-[#f7f8fa] p-4"
          >
            <div>
              <p className="text-[14px] font-semibold">{assignment.title}</p>
              <p className="mt-1 text-[12px] text-[#667085]">
                {assignment.due_at
                  ? `마감 ${formatDday(assignment.due_at, todayKst())}`
                  : "마감일 없음"}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Badge tone={status.tone}>{status.label}</Badge>
              <a
                href={assignment.html_url}
                target="_blank"
                rel="noreferrer"
                className="text-[12px] font-semibold text-[#4f6ef7]"
              >
                LMS에서 제출
              </a>
            </div>
          </article>
        );
      })}
    </div>
  );
}
```

#### `web/src/screens/Academics.tsx`

```tsx
import { useState } from "react";
import {
  getCourses,
  getLmsConnection,
  getLmsUpdates,
  nowIso,
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
  const request = useAsyncData(
    () => Promise.all([getLmsConnection(), getCourses(), getLmsUpdates()]),
    [],
  );
  const [connectionOverride, setConnectionOverride] =
    useState<LmsConnection | null>(null);
  const [connectOpen, setConnectOpen] = useState(false);

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
        <LmsConnectModal
          open={connectOpen}
          onClose={() => setConnectOpen(false)}
          onConnected={setConnectionOverride}
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
            LearningX 연결이 끊겼어요. 토큰이 만료됐거나 삭제됐어요
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
      <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
        <h2 className="text-[18px] font-semibold">새로 들어온 학업 정보</h2>
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
        open={connectOpen}
        onClose={() => setConnectOpen(false)}
        onConnected={setConnectionOverride}
      />
    </>
  );
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
  todayKst,
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
  const [view, setView] = useState(() => ({
    year: Number(todayKst().slice(0, 4)),
    month: Number(todayKst().slice(5, 7)),
  }));
  const [selectedDate, setSelectedDate] = useState(todayKst);
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

### 목데이터

#### `web/src/mocks/account.ts`

```ts
import type { Department, Me, Profile, Settings } from "@/types/api";

export const mockToday = "2026-10-05";
export const mockNow = "2026-10-05T10:00:00+09:00";

export const me: Me = {
  user_id: "user-jinseo",
  display_name: "진서",
  hyin_verified: true,
  calendar_connected: true,
  lms: {
    status: "active",
    last_synced_at: "2026-10-05T09:30:00+09:00",
  },
  profile_completion: { filled: 9, total: 15 },
  consented: true,
  income_info_consented: true, // 목 프로필에 소득 값이 있다(동의 없이 소득 값을 둘 수 없다)
  unread_notifications: 3,
};

export const profile: Profile = {
  department: "컴퓨터학부",
  grade: 3,
  enrollment_status: "enrolled",
  semesters_completed: 5,
  credits_total: 82,
  credits_last_semester: 18,
  gpa_total: 3.62,
  gpa_last_semester: 3.8,
  gpa_scale: 4.5,
  birth_date: "2003-04-18",
  military_service_months: null,
  region_sido: "경기도",
  region_sigungu: null, // 시·군·구 단위 지역 조건은 "정보 필요"가 된다(목 공고 youth-capability)
  income_bracket: null, // 목 공고 data-certificate의 "정보 필요"
  median_income_pct: null,
  welfare_status: "none",
  is_international: false,
};

export const mockDepartments: Department[] = [
  { name: "컴퓨터학부", college: "소프트웨어융합대학", field_group: "공학" },
  { name: "인공지능학과", college: "소프트웨어융합대학", field_group: "공학" },
  { name: "경영학부", college: "경상대학", field_group: "사회" },
  { name: "디자인학부", college: "디자인대학", field_group: "예체능" },
];

export const settings: Settings = {
  push_enabled: true,
  muted_notification_types: [],
  calendar_auto_lms: true,
};
```

#### `web/src/mocks/opportunities.ts`

```ts
import type { OpportunityItem } from "@/types/api";

export const opportunities: OpportunityItem[] = [
  {
    id: "hanyang-support-2026",
    title: "2026 ERICA 생활지원 장학금",
    organizer: "ERICA 학생지원팀",
    category: "scholarship",
    source_type: "school_notice",
    deadline_at: "2026-10-10T18:00:00+09:00",
    d_day: 5,
    easy_summary: "경제적 지원이 필요한 재학생에게 생활비 장학금을 지원해요.",
    eligibility: { status: "eligible", display_status: "eligible", summary: "현재 입력한 조건을 모두 충족해요.", missing_fields: [] },
    recommend_reason: "학적과 성적, 학자금 지원구간이 기준에 맞아요.",
    needs_review: false,
    uploaded_by_me: false,
    course_name: null,
    prepared: true,
    is_new: false,
  },
  {
    id: "youth-capability",
    title: "경기도 청년 역량개발 지원사업",
    organizer: "경기도",
    category: "youth_policy",
    source_type: "youth_policy",
    deadline_at: "2026-10-17T18:00:00+09:00",
    d_day: 12,
    easy_summary: "취업 준비에 필요한 자격시험과 어학시험 응시료를 지원해요.",
    eligibility: { status: "undetermined", display_status: "missing_info", summary: "거주 시·군·구를 입력하면 판정할 수 있어요.", missing_fields: ["region"] },
    recommend_reason: "경기도 거주 대학생에게 유용한 정책이에요.",
    needs_review: false,
    uploaded_by_me: false,
    course_name: null,
    prepared: false,
    is_new: false,
  },
  {
    id: "city-idea-contest",
    title: "2026 대학생 도시 아이디어 공모전",
    organizer: "○○도시공사",
    category: "contest",
    source_type: "poster",
    deadline_at: "2026-10-23T23:59:00+09:00",
    d_day: 18,
    easy_summary: "대학생이 도시 문제 해결 아이디어를 제안하는 공모전이에요.",
    eligibility: { status: "ineligible", display_status: "ineligible", summary: "팀 구성 조건을 충족하지 못했어요.", missing_fields: [] },
    recommend_reason: null,
    needs_review: false,
    uploaded_by_me: true,
    course_name: null,
    prepared: false,
    is_new: false,
  },
  {
    id: "erica-startup-camp",
    title: "ERICA 창업 아이디어 캠프 참가자 모집",
    organizer: "ERICA 창업지원단",
    category: "school_program",
    source_type: "school_notice",
    deadline_at: "2026-10-08T17:00:00+09:00",
    d_day: 3,
    easy_summary: "아이디어 구체화와 멘토링을 제공하는 교내 창업 프로그램이에요.",
    eligibility: { status: "eligible", display_status: "eligible", summary: "지원 가능하지만 모집 학과 범위를 원문에서 확인해야 해요.", missing_fields: [] },
    recommend_reason: "전공 프로젝트를 창업 아이디어로 발전시키기 좋아요.",
    needs_review: true,
    uploaded_by_me: false,
    course_name: null,
    prepared: false,
    is_new: true,
  },
  {
    id: "climate-supporters",
    title: "대학생 기후행동 서포터즈",
    organizer: "환경부",
    category: "activity",
    source_type: "contest",
    deadline_at: "2026-10-06T18:00:00+09:00",
    d_day: 1,
    easy_summary: "지역 기후 캠페인을 직접 기획하고 운영하는 대외활동이에요.",
    eligibility: { status: "eligible", display_status: "eligible", summary: "대학생 재학 조건을 충족해요.", missing_fields: [] },
    recommend_reason: "기획 활동 경험을 쌓을 수 있어요.",
    needs_review: false,
    uploaded_by_me: false,
    course_name: null,
    prepared: false,
    is_new: true,
  },
  {
    id: "database-hackathon",
    title: "데이터베이스 수업 연계 해커톤",
    organizer: "ERICA 소프트웨어융합대학",
    category: "contest",
    source_type: "lms_announcement",
    deadline_at: "2026-10-05T23:59:00+09:00",
    d_day: 0,
    easy_summary: "데이터베이스 과목 수강생이 팀으로 참여하는 교내 해커톤이에요.",
    eligibility: { status: "undetermined", display_status: "needs_review", summary: "팀 구성 방식이 공지마다 달라 원문 확인이 필요해요.", missing_fields: [] },
    recommend_reason: "현재 수강 중인 과목과 연계된 공고예요.",
    needs_review: true,
    uploaded_by_me: false,
    course_name: "데이터베이스",
    prepared: false,
    is_new: false,
  },
  {
    id: "ai-research-intern",
    title: "학부생 AI 연구 참여 인턴 모집",
    organizer: "ERICA 인공지능연구실",
    category: "research",
    source_type: "school_notice",
    deadline_at: null,
    d_day: null,
    easy_summary: "학기 중 연구 프로젝트에 참여할 학부생을 상시 모집해요.",
    eligibility: { status: "eligible", display_status: "eligible", summary: "전공과 학적 조건을 충족해요.", missing_fields: [] },
    recommend_reason: "관심 분야와 전공이 일치해요.",
    needs_review: false,
    uploaded_by_me: false,
    course_name: null,
    prepared: false,
    is_new: false,
  },
  {
    id: "data-certificate",
    title: "데이터 자격시험 응시료 지원",
    organizer: "ERICA 비교과통합관리센터",
    category: "exam",
    source_type: "school_notice",
    deadline_at: "2026-10-20T17:00:00+09:00",
    d_day: 15,
    easy_summary: "데이터 분야 자격시험 응시료 일부를 지원해요.",
    eligibility: { status: "undetermined", display_status: "missing_info", summary: "학자금 지원구간을 입력하면 판정할 수 있어요.", missing_fields: ["income_bracket"] },
    recommend_reason: "전공 관련 자격시험 비용을 줄일 수 있어요.",
    needs_review: false,
    uploaded_by_me: false,
    course_name: null,
    prepared: false,
    is_new: false,
  },
  {
    id: "career-poster",
    title: "청년 커리어 포트폴리오 경진대회",
    organizer: "안산시 청년센터",
    category: "activity",
    source_type: "poster",
    deadline_at: "2026-10-12T18:00:00+09:00",
    d_day: 7,
    easy_summary: "진로 경험을 포트폴리오로 정리해 발표하는 경진대회예요.",
    eligibility: { status: "undetermined", display_status: "needs_review", summary: "휴학생 참여 가능 여부를 원문에서 확인해야 해요.", missing_fields: [] },
    recommend_reason: "진로 활동을 정리하기 좋아요.",
    needs_review: true,
    uploaded_by_me: true,
    course_name: null,
    prepared: false,
    is_new: false,
  },
  {
    id: "youth-rent",
    title: "경기도 청년 월세 특별지원",
    organizer: "경기도",
    category: "youth_policy",
    source_type: "youth_policy",
    deadline_at: "2026-10-25T18:00:00+09:00",
    d_day: 20,
    easy_summary: "독립 거주 청년의 월세를 일정 기간 지원해요.",
    eligibility: { status: "eligible", display_status: "eligible", summary: "연령과 거주지 조건을 충족해요.", missing_fields: [] },
    recommend_reason: "현재 거주 지역에서 신청할 수 있어요.",
    needs_review: false,
    uploaded_by_me: false,
    course_name: null,
    prepared: false,
    is_new: false,
  },
  {
    id: "global-design-contest",
    title: "글로벌 대학생 서비스 디자인 공모전",
    organizer: "한국디자인진흥원",
    category: "contest",
    source_type: "contest",
    deadline_at: "2026-10-30T23:59:00+09:00",
    d_day: 25,
    easy_summary: "사회 문제를 해결하는 서비스 디자인을 제안하는 공모전이에요.",
    eligibility: { status: "ineligible", display_status: "ineligible", summary: "요구되는 디자인 전공 조건에 맞지 않아요.", missing_fields: [] },
    recommend_reason: null,
    needs_review: false,
    uploaded_by_me: false,
    course_name: null,
    prepared: false,
    is_new: false,
  },
  {
    id: "bio-presentation",
    title: "학부생 바이오 연구 발표 지원",
    organizer: "한국연구재단",
    category: "research",
    source_type: "school_notice",
    deadline_at: "2026-10-15T17:00:00+09:00",
    d_day: 10,
    easy_summary: "바이오 분야 학부생 연구 발표 비용을 지원해요.",
    eligibility: { status: "ineligible", display_status: "ineligible", summary: "지원 대상 전공에 포함되지 않아요.", missing_fields: [] },
    recommend_reason: null,
    needs_review: false,
    uploaded_by_me: false,
    course_name: null,
    prepared: false,
    is_new: false,
  },
];
```

#### `web/src/mocks/opportunityDetails.ts`

```ts
import { mockToday } from "@/mocks/account";
import { opportunities } from "@/mocks/opportunities";
import type {
  AttachmentItem,
  Clause,
  Condition,
  DocumentItem,
  OpportunityDetail,
  OpportunityItem,
  ProcessStep,
} from "@/types/api";

// 공고 상세 목데이터 (API 명세 v0.4 5장 모양). 판정표 문구는 서버 판정 엔진의 문구를 흉내 낸다
const EVALUATED_AT = "2026-10-05T09:35:00+09:00";

function step(seq: number, tool: string, label: string, latency: number, note: string | null): ProcessStep {
  return { seq, tool, label, status: "succeeded", latency_ms: latency, chosen_by: "agent", note };
}

function extractionSteps(attachment: AttachmentItem | undefined): ProcessStep[] {
  const read = [step(1, "fetch_original", "공고 원문 페이지 읽기", 420, "본문에 지원 자격이 적혀 있어 원문을 읽음")];
  if (attachment) {
    read.push(step(2, "read_attachment_text", `첨부 '${attachment.file_name}' 읽기`, 910, "본문에 '첨부 참조'만 있어 첨부를 읽음"));
    if (attachment.extract_status === "failed") read[1].status = "failed";
  }
  return [...read, step(read.length + 1, "submit_requirements", "지원 자격 정리", 310, null)];
}

function condition(
  id: string,
  clauseNo: number,
  field: string,
  label: string,
  text: string,
  mine: string | null,
  outcome: Condition["outcome"],
  evidence: string,
  unknownReason: Condition["unknown_reason"] = null,
): Condition {
  return {
    requirement_id: id, clause_no: clauseNo, field, label, operator: "eq", value: text, user_value: mine,
    condition_text: text, user_value_text: mine, outcome, unknown_reason: unknownReason,
    evidence_text: evidence, is_ambiguous: unknownReason === "ambiguous",
  };
}

const CREDITS = "직전학기 12학점 이상 이수한 학생 (단, 4학년은 학년만 확인)";
const enrollment = condition("req-enrollment", 1, "enrollment_status", "학적 상태", "재학", "재학", "pass", "신청일 기준 재학생이어야 합니다.");
// 같은 묶음(clause 2)의 두 조건은 "다음 중 하나"다
const credits = condition("req-credit", 2, "credits_last_semester", "직전학기 이수학점", "12학점 이상", "18학점", "pass", CREDITS);
const fourthGrade = condition("req-grade", 2, "grade", "학년", "4학년", "3학년", "fail", CREDITS);
const gpaPass = condition("req-gpa", 3, "gpa_last_semester", "직전학기 평점", "3.5 이상", "3.80", "pass", "직전학기 평점 3.5 이상");
const gpaFail = condition("req-gpa", 3, "gpa_last_semester", "직전학기 평점", "4.0 이상", "3.80", "fail", "직전학기 평점은 4.0 이상이어야 합니다.");
const team = condition("req-team", 4, "other", "기타 조건", "3인 이상 팀 구성", null, "unknown", "개인 또는 3인 이상 팀으로 참가할 수 있습니다.", "unsupported_field");
const detailRule = condition("req-detail-rule", 3, "other", "기타 조건", "세부 참가 자격", null, "unknown", "세부 참가 자격은 별도 공지를 따릅니다.", "ambiguous");

const missingConditions: Record<string, Condition> = {
  region: condition("req-region", 3, "region", "거주지역", "경기도 안산시", "경기도", "unknown", "안산시에 주민등록을 둔 청년", "missing_profile"),
  income_bracket: condition("req-income", 3, "income_bracket", "학자금 지원구간", "8구간 이하", null, "unknown", "학자금 지원구간 8구간 이하", "missing_profile"),
};

// 묶음 결과: 하나라도 충족이면 충족, 모두 불충족이면 불충족, 나머지는 모름 (판정엔진_규칙.md)
export function clausesOf(conditions: Condition[]): Clause[] {
  const groups = new Map<number, Condition[]>();
  for (const row of conditions) groups.set(row.clause_no, [...(groups.get(row.clause_no) ?? []), row]);
  return [...groups].map(([clauseNo, rows]) => ({
    clause_no: clauseNo,
    outcome: rows.some((row) => row.outcome === "pass") ? "pass" : rows.every((row) => row.outcome === "fail") ? "fail" : "unknown",
    condition_count: rows.length,
  }));
}

function conditionsFor(item: OpportunityItem): Condition[] {
  const base = [enrollment, credits, fourthGrade];
  if (item.eligibility.display_status === "ineligible") return [...base, gpaFail, team];
  if (item.eligibility.display_status === "missing_info") {
    return [...base, ...item.eligibility.missing_fields.map((field) => missingConditions[field])];
  }
  if (item.eligibility.display_status === "needs_review") return [...base, detailRule];
  return [...base, gpaPass];
}

function attachmentsFor(item: OpportunityItem): AttachmentItem[] {
  if (item.source_type !== "school_notice" && item.source_type !== "lms_announcement") return [];
  const failed = item.eligibility.display_status === "needs_review";
  return [{
    id: `att-${item.id}`,
    file_name: failed ? "모집 요강.pdf" : "신청서 양식.hwp",
    source_url: `https://example.edu/files/${item.id}`,
    extract_status: failed ? "failed" : "succeeded",
  }];
}

const preparedDocuments: DocumentItem[] = [
  { id: "doc-enrollment", name: "재학증명서", issuer: "HY-in", how_to: "HY-in 증명발급 메뉴에서 발급", lead_days: 0, effort_minutes: null, form_url: null, is_required: true, task_id: "task-student-cert", is_done: true },
  { id: "doc-grade", name: "성적증명서", issuer: "HY-in", how_to: "HY-in 증명발급 메뉴에서 발급", lead_days: 2, effort_minutes: null, form_url: null, is_required: true, task_id: "task-grade-cert", is_done: false },
  { id: "doc-application", name: "장학금 신청서", issuer: "ERICA 학생지원팀", how_to: "양식을 내려받아 작성", lead_days: null, effort_minutes: 30, form_url: "https://example.edu/forms/scholarship-2026", is_required: true, task_id: "task-application", is_done: false },
];

function makeDetail(item: OpportunityItem): OpportunityDetail {
  const prepared = item.id === "hanyang-support-2026";
  const conditions = conditionsFor(item);
  const attachments = attachmentsFor(item);
  const failedAttachment = attachments.find((attachment) => attachment.extract_status === "failed");
  return {
    id: item.id,
    title: item.title,
    organizer: item.organizer,
    category: item.category,
    source_type: item.source_type,
    status: "active",
    original_url: item.source_type === "poster" ? null : "https://example.edu/notices/" + item.id,
    poster_url: item.source_type === "poster" ? "/assets/mock-opportunity-poster.svg" : null,
    easy_summary: item.easy_summary,
    apply_start_at: "2026-09-20T09:00:00+09:00",
    deadline_at: item.deadline_at,
    needs_review: item.needs_review,
    review_reasons: item.needs_review
      ? [...(failedAttachment ? [`첨부 '${failedAttachment.file_name}'을 읽지 못했어요.`] : []), "AI 메모: 세부 참가 자격이 원문에 따로 적혀 있어요."]
      : [],
    extraction_confidence: item.source_type === "poster" ? 0.84 : 0.97,
    uploaded_by_me: item.uploaded_by_me,
    course_name: item.course_name,
    attachments,
    eligibility: {
      status: item.eligibility.status,
      display_status: item.eligibility.display_status,
      reason_text: item.eligibility.summary,
      basis_date: item.deadline_at ? item.deadline_at.slice(0, 10) : mockToday,
      requirements_version: 1,
      missing_fields: item.eligibility.missing_fields,
      clauses: clausesOf(conditions),
      conditions,
      evaluated_at: EVALUATED_AT,
    },
    documents: prepared ? preparedDocuments : preparedDocuments.map((document) => ({ ...document, task_id: null, is_done: null })),
    prep: {
      prepared,
      prep_plan_id: prepared ? "prep-hanyang-support" : null,
      tasks_total: prepared ? 4 : 0,
      tasks_done: prepared ? 1 : 0,
      calendar_events: prepared ? [{ id: "gcal-hanyang", provider: "google" }] : [],
    },
    process: {
      extraction: extractionSteps(attachments[0]),
      evaluated_at: EVALUATED_AT,
      prepare_run_id: prepared ? "run-prepare-hanyang" : null,
    },
    reported_by_me: false,
  };
}

export const opportunityDetails: Record<string, OpportunityDetail> = Object.fromEntries(
  opportunities.map((item) => [item.id, makeDetail(item)]),
);
```

#### `web/src/mocks/store.ts`

```ts
import { opportunityDetails } from "@/mocks/opportunityDetails";
import { opportunities } from "@/mocks/opportunities";
import { planner } from "@/mocks/planner";
import { mockToday } from "@/mocks/account";
import type {
  OpportunityItem,
  OpportunityDetail,
  PlannerResponse,
  PlannerTask,
  PrepareResult,
} from "@/types/api";

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

const detailsState = clone(opportunityDetails);
const plannerState = clone(planner);

function subtractDays(date: string, days: number): string {
  const value = new Date(`${date.slice(0, 10)}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() - days);
  return value.toISOString().slice(0, 10);
}

// 역산한 날짜가 오늘보다 앞서면 오늘로 당긴다 (API v0.3 보완 규칙)
function clampToToday(date: string): string {
  return date < mockToday ? mockToday : date;
}

function tasksForOpportunity(opportunityId: string): PlannerTask[] {
  return plannerState.items.filter(
    (task) => task.source === "prep_plan" && task.link.id === opportunityId,
  );
}

export function getStoredOpportunity(id: string): OpportunityDetail | undefined {
  return detailsState[id];
}

export function getStoredPlanner(): PlannerResponse {
  return plannerState;
}

export function prepareStoredOpportunity(
  id: string,
  includeCalendar: boolean,
  targetDate?: string,
): PrepareResult {
  const detail = detailsState[id];
  if (!detail) throw new Error("공고를 찾을 수 없어요.");

  // 상시 공고는 사용자가 고른 목표일을 마감일처럼 쓴다
  const deadline = detail.deadline_at?.slice(0, 10) ?? targetDate ?? mockToday;
  const prepPlanId = detail.prep.prep_plan_id ?? `prep-${id}`;

  if (!detail.prep.prepared) {
    const documentTasks: PlannerTask[] = detail.documents.map((document) => {
      const taskId = `task-${id}-${document.id}`;
      document.task_id = taskId;
      document.is_done = false;
      return {
        id: taskId,
        title: `${document.name} 준비`,
        // 제출 2일 전까지 서류를 갖추도록 발급 소요일만큼 앞당긴다
        due_date: clampToToday(subtractDays(deadline, 2 + (document.lead_days ?? 0))),
        is_done: false,
        source: "prep_plan",
        link: {
          type: "opportunity",
          id,
          title: detail.title,
          category: detail.category,
        },
      };
    });
    const submitTask: PlannerTask = {
      id: `task-${id}-submit`,
      title: "신청서 제출",
      due_date: deadline,
      is_done: false,
      source: "prep_plan",
      link: {
        type: "opportunity",
        id,
        title: detail.title,
        category: detail.category,
      },
    };
    plannerState.items.push(...documentTasks, submitTask);
    if (detail.deadline_at && !plannerState.markers.some((marker) => marker.opportunity_id === id)) {
      plannerState.markers.push({
        kind: "deadline",
        date: deadline,
        title: `${detail.title} 마감`,
        opportunity_id: id,
        category: detail.category,
      });
    }
    const feedItem = opportunities.find((item) => item.id === id);
    if (feedItem) feedItem.prepared = true;
  }

  const tasks = tasksForOpportunity(id);
  detail.prep = {
    prepared: true,
    prep_plan_id: prepPlanId,
    tasks_total: tasks.length,
    tasks_done: tasks.filter((task) => task.is_done).length,
    calendar_events:
      includeCalendar && detail.deadline_at
        ? [{ id: `gcal-${id}`, provider: "google" }]
        : [],
  };
  detail.process.prepare_run_id = `run-prepare-${id}`;

  return {
    kind: "prepare",
    prep_plan_id: prepPlanId,
    documents: detail.documents,
    tasks: tasks.map((task) => ({
      id: task.id,
      title: task.title,
      due_date: task.due_date,
      document_id:
        detail.documents.find((document) => document.task_id === task.id)?.id ?? null,
    })),
    calendar_event:
      includeCalendar && detail.deadline_at
        ? {
            id: `gcal-${id}`,
            provider: "google",
            starts_at: detail.deadline_at,
          }
        : null,
  };
}

export function setStoredDocumentDone(
  opportunityId: string,
  documentId: string,
  isDone: boolean,
): OpportunityDetail {
  const detail = detailsState[opportunityId];
  if (!detail) throw new Error("공고를 찾을 수 없어요.");
  const document = detail.documents.find((item) => item.id === documentId);
  if (!document?.task_id) throw new Error("준비 일정을 먼저 만들어 주세요.");

  document.is_done = isDone;
  const task = plannerState.items.find((item) => item.id === document.task_id);
  if (task) task.is_done = isDone;
  const tasks = tasksForOpportunity(opportunityId);
  detail.prep.tasks_done = tasks.filter((item) => item.is_done).length;
  detail.prep.tasks_total = tasks.length;
  return detail;
}

// 포스터 등록(posterStore.ts)이 만든 공고를 피드 맨 앞과 상세에 넣는다
export function addStoredOpportunity(item: OpportunityItem, detail: OpportunityDetail): void {
  opportunities.unshift(item);
  detailsState[detail.id] = detail;
}

export function setStoredPlannerTaskDone(
  taskId: string,
  isDone: boolean,
): PlannerTask {
  const task = plannerState.items.find((item) => item.id === taskId);
  if (!task) throw new Error("할 일을 찾을 수 없어요.");
  task.is_done = isDone;

  if (task.link.type === "opportunity" && task.link.id) {
    const detail = detailsState[task.link.id];
    const document = detail?.documents.find((item) => item.task_id === taskId);
    if (document) document.is_done = isDone;
    if (detail) {
      const tasks = tasksForOpportunity(detail.id);
      detail.prep.tasks_done = tasks.filter((item) => item.is_done).length;
    }
  }
  return task;
}

export function addStoredManualTask(
  title: string,
  dueDate: string,
): PlannerTask {
  const task: PlannerTask = {
    id: `manual-${Date.now()}`,
    title,
    due_date: dueDate,
    is_done: false,
    source: "manual",
    link: { type: null, id: null, title: null, category: null },
  };
  plannerState.items.push(task);
  return task;
}

export function updateStoredManualTask(
  id: string,
  title: string,
  dueDate: string,
): PlannerTask {
  const task = plannerState.items.find((item) => item.id === id);
  if (!task || task.source !== "manual") {
    throw new Error("직접 추가한 일정만 수정할 수 있어요.");
  }
  task.title = title;
  task.due_date = dueDate;
  return task;
}

export function deleteStoredManualTask(id: string): void {
  const index = plannerState.items.findIndex(
    (item) => item.id === id && item.source === "manual",
  );
  if (index < 0) throw new Error("직접 추가한 일정을 찾을 수 없어요.");
  plannerState.items.splice(index, 1);
}
```

#### `web/src/mocks/posterStore.ts`

```ts
import { mockToday } from "@/mocks/account";
import { clausesOf } from "@/mocks/opportunityDetails";
import { addStoredOpportunity } from "@/mocks/store";
import type {
  Condition,
  OpportunityDetail,
  OpportunityItem,
  PosterExtractResult,
  ProcessStep,
} from "@/types/api";

const EVALUATED_AT = "2026-10-05T10:30:00+09:00";

function step(seq: number, tool: string, label: string, latency: number): ProcessStep {
  return { seq, tool, label, status: "succeeded", latency_ms: latency, chosen_by: "pipeline", note: null };
}

// 목 모드의 포스터 등록 (POST /posters/confirm 흉내). 포스터 공고는 올린 사람에게만 보인다(uploaded_by_me)
export function registerStoredPoster(
  draft: PosterExtractResult["draft"],
): OpportunityDetail {
  const id = `poster-${Date.now()}`;
  const conditions: Condition[] = draft.requirements.map((requirement, index) => ({
    requirement_id: `poster-requirement-${index}`,
    clause_no: index + 1,
    field: requirement.field,
    label: "", // 포스터 추출 결과에는 항목 이름이 없어 조건 문구만 보여 준다
    operator: requirement.operator,
    value: requirement.value,
    user_value: "확인됨",
    condition_text: requirement.condition_text,
    user_value_text: "확인됨",
    outcome: "pass",
    unknown_reason: null,
    evidence_text: requirement.evidence_text,
    is_ambiguous: requirement.is_ambiguous,
  }));
  const item: OpportunityItem = {
    id,
    title: draft.title,
    organizer: draft.organizer,
    category: draft.category,
    source_type: "poster",
    deadline_at: draft.deadline_at,
    d_day: draft.deadline_at ? 25 : null,
    easy_summary: draft.easy_summary,
    eligibility: {
      status: "eligible",
      display_status: "eligible",
      summary: "모든 조건 충족",
      missing_fields: [],
    },
    recommend_reason: "직접 등록한 포스터 공고예요.",
    needs_review: draft.low_confidence_fields.length > 0,
    uploaded_by_me: true,
    course_name: null,
    prepared: false,
    is_new: true,
  };
  const detail: OpportunityDetail = {
    id,
    title: draft.title,
    organizer: draft.organizer,
    category: draft.category,
    source_type: "poster",
    status: "active",
    original_url: null,
    poster_url: "/assets/mock-opportunity-poster.svg",
    easy_summary: draft.easy_summary,
    apply_start_at: draft.apply_start_at,
    deadline_at: draft.deadline_at,
    needs_review: draft.low_confidence_fields.length > 0,
    review_reasons: draft.low_confidence_fields.length > 0 ? ["포스터에서 일부 글자를 또렷하게 읽지 못했어요."] : [],
    extraction_confidence: draft.extraction_confidence,
    uploaded_by_me: true,
    course_name: null,
    attachments: [],
    eligibility: {
      status: "eligible",
      display_status: "eligible",
      reason_text: "모든 조건 충족",
      basis_date: draft.deadline_at ? draft.deadline_at.slice(0, 10) : mockToday,
      requirements_version: 1,
      missing_fields: [],
      clauses: clausesOf(conditions),
      conditions,
      evaluated_at: EVALUATED_AT,
    },
    documents: draft.documents.map((document, index) => ({
      id: `poster-document-${index}`,
      ...document,
      how_to: null,
      is_required: true,
      task_id: null,
      is_done: null,
    })),
    prep: {
      prepared: false,
      prep_plan_id: null,
      tasks_total: 0,
      tasks_done: 0,
      calendar_events: [],
    },
    process: {
      extraction: [
        step(1, "extract_from_image", "포스터에서 글자·날짜 읽기", 380),
        step(2, "extract_requirements", "지원 자격 정리", 240),
      ],
      evaluated_at: EVALUATED_AT,
      prepare_run_id: null,
    },
    reported_by_me: false,
  };
  addStoredOpportunity(item, detail);
  return detail;
}
```

#### `web/src/mocks/rejudge.ts`

```ts
import { mockNow } from "@/mocks/account";
import { opportunities } from "@/mocks/opportunities";
import { clausesOf } from "@/mocks/opportunityDetails";
import { getStoredOpportunity } from "@/mocks/store";
import type { Condition, OpportunityDetail, Profile } from "@/types/api";

// 목 모드의 다시 판정. 실제 모드는 서버가 공고 상세를 줄 때 지금 프로필로 판정한다.
// "정보 필요" 공고에서 비어 있던 항목이 모두 채워지면 그 조건을 충족으로 바꾼다
const PROFILE_KEYS: Record<string, (keyof Profile)[]> = {
  age: ["birth_date"],
  region: ["region_sido", "region_sigungu"],
};

function filledValue(field: string, profile: Profile): string | null {
  const values = (PROFILE_KEYS[field] ?? [field as keyof Profile]).map((key) => profile[key]);
  if (values.some((value) => value === null || value === undefined || value === "")) return null;
  return values.join(" ");
}

export function rejudgeStoredOpportunity(id: string, profile: Profile): OpportunityDetail | undefined {
  const detail = getStoredOpportunity(id);
  if (!detail || detail.eligibility.display_status !== "missing_info") return detail;
  const eligibility = detail.eligibility;
  const filled = new Map(eligibility.missing_fields.map((field) => [field, filledValue(field, profile)]));
  if ([...filled.values()].some((value) => value === null)) return detail;

  eligibility.conditions = eligibility.conditions.map((row): Condition => {
    const value = filled.get(row.field);
    if (row.unknown_reason !== "missing_profile" || !value) return row;
    return { ...row, user_value: value, user_value_text: value, outcome: "pass", unknown_reason: null };
  });
  eligibility.status = "eligible";
  eligibility.display_status = "eligible";
  eligibility.reason_text = "모든 조건 충족";
  eligibility.missing_fields = [];
  eligibility.clauses = clausesOf(eligibility.conditions);
  eligibility.evaluated_at = mockNow;
  detail.process.evaluated_at = mockNow;
  const item = opportunities.find((entry) => entry.id === id);
  if (item) {
    item.eligibility = { status: "eligible", display_status: "eligible", summary: "모든 조건 충족", missing_fields: [] };
  }
  return detail;
}
```

### 설정과 규칙

#### `web/next.config.ts`

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // next dev가 AI 코딩 도구를 알아채면 web/AGENTS.md를 만든다. 규칙은 web/CLAUDE.md 하나로 두고 만들지 않게 한다
  agentRules: false,
};

export default nextConfig;
```

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
- 오류 문구는 `errorMessage(error, 화면 문구)`로 만들고, 422 항목 오류는 `fieldErrors`로 입력란 아래에 보여 준다. 실제 모드에서 아직 API가 없는 계정·LMS·준비하기·포스터 등록 기능은 목데이터 대신 빈 값이나 `NOT_READY`(준비 중) 안내를 준다(알림 설정 P1만 목 값, 플래너는 그 API를 붙이기 전까지 목).
- 타입 필드 이름은 API 명세와 같아야 한다. 없는 값이 필요하면 만들지 말고 그 자리에 `// TODO(api):`를 남긴다.
- `NEXT_PUBLIC_USE_MOCKS=true`면 목데이터와 상태 미리보기를 쓴다. 목 상태는 메모리에만 있어 새로고침하면 초기화된다.
- Supabase는 로그인과 세션 토큰에만 쓴다. 데이터는 DB를 직접 읽지 않고 FastAPI로만 받는다.
- 날짜·D-day·카테고리 이름은 `src/lib/format.ts`로만 만든다. 시간대는 KST, 마감일이 없으면 "상시"다. 공고 카드의 D-day는 서버가 준 `d_day`를 쓴다.
- 오늘·지금은 `client.ts`의 `todayKst()`·`nowIso()`로만 얻는다. 목 모드는 목데이터 기준일(2026-10-05)을 돌려준다.
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
