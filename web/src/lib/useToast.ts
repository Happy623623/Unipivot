import { useCallback, useEffect, useRef, useState } from "react";

// 화면 아래 안내(components/Toast)의 글과 번호. 같은 글이 이어 떠도 번호가 바뀌어 화면 읽기 프로그램이 다시 읽는다
export interface ToastState {
  text: string;
  id: number;
}

// 안내를 잠깐 띄운다. 안내가 이어 뜨면 앞 안내의 타이머를 지워 새 안내가 일찍 사라지지 않게 한다
export default function useToast(duration = 2200): [ToastState, (text: string) => void] {
  const [toast, setToast] = useState<ToastState>({ text: "", id: 0 });
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const show = useCallback(
    (text: string) => {
      clearTimeout(timer.current);
      setToast((current) => ({ text, id: current.id + 1 }));
      timer.current = setTimeout(() => setToast((current) => ({ ...current, text: "" })), duration);
    },
    [duration],
  );
  return [toast, show];
}
