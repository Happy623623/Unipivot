# Next.js 이식 가이드 — Figma Make 코드 → Next.js 16

> 📝 기준: Figma Make 0–11 결과 + `Make_0-11_검토.md` 수정 · Next.js 16.3 · Tailwind CSS 4.3 · @supabase/ssr 0.12 · 2026-10-06

Make 화면 코드는 한 줄도 고치지 않고 옮기고, 라우팅·레이아웃·글꼴만 Next.js 방식으로 바꾼다. 샌드박스에서 이 순서대로 옮겨 `next build`로 11개 라우트를 만들었고, 브라우저 점검 19개 항목을 통과했다.

## 결과 구조

```text
unipivot-web/
├── .env.local.example
├── next.config.ts · postcss.config.mjs · tsconfig.json
├── public/assets/                  ← Make public/assets 그대로
└── src/
    ├── app/
    │   ├── layout.tsx              (신규) 글꼴·전역 CSS
    │   ├── globals.css             Make index.css에서 Figma 글꼴만 뺀 것
    │   ├── (app)/layout.tsx        (신규) AppFrame으로 감싼다
    │   ├── (app)/…/page.tsx        (신규) 화면마다 3–25줄
    │   ├── (auth)/…                로그인·온보딩 → 온보딩_구현.md
    │   └── auth/callback/route.ts  → 온보딩_구현.md
    ├── components/AppFrame.tsx     (신규) Make App.tsx 대체
    ├── lib/routes.ts               (신규) Route ↔ URL
    └── components/ screens/ api/ mocks/ lib/ types/ dev/   ← Make src 그대로(검토 수정 포함)
```

## 라우트 대응

화면 코드는 지금처럼 `navigate(route)`를 부르고, `lib/routes.ts`가 URL로 바꾼다.

| Make `Route` | URL | 페이지 |
| --- | --- | --- |
| `{ name: "home" }` | `/` | `(app)/page.tsx` |
| `{ name: "opportunity", id, focus }` | `/opportunities/{id}?focus=profile_input` | `(app)/opportunities/[id]/page.tsx` |
| `{ name: "planner" }` | `/planner` | `(app)/planner/page.tsx` |
| `{ name: "academics" }` | `/academics` | `(app)/academics/page.tsx` |
| `{ name: "course", id, tab }` | `/academics/{id}?tab=materials` | `(app)/academics/[courseId]/page.tsx` |
| `{ name: "upload" }` | `/upload` | `(app)/upload/page.tsx` |
| `{ name: "settings" }` | `/settings` | `(app)/settings/page.tsx` |
| `{ name: "onboarding" }` | `/onboarding` | `(auth)/onboarding/page.tsx` |
| — | `/login`, `/auth/callback` | 온보딩_구현.md |

## 옮기는 순서

### 1. 프로젝트 만들기

```bash
mkdir unipivot-web && cd unipivot-web
npm init -y
npm install next@16 react@19 react-dom@19 @supabase/ssr @supabase/supabase-js
npm install -D typescript@5 @types/react@19 @types/react-dom@19 @types/node@22 tailwindcss@4 @tailwindcss/postcss@4 postcss
npm pkg set scripts.dev="next dev" scripts.build="next build" scripts.start="next start" scripts.typecheck="tsc --noEmit"
```

### 2. 설정 파일

#### `tsconfig.json`

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": [
      "dom",
      "dom.iterable",
      "esnext"
    ],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "react-jsx",
    "incremental": true,
    "plugins": [
      {
        "name": "next"
      }
    ],
    "paths": {
      "@/*": [
        "./src/*"
      ]
    }
  },
  "include": [
    "next-env.d.ts",
    "**/*.ts",
    "**/*.tsx",
    ".next/types/**/*.ts",
    ".next/dev/types/**/*.ts"
  ],
  "exclude": [
    "node_modules"
  ]
}
```

#### `next.config.ts`

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {};

export default nextConfig;
```

#### `postcss.config.mjs`

```js
export default {
  plugins: { "@tailwindcss/postcss": {} },
};
```

#### `.env.local.example`

```bash
# 목데이터로 화면만 볼 때 true (상태 미리보기 패널도 켜진다). 실제 API를 붙이면 false
NEXT_PUBLIC_USE_MOCKS=true
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon 또는 publishable key>
```

`cp .env.local.example .env.local`로 복사해 쓴다. 지금은 목데이터로 돌리므로 `NEXT_PUBLIC_USE_MOCKS=true`만 있어도 된다.

### 3. Make 코드 복사

