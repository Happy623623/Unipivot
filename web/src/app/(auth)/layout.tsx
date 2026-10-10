import type { ReactNode } from "react";

// 로그인·온보딩은 사이드바 없이 가운데 카드로 보여준다
export default function AuthLayout({ children }: { children: ReactNode }) {
  return <main className="min-h-dvh bg-[#f7f8fa] px-4 py-16 text-[#181a20] max-[760px]:py-8">{children}</main>;
}
