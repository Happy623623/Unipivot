"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMe } from "@/components/AppFrame";
import { useAppNavigate } from "@/lib/routes";
import OpportunityDetail from "@/screens/OpportunityDetail";

function OpportunityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const query = useSearchParams();
  const router = useRouter();
  const focus = query.get("focus") === "profile_input" ? "profile_input" : undefined;
  // Google 캘린더 연결에서 돌아왔다(?calendar=connected|error). 처음 한 번만 쓰고 주소에서 지운다
  const calendarQuery = query.get("calendar");
  const [calendarResult] = useState<"connected" | "error" | null>(
    calendarQuery === "connected" || calendarQuery === "error" ? calendarQuery : null,
  );
  useEffect(() => {
    if (calendarQuery) router.replace(`/opportunities/${id}`, { scroll: false });
  }, [calendarQuery, id, router]);
  const navigate = useAppNavigate();
  const me = useMe();
  return (
    <OpportunityDetail
      id={id}
      focus={focus}
      calendarConnected={me?.calendar_connected ?? false}
      calendarResult={calendarResult}
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
