import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

// 라우트 핸들러(로그인 콜백)에서 쓰는 Supabase 클라이언트
export async function createServerSupabase() {
  const cookieStore = await cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options));
          } catch {
            // 서버 컴포넌트에서 부르면 쿠키를 쓸 수 없다. 라우트 핸들러에서는 정상 동작한다
          }
        },
      },
    },
  );
}

// 쿠키를 읽기만 하는 클라이언트. 확인용 호출(getUser)이 세션·PKCE 쿠키를 바꾸거나 지우지 않게 한다
// (세션이 끊겨 있으면 auth-js가 저장소를 비우면서 코드 교환에 쓸 PKCE 값까지 지운다)
export async function createReadOnlyServerSupabase() {
  const cookieStore = await cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll() {},
      },
    },
  );
}
