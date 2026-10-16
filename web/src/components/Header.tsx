import { useState, type ReactNode } from "react";
import { useAppShell } from "@/components/AppShell";
import NotificationPanel from "@/components/NotificationPanel";

interface HeaderProps {
  title: string;
  subtitle: string;
  action?: ReactNode;
}

// 화면 제목과 알림 버튼. 배지 숫자는 내 정보의 안 읽은 알림 수이고, 알림함을 열면 목록이 센 수로 맞춘다
export default function Header({ title, subtitle, action }: HeaderProps) {
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const { unreadNotifications } = useAppShell();

  return (
    <>
      <header className="flex items-center justify-between gap-6">
        <div className="min-w-0">
          {/* 좁은 화면에서 제목과 버튼이 한 줄에 다 들어가지 않으면 버튼을 다음 줄로 내린다 */}
          <div className="flex items-center gap-3 max-[760px]:flex-wrap max-[760px]:gap-y-1">
            <h1 className="truncate text-[28px] font-bold leading-[1.45] text-[#181a20]">{title}</h1>
            {action}
          </div>
          <p className="mt-[2px] text-[14px] leading-[1.45] text-[#667085]">{subtitle}</p>
        </div>
        <button
          type="button"
          onClick={() => setNotificationsOpen(true)}
          aria-expanded={notificationsOpen}
          aria-controls="notification-panel"
          aria-haspopup="dialog"
          className="relative flex size-10 shrink-0 items-center justify-center rounded-full bg-[#4f6ef7] text-white transition hover:-translate-y-0.5 hover:bg-[#425fe0] hover:shadow-[0_6px_16px_rgba(79,110,247,0.24)] active:scale-95"
          aria-label={`읽지 않은 알림 ${unreadNotifications}개 열기`}
        >
          <svg
            aria-hidden="true"
            width="19"
            height="19"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
            <path d="M10 21h4" />
          </svg>
          {unreadNotifications > 0 && (
            <span className="absolute -right-1 -top-1 flex min-w-5 items-center justify-center rounded-full bg-[#c53030] px-1.5 py-0.5 text-[10px] font-bold leading-4 text-white">
              {unreadNotifications}
            </span>
          )}
        </button>
      </header>
      <NotificationPanel open={notificationsOpen} onClose={() => setNotificationsOpen(false)} />
    </>
  );
}
