import { createBrowserSupabase } from "@/lib/supabase/client";

export const CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events";

/**
 * 캘린더 쓰기 권한을 처음 받을 때 부른다(증분 승인, PRD F-01).
 * 부르는 곳: 준비하기 결과의 "캘린더에도 등록", 설정의 캘린더 연결·재연결, LMS 과제 자동 등록 켜기.
 *
 * Google 화면을 거쳐 /auth/callback?connect=calendar로 돌아오고, 콜백이 토큰을 백엔드에 저장한 뒤
 * next 경로로 보낸다(?calendar=connected 또는 ?calendar=error). 성공하면 페이지를 떠나고,
 * 시작하지 못하면 화면에 띄울 오류 문구를 돌려준다. 목 모드에서는 부르지 않는다.
 */
export async function connectGoogleCalendar(next: string): Promise<string | null> {
  const redirectTo = new URL("/auth/callback", window.location.origin);
  redirectTo.searchParams.set("connect", "calendar");
  redirectTo.searchParams.set("next", next);
  const { error } = await createBrowserSupabase().auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: redirectTo.toString(),
      scopes: CALENDAR_SCOPE,
      // refresh token을 받으려면 offline + consent. 이미 받은 범위는 유지한다
      queryParams: { access_type: "offline", prompt: "consent", include_granted_scopes: "true" },
    },
  });
  return error ? "Google 캘린더 연결을 시작하지 못했어요. 잠시 후 다시 시도해 주세요." : null;
}
