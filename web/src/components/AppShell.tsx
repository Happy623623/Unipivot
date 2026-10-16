import { createContext, useContext, type ReactNode } from "react";
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

const AppShellContext = createContext<AppShellContextValue | null>(null);

export function useAppShell() {
  const context = useContext(AppShellContext);
  if (!context) {
    throw new Error("useAppShell must be used inside AppShell");
  }
  return context;
}

export default function AppShell({
  route,
  unreadNotifications,
  setUnreadNotifications,
  navigate,
  children,
}: AppShellProps) {
  return (
    <AppShellContext.Provider
      value={{ unreadNotifications, setUnreadNotifications, navigate }}
    >
      <div className="min-h-dvh bg-[#f7f8fa] text-[#181a20]">
        <Sidebar route={route} navigate={navigate} />
        <main className="ml-[220px] min-h-dvh px-12 py-10 max-[1000px]:px-6 max-[760px]:ml-0 max-[760px]:px-4 max-[760px]:py-6">
          <div className="mx-auto flex w-full max-w-[1124px] flex-col gap-7">{children}</div>
        </main>
      </div>
    </AppShellContext.Provider>
  );
}
