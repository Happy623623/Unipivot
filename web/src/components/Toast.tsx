import type { ToastState } from "@/lib/useToast";

// 화면 아래 안내(lib/useToast). 스크린 리더가 읽도록 role="status" 자리는 늘 두고 안의 글만 바꾼다.
// 글마다 key를 새로 줘서 같은 글이 이어 떠도 다시 읽힌다
export default function Toast({ toast }: { toast: ToastState }) {
  return (
    <div
      role="status"
      className={
        toast.text
          ? "fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white"
          : "sr-only"
      }
    >
      {toast.text && <span key={toast.id}>{toast.text}</span>}
    </div>
  );
}
