# Figma Make 0–11번 결과 검토

> 📝 대상: Figma Make "Upload_Poster_Feature" 내보내기(프롬프트 0–11 반영) · 기준: PRD v0.8, API 명세 v0.3 · 검토일 2026-10-06
>
> 함께 보는 파일: `Nextjs_이식_가이드.md` · `온보딩_구현.md`

프롬프트 0–11의 구조와 화면은 명세대로 나왔다. 버그 7건과 자잘한 문제 5건을 고쳤고, 명세에 빈 곳 5군데를 찾아 API v0.3 보완안으로 정리했다. 수정본은 Make 프로젝트 기준 `tsc`·`vite build`, Next.js 이식본 기준 `next build`와 브라우저 점검 19개 항목을 모두 통과했다.

## 점검 결과

| 항목 | 결과 |
| --- | --- |
| `src/types/api.ts` | 명세 v0.3과 동일(끝 줄바꿈만 다름) |
| `AGENTS.md` | 전달한 파일 그대로 적용 |
| 구조 | screens·components·mocks·api·lib·dev로 분리, `App.tsx` 93줄, 모든 파일 300줄 이하 |
| 빌드 | `vite build` 통과, `tsc`는 `format.ts`의 `replaceAll` 1건 실패(ES2020 lib) |
| 상태 미리보기 | 기본·첫 접속·LMS 미연결·LMS 오류·캘린더 만료·빈 피드·포스터 실패·중복·한도 9개 동작 |
| `TODO(api)` 주석 | 7곳. 그중 2곳이 실제 명세 빈 곳(상세 `summary`, 과목 `html_url`) |

## 고친 문제

| # | 증상 | 원인 | 수정 |
| --- | --- | --- | --- |
| 1 | 원문 확인 필요 공고에서 상태 카드의 "원문 보기"를 눌러도 아무 일이 없다 | `openOriginal`이 포스터만 처리 | 포스터가 아니면 원문 링크를 새 탭으로 연다. 원문 링크가 없으면 헤더 버튼을 숨긴다 |
| 2 | 10/6 마감 공고를 준비하면 서류 할 일이 10/1~10/3(지난 날짜)으로 생긴다 | 마감에서 5·4·3일을 고정으로 빼고 `lead_days`를 무시 | 서류마다 "마감 2일 전 − 발급 소요일", 오늘보다 앞서면 오늘로 당긴다 |
| 3 | 준비한 공고의 마감이 플래너에 표시되지 않는다 | 준비할 때 `markers`를 추가하지 않음 | 준비하면 마감 표시를 넣고 피드의 `prepared`도 켠다 |
| 4 | 알림에서 과목으로 가는 이동이 실제 API를 붙이면 깨진다 | 목데이터가 `link.id`에 과목 ID를 넣는 꼼수 | `link.course_id`를 추가해 과목 이동에 쓴다. 없으면 학업 화면으로 보낸다 |
| 5 | 760px 이하 화면에서 설정에 들어갈 방법이 없다(LMS 해제·탈퇴 불가) | 사이드바 하단 설정 버튼이 모바일에서 숨음 | 모바일 가로 메뉴에 설정을 넣는다. 동작 없는 문서함 메뉴는 P1 전까지 숨긴다 |
| 6 | 플래너에서 12월 다음 달이 2026년 1월로 나온다 | 연도 2026 하드코딩 | 연·월을 상태로 두고 `Date.UTC`로 칸을 만든다 |
| 7 | 신고 사유·내용이 어디에도 전달되지 않는다 | `ReportModal`이 값을 넘기지 않음 | `reason`(ERD enum)·`detail`을 넘기고 `reportOpportunity` 목업을 추가 |
| 8 | 자잘한 것 | — | 마감 임박 집계·필터에서 지원 어려움 제외, "마지막 동기화: 방금 전" 고정 문구를 실제 시각으로, `other` 조건은 "미입력" 대신 "원문 확인", 최신순 파라미터 `latest` → API 이름 `recent`, `replaceAll` → `replace(/-/g, …)` |

설정 화면 프로필 폼에서 빠져 있던 5개 항목(누적 취득학점, 누적 평점, 평점 만점, 병역 복무 개월, 기준 중위소득 %)은 `온보딩_구현.md`에서 항목 정의를 공용으로 바꾸며 함께 고쳤다.

## 명세 보완 — API v0.3에 더할 것

| 위치 | 추가 | 이유 |
| --- | --- | --- |
| `GET /opportunities/{id}` | `eligibility.summary` | 상태 카드의 사유 한 줄. 지금은 `easy_summary`로 대신하고 있었다 |
| `GET /lms/courses/{id}` | `course.html_url` | "LMS에서 열기" 링크. 지금은 첫 과제 링크로 대신하고 있었다 |
| `GET /notifications` | `link.course_id`(lms_* 링크) | `link.id`는 과제·자료·공지 ID라서 과목 탭으로 이동할 수 없다 |
| `POST /opportunities/{id}/prepare` | `target_date`(`deadline_at`이 null이면 필수) | 상시 공고는 마감일이 없는데 `planner_tasks.due_date`는 NOT NULL이다. 화면에서 목표일을 받는다 |
| `build_prep_plan` 규칙 | 서류 할 일 = 마감 2일 전 − `lead_days`, 오늘보다 앞서면 오늘 | 촉박한 공고에서 지난 날짜가 생기지 않게 한다 |

