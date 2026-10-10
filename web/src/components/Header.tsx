import { useState, type ReactNode } from "react";
import { MOCK_NOW } from "@/api/client";
import { useAppShell } from "@/components/AppShell";
import { formatRelativeTime } from "@/lib/format";
import type { AppNotification, NotificationType } from "@/types/api";
import type { Route } from "@/types/route";

interface HeaderProps {
  title: string;
  subtitle: string;
  action?: ReactNode;
}

function getNotificationRoute(notification: AppNotification): Route {
  if (notification.link.type === "opportunity") {
    return {
      name: "opportunity",
      id: notification.link.id,
      focus: notification.link.focus,
    };
  }
  if (notification.link.type === "planner_task") return { name: "planner" };
  // lms_* 알림의 link.id는 과제·자료·공지 ID라서 과목 이동에는 course_id를 쓴다
  const courseId = notification.link.course_id;
  if (!courseId) return { name: "academics" };
  if (notification.link.type === "lms_module_item") {
    return { name: "course", id: courseId, tab: "materials" };
  }
  if (notification.link.type === "lms_announcement") {
    return { name: "course", id: courseId, tab: "announcements" };
  }
  return { name: "course", id: courseId, tab: "assignments" };
}

function getNotificationDot(type: NotificationType): string {
  if (type === "deadline_soon" || type === "task_due") return "bg-[#c53030]";
  if (type === "profile_needed") return "bg-[#b7791f]";
  if (type === "schedule_change") return "bg-[#a0a4ab]";
  return "bg-[#4f6ef7]";
}

export default function Header({ title, subtitle, action }: HeaderProps) {
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const {
    notifications,
    unreadNotifications,
    markNotificationRead,
    markAllNotificationsRead,
    navigate,
  } = useAppShell();

  const openNotification = async (notification: AppNotification) => {
    if (notification.read_at === null) {
      await markNotificationRead(notification.id);
    }
    navigate(getNotificationRoute(notification));
    setNotificationsOpen(false);
  };

  return (
    <>
      <header className="flex items-center justify-between gap-6">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h1 className="truncate text-[28px] font-bold leading-[1.45] text-[#181a20]">{title}</h1>
            {action}
          </div>
          <p className="mt-[2px] text-[14px] leading-[1.45] text-[#667085]">{subtitle}</p>
        </div>
        <button
          type="button"
          onClick={() => setNotificationsOpen(true)}
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
      <div
        className={`fixed inset-0 z-40 bg-[#181a20]/20 transition-opacity duration-300 ${
          notificationsOpen
            ? "pointer-events-auto opacity-100"
            : "pointer-events-none opacity-0"
        }`}
        onClick={() => setNotificationsOpen(false)}
        aria-hidden="true"
      />
      <aside
        className={`fixed inset-y-0 right-0 z-50 flex w-[380px] max-w-[92vw] flex-col bg-white p-6 shadow-[-16px_0_50px_rgba(24,26,32,0.12)] transition-transform duration-300 ease-out ${
          notificationsOpen ? "translate-x-0" : "translate-x-full"
        }`}
        aria-label="알림 패널"
        aria-hidden={!notificationsOpen}
      >
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-[20px] font-bold">알림</h2>
            <p className="mt-1 text-[12px] text-[#667085]">
              읽지 않은 알림 {unreadNotifications}개
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={markAllNotificationsRead}
              disabled={unreadNotifications === 0}
              className="text-[12px] font-semibold text-[#4f6ef7] disabled:cursor-default disabled:text-[#a0a4ab]"
            >
              모두 읽음
            </button>
            <button
              type="button"
              onClick={() => setNotificationsOpen(false)}
              className="flex size-9 items-center justify-center rounded-[10px] bg-[#f7f8fa] text-[20px] text-[#667085]"
              aria-label="알림 닫기"
            >
              ×
            </button>
          </div>
        </div>
        <div className="mt-6 flex flex-col gap-2">
          {notifications.map((notification, index) => (
            <button
              type="button"
              key={notification.id}
              onClick={() => openNotification(notification)}
              className={`${notificationsOpen ? "notification-item" : ""} rounded-[14px] border border-transparent p-4 text-left transition hover:border-[#cfd7ff] ${
                notification.read_at === null ? "bg-[#eef2ff]" : "bg-white"
              }`}
              style={{ animationDelay: `${index * 70}ms` }}
            >
              <span className="flex items-start gap-3">
                <span
                  className={`mt-1.5 size-2 shrink-0 rounded-full ${getNotificationDot(notification.type)}`}
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-start justify-between gap-3">
                    <b className="text-[14px] font-semibold">{notification.title}</b>
                    <span className="shrink-0 text-[11px] text-[#a0a4ab]">
                      {formatRelativeTime(notification.scheduled_at, MOCK_NOW)}
                    </span>
                  </span>
                  {notification.body && (
                    <span className="mt-1 block text-[12px] leading-5 text-[#667085]">
                      {notification.body}
                    </span>
                  )}
                </span>
              </span>
            </button>
          ))}
          {notifications.length === 0 && (
            <div className="flex min-h-52 items-center justify-center rounded-[14px] border border-dashed border-[#e5e7eb] text-[14px] font-semibold text-[#667085]">
              새 알림이 없어요
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
