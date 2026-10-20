import { useEffect } from "react";
import { USE_MOCKS } from "@/api/http";
import { createBrowserSupabase } from "@/lib/supabase/client";

// 다른 탭에서 로그아웃·탈퇴했거나 이 브라우저의 로그인이 끝나면 이 탭도 개인 정보 화면을 내린다 (F-06).
// 1) Supabase가 탭끼리 넘겨주는 SIGNED_OUT(supabase-js의 BroadcastChannel)을 받으면 바로 로그인 화면으로 간다.
// 2) 알림을 못 받은 탭(잠들었던 탭, 뒤로 가기로 복원된 화면, BroadcastChannel이 없는 브라우저)은 다시 보일 때 세션을
//    확인해, 없으면 로그인 화면으로, 다른 계정으로 바뀌었으면 홈으로 간다.
// 로그인 화면 안내는 이유를 따른다. 로그아웃·탈퇴하는 탭이 세션을 지우기 직전에 이유를 우리 채널로 알리고(announceLeaving),
// 그 뒤 30초 안에 세션이 끝나면 그 이유로(notice=signed_out·deleted), 아니면(로그인 만료·갱신 실패) error=session으로 간다.
// 로그인 화면으로는 replace로 간다(지금 화면이 기록에 남지 않게). 그보다 앞의 기록이 뒤로 가기 캐시(bfcache)로 살아 돌아오면
// pageshow에서 다시 확인한다. 로그아웃·탈퇴하는 탭 자신도 감시는 그대로 둔다 — 자기 흐름과 같은 주소로 가고, 그 탭의 앞
// 기록이 캐시로 돌아와도 확인하게.
// 서버(로그인 콜백 등)에서 바뀐 세션은 알림이 없어 다시 보일 때 확인하거나 다음 요청(401)이 맡는다.
// 처음부터 세션이 없던 화면은 http.ts(401)가 맡는다. 목 모드는 세션이 없어 하지 않는다
export type LeaveReason = "signed_out" | "deleted";

const CHANNEL_NAME = "unipivot-auth";
const REASON_FRESH_MS = 30_000; // 로그아웃 요청이 끊겨 supabase-js가 다시 해 보는 시간(25초쯤)보다 길게

let channel: BroadcastChannel | null | undefined; // undefined: 아직 안 만듦, null: 브라우저에 없음
let lastReason: { reason: LeaveReason; at: number } | null = null;

function remember(reason: unknown): void {
  if (reason === "signed_out" || reason === "deleted") lastReason = { reason, at: Date.now() };
}

function authChannel(): BroadcastChannel | null {
  if (channel === undefined) {
    channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(CHANNEL_NAME);
    channel?.addEventListener("message", (event: MessageEvent) => remember(event.data?.reason));
  }
  return channel;
}

// 이 탭이 세션을 지우기 직전에 부른다. 다른 탭에 이유를 알리고 이 탭도 기억한다(8초 안에 못 끝내 화면에 남았다가
// 나중에 세션이 끝나도 같은 안내로 간다)
export function announceLeaving(reason: LeaveReason): void {
  remember(reason);
  authChannel()?.postMessage({ reason });
}

function goToLogin(): void {
  const fresh = lastReason && Date.now() - lastReason.at < REASON_FRESH_MS ? lastReason.reason : null;
  window.location.replace(fresh ? `/login?notice=${fresh}` : "/login?error=session");
}

export default function useSessionWatch(): void {
  useEffect(() => {
    if (USE_MOCKS) return;
    const supabase = createBrowserSupabase();
    authChannel();
    let userId: string | null | undefined; // 이 화면을 그린 사용자. undefined면 아직 모른다

    const follow = (sessionUserId: string | null) => {
      if (!userId) return;
      if (sessionUserId === null) goToLogin();
      else if (sessionUserId !== userId) window.location.replace("/");
    };

    // 첫 세션이 없었는데(오프라인으로 열어 갱신을 못 함 등) 나중에 세션이 생기면 그 사용자를 이 화면의 사용자로 본다
    const { data } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "INITIAL_SESSION") userId = session?.user.id ?? null;
      else if (!userId && session) userId = session.user.id;
      else if (event === "SIGNED_OUT") follow(null);
      else if (session) follow(session.user.id);
    });

    // 다시 보일 때 확인한다. 갱신이 실패하면(오프라인 등) 세션이 없다고 보지 않는다 — 다음 요청이 맡는다
    const recheck = () => {
      if (document.visibilityState !== "visible" || !userId) return;
      void supabase.auth.getSession().then(({ data: current, error }) => {
        if (!error) follow(current.session?.user.id ?? null);
      });
    };
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) recheck();
    };
    document.addEventListener("visibilitychange", recheck);
    window.addEventListener("pageshow", onPageShow);
    return () => {
      data.subscription.unsubscribe();
      document.removeEventListener("visibilitychange", recheck);
      window.removeEventListener("pageshow", onPageShow);
    };
  }, []);
}
