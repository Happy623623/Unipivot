"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { CalendarResult } from "@/components/ConnectedServices";
import { useAppNavigate } from "@/lib/routes";
import Settings from "@/screens/Settings";

// 캘린더 연결 콜백이 돌려보낸 결과(?calendar=connected·error)를 한 번 읽고 주소에서 지운다.
// 새로 고침해도 같은 안내가 다시 뜨지 않게 하려는 것이다
function SettingsPage() {
  const navigate = useAppNavigate();
  const router = useRouter();
  const query = useSearchParams().get("calendar");
  const [calendarResult] = useState<CalendarResult | null>(
    query === "connected" || query === "error" ? query : null,
  );

  useEffect(() => {
    if (query) router.replace("/settings", { scroll: false });
  }, [query, router]);

  return <Settings navigate={navigate} calendarResult={calendarResult} />;
}

export default function Page() {
  return (
    <Suspense>
      <SettingsPage />
    </Suspense>
  );
}
