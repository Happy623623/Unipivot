import { isAuthApiError, isAuthSessionMissingError, type SupabaseClient } from "@supabase/supabase-js";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { safeNextPath, withQuery } from "@/lib/redirectPath";
import { createReadOnlyServerSupabase, createServerSupabase } from "@/lib/supabase/server";

// 로그인과 캘린더 연결이 함께 쓰는 콜백 (API 4장, 증분 승인)
// - 로그인: 세션만 만든다. 동의 전이면 홈의 AppFrame이 /onboarding으로 보낸다
// - 캘린더 연결(connect=calendar): Google 토큰을 백엔드에 한 번 넘겨 암호화 저장한다
// 어느 쪽이든 Google 토큰(provider_token·provider_refresh_token)은 브라우저 쿠키에 남기지 않는다.
// 코드 교환 직후 세션에만 실려 오므로, 세션을 한 번 새로 받아 Google 토큰이 없는 세션으로 바꾼다
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const next = safeNextPath(searchParams.get("next"));
  const connectCalendar = searchParams.get("connect") === "calendar";
  const toLogin = (reason: string) => NextResponse.redirect(`${origin}/login?error=${reason}`);
  // 캘린더 연결은 실패해도 로그인을 그대로 두고 원래 화면으로 돌려보낸다
  const backWith = (result: string) => NextResponse.redirect(`${origin}${withQuery(next, "calendar", result)}`);
  // Google 화면에서 취소·거절하면 code 없이 돌아온다
  if (!code) return connectCalendar ? backWith("error") : toLogin("missing_code");

  // 캘린더 연결 전에 로그인해 있던 사용자. Google에서 다른 계정을 고르면 세션이 그 계정으로 바뀌므로 비교한다
  const before = connectCalendar ? await signedInUserId() : null;
  if (before === undefined) return backWith("error");

  const supabase = await createServerSupabase();
  const { data, error } = await supabase.auth.exchangeCodeForSession(code);
  if (error || !data.session) {
    logFailure("로그인 코드 교환", error ?? "세션 없음");
    return connectCalendar ? backWith("error") : toLogin("auth");
  }
  if (!connectCalendar) {
    return (await dropGoogleTokens(supabase)) ? NextResponse.redirect(`${origin}${next}`) : toLogin("auth");
  }
  if (before && before !== data.session.user.id) {
    // 다른 계정의 토큰은 저장하지 않고, 바뀐 세션도 이 기기에서 지운다. 처음 계정으로 다시 로그인하게 한다
    // TODO: 처음 쓰는 Google 계정이었다면 Supabase 사용자만 생기고 남는다. 정리는 탈퇴(DELETE /me) 작업 때 정한다
    await endSession(supabase);
    return toLogin("other_account");
  }

  const { access_token, provider_token, provider_refresh_token } = data.session;
  let result = "error";
  try {
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/auth/google/tokens`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${access_token}` },
      body: JSON.stringify({ provider_token, provider_refresh_token }),
    });
    if (response.ok) result = "connected";
    else logFailure("캘린더 토큰 저장", { status: response.status, code: await errorCode(response) });
  } catch (caught) {
    // 백엔드에 닿지 못해도 로그인 세션은 그대로 두고, 돌아간 화면에서 다시 연결하게 한다
    logFailure("캘린더 토큰 저장(API 연결)", caught);
  }
  // refresh token을 못 받았을 때(422 GOOGLE_REFRESH_TOKEN_MISSING)도 error로 돌아가 다시 연결을 안내한다
  return (await dropGoogleTokens(supabase)) ? backWith(result) : toLogin("auth");
}

// 지금 로그인한 사용자 id. 세션이 없거나 끊겼으면 null(새 로그인처럼 진행), Auth 서버 오류로 확인하지 못하면 undefined.
// 쿠키를 바꾸지 않는 클라이언트로 확인한다(세션이 끊겨 있으면 auth-js가 PKCE 값까지 지워 교환이 실패한다)
async function signedInUserId(): Promise<string | null | undefined> {
  const { data, error } = await (await createReadOnlyServerSupabase()).auth.getUser();
  if (data.user) return data.user.id;
  const gone = isAuthSessionMissingError(error) || (isAuthApiError(error) && error.status < 500 && error.status !== 429);
  if (error && !gone) logFailure("로그인한 사용자 확인", error);
  return !error || gone ? null : undefined;
}

// 세션을 새로 받아 Google 토큰이 없는 세션으로 바꾼다. 실패하면 Google 토큰이 남지 않게 이 기기에서 로그아웃한다
async function dropGoogleTokens(supabase: SupabaseClient): Promise<boolean> {
  const { error } = await supabase.auth.refreshSession();
  if (!error) return true;
  logFailure("세션 새로 받기", error);
  await endSession(supabase);
  return false;
}

// 이 기기의 세션을 끝낸다. 로그아웃 요청이 실패해도 세션 쿠키는 지운다
async function endSession(supabase: SupabaseClient): Promise<void> {
  await supabase.auth.signOut({ scope: "local" });
  const cookieStore = await cookies();
  for (const { name } of cookieStore.getAll()) {
    if (name.startsWith("sb-") && name.includes("-auth-token")) cookieStore.delete(name);
  }
}

// 실패 이유를 서버 로그(npm run dev 터미널)에 남긴다. 토큰·코드 값은 남기지 않는다.
// fetch 실패는 cause에 연결 오류 코드(ECONNREFUSED 등)가 있다
function logFailure(step: string, reason: unknown): void {
  const fields = typeof reason === "object" && reason !== null ? (reason as Record<string, unknown>) : { message: reason };
  const cause = fields.cause as { code?: unknown } | undefined;
  const detail = Object.fromEntries(
    Object.entries({ name: fields.name, code: fields.code, status: fields.status, message: fields.message, cause: cause?.code })
      .filter(([, value]) => value !== undefined && value !== null)
      .map(([key, value]) => [key, String(value).slice(0, 200)]),
  );
  console.warn(`[auth/callback] ${step} 실패`, detail);
}

// API 오류 응답의 code(API 명세 13장). 본문을 읽지 못하면 null
async function errorCode(response: Response): Promise<string | null> {
  const body = await response.json().catch(() => null);
  return typeof body?.error?.code === "string" ? body.error.code : null;
}
