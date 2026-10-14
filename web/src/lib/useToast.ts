import { useCallback, useEffect, useRef, useState } from "react";

// 안내의 버튼 하나(예: 홈의 "관심 탭 보기")
export interface ToastAction {
  label: string;
  onAction: () => void;
}

// 화면 아래 안내(components/Toast)의 글·번호·버튼. 같은 글이 이어 떠도 번호가 바뀌어 화면 읽기 프로그램이 다시 읽는다
export interface ToastState {
  text: string;
  id: number;
  action?: ToastAction;
}

// 안내를 붙잡아 두는 까닭. 안내 위에 마우스가 있거나(hover) 안내 안에 초점이 있으면(focus) 닫지 않는다
export type ToastHold = (reason: "hover" | "focus", on: boolean) => void;

// 안내를 잠깐 띄운다. 안내가 이어 뜨면 앞 안내의 타이머를 지워 새 안내가 일찍 사라지지 않게 한다.
// 버튼이 있으면 누를 시간을 두 배로 준다. 세 번째 값은 안내를 바로 닫고, 네 번째 값(Toast의 onHold)은
// 붙잡는 동안 타이머를 멈췄다가 놓으면 기본 시간 뒤에 닫는다. 새 안내를 띄우거나 닫으면 붙잡은 것도 푼다
export default function useToast(duration = 2200): [ToastState, (text: string, action?: ToastAction) => void, () => void, ToastHold] {
  const [toast, setToast] = useState<ToastState>({ text: "", id: 0 });
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const holding = useRef({ hover: false, focus: false });
  useEffect(() => () => clearTimeout(timer.current), []);
  const close = useCallback(() => setToast((current) => (current.text ? { id: current.id, text: "" } : current)), []);
  const hide = useCallback(() => {
    clearTimeout(timer.current);
    holding.current = { hover: false, focus: false };
    close();
  }, [close]);
  const show = useCallback(
    (text: string, action?: ToastAction) => {
      clearTimeout(timer.current);
      holding.current = { hover: false, focus: false };
      setToast((current) => ({ text, id: current.id + 1, action }));
      timer.current = setTimeout(close, action ? duration * 2 : duration);
    },
    [close, duration],
  );
  const hold = useCallback<ToastHold>(
    (reason, on) => {
      holding.current[reason] = on;
      clearTimeout(timer.current);
      if (!holding.current.hover && !holding.current.focus) timer.current = setTimeout(close, duration);
    },
    [close, duration],
  );
  return [toast, show, hide, hold];
}
