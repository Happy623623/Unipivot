import type { ReactNode } from "react";

interface ButtonProps {
  children: ReactNode;
  type?: "button" | "submit";
  secondary?: boolean;
  onClick?: () => void;
  disabled?: boolean; // 지금은 할 수 없는 일(입력이 덜 됐다 등). 초점을 받지 않는다
  busy?: boolean; // 누른 일이 아직 진행 중. 눌러도 지나가지만 초점은 남는다(아래). disabled와 같이 주지 않는다
  inactive?: boolean; // 다른 일이 진행 중이라 지금은 누를 수 없다(창의 "취소" 등). busy처럼 초점은 남고, 진행 중 표시(aria-busy)는 없다
  title?: string;
}

const BASE = "h-[42px] rounded-[10px] border px-[18px] text-[14px] font-semibold transition active:scale-[0.98]";
const PRIMARY = "border-[#4f6ef7] bg-[#4f6ef7] text-white hover:bg-[#425fe0]";

// 바깥 주소(공고 원문 등)를 새 탭으로 여는 버튼 모양 링크
export function ButtonLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={`inline-flex items-center ${BASE} ${PRIMARY}`}>
      {children}
    </a>
  );
}

// 진행 중(busy)인 버튼은 disabled로 막지 않는다. disabled가 되면 키보드 초점이 버튼에서 빠져 문서 맨 위로 튀고,
// 일이 끝난 뒤 같은 버튼을 다시 누르려면(더 보기) 처음부터 Tab으로 찾아와야 한다. 대신 aria-disabled·aria-busy로
// 알리고 누름을 취소한다(components/DownloadButton.tsx와 같은 방식). 누름을 취소해야 type="submit"일 때 폼 제출
// (입력란에서 Enter도 이 버튼의 click이다)까지 막힌다
export default function Button({
  children,
  type = "button",
  secondary = false,
  onClick,
  disabled = false,
  busy = false,
  inactive = false,
  title,
}: ButtonProps) {
  const blocked = busy || inactive;
  return (
    <button
      type={type}
      onClick={(event) => {
        if (blocked) {
          event.preventDefault();
          return;
        }
        onClick?.();
      }}
      disabled={disabled}
      aria-disabled={blocked || undefined}
      aria-busy={busy || undefined}
      title={title}
      className={`${BASE} disabled:cursor-not-allowed disabled:opacity-45 aria-disabled:opacity-45 aria-busy:cursor-wait aria-disabled:not-aria-busy:cursor-not-allowed aria-disabled:active:scale-100 ${
        secondary ? "border-[#e5e7eb] bg-white text-[#181a20] hover:bg-[#f7f8fa]" : PRIMARY
      }`}
    >
      {children}
    </button>
  );
}
