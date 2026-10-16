import { nowIso } from "@/api/client";
import { formatRelativeTime } from "@/lib/format";
import type { AppNotification, NotificationType } from "@/types/api";

interface NotificationRowProps {
  notification: AppNotification;
  onOpen: (notification: AppNotification) => void;
  enterDelay?: number; // 패널이 열릴 때 한 줄씩 나타나는 시간차(ms). 없으면 그냥 그린다
}

// 알림 종류별 점 색. 급한 것은 빨강, 입력이 필요한 것은 노랑, 안내는 회색이다
function dotColor(type: NotificationType): string {
  if (type === "deadline_soon" || type === "task_due") return "bg-[#c53030]";
  if (type === "profile_needed") return "bg-[#b7791f]";
  if (type === "schedule_change") return "bg-[#a0a4ab]";
  return "bg-[#4f6ef7]";
}

// 알림 한 줄. 헤더 패널과 알림함 화면이 같은 줄을 쓴다. 안 읽은 알림은 연한 주색 바탕이다
export default function NotificationRow({ notification, onOpen, enterDelay }: NotificationRowProps) {
  const unread = notification.read_at === null;
  return (
    <button
      type="button"
      onClick={() => onOpen(notification)}
      className={`${enterDelay === undefined ? "" : "notification-item"} w-full rounded-[14px] border border-transparent p-4 text-left transition hover:border-[#cfd7ff] ${
        unread ? "bg-[#eef2ff]" : "bg-white"
      }`}
      style={enterDelay === undefined ? undefined : { animationDelay: `${enterDelay}ms` }}
    >
      <span className="flex items-start gap-3">
        {/* 안 읽음은 바탕색으로도 보이지만, 화면 읽기 프로그램에는 글로 알린다 */}
        {unread && <span className="sr-only">안 읽음</span>}
        <span className={`mt-1.5 size-2 shrink-0 rounded-full ${dotColor(notification.type)}`} />
        <span className="min-w-0 flex-1">
          <span className="flex items-start justify-between gap-3">
            <b className="text-[14px] font-semibold">{notification.title}</b>
            <span className="shrink-0 text-[11px] text-[#a0a4ab]">
              {formatRelativeTime(notification.scheduled_at, nowIso())}
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
  );
}
