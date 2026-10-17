"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMe } from "@/components/AppFrame";
import { useAppNavigate } from "@/lib/routes";
import Course from "@/screens/Course";

const tabs = ["assignments", "materials", "announcements", "syllabus"] as const;
type CourseTab = (typeof tabs)[number];

function CoursePage() {
  const { courseId } = useParams<{ courseId: string }>();
  const query = useSearchParams();
  const router = useRouter();
  const tabParam = query.get("tab");
  const tab = tabs.find((item) => item === tabParam) as CourseTab | undefined;
  // Google 캘린더 연결에서 돌아왔다(?calendar=connected|error). 한 번 쓰고 주소에서 지운다
  const calendarQuery = query.get("calendar");
  const [calendarResult] = useState<"connected" | "error" | null>(
    calendarQuery === "connected" || calendarQuery === "error" ? calendarQuery : null,
  );
  useEffect(() => {
    if (calendarQuery) {
      router.replace(`/academics/${courseId}${tabParam ? `?tab=${tabParam}` : ""}`, {
        scroll: false,
      });
    }
  }, [calendarQuery, courseId, router, tabParam]);
  const navigate = useAppNavigate();
  const me = useMe();
  return (
    <Course
      id={courseId}
      initialTab={tab}
      calendarConnected={me?.calendar_connected ?? false}
      calendarResult={calendarResult}
      navigate={navigate}
    />
  );
}

export default function Page() {
  return (
    <Suspense>
      <CoursePage />
    </Suspense>
  );
}