강의자료 응답(8장)의 필드 이름 대조는 `TODO(api)`로 그대로 남아 있다.

## 수정 코드

아래 diff는 Next.js 이식본에 이미 들어가 있다. Make 코드 보기에서 직접 고칠 때도 같은 내용을 쓰면 되고, Claude Code에는 "Make_0-11_검토.md의 diff를 적용해줘"로 넘기면 된다.

### 1·7. 원문 보기, 재판정 문구, 신고 전달 — `src/screens/OpportunityDetail.tsx`

```diff
--- a/src/screens/OpportunityDetail.tsx
+++ b/src/screens/OpportunityDetail.tsx
@@ -1,4 +1,4 @@
 import { useEffect, useState } from "react";
-import { getOpportunity, setDocumentDone } from "@/api/client";
+import { getOpportunity, reportOpportunity, setDocumentDone } from "@/api/client";
 import AiProcessPanel from "@/components/AiProcessPanel";
 import Header from "@/components/Header";
@@ -77,5 +77,11 @@
   const detail = override ?? request.data;
   const isPoster = detail.source_type === "poster";
-  const openOriginal = () => isPoster && detail.poster_url && setPosterOpen(true);
+  const openOriginal = () => {
+    if (isPoster) {
+      if (detail.poster_url) setPosterOpen(true);
+      return;
+    }
+    if (detail.original_url) window.open(detail.original_url, "_blank", "noopener,noreferrer");
+  };
   const showToast = (message: string) => {
     setToast(message);
@@ -93,4 +99,5 @@
           status: "eligible",
           display_status: "eligible",
+          summary: "입력한 정보로 다시 판정했어요. 모든 조건을 충족해요.",
           reason_text: null,
           missing_fields: [],
@@ -114,9 +121,8 @@
   };
 
-  const originalAction = isPoster ? (
-    <button type="button" onClick={openOriginal} className="text-[13px] font-semibold text-[#4f6ef7]">원문 보기</button>
-  ) : (
-    <a href={detail.original_url ?? undefined} target="_blank" rel="noreferrer" className="text-[13px] font-semibold text-[#4f6ef7]">원문 보기</a>
-  );
+  const originalAction =
+    isPoster || detail.original_url ? (
+      <button type="button" onClick={openOriginal} className="text-[13px] font-semibold text-[#4f6ef7]">원문 보기</button>
+    ) : null;
 
   return (
@@ -208,5 +214,6 @@
         open={reportOpen}
         onClose={() => setReportOpen(false)}
-        onSubmit={() => {
+        onSubmit={async (reason, detailText) => {
+          await reportOpportunity(detail.id, reason, detailText);
           setReported(true);
           setReportOpen(false);
```

### 7. 신고 사유·내용 넘기기 — `src/components/ReportModal.tsx`

```diff
--- a/src/components/ReportModal.tsx
+++ b/src/components/ReportModal.tsx
@@ -2,15 +2,22 @@
 import Button from "@/components/Button";
 import Modal from "@/components/Modal";
+import type { ReportReason } from "@/types/api";
 
 interface ReportModalProps {
   open: boolean;
   onClose: () => void;
-  onSubmit: () => void;
+  onSubmit: (reason: ReportReason, detail: string) => void;
 }
 
-const reasons = ["잘못된 정보", "중복", "마감됨", "부적절"] as const;
+const reasons: { value: ReportReason; label: string }[] = [
+  { value: "wrong_info", label: "잘못된 정보" },
+  { value: "duplicate", label: "중복" },
+  { value: "expired", label: "마감됨" },
+  { value: "inappropriate", label: "부적절" },
+];
 
 export default function ReportModal({ open, onClose, onSubmit }: ReportModalProps) {
-  const [reason, setReason] = useState<(typeof reasons)[number]>("잘못된 정보");
+  const [reason, setReason] = useState<ReportReason>("wrong_info");
+  const [detail, setDetail] = useState("");
 
   return (
@@ -19,14 +26,14 @@
         {reasons.map((item) => (
           <button
-            key={item}
+            key={item.value}
             type="button"
-            onClick={() => setReason(item)}
+            onClick={() => setReason(item.value)}
             className={`rounded-[10px] border px-3 py-3 text-[13px] font-semibold ${
-              reason === item
+              reason === item.value
                 ? "border-[#4f6ef7] bg-[#eef2ff] text-[#4f6ef7]"
                 : "border-[#e5e7eb] text-[#667085]"
             }`}
           >
-            {item}
+            {item.label}
           </button>
         ))}
@@ -35,4 +42,6 @@
         <span className="mb-2 block text-[13px] font-semibold">상세 내용</span>
         <textarea
+          value={detail}
+          onChange={(event) => setDetail(event.target.value)}
           className="min-h-28 w-full resize-none rounded-[10px] border border-[#e5e7eb] p-3 text-[14px] outline-none focus:border-[#4f6ef7]"
           placeholder="확인이 필요한 내용을 적어 주세요."
@@ -41,5 +50,5 @@
       <div className="mt-6 flex justify-end gap-2">
         <Button secondary onClick={onClose}>취소</Button>
-        <Button onClick={onSubmit}>신고하기</Button>
+        <Button onClick={() => onSubmit(reason, detail.trim())}>신고하기</Button>
       </div>
     </Modal>
```

