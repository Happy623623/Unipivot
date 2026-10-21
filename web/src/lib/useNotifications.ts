import { useCallback, useEffect, useRef, useState } from "react";
import {
  errorMessage,
  fieldErrors,
  getNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  nowIso,
} from "@/api/client";
import type { AppNotification, NotificationList } from "@/types/api";

// 알림함 목록 상태. 헤더 패널(열릴 때만)과 전체 목록 화면이 각각 하나씩 쓴다.
// 읽음 처리는 응답을 기다리지 않고 먼저 화면에 반영하고, 저장하지 못하면 되돌린다(F-45와 같은 방식).
// 한쪽에서 저장한 읽음 처리는 같은 탭의 다른 목록에도 바로 반영한다(알림함 화면 위에서 패널의 "모두 읽음" 등).
// 그때 받던 중이던 쪽이 늦게 오거나 이쪽의 읽음 저장이 실패해 되돌릴 때도 그새 저장된 읽음 처리는 다시 입힌다
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
  generation: number; // 첫 쪽부터 다시 받은 횟수. 더 보기가 422로 처음부터 다시 받았는지 알아보는 데 쓴다(lib/useLoadMoreFocus.ts)
  reload: () => void;
  loadMore: () => void;
  read: (notification: AppNotification) => Promise<boolean>;
  readAll: () => Promise<boolean>;
}

// 저장된 읽음 처리. ids가 "all"이면 전체 읽음이다. 서버는 그때 보낼 때가 된 알림만 읽음으로 하므로, 누른 시각(readAt)
// 뒤에 보낼 때가 된 알림(그사이 받은 첫 쪽에 섞여 올 수 있다)에는 입히지 않는다
interface SavedRead {
  ids: string[] | "all";
  readAt: string; // 누를 때 시각(nowIso)
  unread: number; // 서버가 센 안 읽은 수
}

const listeners = new Set<(saved: SavedRead) => void>();
const KEEP = 50; // 받던 중에 들은 읽음 처리를 다시 입히려고 최근 것만 들고 있는다

function announce(saved: SavedRead): void {
  listeners.forEach((listener) => listener(saved));
}

