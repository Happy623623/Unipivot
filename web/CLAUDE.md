# web — Next.js 화면

Figma Make 시안을 옮긴 코드다. 아래 화면·데이터 규칙을 지키며 이어서 만든다.

## 구조

- `src/app/` 라우트. `(app)`은 사이드바가 있는 화면(`AppFrame`), `(auth)`는 로그인·온보딩, `auth/callback`은 로그인 콜백
- `src/screens/` 화면, `src/components/` 공통 조각. 페이지 파일은 화면에 `navigate`만 넘긴다
- `src/lib/routes.ts` Route ↔ URL 변환, `src/components/AppFrame.tsx` 내 정보·알림·동의 확인
- `src/api/client.ts` 화면이 쓰는 데이터 함수, `src/api/http.ts` 실제 API 호출(`apiFetch`, `waitForRun`)
- `src/mocks/` 목데이터, `src/dev/` 상태 미리보기(목 모드에서만 보인다)
- `src/types/api.ts` API 명세와 1:1인 타입

## 데이터

- 화면은 `src/api/client.ts` 함수로만 데이터를 받는다. 함수 이름·인자·반환 타입은 그대로 두고 안쪽만 목에서 `apiFetch`로 바꾼다(스킬 `mock-to-api`).
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
- 업로더는 `uploader_masked`만, LMS 토큰은 끝 4자리만 보여준다.

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
