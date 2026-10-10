"use client";

import { createContext, Fragment, useContext, useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  getMe,
  getNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/api/client";
import AppShell from "@/components/AppShell";
import StatusPreview from "@/dev/StatusPreview";
import { pathnameToRoute, useAppNavigate } from "@/lib/routes";
import useAsyncData from "@/lib/useAsyncData";
import type { AppNotification, Me } from "@/types/api";

// Make의 App.tsx가 하던 일: 내 정보·알림 불러오기, 동의 전이면 온보딩으로 보내기, 상태 미리보기
const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext);

const showDevTools = process.env.NEXT_PUBLIC_USE_MOCKS === "true";

export default function AppFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const navigate = useAppNavigate();
  const [revision, setRevision] = useState(0);
  const [notificationsOverride, setNotificationsOverride] = useState<AppNotification[] | null>(null);
  const [unreadOverride, setUnreadOverride] = useState<number | null>(null);
  const meRequest = useAsyncData(getMe, [revision]);
  const notificationsRequest = useAsyncData(getNotifications, [revision]);

  useEffect(() => {
    setNotificationsOverride(null);
    setUnreadOverride(null);
  }, [revision]);

  useEffect(() => {
    if (meRequest.data && !meRequest.data.consented) router.replace("/onboarding");
  }, [meRequest.data, router]);

  return (
    <MeContext.Provider value={meRequest.data}>
      <AppShell
        route={pathnameToRoute(pathname)}
        notifications={notificationsOverride ?? notificationsRequest.data ?? []}
        unreadNotifications={unreadOverride ?? meRequest.data?.unread_notifications ?? 0}
        markNotificationRead={async (id) => {
          const notifications = await markNotificationRead(id);
          setNotificationsOverride(notifications);
          setUnreadOverride(notifications.filter((item) => item.read_at === null).length);
        }}
        markAllNotificationsRead={async () => {
          setNotificationsOverride(await markAllNotificationsRead());
          setUnreadOverride(0);
        }}
        navigate={navigate}
      >
        <Fragment key={revision}>{children}</Fragment>
      </AppShell>
      {showDevTools && <StatusPreview onChange={() => setRevision((value) => value + 1)} />}
    </MeContext.Provider>
  );
}
