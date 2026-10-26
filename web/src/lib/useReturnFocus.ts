import { useCallback, useRef } from "react";

// 칸(요약 칸 등)을 연 버튼을 기억했다가, 칸을 닫으면 그 버튼으로 초점을 돌려준다. 닫기 버튼이 칸과 함께 사라져
// 초점이 <body>로 빠지면 키보드·화면 읽기 사용자가 자리를 잃는다.
// remember(): 열 때 부른다. 그때 초점이 화면 안에 있었을 때만 기억한다(초점이 없었으면 옮기지 않는다).
// restore(fallback): 닫을 때 부른다. 연 버튼이 그새 사라졌으면 fallback()이 주는 요소로 간다
export default function useReturnFocus() {
  const opener = useRef<HTMLElement | null>(null);

  const remember = useCallback(() => {
    const active = document.activeElement;
    opener.current = active instanceof HTMLElement && active !== document.body ? active : null;
  }, []);

  const restore = useCallback((fallback?: () => HTMLElement | null | undefined) => {
    const target = opener.current;
    opener.current = null;
    if (!target) return;
    requestAnimationFrame(() => {
      const element = target.isConnected ? target : fallback?.();
      element?.focus({ preventScroll: true });
    });
  }, []);

  return { remember, restore };
}
