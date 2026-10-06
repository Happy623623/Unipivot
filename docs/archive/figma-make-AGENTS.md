# figma-make-app

React + Vite + Tailwind CSS project running inside Figma Make.

## Development Server

A Vite development server is **already running** on `$PORT` (default 8443). You don't need to start it manually.

- Preview URL: The user can access the running app through the preview panel
- Hot reload: Changes to source files are reflected immediately

## Project Structure

This is the canonical project structure. Start with task-relevant files below. Only follow imports or inspect other files when required, when a documented path is missing, or when the repository contradicts this guide.

- `src/main.tsx` - React entrypoint; imports `src/index.css` and mounts `src/App.tsx` into the `#root` element
- `src/App.tsx` - Primary application component and the usual starting point for UI work
- `src/index.css` - Global CSS entrypoint and Tailwind CSS v4 import
- `index.html` - Vite HTML shell containing the `#root` element and loading `src/main.tsx`
- `package.json` - Project dependencies and the Vite build, development, preview, and formatting scripts
- `vite.config.ts` - Vite configuration with React, Tailwind CSS v4, and Figma Make plugins plus the `@` alias for `src`
- `.mise.toml` - Toolchain versions for Node.js and pnpm

## Dependencies

- Runtime: React 19 and React DOM 19
- Styling: Tailwind CSS v4 with the `@tailwindcss/vite` plugin
- Build tooling: Vite 8, TypeScript 5.7, and `@vitejs/plugin-react`
- Formatting: oxfmt

## Styling

This project uses **Tailwind CSS v4** through the `@tailwindcss/vite` plugin configured in `vite.config.ts`. `src/index.css` imports Tailwind with `@import 'tailwindcss';`. Use Tailwind utility classes directly in JSX and put global CSS or Tailwind v4 theme customization in `src/index.css`. This scaffold does not need a Tailwind config file or PostCSS config.

`src/main.tsx` imports `src/index.css`, so global font wiring belongs in `src/index.css`. Keep CSS `@import` statements first, then add any `@font-face` rules and font-family defaults there.

## Code quality

- Use double quotes for strings containing apostrophes (`"We're here to help"`), or escape them in single-quoted strings. An unescaped apostrophe in a single-quoted string breaks the build.
- Ensure JSX tags are closed and braces are balanced.
- Export components as default exports.

---

# 프로젝트 규칙 — UNIPIVOT(가칭)

대학생이 장학금·청년정책·공모전 공고에 지원할 수 있는지 판정받고, 준비 일정을 만들고, LMS 과제·자료를 챙기는 웹 서비스의 시안이다. 이 코드는 나중에 Next.js로 옮겨 실제 API에 연결한다. 모든 작업에서 아래 규칙을 지킨다. 기준 문서는 PRD v0.8과 API 명세 v0.3이다.

## 화면

| 화면 | 들어오는 곳 | 담는 것 |
| --- | --- | --- |
| 로그인·온보딩 | 첫 접속(`me.consented`가 false) | Google 로그인, 약관 동의, 프로필 4단계(모두 건너뛰기 가능) |
| 홈 | 사이드바 홈 | 요약 카드 3개, 카테고리 칩, 추천 공고, 맨 아래 지원 어려움 묶음 |
| 공고 상세 | 홈 카드, 알림 | 상태 카드, 조건별 판정표, 필요 서류, 준비하기, AI 처리 과정, 원문 보기·신고 |
| 플래너 | 사이드바 플래너 | 월간 캘린더, 오늘 할 일, 다가오는 일정, 일정 추가 |
| 학업 | 사이드바 학업 | LMS 연결 상태, 과목 카드, 새로 들어온 학업 정보 |
| 과목 상세 | 학업의 과목 카드 | 과제·자료·공지·계획서 탭, 강의자료 요약과 구간 번역 |
| 포스터 등록 | 사이드바 포스터 등록 | 업로드, 분석 과정, 추출 결과 확인·수정, 등록 |
| 알림 패널 | 헤더 알림 버튼 | 최근 알림, 모두 읽음 |
| 설정 | 사이드바 하단 | 프로필, 연결된 서비스, 알림, 탈퇴 |
| 문서함 | 사이드바(P1, 그 전까지 메뉴 숨김) | 올린 강의자료·계획서와 요약 |

## 데이터