### 2·3. 역산 날짜, 마감 표시, 상시 공고 목표일 — `src/mocks/store.ts`

```diff
--- a/src/mocks/store.ts
+++ b/src/mocks/store.ts
@@ -2,4 +2,5 @@
 import { opportunities } from "@/mocks/opportunities";
 import { planner } from "@/mocks/planner";
+import { mockToday } from "@/mocks/account";
 import type {
   Condition,
@@ -25,4 +26,9 @@
 }
 
+// 역산한 날짜가 오늘보다 앞서면 오늘로 당긴다 (API v0.3 보완 규칙)
+function clampToToday(date: string): string {
+  return date < mockToday ? mockToday : date;
+}
+
 function tasksForOpportunity(opportunityId: string): PlannerTask[] {
   return plannerState.items.filter(
@@ -42,13 +48,15 @@
   id: string,
   includeCalendar: boolean,
+  targetDate?: string,
 ): PrepareResult {
   const detail = detailsState[id];
   if (!detail) throw new Error("공고를 찾을 수 없어요.");
 
-  const deadline = detail.deadline_at?.slice(0, 10) ?? "2026-10-30";
+  // 상시 공고는 사용자가 고른 목표일을 마감일처럼 쓴다
+  const deadline = detail.deadline_at?.slice(0, 10) ?? targetDate ?? mockToday;
   const prepPlanId = detail.prep.prep_plan_id ?? `prep-${id}`;
 
   if (!detail.prep.prepared) {
-    const documentTasks: PlannerTask[] = detail.documents.map((document, index) => {
+    const documentTasks: PlannerTask[] = detail.documents.map((document) => {
       const taskId = `task-${id}-${document.id}`;
       document.task_id = taskId;
@@ -57,5 +65,6 @@
         id: taskId,
         title: `${document.name} 준비`,
-        due_date: subtractDays(deadline, 5 - index),
+        // 제출 2일 전까지 서류를 갖추도록 발급 소요일만큼 앞당긴다
+        due_date: clampToToday(subtractDays(deadline, 2 + (document.lead_days ?? 0))),
         is_done: false,
         source: "prep_plan",
@@ -82,4 +91,15 @@
     };
     plannerState.items.push(...documentTasks, submitTask);
+    if (detail.deadline_at && !plannerState.markers.some((marker) => marker.opportunity_id === id)) {
+      plannerState.markers.push({
+        kind: "deadline",
+        date: deadline,
+        title: `${detail.title} 마감`,
+        opportunity_id: id,
+        category: detail.category,
+      });
+    }
+    const feedItem = opportunities.find((item) => item.id === id);
+    if (feedItem) feedItem.prepared = true;
   }
 
@@ -195,4 +215,5 @@
       status: "eligible",
       display_status: "eligible",
+      summary: "현재 입력한 조건을 충족해요.",
       reason_text: null,
       missing_fields: [],
```

### 상태 카드 사유(`summary`), 상시 공고 목표일 입력 — `src/components/OpportunityPreparation.tsx`

```diff
--- a/src/components/OpportunityPreparation.tsx
+++ b/src/components/OpportunityPreparation.tsx
@@ -54,4 +54,5 @@
   const [finishing, setFinishing] = useState(false);
   const [completed, setCompleted] = useState(false);
+  const [targetDate, setTargetDate] = useState(""); // 상시 공고의 준비 목표일
   const ineligible = detail.eligibility.display_status === "ineligible";
   const deadlineSoon = isDeadlineSoon(detail.deadline_at, MOCK_TODAY);
@@ -59,6 +60,5 @@
     detail.deadline_at ? formatKstDate(detail.deadline_at) : "상시"
   }`;