function applyRead(items: AppNotification[], saved: SavedRead): AppNotification[] {
  const until = Date.parse(saved.readAt);
  return items.map((item) =>
    item.read_at === null &&
    (saved.ids === "all" ? Date.parse(item.scheduled_at) <= until : saved.ids.includes(item.id))
      ? { ...item, read_at: saved.readAt }
      : item,
  );
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
  const heard = useRef<{ seq: number; saved: SavedRead }[]>([]); // 이 탭에서 저장된 읽음 처리(이 목록 것 포함)
  const seq = useRef(0);

  useEffect(() => {
    const listener = (saved: SavedRead) => {
      seq.current += 1;
      heard.current = [...heard.current, { seq: seq.current, saved }].slice(-KEEP);
      setItems((current) => applyRead(current, saved));
      // 아직 목록을 받지 않은 쪽(닫혀 있던 패널)은 받을 때까지 null로 둔다 — 받기 전에는 "모두 읽음"을 막는다
      setUnread((current) => (current === null ? null : saved.unread));
    };
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  // since(seq) 뒤에 들은 읽음 처리를 list에 다시 입힌다. 안 읽은 수는 그중 마지막 것(없으면 fallback)
  const replay = useCallback((since: number, list: AppNotification[]) => {
    const missed = heard.current.filter((entry) => entry.seq > since);
    return missed.reduce((current, entry) => applyRead(current, entry.saved), list);
  }, []);
  const heardUnread = useCallback(<T extends number | null>(since: number, fallback: T): number | T => {
    const last = heard.current.at(-1);
    return last && last.seq > since ? last.saved.unread : fallback;
  }, []);
  // 요청을 보낸 뒤 들은 읽음 처리를 늦게 온 쪽에 다시 입힌다. 안 읽은 수도 그때 들은 것이 더 새것으로 본다.
  // 다만 쪽에 마지막 "모두 읽음" 뒤에 보낼 때가 된 안 읽은 알림이 있으면 서버가 그 뒤에 센 것이라 쪽의 수를 쓴다
  const catchUp = useCallback(
    (since: number, page: NotificationList) => {
      const lastAll = [...heard.current].reverse().find((entry) => entry.seq > since && entry.saved.ids === "all");
      const after = lastAll ? Date.parse(lastAll.saved.readAt) : Infinity;
      const counted = page.items.some((item) => item.read_at === null && Date.parse(item.scheduled_at) > after);
      return {
        items: replay(since, page.items),
        unread: counted ? page.unread_count : heardUnread(since, page.unread_count),
      };
    },
    [heardUnread, replay],
  );

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
    const since = seq.current;
    getNotifications({ unreadOnly })
      .then((page) => {
        if (token !== latest.current) return;
        const fresh = catchUp(since, page);
        setItems(fresh.items);
        setUnread(fresh.unread);
        setCursor(page.next_cursor);
        setLoading(false);
      })
      .catch((cause: unknown) => {
        if (token !== latest.current) return;
        setError(errorMessage(cause, "알림을 불러오지 못했어요."));
        setLoading(false);
      });
  }, [enabled, unreadOnly, round, catchUp]);

  const reload = useCallback(() => setRound((value) => value + 1), []);

  const loadMore = useCallback(() => {
    if (!cursor || loadingMore) return;
    const token = latest.current;
    setLoadingMore(true);
    const since = seq.current;
    getNotifications({ unreadOnly, cursor })
      .then((page) => {
        if (token !== latest.current) return;
        const fresh = catchUp(since, page);
        setLoadingMore(false);
        setItems((current) => [...current, ...fresh.items]);
        setUnread(fresh.unread);
        setCursor(page.next_cursor);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (token !== latest.current) return;
        setLoadingMore(false);
        // 조건이 바뀐 목록의 cursor는 details.fields.cursor가 있는 422다. 처음부터 다시 받는다
        if (fieldErrors(cause).cursor) {
          setCursor(null);
          setLoading(true); // 다시 받기 effect보다 먼저 "받는 중"으로 둔다(그 사이 그리기가 마지막 쪽처럼 보이지 않게)
          reload();
          return;
        }
        setError(errorMessage(cause, "알림을 더 불러오지 못했어요."));
      });
  }, [catchUp, cursor, loadingMore, reload, unreadOnly]);

  // 저장하지 못한 읽음 표시를 되돌린다. 그사이 저장된 읽음 처리(다른 목록의 "모두 읽음" 등)는 다시 입히고,
  // 안 읽은 수도 그때 들은 것이 있으면 그것을 쓴다(누르기 전 수로 되돌리면 배지가 서버보다 많아진다)
  const undo = useCallback(
    (ids: string[], start: number, before: number | null) => {
      setItems((current) =>
        replay(
          start,
          current.map((item) => (ids.includes(item.id) ? { ...item, read_at: null } : item)),
        ),
      );
      setUnread(heardUnread(start, before));
    },
    [heardUnread, replay],
  );

  // 읽음 처리한 알림은 "안 읽은 알림만" 목록에서도 바로 사라지지 않는다(누른 자리가 그대로 보여야 한다)
  const read = useCallback(
    async (notification: AppNotification) => {
      if (notification.read_at !== null) return true;
      const before = unread;
      const start = seq.current;
      const readAt = nowIso();
      mark(setItems, [notification.id], readAt);
      setUnread(before === null ? null : Math.max(0, before - 1));
      try {
        announce({ ids: [notification.id], readAt, unread: await markNotificationRead(notification.id) });
        return true;
      } catch {
        undo([notification.id], start, before);
        return false;
      }
    },
    [undo, unread],
  );

  // 받아 둔 쪽에 안 읽은 알림이 없어도 아래 쪽에 남아 있을 수 있어 전체 읽음은 서버가 센 수로 맞춘다.
  // 목록을 받기 전(unread === null)에는 되돌릴 수가 없어 부르지 않는다(부르는 쪽도 단추를 막는다)
  const readAll = useCallback(async () => {
    if (unread === null || unread === 0) return true;
    const ids = items.filter((item) => item.read_at === null).map((item) => item.id);
    const before = unread;
    const start = seq.current;
    const readAt = nowIso();
    mark(setItems, ids, readAt);
    setUnread(0);
    try {
      announce({ ids: "all", readAt, unread: await markAllNotificationsRead() });
      return true;
    } catch {
      undo(ids, start, before);
      return false;
    }
  }, [items, undo, unread]);

  return {
    items,
    unread,
    loading,
    error,
    hasMore: cursor !== null,
    loadingMore,
    generation: round,
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
