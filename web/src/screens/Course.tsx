import { useCallback, useEffect, useState } from "react";
import { connectCalendar, getCourse } from "@/api/client";
import CourseAnnouncements from "@/components/CourseAnnouncements";
import CourseAssignments from "@/components/CourseAssignments";
import CourseMaterials from "@/components/CourseMaterials";
import CourseSyllabus from "@/components/CourseSyllabus";
import Header from "@/components/Header";
import MaterialSummaryPanel from "@/components/MaterialSummaryPanel";
import Skeleton from "@/components/Skeleton";
import Toast from "@/components/Toast";
import { routeToHref } from "@/lib/routes";
import useAsyncData from "@/lib/useAsyncData";
import useToast from "@/lib/useToast";
import type { Route } from "@/types/route";

type CourseTab = NonNullable<Extract<Route, { name: "course" }>["tab"]>;

// 캘린더 연결에서 돌아올 곳(계획서 탭). 연결하면 ?calendar=connected로 여기로 온다
function courseHref(id: string): string {
  return `${routeToHref({ name: "course", id })}?tab=syllabus`;
}

interface CourseProps {
  id: string;
  initialTab?: CourseTab;
  calendarConnected: boolean;
  calendarResult?: "connected" | "error" | null; // 캘린더 연결에서 돌아온 결과
  navigate: (route: Route) => void;
}

const tabs: { id: CourseTab; label: string }[] = [
  { id: "assignments", label: "과제" },
  { id: "materials", label: "자료" },
  { id: "announcements", label: "공지" },
  { id: "syllabus", label: "계획서" },
];

export default function Course({
  id,
  initialTab = "assignments",
  calendarConnected,
  calendarResult = null,
  navigate,
}: CourseProps) {
  const [tab, setTab] = useState<CourseTab>(initialTab);
  const [summaryFileId, setSummaryFileId] = useState<string | null>(null);
  // 계획서를 확정하면 과목 상세를 다시 받아 확정 표시와 새 일정을 보여 준다
  const [reloads, setReloads] = useState(0);
  // 다시 받는 동안 지난 상세를 둔다(뼈대로 바꾸면 요약 창과 안내가 내려간다)
  const request = useAsyncData(() => getCourse(id), [id, reloads], { keep: true });
  const reload = useCallback(() => setReloads((count) => count + 1), []);
  // 다른 과목으로 옮겼으면 지난 과목의 상세는 쓰지 않는다(그 과목의 올리기 버튼이 남지 않게)
  const loaded = request.data?.course.id === id ? request.data : null;
  const [toast, showToast] = useToast();

  useEffect(() => {
    setTab(initialTab);
    setSummaryFileId(null);
  }, [id, initialTab]);

  // 계획서를 확정해 다시 받는 동안에는 뼈대로 갈아 치우지 않는다 — 화면이 번쩍이고 안내가 사라진다
  if (request.loading && !loaded) {
    return (
      <>
        <Skeleton className="h-[70px] w-[360px]" />
        <Skeleton className="h-[54px] w-full rounded-[14px]" />
        <Skeleton className="h-[430px] w-full rounded-2xl" />
      </>
    );
  }
  if (!loaded) {
    return (
      <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">
        {request.error ?? "과목 정보를 불러오지 못했어요."}
      </p>
    );
  }

  const course = loaded;
  const lmsUrl = course.course.html_url;

  return (
    <>
      <Header
        title={course.course.short_name}
        subtitle="마지막 동기화: 방금 전"
        action={
          <a
            href={lmsUrl}
            target="_blank"
            rel="noreferrer"
            className="text-[13px] font-semibold text-[#4f6ef7]"
          >
            LMS에서 열기
          </a>
        }
      />
      {request.error && (
        <p role="status" className="rounded-[14px] bg-[#fef2f2] p-4 text-[13px] text-[#c53030]">
          과목 정보를 새로 받지 못해 지난 내용을 보여 주고 있어요. 잠시 후 이 화면을 다시 열어 주세요.
        </p>
      )}
      <nav className="flex gap-2 rounded-[14px] bg-white p-2">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => {
              setTab(item.id);
              if (item.id !== "materials") setSummaryFileId(null);
            }}
            className={`rounded-[10px] px-4 py-2 text-[13px] font-semibold ${
              tab === item.id
                ? "bg-[#eef2ff] text-[#4f6ef7]"
                : "text-[#667085]"
            }`}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <div
        className={
          tab === "materials" && summaryFileId
            ? "grid grid-cols-[0.9fr_1.1fr] gap-5 max-[1000px]:grid-cols-1"
            : ""
        }
      >
        <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
          {tab === "assignments" && (
            <CourseAssignments assignments={course.assignments} />
          )}
          {tab === "materials" && (
            <CourseMaterials
              course={course}
              onOpenSummary={setSummaryFileId}
              onUploaded={reload}
            />
          )}
          {tab === "announcements" && (
            <CourseAnnouncements
              announcements={course.announcements}
              navigate={navigate}
              onToast={showToast}
            />
          )}
          {tab === "syllabus" && (
            <CourseSyllabus
              course={course}
              calendarConnected={calendarConnected}
              calendarResult={calendarResult}
              onRefresh={reload}
              onConnectCalendar={() => connectCalendar(courseHref(id))}
              onToast={showToast}
            />
          )}
        </section>
        {tab === "materials" && summaryFileId && (
          <MaterialSummaryPanel
            key={summaryFileId}
            fileId={summaryFileId}
            onClose={() => setSummaryFileId(null)}
            onChange={reload}
          />
        )}
      </div>
      <Toast toast={toast} />
    </>
  );
}
