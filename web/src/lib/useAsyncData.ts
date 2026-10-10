import { useEffect, useState } from "react";

interface AsyncData<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

export default function useAsyncData<T>(load: () => Promise<T>, dependencies: unknown[]): AsyncData<T> {
  const [state, setState] = useState<AsyncData<T>>({
    data: null,
    error: null,
    loading: true,
  });

  useEffect(() => {
    let active = true;
    setState({ data: null, error: null, loading: true });

    load()
      .then((data) => {
        if (active) setState({ data, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (active) {
          setState({
            data: null,
            error: error instanceof Error ? error.message : "데이터를 불러오지 못했어요.",
            loading: false,
          });
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
