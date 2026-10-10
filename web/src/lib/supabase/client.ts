import { createBrowserClient } from "@supabase/ssr";

// 브라우저에서 쓰는 Supabase 클라이언트 (로그인·세션 토큰 조회에만 쓴다. 데이터는 FastAPI로만 받는다)
export function createBrowserSupabase() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