-  // TODO(api): OpportunityDetail eligibility에 summary가 추가되면 easy_summary를 대체한다.
-  const reason = ineligible ? detail.eligibility.reason_text : detail.easy_summary;
+  const reason = ineligible ? detail.eligibility.reason_text : detail.eligibility.summary;
 
   const startPreparation = async () => {
@@ -70,5 +70,5 @@
     setSteps(["done", "running"]);
     const [prepared] = await Promise.all([
-      prepareOpportunity(detail.id, false),
+      prepareOpportunity(detail.id, false, targetDate || undefined),
       wait(600),
     ]);
@@ -82,5 +82,5 @@
     setFinishing(true);
     if (includeCalendar && calendarConnected) {
-      await prepareOpportunity(detail.id, true);
+      await prepareOpportunity(detail.id, true, targetDate || undefined);
     }
     const updated = await getOpportunity(detail.id);
@@ -114,4 +114,21 @@
     }
     if (detail.eligibility.display_status === "eligible") {
+      if (!detail.deadline_at) {
+        return (
+          <div className="flex items-end gap-2">
+            <label className="text-[12px] font-semibold text-[#667085]">
+              목표일
+              <input
+                type="date"
+                value={targetDate}
+                min={MOCK_TODAY}
+                onChange={(event) => setTargetDate(event.target.value)}
+                className="mt-1 block h-[42px] rounded-[10px] border border-[#e5e7eb] px-3 text-[14px] text-[#181a20]"
+              />
+            </label>
+            <Button onClick={startPreparation} disabled={!targetDate}>준비 일정 만들기</Button>
+          </div>
+        );
+      }
       return <Button onClick={startPreparation}>준비 일정 만들기</Button>;
     }
```

### 4. 알림 → 과목 이동 — `src/components/Header.tsx`

```diff
--- a/src/components/Header.tsx
+++ b/src/components/Header.tsx
@@ -21,11 +21,14 @@
   }
   if (notification.link.type === "planner_task") return { name: "planner" };
+  // lms_* 알림의 link.id는 과제·자료·공지 ID라서 과목 이동에는 course_id를 쓴다
+  const courseId = notification.link.course_id;
+  if (!courseId) return { name: "academics" };
   if (notification.link.type === "lms_module_item") {
-    return { name: "course", id: notification.link.id, tab: "materials" };
+    return { name: "course", id: courseId, tab: "materials" };
   }
   if (notification.link.type === "lms_announcement") {
-    return { name: "course", id: notification.link.id, tab: "announcements" };
+    return { name: "course", id: courseId, tab: "announcements" };
   }
-  return { name: "course", id: notification.link.id, tab: "assignments" };
+  return { name: "course", id: courseId, tab: "assignments" };
 }
```

### 4. 알림 목데이터에 `course_id` — `src/mocks/notifications.ts`

```diff
--- a/src/mocks/notifications.ts
+++ b/src/mocks/notifications.ts
@@ -3,8 +3,8 @@
 export const notifications: AppNotification[] = [
   { id: "notification-1", type: "deadline_soon", title: "창업 캠프 마감이 가까워요", body: "ERICA 창업 아이디어 캠프 마감까지 3일 남았어요.", scheduled_at: "2026-10-05T09:00:00+09:00", read_at: null, link: { type: "opportunity", id: "erica-startup-camp" } },
-  { id: "notification-2", type: "new_assignment", title: "새 과제가 등록됐어요", body: "해석학 Homework 4를 확인하세요.", scheduled_at: "2026-10-05T08:40:00+09:00", read_at: null, link: { type: "lms_assignment", id: "analysis" } },
+  { id: "notification-2", type: "new_assignment", title: "새 과제가 등록됐어요", body: "해석학 Homework 4를 확인하세요.", scheduled_at: "2026-10-05T08:40:00+09:00", read_at: null, link: { type: "lms_assignment", id: "analysis-a1", course_id: "analysis" } },
   { id: "notification-3", type: "profile_needed", title: "프로필 정보가 필요해요", body: "거주지를 입력하면 청년정책 지원 가능 여부를 판정할 수 있어요.", scheduled_at: "2026-10-05T08:10:00+09:00", read_at: null, link: { type: "opportunity", id: "youth-capability", focus: "profile_input" } },
-  { id: "notification-4", type: "new_material", title: "새 강의자료가 등록됐어요", body: "선형대수 8주차 강의자료를 확인하세요.", scheduled_at: "2026-10-04T17:00:00+09:00", read_at: "2026-10-04T18:00:00+09:00", link: { type: "lms_module_item", id: "linear-algebra" } },
-  { id: "notification-5", type: "schedule_change", title: "강의실이 변경됐어요", body: "데이터베이스 수업은 제2공학관 301호에서 진행해요.", scheduled_at: "2026-10-04T14:00:00+09:00", read_at: "2026-10-04T15:00:00+09:00", link: { type: "lms_announcement", id: "database" } },
+  { id: "notification-4", type: "new_material", title: "새 강의자료가 등록됐어요", body: "선형대수 8주차 강의자료를 확인하세요.", scheduled_at: "2026-10-04T17:00:00+09:00", read_at: "2026-10-04T18:00:00+09:00", link: { type: "lms_module_item", id: "linear-algebra-m4", course_id: "linear-algebra" } },
+  { id: "notification-5", type: "schedule_change", title: "강의실이 변경됐어요", body: "데이터베이스 수업은 제2공학관 301호에서 진행해요.", scheduled_at: "2026-10-04T14:00:00+09:00", read_at: "2026-10-04T15:00:00+09:00", link: { type: "lms_announcement", id: "database-n1", course_id: "database" } },
   { id: "notification-6", type: "task_due", title: "오늘 할 일이 있어요", body: "재학증명서 발급과 캡스톤 과제 제출을 확인하세요.", scheduled_at: "2026-10-04T09:00:00+09:00", read_at: "2026-10-04T10:00:00+09:00", link: { type: "planner_task", id: "task-student-cert" } },
 ];