- 화면 데이터는 `src/api/client.ts`의 함수로만 받는다. 지금은 `src/mocks/` 목데이터를 Promise로 돌려준다.
- 데이터 형태는 `src/types/api.ts`를 따른다. API 명세와 1:1이라 필드 이름을 바꾸거나 없는 필드를 만들지 않는다. 필요한 값이 없으면 그 자리에 `// TODO(api):` 주석을 남긴다.
- 날짜, D-day, 카테고리 이름은 `src/lib/format.ts`로만 만든다. 시간대는 KST, 마감일이 없으면 "상시"다.
- 화면은 `src/screens/`, 공통 조각은 `src/components/`에 두고 한 파일이 300줄을 넘지 않게 나눈다. 화면 코드에서 `window`·`localStorage`를 직접 쓰지 않는다.
- 개발용 상태 미리보기 코드는 `src/dev/`에만 둔다.

## 판정 라벨 (4종 고정)

| display_status | 라벨 | 톤 | 주 행동 버튼 |
| --- | --- | --- | --- |
| eligible | 지원 가능 | green | 준비 일정 만들기 |
| missing_info | 정보 필요 | yellow | 정보 입력 |
| needs_review | 원문 확인 필요 | gray | 원문 보기 |
| ineligible | 지원 어려움 | red | 대체 공고 보기 |

- "확인 필요"는 홈 요약 카드에서 정보 필요와 원문 확인 필요를 합쳐 부를 때만 쓴다.
- 지원 어려움 공고는 홈 목록 맨 아래 "지원 어려움 N개" 묶음 안에만 둔다. 기본은 접힘이다.
- `needs_review`가 true인 지원 가능 공고는 라벨은 그대로 두고 옆에 작은 "원문 확인 필요" 배지를 붙인다.

## 기준값

- 마감 임박은 D-3 이내(당일 포함)다. 새 공고는 서버가 계산한 `is_new`를 그대로 쓴다.
- 카테고리 칩: 전체, 장학금(scholarship), 교내 프로그램(school_program), 청년정책(youth_policy), 공모전(contest), 대외활동(activity), 기타(research·exam·etc). 상세에서는 research를 "연구 참여", exam을 "시험·자격"으로 표시한다.
- 포스터 파일은 JPG·PNG·WEBP·HEIC와 2쪽 이하 PDF, 20MB 이하다.
- 업로더는 `uploader_masked`(예: 김\*지)만 보여주고, LMS 토큰은 끝 4자리만 보여준다.

## 디자인 토큰 (지금 시안 유지, 새 색·글꼴 추가 금지)

- 주색 #4f6ef7(hover #425fe0), 연한 주색 #eef2ff, 강조 테두리 #cfd7ff
- 글자 #181a20, 보조 #667085, 본문 보조 #344054, 비활성 #a0a4ab
- 배경 #f7f8fa, 카드 흰색, 테두리 #e5e7eb. 모서리는 버튼 10px, 카드 14–18px, 칩은 완전히 둥글게
- 상태 톤(글자/배경): green #15803d/#ecfdf3, yellow #b7791f/#fff8e1, red #c53030/#fef2f2, gray #475467/#f2f4f7
- 글꼴은 index.css의 Inter + Noto Sans KR을 쓴다. `prefers-reduced-motion` 규칙을 유지하고, 새 움직임은 사용자 동작(열기·펼치기·완료)에 대한 반응에만 쓴다.

## 문구

- 해요체 평서문으로 쓴다. 버튼은 실제로 일어나는 동작을 쓰고, 같은 동작은 흐름 내내 같은 이름을 쓴다("준비 일정 만들기" → 완료 토스트 "준비 일정을 만들었어요").
- 오류는 무엇이 잘못됐고 어떻게 고치는지 말한다. 사과하거나 뭉뚱그리지 않는다.
- 빈 화면은 다음 행동 하나를 버튼과 함께 안내한다.
- 소득·수급 같은 민감 항목 입력란 위에는 "자격 판정에만 쓰고, 탈퇴하면 바로 지워요"를 붙인다.

## 하지 않는 것

- 실제 API·외부 이미지 호출, 라우터·상태관리 라이브러리 추가(아이콘용 lucide-react만 허용)
- 채팅 UI(이 서비스는 대시보드형이다)
- 실명이나 토큰 원문 표시
