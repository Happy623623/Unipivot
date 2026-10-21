import { useEffect, useState } from "react";

interface AsyncData<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

// keep: 다시 받는 동안(loading은 true)과 다시 받지 못했을 때(error가 찬다) 지난 데이터를 그대로 둔다.
// 화면이 뼈대·오류 글로 바뀌며 열린 창·안내가 사라지지 않게 할 때 쓴다
export default function useAsyncData<T>(
  load: () => Promise<T>,
  dependencies: unknown[],
  { keep = false }: { keep?: boolean } = {},
): AsyncData<T> {
  const [state, setState] = useState<AsyncData<T>>({
    data: null,
    error: null,
    loading: true,
  });

  useEffect(() => {
    let active = true;
    setState((current) => ({ data: keep ? current.data : null, error: null, loading: true }));

    load()
      .then((data) => {
        if (active) setState({ data, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (active) {
          setState((current) => ({
            data: keep ? current.data : null,
            error: error instanceof Error ? error.message : "데이터를 불러오지 못했어요.",
            loading: false,
          }));
        }
      });

    return () => {
      active = false;
    };
    // The caller controls reloads through the dependency list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies);

  return state;
}