```

### 5. 모바일 설정 메뉴, 문서함 숨김 — `src/components/Sidebar.tsx`

```diff
--- a/src/components/Sidebar.tsx
+++ b/src/components/Sidebar.tsx
@@ -38,10 +38,5 @@
           </button>
         ))}
-        <button
-          type="button"
-          className="flex items-center gap-[10px] whitespace-nowrap rounded-[10px] px-3 py-[10px] text-[14px] font-medium text-[#667085] hover:bg-[#f7f8fa]"
-        >
-          <span className="text-[15px]">▤</span>문서함
-        </button>
+        {/* 문서함은 P1이라 구현 전까지 메뉴를 숨긴다 */}
         <button
           type="button"
@@ -54,4 +49,16 @@
         >
           <span className="text-[15px]">＋</span>포스터 등록
+        </button>
+        {/* 760px 이하에서는 아래 설정 버튼이 숨으므로 가로 메뉴에 설정을 넣는다 */}
+        <button
+          type="button"
+          onClick={() => navigate({ name: "settings" })}
+          className={`hidden items-center gap-[10px] whitespace-nowrap rounded-[10px] px-3 py-[10px] text-[14px] max-[760px]:flex ${
+            route.name === "settings"
+              ? "bg-[#eef2ff] font-semibold text-[#4f6ef7]"
+              : "font-medium text-[#667085] hover:bg-[#f7f8fa]"
+          }`}
+        >
+          <span className="text-[15px]">⚙</span>설정
         </button>
       </nav>
```

### 6. 플래너 연·월 상태 — `src/screens/Planner.tsx`

```diff
--- a/src/screens/Planner.tsx
+++ b/src/screens/Planner.tsx
@@ -17,10 +17,8 @@
 import type { PlannerResponse, PlannerTask } from "@/types/api";
 
