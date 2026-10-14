import type { ToastHold, ToastState } from "@/lib/useToast";

interface ToastProps {
  toast: ToastState;
  onHold?: ToastHold; // 주면 안내 위에 마우스나 초점이 있는 동안 닫지 않는다(버튼이 있는 안내)
}

// 화면 아래 안내(lib/useToast). 스크린 리더가 읽도록 role="status" 자리는 늘 두고 안의 글만 바꾼다.
// 글마다 key를 새로 줘서 같은 글이 이어 떠도 다시 읽힌다. 버튼이 있으면 글 오른쪽에 둔다.
// 마우스로만 붙잡는다. 터치는 손을 떼도 떠난 것으로 치지 않아 안내가 닫히지 않게 된다
export default function Toast({ toast, onHold }: ToastProps) {
  return (
    <div
      role="status"
      onPointerEnter={(event) => event.pointerType === "mouse" && onHold?.("hover", true)}
      onPointerLeave={(event) => event.pointerType === "mouse" && onHold?.("hover", false)}
      onFocus={() => onHold?.("focus", true)}
      onBlur={() => onHold?.("focus", false)}
      className={
        toast.text
          ? "fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white"
          : "sr-only"
      }
    >
      {toast.text && (
        <span key={toast.id} className="flex items-center gap-3">
          <span>{toast.text}</span>
          {toast.action && (
            <button
              type="button"
              onClick={toast.action.onAction}
              className="shrink-0 text-[#cfd7ff] underline underline-offset-2 hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#cfd7ff]"
            >
              {toast.action.label}
            </button>
          )}
        </span>
      )}
    </div>
  );
}
