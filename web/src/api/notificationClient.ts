import {
  getStoredNotifications,
  readAllStoredNotifications,
  readStoredNotification,
} from "@/mocks/notificationStore";
import { mockNow } from "@/mocks/account";
import type { AppNotification } from "@/types/api";

const WAIT_MS = 300;

function respond(value: AppNotification[]): Promise<AppNotification[]> {
  return new Promise((resolve) => {
    setTimeout(
      () =>
        resolve(
          JSON.parse(JSON.stringify(value)) as AppNotification[],
        ),
      WAIT_MS,
    );
  });
}

export function getNotifications(): Promise<AppNotification[]> {
  return respond(getStoredNotifications());
}

export function markNotificationRead(
  id: string,
): Promise<AppNotification[]> {
  return respond(readStoredNotification(id, mockNow));
}

export function markAllNotificationsRead(): Promise<AppNotification[]> {
  return respond(readAllStoredNotifications(mockNow));
}