Make 내보내기의 `src/components`, `src/screens`, `src/api`, `src/mocks`, `src/lib`, `src/types`, `src/dev`와 `public/assets`를 같은 경로로 복사한다. `App.tsx`, `main.tsx`, `index.css`, `vite-env.d.ts`, `vite.config.ts`, `.figma/`는 가져오지 않는다. 그다음 `Make_0-11_검토.md`의 diff를 적용한다.

### 4. 전역 CSS

Make `index.css`에서 세 가지만 바꾼다. Figma CDN(`static.figma.com`) `@font-face` 블록 16개를 지우고, `:root`의 글꼴을 `next/font` 변수로 바꾸고, `.font-medium`·`.font-semibold`·`.font-bold`가 글꼴 이름을 바꾸던 덮어쓰기를 지운다. 가변 글꼴이라 Tailwind 굵기 클래스만으로 충분하다. Make 밖에서는 Figma 글꼴 주소를 불러오지 못하는 것을 직접 확인했다.

#### `src/app/globals.css`

```css
@import "tailwindcss";

:root {
  font-family: var(--font-inter), var(--font-noto-kr), sans-serif;
  font-synthesis: none;
  background: #f7f8fa;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 320px;
}

button {
  cursor: pointer;
}

@keyframes notification-enter {
  from {
    opacity: 0;
    transform: translateX(16px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes opportunity-enter {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.notification-item {
  animation: notification-enter 360ms ease-out both;
}

.opportunity-list {
  animation: opportunity-enter 320ms ease-out both;
}

.opportunity-card {
  animation: opportunity-enter 360ms ease-out both;
}

.opportunity-card:nth-child(2) {
  animation-delay: 60ms;
}

.opportunity-card:nth-child(3) {
  animation-delay: 120ms;
}

.filter-chip:active {
  transform: scale(0.96);
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

### 5. 루트 레이아웃

#### `src/app/layout.tsx`

```tsx
import type { Metadata } from "next";
import { Inter, Noto_Sans_KR } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";

// Figma CDN 글꼴 대신 next/font로 직접 불러온다. 둘 다 가변 글꼴이라 굵기 지정이 필요 없다.
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const notoSansKr = Noto_Sans_KR({ preload: false, variable: "--font-noto-kr", display: "swap" });

export const metadata: Metadata = {
  title: "UNIPIVOT",
  description: "지원할 수 있는 장학금·정책·공모전을 찾아 준비 일정까지 만들어요",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko" className={`${inter.variable} ${notoSansKr.variable}`}>
      <body>{children}</body>
    </html>
  );
}
```

### 6. 라우트 변환과 AppFrame

`AppFrame`은 Make `App.tsx`가 하던 일을 그대로 한다. 내 정보·알림을 불러오고, 동의 전이면 `/onboarding`으로 보내고, 상태 미리보기는 목 모드에서만 띄운다. 내 정보는 `useMe()`로 페이지에 나눠 준다.

#### `src/lib/routes.ts`

```ts
"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "@/types/route";

// Make의 상태 기반 Route를 Next.js URL로 바꾼다. 화면 코드는 navigate(route)를 그대로 쓴다.
export function routeToHref(route: Route): string {
  switch (route.name) {
    case "home":
      return "/";
    case "opportunity":
      return `/opportunities/${encodeURIComponent(route.id)}${route.focus ? `?focus=${route.focus}` : ""}`;
    case "planner":
      return "/planner";
    case "academics":
      return "/academics";
    case "course":
      return `/academics/${encodeURIComponent(route.id)}${route.tab ? `?tab=${route.tab}` : ""}`;
    case "upload":
      return "/upload";
    case "settings":
      return "/settings";
    case "onboarding":
      return "/onboarding";
  }
}

// 사이드바 활성 표시용. 과목 상세는 학업 메뉴를 켠다.
export function pathnameToRoute(pathname: string): Route {
  const [, first, second] = pathname.split("/");
  if (first === "opportunities" && second) return { name: "opportunity", id: decodeURIComponent(second) };
  if (first === "academics") return { name: "academics" };
  if (first === "planner") return { name: "planner" };
  if (first === "upload") return { name: "upload" };
  if (first === "settings") return { name: "settings" };
  if (first === "onboarding") return { name: "onboarding" };
  return { name: "home" };
}

export function useAppNavigate(): (route: Route) => void {
  const router = useRouter();
  return useCallback((route: Route) => router.push(routeToHref(route)), [router]);
}
```

#### `src/components/AppFrame.tsx`

```tsx
"use client";

