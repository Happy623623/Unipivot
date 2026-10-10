import { useEffect, useState } from "react";
import { getCourse } from "@/api/client";
import CourseAnnouncements from "@/components/CourseAnnouncements";
import CourseAssignments from "@/components/CourseAssignments";
import CourseMaterials from "@/components/CourseMaterials";
import CourseSyllabus from "@/components/CourseSyllabus";
import Header from "@/components/Header";
import MaterialSummaryPanel from "@/components/MaterialSummaryPanel";
import Skeleton from "@/components/Skeleton";
import useAsyncData from "@/lib/useAsyncData";
import type { Route } from "@/types/route";

type CourseTab = NonNullable<Extract<Route, { name: "course" }>["tab"]>;

interface CourseProps {
  id: string;
  initialTab?: CourseTab;
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
  navigate,
}: CourseProps) {
  const [tab, setTab] = useState<CourseTab>(initialTab);
  const [summaryFileId, setSummaryFileId] = useState<string | null>(null);
  const request = useAsyncData(() => getCourse(id), [id]);

  useEffect(() => {
    setTab(initialTab);
    setSummaryFileId(null);
  }, [id, initialTab]);

  if (request.loading) {
    return (
      <>
        <Skeleton className="h-[70px] w-[360px]" />
        <Skeleton className="h-[54px] w-full rounded-[14px]" />
        <Skeleton className="h-[430px] w-full rounded-2xl" />
      </>
    );
  }
  if (request.error || !request.data) {
    return (
      <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">
        {request.error ?? "과목 정보를 불러오지 못했어요."}
      </p>
    );
  }

  const course = request.data;
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
            />
          )}
          {tab === "announcements" && (
            <CourseAnnouncements
              announcements={course.announcements}
              navigate={navigate}
            />
          )}
          {tab === "syllabus" && <CourseSyllabus course={course} />}
        </section>
        {tab === "materials" && summaryFileId && (
          <MaterialSummaryPanel
            fileId={summaryFileId}
            onClose={() => setSummaryFileId(null)}
          />
        )}
      </div>
    </>
  );
}
