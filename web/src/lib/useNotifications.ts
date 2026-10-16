import { useCallback, useEffect, useRef, useState } from "react";
import {
  errorMessage,
  fieldErrors,
  getNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  nowIso,
} from "@/api/client";
import type { AppNotification } from "@/types/api";

// 알림함 목록 상태. 헤더 패널(열릴 때만)과 전체 목록 화면이 각각 하나씩 쓴다.
// 읽음 처리는 응답을 기다리지 않고 먼저 화면에 반영하고, 저장하지 못하면 되돌린다(F-45와 같은 방식).
interface Options {
  enabled?: boolean; // 패널은 열려 있을 때만 받는다
  unreadOnly?: boolean;
}

export interface NotificationsState {
  items: AppNotification[];
  unread: number | null; // 아직 목록을 받지 못했으면 null (헤더는 내 정보의 수를 쓴다)
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  loadingMore: boolean;
  reload: () => void;
  loadMore: () => void;
  read: (notification: AppNotification) => Promise<boolean>;
  readAll: () => Promise<boolean>;
}

export default function useNotifications({
  enabled = true,
  unreadOnly = false,
}: Options = {}): NotificationsState {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState<number | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState(0);
  const latest = useRef(0); // 늦게 온 응답은 버린다
  const shown = useRef(unreadOnly); // 지금 들고 있는 목록이 어느 필터의 것인지

  // 첫 쪽. 다시 받는 동안 이미 받은 알림은 그대로 둬서 패널을 다시 열 때 빈 화면이 보이지 않게 한다
  useEffect(() => {
    if (!enabled) return;
    const token = (latest.current += 1);
    // 필터가 바뀌면 앞 필터의 목록과 cursor를 먼저 버린다(옛 cursor로 다음 쪽을 부르면 422다)
    if (shown.current !== unreadOnly) {
      shown.current = unreadOnly;
      setItems([]);
      setCursor(null);
    }
    setLoading(true);
    setError(null);
    // 다음 쪽을 받던 중에 필터가 바뀌면 그 응답을 버린다. 여기서 풀어 주지 않으면 "더 보기"가 멈춘다
    setLoadingMore(false);
    getNotifications({ unreadOnly })
      .then((page) => {
        if (token !== latest.current) return;
        setItems(page.items);
        setUnread(page.unread_count);
        setCursor(page.next_cursor);
        setLoading(false);
      })
      .catch((cause: unknown) => {
        if (token !== latest.current) return;
        setError(errorMessage(cause, "알림을 불러오지 못했어요."));
        setLoading(false);
      });
  }, [enabled, unreadOnly, round]);

  const reload = useCallback(() => setRound((value) => value + 1), []);

  const loadMore = useCallback(() => {
    if (!cursor || loadingMore) return;
    const token = latest.current;
    setLoadingMore(true);
    getNotifications({ unreadOnly, cursor })
      .then((page) => {
        if (token !== latest.current) return;
        setLoadingMore(false);
        setItems((current) => [...current, ...page.items]);
        setUnread(page.unread_count);
        setCursor(page.next_cursor);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (token !== latest.current) return;
        setLoadingMore(false);
        // 조건이 바뀐 목록의 cursor는 details.fields.cursor가 있는 422다. 처음부터 다시 받는다
        if (fieldErrors(cause).cursor) {
          setCursor(null);
          reload();
          return;
        }
        setError(errorMessage(cause, "알림을 더 불러오지 못했어요."));
      });
  }, [cursor, loadingMore, reload, unreadOnly]);

  // 읽음 처리한 알림은 "안 읽은 알림만" 목록에서도 바로 사라지지 않는다(누른 자리가 그대로 보여야 한다)
  const read = useCallback(
    async (notification: AppNotification) => {
      if (notification.read_at !== null) return true;
      const before = unread;
      mark(setItems, [notification.id], nowIso());
      setUnread(before === null ? null : Math.max(0, before - 1));
      try {
        setUnread(await markNotificationRead(notification.id));
        return true;
      } catch {
        mark(setItems, [notification.id], null);
        setUnread(before);
        return false;
      }
    },
    [unread],
  );

  // 받아 둔 쪽에 안 읽은 알림이 없어도 아래 쪽에 남아 있을 수 있어 전체 읽음은 서버가 센 수로 맞춘다.
  // 목록을 받기 전(unread === null)에는 되돌릴 수가 없어 부르지 않는다(부르는 쪽도 단추를 막는다)
  const readAll = useCallback(async () => {
    if (unread === null || unread === 0) return true;
    const ids = items.filter((item) => item.read_at === null).map((item) => item.id);
    const before = unread;
    mark(setItems, ids, nowIso());
    setUnread(0);
    try {
      setUnread(await markAllNotificationsRead());
      return true;
    } catch {
      mark(setItems, ids, null);
      setUnread(before);
      return false;
    }
  }, [items, unread]);

  return {
    items,
    unread,
    loading,
    error,
    hasMore: cursor !== null,
    loadingMore,
    reload,
    loadMore,
    read,
    readAll,
  };
}

type SetItems = (update: (current: AppNotification[]) => AppNotification[]) => void;

function mark(setItems: SetItems, ids: string[], readAt: string | null): void {
  setItems((current) =>
    current.map((item) => (ids.includes(item.id) ? { ...item, read_at: readAt } : item)),
  );
}
