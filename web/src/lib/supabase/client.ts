import { createBrowserClient } from "@supabase/ssr";

// 브라우저에서 쓰는 Supabase 클라이언트 (로그인·세션 토큰 조회에만 쓴다. 데이터는 FastAPI로만 받는다)
export function createBrowserSupabase() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}

// 이 브라우저에 로그인 세션 쿠키(`sb-<프로젝트>-auth-token`, 길면 `.0`·`.1`로 나뉜다)가 남아 있는지. 로그아웃이 정말
// 세션을 지웠는지 확인할 때 쓴다(세션을 불러오다 실패하면 supabase-js가 지우지 않고 오류만 돌려준다)
export function hasStoredSession(): boolean {
  return document.cookie.split("; ").some((cookie) => /^sb-[^=]*-auth-token(\.\d+)?=/.test(cookie));
}