-function monthRange(month: number) {
-  const lastDay = new Date(Date.UTC(2026, month, 0)).getUTCDate();
-  return {
-    from: `2026-${String(month).padStart(2, "0")}-01`,
-    to: `2026-${String(month).padStart(2, "0")}-${lastDay}`,
-  };
+function monthRange(year: number, month: number) {
+  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
+  const prefix = `${year}-${String(month).padStart(2, "0")}`;
+  return { from: `${prefix}-01`, to: `${prefix}-${String(lastDay).padStart(2, "0")}` };
 }
 
@@ -38,10 +36,13 @@
 
 export default function Planner() {
-  const [month, setMonth] = useState(10);
+  const [view, setView] = useState({
+    year: Number(MOCK_TODAY.slice(0, 4)),
+    month: Number(MOCK_TODAY.slice(5, 7)),
+  });
   const [selectedDate, setSelectedDate] = useState(MOCK_TODAY);
   const [plannerOverride, setPlannerOverride] =
     useState<PlannerResponse | null>(null);
   const [calendarOverride, setCalendarOverride] = useState<boolean | null>(null);
-  const range = monthRange(month);
+  const range = monthRange(view.year, view.month);
   const request = useAsyncData(
     () => Promise.all([getPlanner(range.from, range.to), getMe()]),
@@ -89,9 +90,10 @@
       <section className="grid grid-cols-[1.77fr_1fr] gap-5 max-[1000px]:grid-cols-1">
         <PlannerCalendar
-          month={month}
+          year={view.year}
+          month={view.month}
           planner={planner}
           selectedDate={selectedDate}
           onSelectDate={setSelectedDate}
-          onMonthChange={setMonth}
+          onMonthChange={(year, month) => setView({ year, month })}
         />
         <PlannerDayPanel
```

### 6. 연도를 넘는 달력 칸 — `src/components/PlannerCalendar.tsx`

```diff
--- a/src/components/PlannerCalendar.tsx
+++ b/src/components/PlannerCalendar.tsx
@@ -3,42 +3,23 @@
 
 interface PlannerCalendarProps {
+  year: number;
   month: number;
   planner: PlannerResponse;
   selectedDate: string;
   onSelectDate: (date: string) => void;
-  onMonthChange: (month: number) => void;
+  onMonthChange: (year: number, month: number) => void;
 }
 
-function calendarCells(month: number) {
-  const firstWeekday = new Date(Date.UTC(2026, month - 1, 1)).getUTCDay();
-  const daysInMonth = new Date(Date.UTC(2026, month, 0)).getUTCDate();
-  const daysInPrevious = new Date(Date.UTC(2026, month - 1, 0)).getUTCDate();
+const pad = (value: number) => String(value).padStart(2, "0");
 
+// 연도가 바뀌어도 맞도록 Date.UTC로 6주(42칸)를 만든다
+function calendarCells(year: number, month: number) {
+  const firstWeekday = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
   return Array.from({ length: 42 }, (_, index) => {
-    const relativeDay = index - firstWeekday + 1;
-    if (relativeDay < 1) {
-      const previousMonth = month === 1 ? 12 : month - 1;
-      const year = month === 1 ? 2025 : 2026;
-      const day = daysInPrevious + relativeDay;
-      return {
-        day,
-        date: `${year}-${String(previousMonth).padStart(2, "0")}-${String(day).padStart(2, "0")}`,
-        dim: true,
-      };
-    }
-    if (relativeDay > daysInMonth) {
-      const nextMonth = month === 12 ? 1 : month + 1;
-      const year = month === 12 ? 2027 : 2026;
-      const day = relativeDay - daysInMonth;
-      return {
-        day,
-        date: `${year}-${String(nextMonth).padStart(2, "0")}-${String(day).padStart(2, "0")}`,
-        dim: true,
-      };
-    }
+    const date = new Date(Date.UTC(year, month - 1, 1 + index - firstWeekday));
     return {
-      day: relativeDay,
-      date: `2026-${String(month).padStart(2, "0")}-${String(relativeDay).padStart(2, "0")}`,
-      dim: false,
+      day: date.getUTCDate(),
+      date: `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`,
+      dim: date.getUTCMonth() !== month - 1,
     };
   });
@@ -46,4 +27,5 @@
 
 export default function PlannerCalendar({
+  year,
   month,
   planner,
@@ -52,9 +34,11 @@
   onMonthChange,
 }: PlannerCalendarProps) {
-  const cells = calendarCells(month);
-  const changeMonth = (nextMonth: number) => {
-    const normalized = nextMonth === 0 ? 12 : nextMonth === 13 ? 1 : nextMonth;
-    onMonthChange(normalized);
-    onSelectDate(`2026-${String(normalized).padStart(2, "0")}-01`);
+  const cells = calendarCells(year, month);
+  const changeMonth = (delta: number) => {
+    const next = new Date(Date.UTC(year, month - 1 + delta, 1));
+    const nextYear = next.getUTCFullYear();
+    const nextMonth = next.getUTCMonth() + 1;
+    onMonthChange(nextYear, nextMonth);
+    onSelectDate(`${nextYear}-${pad(nextMonth)}-01`);
   };
 
@@ -62,8 +46,8 @@
     <div className="min-h-[650px] rounded-2xl border border-[#e5e7eb] bg-white p-[22px]">
       <div className="flex items-center justify-between">
-        <h2 className="text-[22px] font-bold">2026년 {month}월</h2>
+        <h2 className="text-[22px] font-bold">{year}년 {month}월</h2>
         <div className="flex gap-2">
-          <button type="button" onClick={() => changeMonth(month - 1)} className="size-9 rounded-[10px] bg-[#f7f8fa] text-[22px] font-semibold text-[#667085]">‹</button>
-          <button type="button" onClick={() => changeMonth(month + 1)} className="size-9 rounded-[10px] bg-[#f7f8fa] text-[22px] font-semibold text-[#667085]">›</button>
+          <button type="button" aria-label="이전 달" onClick={() => changeMonth(-1)} className="size-9 rounded-[10px] bg-[#f7f8fa] text-[22px] font-semibold text-[#667085]">‹</button>
+          <button type="button" aria-label="다음 달" onClick={() => changeMonth(1)} className="size-9 rounded-[10px] bg-[#f7f8fa] text-[22px] font-semibold text-[#667085]">›</button>
         </div>
       </div>
```

### 8. 집계·정렬, 준비 목표일, 신고 목업 — `src/api/client.ts`

```diff
--- a/src/api/client.ts
+++ b/src/api/client.ts
@@ -48,4 +48,5 @@
   PrepareResult,
   Profile,
+  ReportReason,
   Settings,
 } from "@/types/api";
@@ -54,5 +55,5 @@
   eligibility?: DisplayStatus | "all";
   category?: Category | "all";
-  sort?: "deadline" | "latest";
+  sort?: "deadline" | "recent";
 }
 
@@ -100,5 +101,5 @@
     needs_review: items.filter((item) => item.eligibility.display_status === "needs_review").length,
     ineligible: items.filter((item) => item.eligibility.status === "ineligible").length,
-    deadline_soon: items.filter((item) => item.d_day !== null && item.d_day >= 0 && item.d_day <= 3).length,
+    deadline_soon: items.filter((item) => item.eligibility.status !== "ineligible" && item.d_day !== null && item.d_day >= 0 && item.d_day <= 3).length,
   };
 }
@@ -143,8 +144,8 @@
 
   items.sort((a, b) => {
-    if (params.sort !== "latest") {
+    if (params.sort !== "recent") {
       return (a.d_day ?? Number.MAX_SAFE_INTEGER) - (b.d_day ?? Number.MAX_SAFE_INTEGER);
     }
-    // TODO(api): 최신순 정렬용 created_at이 추가되면 is_new 대신 해당 필드를 사용한다.
+    // 실제 API는 sort=recent를 받아 서버가 등록순으로 정렬한다. 목업은 새 공고를 앞으로만 보낸다.
     return Number(b.is_new) - Number(a.is_new);
   });
@@ -188,6 +189,7 @@
   id: string,
   includeCalendar: boolean,
+  targetDate?: string,
 ): Promise<PrepareResult> {
-  return respond(prepareStoredOpportunity(id, includeCalendar));
+  return respond(prepareStoredOpportunity(id, includeCalendar, targetDate));
 }
 
@@ -199,4 +201,13 @@
 ): Promise<OpportunityDetail> {
   return respond(setStoredDocumentDone(opportunityId, documentId, isDone));
+}
+
+// TODO(api): POST /opportunities/{id}/reports { reason, detail } — 서로 다른 3명째 신고에서 hidden: true
+export function reportOpportunity(
+  _id: string,
+  _reason: ReportReason,
+  _detail: string,
+): Promise<{ reported: boolean; hidden: boolean }> {
+  return respond({ reported: true, hidden: false });
 }
```

### 8. 마감 임박 필터, 최신순 값 — `src/screens/Home.tsx`

```diff
--- a/src/screens/Home.tsx
+++ b/src/screens/Home.tsx
@@ -128,5 +128,5 @@
     if (summaryFilter === "undetermined") return item.eligibility.status === "undetermined";
     if (summaryFilter === "deadline_soon") {
-      return item.d_day !== null && item.d_day >= 0 && item.d_day <= 3;
+      return item.eligibility.status !== "ineligible" && item.d_day !== null && item.d_day >= 0 && item.d_day <= 3;
     }
     return true;
@@ -200,5 +200,5 @@
           >
             <option value="deadline">마감 임박순</option>
-            <option value="latest">최신순</option>
+            <option value="recent">최신순</option>
           </select>
         </div>
```

### 명세 보완 필드 — `src/types/api.ts`

```diff
--- a/src/types/api.ts
+++ b/src/types/api.ts
@@ -10,4 +10,5 @@
   | "new_eligible" | "new_assignment" | "new_material" | "schedule_change"
   | "task_due" | "deadline_soon" | "profile_needed";
+export type ReportReason = "wrong_info" | "duplicate" | "expired" | "inappropriate";
 
 // GET /me
@@ -126,4 +127,5 @@
     status: EligibilityStatus;
     display_status: DisplayStatus;
+    summary: string;                     // 상태 사유 한 줄 (API v0.3 보완)
     reason_text: string | null;          // 탈락 사유
     missing_fields: string[];
@@ -219,5 +221,5 @@
 export type AnnouncementCategory = "schedule_change" | "material" | "opportunity" | "general";
 export interface CourseDetail {
-  course: { id: string; short_name: string; has_syllabus: boolean; portal_syllabus_url: string };
+  course: { id: string; short_name: string; html_url: string; has_syllabus: boolean; portal_syllabus_url: string }; // html_url: 과목 홈 (API v0.3 보완)
   assignments: { id: string; title: string; due_at: string | null; submission_state: SubmissionState; html_url: string }[];
   module_items: { id: string; module_name: string; title: string; html_url: string; is_new: boolean; uploaded_file_id: string | null }[];
@@ -266,4 +268,5 @@
     type: "opportunity" | "planner_task" | "lms_assignment" | "lms_module_item" | "lms_announcement";
     id: string;
+    course_id?: string;                  // lms_* 링크의 과목 ID (API v0.3 보완)
     focus?: "profile_input";
   };
```

### `other` 조건, 상세 `summary` — `src/mocks/opportunityDetails.ts`

```diff
--- a/src/mocks/opportunityDetails.ts
+++ b/src/mocks/opportunityDetails.ts
@@ -18,5 +18,5 @@
   { requirement_id: "req-credit", field: "credits_last_semester", label: "직전학기 취득학점", operator: "gte", value: 12, user_value: 18, condition_text: "직전학기 12학점 이상", user_value_text: "18학점", outcome: "pass", evidence_text: "직전학기 12학점 이상 이수한 학생을 대상으로 합니다.", is_ambiguous: false },
   { requirement_id: "req-gpa", field: "gpa_last_semester", label: "직전학기 평점", operator: "gte", value: 4, user_value: 3.8, condition_text: "직전학기 평점 4.0 이상", user_value_text: "3.80", outcome: "fail", evidence_text: "직전학기 평점은 4.0 이상이어야 합니다.", is_ambiguous: false },
-  { requirement_id: "req-team", field: "team_size", label: "팀 구성", operator: "gte", value: 3, user_value: null, condition_text: "3인 이상 팀 구성", user_value_text: null, outcome: "unknown", evidence_text: "개인 또는 3인 이상 팀으로 참가할 수 있습니다.", is_ambiguous: true },
+  { requirement_id: "req-team", field: "other", label: "팀 구성", operator: "gte", value: 3, user_value: null, condition_text: "3인 이상 팀 구성", user_value_text: null, outcome: "unknown", evidence_text: "개인 또는 3인 이상 팀으로 참가할 수 있습니다.", is_ambiguous: true },
 ];
 
@@ -81,4 +81,5 @@
       status: item.eligibility.status,
       display_status: item.eligibility.display_status,
+      summary: item.eligibility.summary,
       reason_text: item.eligibility.display_status === "ineligible" ? item.eligibility.summary : null,
       missing_fields: item.eligibility.missing_fields,
```

### 과목 `html_url` — `src/mocks/lms.ts`

```diff
--- a/src/mocks/lms.ts
+++ b/src/mocks/lms.ts
@@ -27,4 +27,5 @@
       id: course.id,
       short_name: course.short_name,
+      html_url: `https://lms.example.edu/courses/${course.canvas_course_id}`,
       has_syllabus: course.has_syllabus,
       portal_syllabus_url: course.portal_syllabus_url,
```

### LMS에서 열기 링크 — `src/screens/Course.tsx`

```diff
--- a/src/screens/Course.tsx
+++ b/src/screens/Course.tsx
@@ -58,8 +58,5 @@
 
   const course = request.data;
-  // TODO(api): CourseDetail에 과목 홈 html_url이 추가되면 첫 과제 링크 대체를 제거한다.
-  const lmsUrl =
-    course.assignments[0]?.html_url ??
-    course.course.portal_syllabus_url;
+  const lmsUrl = course.course.html_url;
 
   return (
```

### 마지막 동기화 시각 — `src/screens/Academics.tsx`

```diff
--- a/src/screens/Academics.tsx
+++ b/src/screens/Academics.tsx
@@ -4,4 +4,5 @@
   getLmsConnection,
   getLmsUpdates,
+  MOCK_NOW,
   MOCK_TODAY,
 } from "@/api/client";
@@ -11,5 +12,5 @@
 import LmsConnectModal from "@/components/LmsConnectModal";
 import Skeleton from "@/components/Skeleton";
-import { formatDday, isDeadlineSoon } from "@/lib/format";
+import { formatDday, formatRelativeTime, isDeadlineSoon } from "@/lib/format";
 import useAsyncData from "@/lib/useAsyncData";
 import type { LmsConnection, LmsUpdate } from "@/types/api";
@@ -143,5 +144,5 @@
           <Badge tone="green">LearningX 연결됨</Badge>
           <p className="text-[13px] font-medium text-[#344054]">
-            마지막 동기화: 방금 전 · 토큰 끝 4자리 {connection.token_last4}
+            마지막 동기화: {connection.last_synced_at ? formatRelativeTime(connection.last_synced_at, MOCK_NOW) : "아직 없음"} · 토큰 끝 4자리 {connection.token_last4}
           </p>
         </section>
```

### `other`·모호 조건 표시 — `src/components/OpportunityConditions.tsx`

```diff
--- a/src/components/OpportunityConditions.tsx
+++ b/src/components/OpportunityConditions.tsx
@@ -52,5 +52,6 @@
               <span className="flex shrink-0 items-center gap-2 text-[13px] font-semibold">
                 <span className={valueIsFailure ? "text-[#c53030]" : ""}>
-                  {condition.user_value_text ?? "미입력"}
+                  {condition.user_value_text ??
+                    (condition.field === "other" || condition.is_ambiguous ? "원문 확인" : "미입력")}
                 </span>
                 <Badge tone={result.tone}>{result.label}</Badge>
```

### ES2020에서도 통과 — `src/lib/format.ts`

```diff
--- a/src/lib/format.ts
+++ b/src/lib/format.ts
@@ -37,5 +37,5 @@
 
 export function formatKstDate(value: string | Date): string {
-  return getKstDateKey(value).replaceAll("-", ".");
+  return getKstDateKey(value).replace(/-/g, ".");
 }
```

## 남은 것

- 목데이터 불일치: 준비하지 않은 공모전의 마감 표시가 플래너에 있고, 탈락 사유 문구와 실제 불충족 조건이 다르며, 모든 공고가 장학금 서류를 같이 쓴다. 데모 전에 정리한다.
- 모바일 플래너 칩이 잘린다. 프롬프트 13(주간 목록)으로 해결한다.
- `src/api/client.ts`가 310줄로 300줄 기준을 넘었다. 실제 API로 바꿀 때 기능별 파일로 나눈다.
- 목 상태는 메모리에만 있어서 새로고침하면 초기화된다. 화면 이동은 앱 안 링크로 해야 상태가 이어진다.
