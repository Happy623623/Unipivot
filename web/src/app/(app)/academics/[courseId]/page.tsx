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
