import { useEffect, useRef, type RefObject } from "react";

// 창(components/Modal.tsx)의 키보드 초점.
// 열리면 창으로 초점을 옮기고(창 자체 — 제목을 읽고, 탈퇴처럼 되돌릴 수 없는 버튼에 바로 가지 않게),
// Tab·Shift+Tab은 창 안에서 돌고, Esc는 닫기와 같고, 닫히면 연 버튼으로 초점을 돌려준다.
// 연 버튼이 그새 사라졌으면(메뉴 안의 버튼 등) fallback(메뉴를 연 버튼 등)으로, 그것도 없거나 사용자가 이미 다른 곳에
// 있으면 돌려주지 않는다. 창이 여러 개 열리면 맨 위(나중에 연) 창만 키와 초점을 맡는다
const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

const openDialogs: HTMLElement[] = []; // 열린 창, 나중에 연 것이 끝

function focusables(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((element) => element.getClientRects().length > 0);
}

// Esc를 창 닫기로 보지 않는 때: 한글 조합 중(조합 취소), 다른 곳이 이미 처리함, 펼친 select를 접는 Esc(브라우저마다 다르다)
function escapeBelongsElsewhere(event: KeyboardEvent): boolean {
  return event.isComposing || event.keyCode === 229 || event.defaultPrevented || event.target instanceof HTMLSelectElement;
}

export default function useDialogFocus(
  dialogRef: RefObject<HTMLElement | null>,
  open: boolean,
  onClose: () => void,
  fallbackRef?: RefObject<HTMLElement | null>,
) {
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!open || !dialog) return;
    const doc = dialog.ownerDocument;
    const active = doc.activeElement;
    const opener = active instanceof HTMLElement && active !== doc.body && !dialog.contains(active) ? active : null;
    openDialogs.push(dialog);
    const isTop = () => openDialogs[openDialogs.length - 1] === dialog;
    if (!dialog.contains(doc.activeElement)) dialog.focus({ preventScroll: true });

    const onKeyDown = (event: KeyboardEvent) => {
      if (!isTop()) return;
      if (event.key === "Escape") {
        if (escapeBelongsElsewhere(event)) return;
        event.preventDefault();
        close.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusables(dialog);
      const current = doc.activeElement as HTMLElement | null;
      if (items.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const listed = current !== null && items.includes(current);
      // 창 자체나 목록에 없는 곳(tabIndex=-1 상자 등)에 있으면 처음·끝으로 보낸다(브라우저가 창 밖으로 보내지 않게)
      if (!listed) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && current === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && current === last) {
        event.preventDefault();
        first.focus();
      }
    };
    // 화면 읽기 프로그램이나 스크립트가 초점을 창 밖으로 옮기면 창으로 되돌린다(aria-modal을 지키지 않는 브라우저 대비)
    const onFocusIn = (event: FocusEvent) => {
      if (isTop() && event.target instanceof Node && !dialog.contains(event.target)) dialog.focus({ preventScroll: true });
    };
    dialog.addEventListener("keydown", onKeyDown);
    doc.addEventListener("focusin", onFocusIn);
    return () => {
      dialog.removeEventListener("keydown", onKeyDown);
      doc.removeEventListener("focusin", onFocusIn);
      openDialogs.splice(openDialogs.indexOf(dialog), 1);
      const now = doc.activeElement;
      if (now && now !== doc.body && !dialog.contains(now)) return; // 사용자가 이미 다른 곳에 있다
      const target = opener?.isConnected ? opener : fallbackRef?.current?.isConnected ? fallbackRef.current : null;
      target?.focus({ preventScroll: true });
    };
  }, [dialogRef, fallbackRef, open]);
}
