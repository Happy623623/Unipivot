import type { ReactNode } from "react";
import type { Tone } from "@/types/route";

interface BadgeProps {
  children: ReactNode;
  tone?: Tone;
}

export default function Badge({ children, tone = "blue" }: BadgeProps) {
  const tones: Record<Tone, string> = {
    blue: "bg-[#eef2ff] text-[#4f6ef7]",
    green: "bg-[#ecfdf3] text-[#15803d]",
    yellow: "bg-[#fff8e1] text-[#b7791f]",
    red: "bg-[#fef2f2] text-[#c53030]",
    gray: "bg-[#f2f4f7] text-[#475467]",
  };

  return (
    <span
      className={`inline-flex rounded-full px-[10px] py-[5px] text-[12px] leading-[1.45] font-semibold ${tones[tone]}`}
    >
      {children}
    </span>
  );
}