import { createContext, Fragment, useContext, useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  getMe,
  getNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/api/client";
import AppShell from "@/components/AppShell";
import StatusPreview from "@/dev/StatusPreview";
import { pathnameToRoute, useAppNavigate } from "@/lib/routes";
import useAsyncData from "@/lib/useAsyncData";
import type { AppNotification, Me } from "@/types/api";

// Make의 App.tsx가 하던 일: 내 정보·알림 불러오기, 동의 전이면 온보딩으로 보내기, 상태 미리보기
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
  const notificationsRequest = useAsyncData(getNotifications, [revision]);

  useEffect(() => {
    setNotificationsOverride(null);
    setUnreadOverride(null);
  }, [revision]);

  useEffect(() => {
    if (meRequest.data && !meRequest.data.consented) router.replace("/onboarding");
  }, [meRequest.data, router]);

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

### 7. 레이아웃과 페이지

페이지는 모두 `"use client"`다. 화면이 `useState`·`useEffect`를 쓰기 때문이다. 주소의 쿼리(`focus`, `tab`)를 읽는 페이지는 `useSearchParams` 때문에 `Suspense`로 감싼다.

#### `src/app/(app)/layout.tsx`

```tsx
import type { ReactNode } from "react";
import AppFrame from "@/components/AppFrame";

export default function AppLayout({ children }: { children: ReactNode }) {
  return <AppFrame>{children}</AppFrame>;
}
```

#### `src/app/(app)/page.tsx`

```tsx
"use client";

import { useAppNavigate } from "@/lib/routes";
import Home from "@/screens/Home";

export default function HomePage() {
  const navigate = useAppNavigate();
  return <Home navigate={navigate} />;
}
```

#### `src/app/(app)/opportunities/[id]/page.tsx`

```tsx
"use client";

import { Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useMe } from "@/components/AppFrame";
import { useAppNavigate } from "@/lib/routes";
import OpportunityDetail from "@/screens/OpportunityDetail";

function OpportunityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const focus = useSearchParams().get("focus") === "profile_input" ? "profile_input" : undefined;
  const navigate = useAppNavigate();
  const me = useMe();
  return (
    <OpportunityDetail
      id={id}
      focus={focus}
      calendarConnected={me?.calendar_connected ?? false}
      navigate={navigate}
    />
  );
}

export default function Page() {
  return (
    <Suspense>
      <OpportunityDetailPage />
    </Suspense>
  );
}
```

#### `src/app/(app)/planner/page.tsx`

```tsx
"use client";

import Planner from "@/screens/Planner";

export default function PlannerPage() {
  return <Planner />;
}
```

#### `src/app/(app)/academics/page.tsx`

```tsx
"use client";

import { useAppNavigate } from "@/lib/routes";
import Academics from "@/screens/Academics";

export default function AcademicsPage() {
  const navigate = useAppNavigate();
  return <Academics navigate={navigate} />;
}
```

#### `src/app/(app)/academics/[courseId]/page.tsx`

```tsx
"use client";

import { Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useAppNavigate } from "@/lib/routes";
import Course from "@/screens/Course";

const tabs = ["assignments", "materials", "announcements", "syllabus"] as const;
type CourseTab = (typeof tabs)[number];

function CoursePage() {
  const { courseId } = useParams<{ courseId: string }>();
  const tabParam = useSearchParams().get("tab");
  const tab = tabs.find((item) => item === tabParam) as CourseTab | undefined;
  const navigate = useAppNavigate();
  return <Course id={courseId} initialTab={tab} navigate={navigate} />;
}

export default function Page() {
  return (
    <Suspense>
      <CoursePage />
    </Suspense>
  );
}
```

#### `src/app/(app)/upload/page.tsx`

```tsx
"use client";

import { useAppNavigate } from "@/lib/routes";
import PosterUpload from "@/screens/PosterUpload";

export default function UploadPage() {
  const navigate = useAppNavigate();
  return <PosterUpload navigate={navigate} />;
}
```

#### `src/app/(app)/settings/page.tsx`

```tsx
"use client";

import { useAppNavigate } from "@/lib/routes";
import Settings from "@/screens/Settings";

export default function SettingsPage() {
  const navigate = useAppNavigate();
  return <Settings navigate={navigate} />;
}
```

### 8. 실행

```bash
npm run dev        # http://localhost:3000
npm run build      # 타입 검사 포함
```

## W4: 목데이터를 실제 API로 바꾸기

`src/api/client.ts`의 함수 이름과 반환 타입은 그대로 두고, 함수 안만 `apiFetch`로 바꾼다. 화면은 손대지 않는다. 비동기 작업(포스터 추출, 준비하기)은 `waitForRun`으로 실행 상태를 확인한다.

#### `src/api/http.ts`

```ts
import { createBrowserSupabase } from "@/lib/supabase/client";
import type { Run } from "@/types/api";

// W4에 목데이터를 실제 FastAPI 호출로 바꿀 때 쓰는 공통 함수 (API 명세 1·2·13장)
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details?: unknown,
  ) {
    super(message);
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { data } = await createBrowserSupabase().auth.getSession();
  const token = data.session?.access_token;
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (response.status === 401 && typeof window !== "undefined") window.location.assign("/login");
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      body?.error?.code ?? "UNKNOWN",
      body?.error?.message ?? "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.",
      response.status,
      body?.error?.details,
    );
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
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

| 목 함수 | 실제 API | 비고 |
| --- | --- | --- |
| `getMe` | `GET /me` | `consented`, `unread_notifications` 포함 |
| `getProfile` · `saveProfile` | `GET` · `PATCH /me/profile` | 저장하면 서버가 재판정 |
| `saveConsents` | `POST /me/consents` | 온보딩 동의 |
| `getSettings` · `saveSettings` | `GET` · `PATCH /me/settings` | P1 |
| `getFeed` | `GET /opportunities` | 홈 목록은 `eligibility=eligible,undetermined`, 지원 어려움 묶음을 펼칠 때 `eligibility=ineligible`, 정렬 `deadline`·`recent` |
| `getOpportunity` | `GET /opportunities/{id}` | 서버가 조회 기록을 남긴다 |
| `reportOpportunity` | `POST /opportunities/{id}/reports` | |
| `prepareOpportunity` | `POST /opportunities/{id}/prepare` → `waitForRun` | 상시 공고는 `target_date`. 캘린더 등록은 `POST /calendar/events` |
| `setDocumentDone` · `setPlannerTaskDone` | `PATCH /planner/tasks/{task_id}` | 서류 체크 = 플래너 할 일 |
| `getPlanner` · 직접 추가·수정·삭제 | `GET` · `POST` · `PATCH` · `DELETE /planner/tasks` | |
| `extractPoster` | `POST /files` → `POST /posters/extract` → `waitForRun` | |
| `registerPosterOpportunity` | `POST /posters/confirm` | 중복이면 `merged: true` |
| `getLmsConnection` · `connectLms` · `disconnectLms` | `GET` · `POST` · `DELETE /lms/connection` | |
| `getCourses` · `getCourse` | `GET /lms/courses` · `GET /lms/courses/{id}` | |
| `getLmsUpdates` | `GET /lms/updates` | |
| `getMaterial` | `GET /materials/{file_id}` | 8장 필드 이름 대조 필요 |
| `getNotifications` · 읽음 처리 | `GET /notifications` · `POST /notifications/read` | |
| `reconnectCalendar` | `/login`으로 다시 로그인 | Google 토큰은 로그인 때만 받는다 |
| `deleteAccount` | `DELETE /me` | |

## Claude Code로 옮길 때

세 md 파일을 레포 `docs/`에 넣고 이렇게 요청한다.

```text
docs/Nextjs_이식_가이드.md를 순서대로 따라 Figma Make 코드를 Next.js로 옮겨줘.
Make 코드는 ../make-export에 있어. 3단계 뒤에 docs/Make_0-11_검토.md의 diff를 적용하고,
docs/온보딩_구현.md의 파일을 추가해줘. 마지막에 npm run build가 통과하는지 확인해줘.
화면 컴포넌트(src/screens, src/components)는 diff 말고는 고치지 마.
```

## 확인한 것

샌드박스에서 목 모드로 빌드해 브라우저로 눌러 본 결과다(19개 모두 통과).

| 점검 | 결과 |
| --- | --- |
| `next build` 11개 라우트, `tsc --noEmit` | 통과 |
| 홈 렌더, 문서함 메뉴 숨김 | 통과 |
| 원문 확인 필요 공고의 "원문 보기" → 새 탭 | 통과 |
| `other` 조건에 "원문 확인" 표시 | 통과 |
| 10/6 마감 공고 준비 → 할 일이 10/5·10/5·10/5·10/6 | 통과 |
| 준비한 공고의 마감 표시가 플래너에 추가 | 통과(앱 안 이동 기준) |
| 플래너 12월 다음 달 → 2027년 1월 | 통과 |
| 상시 공고는 목표일을 골라야 준비 버튼이 켜짐 | 통과 |
| 새 과제 알림 → `/academics/analysis?tab=assignments` | 통과 |
| 설정 프로필 폼 16개 항목 | 통과 |
| 첫 접속 → `/onboarding`, 동의 → 프로필 1/4 → … → 홈 | 통과 |
| 평점이 만점보다 크면 오류, 소득 단계에 민감 정보 안내 | 통과 |
| 로그인 화면, 모바일 설정 메뉴, 페이지 오류 없음 | 통과 |

샌드박스는 Google Fonts에 접근할 수 없어 글꼴 응답만 가짜로 바꿔 빌드했다. 실제 환경에서는 `npm run build`가 글꼴을 내려받는다.
