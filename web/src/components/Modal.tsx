import { useId, useRef, type ReactNode, type RefObject } from "react";
import useDialogFocus from "@/lib/useDialogFocus";

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  returnFocusRef?: RefObject<HTMLElement | null>; // 연 버튼이 닫힐 때 없어지는 경우(메뉴 안 버튼) 대신 초점을 돌려줄 곳
}

// 열리면 창으로 초점이 가고, Tab은 창 안에서 돌고, Esc로 닫히며, 닫히면 연 버튼으로 돌아간다(lib/useDialogFocus.ts)
export default function Modal({ open, title, onClose, children, returnFocusRef }: ModalProps) {
  const dialogRef = useRef<HTMLElement>(null);
  const titleId = useId();
  useDialogFocus(dialogRef, open, onClose, returnFocusRef);
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#181a20]/30 p-4">
      {/* 바깥을 누르면 닫는 마우스용 덮개. 키보드는 Esc와 닫기 버튼을 쓴다(Tab 순서에 넣지 않는다) */}
      <button type="button" tabIndex={-1} aria-hidden="true" className="absolute inset-0 cursor-default" onClick={onClose} />
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
            onClick={onClose}
            aria-label="닫기"
            className="flex size-9 items-center justify-center rounded-[10px] bg-[#f7f8fa] text-[20px] text-[#667085]"
          >
            ×
          </button>
        </div>
        <div className="mt-5">{children}</div>
      </section>
    </div>
  );
}
