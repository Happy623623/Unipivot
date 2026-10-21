import { useCallback, useRef } from "react";

// 누른 버튼이 일이 끝나 다른 것으로 바뀌어 사라질 때(예: "캘린더에 넣기" → "캘린더에 넣었어요"), 초점이 <body>로
// 빠져 키보드·화면 읽기 사용자가 자리를 잃지 않게 그 자리에 새로 생긴 것으로 넘긴다.
// mark(key): 누를 때 부른다. 그때 초점이 화면 안에 있었을 때만 기억한다(마우스로 눌러 초점이 없으면 옮기지 않는다).
// target(key): 새로 생긴 요소의 ref로 준다. 생기는 순간 초점이 <body>에 있으면(버튼이 사라져서) 그 요소로 옮긴다.
// 요소에는 tabIndex={-1}을 준다(읽기 전용 글이라 Tab 순서에는 넣지 않는다)
export default function useFocusHandoff() {
  const pending = useRef<string | null>(null);

  const mark = useCallback((key: string) => {
    const active = document.activeElement;
    pending.current = active && active !== document.body ? key : null;
  }, []);

  const target = useCallback(
    (key: string) => (element: HTMLElement | null) => {
      if (!element || pending.current !== key) return;
      pending.current = null;
      if (document.activeElement === document.body || document.activeElement === null) {
        element.focus({ preventScroll: true });
      }
    },
    [],
  );

  const cancel = useCallback(() => {
    pending.current = null;
  }, []);

  return { mark, target, cancel };
}

// 다음 그리기 뒤에, 초점이 <body>로 빠졌으면(누른 것이 사라짐) 후보 중 아직 화면에 있는 첫 요소로 옮긴다.
// 후보는 그때 읽도록 함수로 받는다(ref는 다시 그린 뒤에 바뀐다)
export function focusIfLost(candidates: () => (HTMLElement | null | undefined)[]): void {
  requestAnimationFrame(() => {
    if (document.activeElement !== document.body && document.activeElement !== null) return;
    candidates()
      .find((element) => element?.isConnected)
      ?.focus({ preventScroll: true });
  });
}
