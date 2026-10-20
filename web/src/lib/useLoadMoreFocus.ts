import { useEffect, useRef, useState, type RefObject } from "react";

// "더 보기"를 누른 뒤의 초점과 화면 읽기 안내(문서함·알림함).
// 다음 쪽이 와도 더 보기가 남으면 초점은 그 버튼에 그대로 있다(Button의 busy). 마지막 쪽이라 버튼이 사라지면
// 초점이 <body>로 빠지므로, 새로 온 줄(data-row) 중 화면에서 첫 줄로 옮긴다. 다음 쪽의 cursor가 맞지 않아(422)
// 목록을 처음부터 다시 받으면(generation이 바뀐다) 화면의 첫 줄로 옮긴다.
// 초점은 누를 때 초점이 있었고(키보드) 지금 <body>로 빠졌을 때만 옮긴다 — 마우스로 눌러 초점이 없던 때(Safari)나
// 그새 다른 곳으로 간 때는 그대로 둔다. listKey가 바뀌면(알림함 탭) 앞 목록의 안내와 누른 더 보기를 잊는다
export interface LoadMoreFocus {
  status: string; // 늘 두는 sr-only role="status"에 넣는 글
  loadMore: () => void; // 화면의 더 보기 버튼에 준다
}

interface Options {
  listRef: RefObject<HTMLElement | null>;
  ids: string[]; // 지금 목록의 줄 id(받은 순서). 줄에는 data-row={id}를 단다
  loading: boolean; // 첫 쪽을 (다시) 받는 중
  loadingMore: boolean;
  hasMore: boolean;
  error: string | null;
  generation: number; // 첫 쪽부터 다시 받은 횟수(useDocuments·useNotifications)
  loadMore: () => void;
  listKey?: string;
}

interface Pending {
  ids: Set<string>; // 누를 때 이미 있던 줄
  last: string | undefined;
  generation: number;
  focused: boolean; // 누를 때 초점이 어딘가(그 버튼)에 있었는지
}

type Target = "first" | "fresh" | "last" | null;

export default function useLoadMoreFocus(options: Options): LoadMoreFocus {
  const { listRef, ids, loading, loadingMore, hasMore, error, generation, loadMore, listKey } = options;
  const pending = useRef<Pending | null>(null);
  const [status, setStatus] = useState("");
  const [shownKey, setShownKey] = useState(listKey);

  // 목록이 바뀌면(탭) 앞 목록의 안내와 기다리던 더 보기를 버린다(그리는 중에 맞춘다)
  if (shownKey !== listKey) {
    setShownKey(listKey);
    setStatus("");
    pending.current = null;
  }

  const start = () => {
    if (!loadingMore && !loading && hasMore) {
      const doc = listRef.current?.ownerDocument;
      const active = doc?.activeElement;
      pending.current = { ids: new Set(ids), last: ids.at(-1), generation, focused: Boolean(active && active !== doc?.body) };
      setStatus("다음 쪽을 불러오고 있어요.");
    }
    loadMore();
  };

  useEffect(() => {
    const request = pending.current;
    if (!request || loading || loadingMore) return; // 아직 오는 중(422 뒤 다시 받는 첫 쪽 포함)
    pending.current = null;
    const restarted = generation !== request.generation;
    const fresh = new Set(ids.filter((id) => !request.ids.has(id)));
    let target: Target = null;
    if (restarted) {
      setStatus(ids.length > 0 ? "목록이 바뀌어 처음부터 다시 불러왔어요." : (error ?? "목록을 처음부터 다시 받았는데 비어 있어요."));
      if (ids.length > 0) target = "first";
    } else if (fresh.size === 0 && hasMore) {
      setStatus(error ?? "더 불러오지 못했어요. 다시 눌러 주세요."); // 실패. 버튼과 초점이 남아 있다
    } else if (fresh.size === 0) {
      setStatus("더 불러올 항목이 없어요. 마지막 목록이에요."); // 앞 쪽이 딱 끝에서 끊긴 때
      target = "last";
    } else {
      setStatus(hasMore ? `${fresh.size}개를 더 불러왔어요.` : `${fresh.size}개를 더 불러왔어요. 마지막 목록이에요.`);
      if (!hasMore) target = "fresh";
    }
    const list = listRef.current;
    if (!target || !list || !request.focused) return;
    const doc = list.ownerDocument;
    if (doc.activeElement && doc.activeElement !== doc.body) return; // 그새 다른 곳으로 갔다
    // 화면 순서로 찾는다(문서함은 과목별로 묶어 그려서 받은 순서와 다르다)
    const rows = [...list.querySelectorAll<HTMLElement>("[data-row]")];
    const row =
      target === "first"
        ? rows[0]
        : target === "fresh"
          ? rows.find((element) => fresh.has(element.dataset.row ?? ""))
          : rows.find((element) => element.dataset.row === request.last);
    row?.focus();
  }, [error, generation, hasMore, ids, listRef, loading, loadingMore]);

  return { status, loadMore: start };
}
