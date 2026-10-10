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
