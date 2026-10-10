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
