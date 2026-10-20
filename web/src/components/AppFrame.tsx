"use client";

import { createContext, Fragment, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getMe, recordEvent } from "@/api/client";
import AppShell from "@/components/AppShell";
import StatusPreview from "@/dev/StatusPreview";
import { pathnameToRoute, useAppNavigate } from "@/lib/routes";
import { syncPushSubscription } from "@/lib/usePushSubscription";
import useAsyncData from "@/lib/useAsyncData";
import useSessionWatch from "@/lib/useSessionWatch";
import type { Me } from "@/types/api";

// Make의 App.tsx가 하던 일: 내 정보 불러오기, 동의 전이면 온보딩으로 보내기, 상태 미리보기.
// 동의를 마친 사용자가 앱을 열면 app_open을 한 번 기록한다(서버가 KST 하루 1건만 남긴다).
// 알림 목록은 패널을 열 때 받고(useNotifications), 여기서는 배지 숫자만 들고 있는다.
// 다른 탭에서 로그아웃·탈퇴하면 이 탭도 로그인 화면으로 간다(useSessionWatch)
const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext);

const showDevTools = process.env.NEXT_PUBLIC_USE_MOCKS === "true";

export default function AppFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const navigate = useAppNavigate();
  const [revision, setRevision] = useState(0);
  const [unread, setUnread] = useState<number | null>(null);
  const meRequest = useAsyncData(getMe, [revision]);
  const openRecorded = useRef(false);
  const pushSynced = useRef(false);
  useSessionWatch();

  useEffect(() => {
    setUnread(null);
  }, [revision]);

  useEffect(() => {
    if (meRequest.data && !meRequest.data.consented) router.replace("/onboarding");
  }, [meRequest.data, router]);

  useEffect(() => {
    if (!meRequest.data?.consented || openRecorded.current) return;
    openRecorded.current = true;
    recordEvent("app_open");
  }, [meRequest.data]);

  // 서비스 워커를 등록하고, 이 브라우저가 이미 들고 있는 푸시 구독을 서버에 다시 올린다(F-33).
  // 브라우저가 구독 주소를 바꾸거나 같은 브라우저로 다른 사람이 로그인하면 여기서 맞춰진다
  useEffect(() => {
    if (!meRequest.data?.consented || pushSynced.current) return;
    pushSynced.current = true;
    void syncPushSubscription();
  }, [meRequest.data]);

  return (
    <MeContext.Provider value={meRequest.data}>
      <AppShell
        route={pathnameToRoute(pathname)}
        unreadNotifications={unread ?? meRequest.data?.unread_notifications ?? 0}
        setUnreadNotifications={setUnread}
        navigate={navigate}
      >
        <Fragment key={revision}>{children}</Fragment>
      </AppShell>
      {showDevTools && <StatusPreview onChange={() => setRevision((value) => value + 1)} />}
    </MeContext.Provider>
  );
}
