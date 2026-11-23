import { createContext, useContext, useRef, useState, type ReactNode, type RefObject } from "react";
import MobileNav from "@/components/MobileNav";
import NotificationPanel from "@/components/NotificationPanel";
import Sidebar from "@/components/Sidebar";
import type { Route } from "@/types/route";

interface AppShellContextValue {
  unreadNotifications: number; // 헤더 배지. 알림함 응답이 오면 그 수로 맞춘다
  setUnreadNotifications: (count: number) => void;
  navigate: (route: Route) => void;
}

interface AppShellProps extends AppShellContextValue {
  route: Route;
  children: ReactNode;
}

interface NotificationsContextValue {
  open: boolean;
  openFrom: (trigger: RefObject<HTMLElement | null>) => void; // 패널을 닫으면 초점을 trigger로 돌려준다
}

const AppShellContext = createContext<AppShellContextValue | null>(null);
const NotificationsContext = createContext<NotificationsContextValue | null>(null);

export function useAppShell() {
  const context = useContext(AppShellContext);
  if (!context) {
    throw new Error("useAppShell must be used inside AppShell");
  }
  return context;
}

export function useNotificationPanel() {
  const context = useContext(NotificationsContext);
  if (!context) {
    throw new Error("useNotificationPanel must be used inside AppShell");
  }
  return context;
}

// 알림 패널은 여기 하나만 둔다. 넓은 화면은 머리글(Header)의 종이, 좁은 화면은 위 막대(MobileNav)의 종이 연다
export default function AppShell({
  route,
  unreadNotifications,
  setUnreadNotifications,
  navigate,
  children,
}: AppShellProps) {
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const mobileBellRef = useRef<HTMLButtonElement>(null);
  const openFrom = (trigger: RefObject<HTMLElement | null>) => {
    returnFocusRef.current = trigger.current;
    setNotificationsOpen(true);
  };

  return (
    <AppShellContext.Provider
      value={{ unreadNotifications, setUnreadNotifications, navigate }}
    >
      <NotificationsContext.Provider value={{ open: notificationsOpen, openFrom }}>
        <div className="min-h-dvh bg-[#f7f8fa] text-[#181a20] max-md:overflow-x-clip">
          <Sidebar route={route} navigate={navigate} />
          <MobileNav
            route={route}
            navigate={navigate}
            unreadNotifications={unreadNotifications}
            notificationsOpen={notificationsOpen}
            bellRef={mobileBellRef}
            onOpenNotifications={() => openFrom(mobileBellRef)}
          />
          {/* 좁은 화면: 위 막대(64px)·아래 메뉴(72px)에 가리지 않게 위아래를 비운다 */}
          <main className="ml-[220px] min-h-dvh px-12 py-10 max-[1000px]:px-6 max-md:ml-0 max-md:px-4 max-md:pb-[calc(96px+env(safe-area-inset-bottom))] max-md:pt-[calc(84px+env(safe-area-inset-top))]">
            <div className="mx-auto flex w-full min-w-0 max-w-[1124px] flex-col gap-7 max-md:gap-5">{children}</div>
          </main>
          <NotificationPanel
            open={notificationsOpen}
            onClose={() => setNotificationsOpen(false)}
            returnFocusRef={returnFocusRef}
          />
        </div>
      </NotificationsContext.Provider>
    </AppShellContext.Provider>
  );
}
