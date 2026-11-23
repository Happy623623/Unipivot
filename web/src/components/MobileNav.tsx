import type { RefObject } from "react";
import NavIcon from "@/components/NavIcons";
import { navItems } from "@/components/Sidebar";
import type { Route } from "@/types/route";

interface MobileNavProps {
  route: Route;
  navigate: (route: Route) => void;
  unreadNotifications: number;
  notificationsOpen: boolean;
  bellRef: RefObject<HTMLButtonElement | null>;
  onOpenNotifications: () => void;
}

// 좁은 화면(768px 미만)의 위 막대와 아래 메뉴(Figma Make 11/23 디자인). 넓은 화면에서는 숨기고 사이드바를 쓴다.
// 위 막대: 로고(홈) · 공고 등록 · 설정 · 알림. 설정은 디자인에 없던 자리다 — 사이드바가 숨으면 설정으로 갈 길이 없어서 넣었다.
// 알림 버튼은 넓은 화면의 머리글 종처럼 알림 패널을 연다(AppShell이 패널을 하나만 둔다).
// z-30: 사이드바(20) 위, 알림 패널(40·50)·창(80)·안내(90) 아래
export default function MobileNav({
  route,
  navigate,
  unreadNotifications,
  notificationsOpen,
  bellRef,
  onOpenNotifications,
}: MobileNavProps) {
  const square = "inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl";
  const onUpload = route.name === "upload";
  const onSettings = route.name === "settings";
  return (
    <>
      <header className="fixed inset-x-0 top-0 z-30 hidden h-[calc(64px+env(safe-area-inset-top))] items-end justify-between border-b border-[#e5e7eb] bg-white/96 px-4 pb-[10px] pt-[env(safe-area-inset-top)] shadow-[0_4px_18px_rgba(24,26,32,0.04)] backdrop-blur-[14px] max-md:flex">
        <button
          type="button"
          onClick={() => navigate({ name: "home" })}
          className="min-h-11 text-[21px] font-extrabold tracking-[-0.03em] text-[#5369ff]"
        >
          UNIPIVOT
        </button>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => navigate({ name: "upload" })}
            aria-label="공고 등록"
            aria-current={onUpload ? "page" : undefined}
            className={`${square} gap-[5px] px-[11px] text-[12px] font-bold ${
              onUpload ? "bg-[#5369ff] text-white" : "bg-[#eef2ff] text-[#5369ff]"
            }`}
          >
            <NavIcon name="upload" size={19} />
            <span aria-hidden="true">등록</span>
          </button>
          <button
            type="button"
            onClick={() => navigate({ name: "settings" })}
            aria-label="설정"
            aria-current={onSettings ? "page" : undefined}
            className={`${square} ${onSettings ? "bg-[#eef2ff] text-[#5369ff]" : "text-[#667085]"}`}
          >
            <NavIcon name="settings" size={20} />
          </button>
          <button
            ref={bellRef}
            type="button"
            onClick={onOpenNotifications}
            aria-expanded={notificationsOpen}
            aria-controls="notification-panel"
            aria-haspopup="dialog"
            aria-label={`읽지 않은 알림 ${unreadNotifications}개 열기`}
            className={`${square} relative bg-[#5369ff] text-white`}
          >
            <NavIcon name="bell" size={20} />
            {unreadNotifications > 0 && (
              <span className="absolute right-px top-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full border-2 border-white bg-[#c53030] px-[5px] text-[9px] font-extrabold leading-none text-white">
                {unreadNotifications}
              </span>
            )}
          </button>
        </div>
      </header>
      <nav
        aria-label="모바일 주요 메뉴"
        className="fixed inset-x-0 bottom-0 z-30 hidden min-h-[calc(72px+env(safe-area-inset-bottom))] grid-cols-4 border-t border-[#e5e7eb] bg-white/97 px-2 pb-[env(safe-area-inset-bottom)] pt-1.5 shadow-[0_-8px_28px_rgba(24,26,32,0.07)] backdrop-blur-[14px] max-md:grid"
      >
        {navItems.map((item) => {
          const active = route.name === item.route.name;
          return (
            <button
              type="button"
              key={item.route.name}
              onClick={() => navigate(item.route)}
              aria-current={active ? "page" : undefined}
              className={`flex min-h-[58px] min-w-0 flex-col items-center justify-center gap-1 rounded-xl text-[11px] ${
                active ? "bg-[#eef2ff] font-extrabold text-[#5369ff]" : "font-semibold text-[#667085]"
              }`}
            >
              <NavIcon name={item.icon} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>
    </>
  );
}
