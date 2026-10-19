import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage, fieldErrors, getDocuments } from "@/api/client";
import type { MyFile } from "@/types/api";

// 문서함 목록 상태 (F-44). 첫 쪽을 받고 "더 보기"로 다음 쪽(cursor)을 이어 붙인다.
// 다음 쪽의 cursor가 맞지 않으면(422 details.fields.cursor) 받아 둔 목록을 버리고 처음부터 다시 받는다
export interface DocumentsState {
  items: MyFile[];
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  loadingMore: boolean;
  reload: () => void;
  loadMore: () => void;
}

export default function useDocuments(): DocumentsState {
  const [items, setItems] = useState<MyFile[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState(0);
  const latest = useRef(0); // 늦게 온 응답은 버린다

  // 첫 쪽. 다시 받는 동안 이미 받은 목록은 그대로 둔다(빈 화면이 번쩍이지 않게)
  useEffect(() => {
    const token = (latest.current += 1);
    setLoading(true);
    setError(null);
    setLoadingMore(false);
    getDocuments()
      .then((page) => {
        if (token !== latest.current) return;
        setItems(page.items);
        setCursor(page.next_cursor);
        setLoading(false);
      })
      .catch((cause: unknown) => {
        if (token !== latest.current) return;
        setError(errorMessage(cause, "문서함을 불러오지 못했어요. 잠시 후 다시 시도해 주세요."));
        setLoading(false);
      });
  }, [round]);

  const reload = useCallback(() => setRound((value) => value + 1), []);

  const loadMore = useCallback(() => {
    if (!cursor || loadingMore || loading) return;
    const token = latest.current;
    setLoadingMore(true);
    getDocuments(cursor)
      .then((page) => {
        if (token !== latest.current) return;
        setLoadingMore(false);
        setItems((current) => [...current, ...page.items]);
        setCursor(page.next_cursor);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (token !== latest.current) return;
        setLoadingMore(false);
        // 다시 받다가 실패해도 "다시 시도"가 보이게 받아 둔 목록을 비운다(빈 화면 안내가 그 버튼을 준다)
        if (fieldErrors(cause).cursor) {
          setItems([]);
          setCursor(null);
          reload();
          return;
        }
        setError(errorMessage(cause, "문서함을 더 불러오지 못했어요. 다시 눌러 주세요."));
      });
  }, [cursor, loading, loadingMore, reload]);

  return { items, loading, error, hasMore: cursor !== null, loadingMore, reload, loadMore };
}
