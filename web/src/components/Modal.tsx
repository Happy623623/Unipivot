import type { ReactNode } from "react";

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}

export default function Modal({ open, title, onClose, children }: ModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#181a20]/30 p-4">
      <button type="button" aria-label="모달 닫기" className="absolute inset-0 cursor-default" onClick={onClose} />
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative z-10 max-h-[90dvh] w-full max-w-[520px] overflow-y-auto rounded-[18px] border border-[#e5e7eb] bg-white p-6 shadow-[0_20px_60px_rgba(24,26,32,0.18)]"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-[20px] font-bold">{title}</h2>
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
