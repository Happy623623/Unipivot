import { NextResponse } from "next/server";
import { safeNextPath, withQuery } from "@/lib/redirectPath";
import { createServerSupabase } from "@/lib/supabase/server";

// 로그인과 캘린더 연결이 함께 쓰는 콜백 (API 4장, 증분 승인)
// - 로그인: 세션만 만든다. 동의 전이면 홈의 AppFrame이 /onboarding으로 보낸다
// - 캘린더 연결(connect=calendar): Google 토큰을 백엔드에 한 번 넘겨 암호화 저장한다
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const next = safeNextPath(searchParams.get("next"));
  const connectCalendar = searchParams.get("connect") === "calendar";
  if (!code) return NextResponse.redirect(`${origin}/login?error=missing_code`);

  const supabase = await createServerSupabase();
  const { data, error } = await supabase.auth.exchangeCodeForSession(code);
  if (error || !data.session) return NextResponse.redirect(`${origin}/login?error=auth`);
  if (!connectCalendar) return NextResponse.redirect(`${origin}${next}`);

  const { access_token, provider_token, provider_refresh_token } = data.session;
  let result = "error";
  try {
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/auth/google/tokens`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${access_token}` },
      body: JSON.stringify({ provider_token, provider_refresh_token }),
    });
    if (response.ok) result = "connected";
  } catch {
    // 백엔드에 닿지 못해도 로그인 세션은 그대로 두고, 돌아간 화면에서 다시 연결하게 한다
  }
  // refresh token을 못 받았을 때(422 GOOGLE_REFRESH_TOKEN_MISSING)도 error로 돌아가 다시 연결을 안내한다
  return NextResponse.redirect(`${origin}${withQuery(next, "calendar", result)}`);
}
