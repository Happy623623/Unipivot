import { notifications } from "@/mocks/notifications";
import type { AppNotification } from "@/types/api";

const notificationState: AppNotification[] = JSON.parse(
  JSON.stringify(notifications),
) as AppNotification[];

export function getStoredNotifications(): AppNotification[] {
  return notificationState;
}

export function readStoredNotification(
  id: string,
  readAt: string,
): AppNotification[] {
  const notification = notificationState.find((item) => item.id === id);
  if (notification && notification.read_at === null) {
    notification.read_at = readAt;
  }
  return notificationState;
}

export function readAllStoredNotifications(readAt: string): AppNotification[] {
  notificationState.forEach((notification) => {
    if (notification.read_at === null) notification.read_at = readAt;
  });
  return notificationState;
}
