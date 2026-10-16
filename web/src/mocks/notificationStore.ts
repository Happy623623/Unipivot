import { notifications } from "@/mocks/notifications";
import type { AppNotification, NotificationList } from "@/types/api";

const notificationState: AppNotification[] = JSON.parse(
  JSON.stringify(notifications),
) as AppNotification[];

// 목 알림은 여섯 건이라 쪽이 넘어가지 않는다(next_cursor는 늘 null)
export function listStoredNotifications(unreadOnly: boolean): NotificationList {
  const items = notificationState
    .filter((item) => !unreadOnly || item.read_at === null)
    .map((item) => ({ ...item }));
  return { items, unread_count: countUnread(), next_cursor: null };
}

export function readStoredNotifications(ids: string[], readAt: string): number {
  notificationState.forEach((notification) => {
    if (ids.includes(notification.id) && notification.read_at === null) {
      notification.read_at = readAt;
    }
  });
  return countUnread();
}

export function readAllStoredNotifications(readAt: string): number {
  notificationState.forEach((notification) => {
    if (notification.read_at === null) notification.read_at = readAt;
  });
  return countUnread();
}

function countUnread(): number {
  return notificationState.filter((item) => item.read_at === null).length;
}
