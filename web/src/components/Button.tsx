import type { ReactNode } from "react";

interface ButtonProps {
  children: ReactNode;
  type?: "button" | "submit";
  secondary?: boolean;
  onClick?: () => void;
  disabled?: boolean;
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

export default function Button({
  children,
  type = "button",
  secondary = false,
  onClick,
  disabled = false,
  title,
}: ButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`${BASE} disabled:cursor-not-allowed disabled:opacity-45 ${
        secondary ? "border-[#e5e7eb] bg-white text-[#181a20] hover:bg-[#f7f8fa]" : PRIMARY
      }`}
    >
      {children}
    </button>
  );
}
