import { createContext, useCallback, useContext, useId, useRef, type ReactNode, type RefObject } from "react";
import Button from "@/components/Button";
import useCloseLock from "@/lib/useCloseLock";
import useDialogFocus from "@/lib/useDialogFocus";

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  returnFocusRef?: RefObject<HTMLElement | null>; // 연 버튼이 닫힐 때 없어지는 경우(메뉴 안 버튼) 대신 초점을 돌려줄 곳
  busy?: boolean; // 창 안의 일(저장·탈퇴 등)이 진행 중. 끝나거나 15초가 지날 때까지 Esc·닫기·덮개·취소로 닫히지 않는다
}

// 창 안의 "취소" 버튼이 창 닫기 잠금을 따르게 한다(ModalCancelButton)
const ModalCloseContext = createContext<{ locked: boolean; close: () => void } | null>(null);

// 열리면 창으로 초점이 가고, Tab은 창 안에서 돌고, Esc로 닫히며, 닫히면 연 버튼으로 돌아간다(lib/useDialogFocus.ts).
// busy인 동안은 닫히지 않는다(lib/useCloseLock.ts — 닫힌 뒤 실패하면 오류가 안 보여서. 15초가 지나면 풀린다)
export default function Modal({ open, title, onClose, children, returnFocusRef, busy = false }: ModalProps) {
  const dialogRef = useRef<HTMLElement>(null);
  const titleId = useId();
  const locked = useCloseLock(busy) && open; // 15초는 일 하나에 한 번 — 잠금이 풀려 닫았다가 아직 진행 중에 다시 열어도 다시 잠그지 않는다
  const close = useCallback(() => {
    if (!locked) onClose();
  }, [locked, onClose]);
  useDialogFocus(dialogRef, open, close, returnFocusRef);
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#181a20]/30 p-4">
      {/* 바깥을 누르면 닫는 마우스용 덮개. 키보드는 Esc와 닫기 버튼을 쓴다(Tab 순서에 넣지 않는다) */}
      <button type="button" tabIndex={-1} aria-hidden="true" className="absolute inset-0 cursor-default" onClick={close} />
      <section
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative z-10 max-h-[90dvh] outline-none w-full max-w-[520px] overflow-y-auto rounded-[18px] border border-[#e5e7eb] bg-white p-6 shadow-[0_20px_60px_rgba(24,26,32,0.18)]"
      >
        <div className="flex items-center justify-between">
          <h2 id={titleId} className="text-[20px] font-bold">{title}</h2>
          <button
            type="button"
            onClick={close}
            aria-label="닫기"
            aria-disabled={locked || undefined}
            title={locked ? "진행 중인 일이 끝나면 닫을 수 있어요" : undefined}
            className="flex size-9 items-center justify-center rounded-[10px] bg-[#f7f8fa] text-[20px] text-[#667085] aria-disabled:cursor-not-allowed aria-disabled:opacity-45"
          >
            ×
          </button>
        </div>
        <ModalCloseContext.Provider value={{ locked, close }}>
          <div className="mt-5">{children}</div>
        </ModalCloseContext.Provider>
      </section>
    </div>
  );
}

// 창 닫기가 잠겼는지(busy). 창 밖에서 쓰면 false
export function useModalCloseLocked(): boolean {
  return useContext(ModalCloseContext)?.locked ?? false;
}

// 창을 닫는 "취소" 버튼. 진행 중이면 닫기처럼 누름을 무시하고 aria-disabled로 알린다
export function ModalCancelButton({ children = "취소" }: { children?: ReactNode }) {
  const modal = useContext(ModalCloseContext);
  return (
    <Button secondary inactive={modal?.locked} onClick={modal?.close}>
      {children}
    </Button>
  );
}
