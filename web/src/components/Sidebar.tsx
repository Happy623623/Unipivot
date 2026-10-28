import Link from "next/link";
import type { Route } from "@/types/route";

interface SidebarProps {
  route: Route;
  navigate: (route: Route) => void;
}

const navItems: { route: Route; label: string; icon: string }[] = [
  { route: { name: "home" }, label: "홈", icon: "⌂" },
  { route: { name: "planner" }, label: "플래너", icon: "□" },
  { route: { name: "academics" }, label: "학업", icon: "▣" },
  { route: { name: "documents" }, label: "문서함", icon: "▤" },
];

export default function Sidebar({ route, navigate }: SidebarProps) {
  return (
    <aside className="fixed inset-y-0 left-0 z-20 flex w-[220px] flex-col bg-white px-5 pb-6 pt-7 max-[760px]:relative max-[760px]:w-full max-[760px]:px-4 max-[760px]:py-4">
      <button
        type="button"
        onClick={() => navigate({ name: "home" })}
        className="text-left text-[32px] font-bold leading-[1.45] text-[#4f6ef7]"
      >
        UNIPIVOT
      </button>
      <nav className="mt-3 flex flex-col gap-[2px] max-[760px]:mt-2 max-[760px]:flex-row max-[760px]:overflow-x-auto">
        {navItems.map((item) => (
          <button
            type="button"
            key={item.route.name}
            onClick={() => navigate(item.route)}
            className={`flex items-center gap-[10px] whitespace-nowrap rounded-[10px] px-3 py-[10px] text-[14px] ${
              route.name === item.route.name
                ? "bg-[#eef2ff] font-semibold text-[#4f6ef7]"
                : "font-medium text-[#667085] hover:bg-[#f7f8fa]"
            }`}
          >
            <span className="text-[15px] font-normal">{item.icon}</span>
            {item.label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => navigate({ name: "upload" })}
          className={`flex items-center gap-[10px] whitespace-nowrap rounded-[10px] border border-[#e5e7eb] px-3 py-[10px] text-[14px] ${
            route.name === "upload"
              ? "bg-[#eef2ff] font-semibold text-[#4f6ef7]"
              : "font-medium text-[#667085] hover:bg-[#f7f8fa]"
          }`}
        >
          <span className="text-[15px]">＋</span>포스터 등록
        </button>
        {/* 760px 이하에서는 아래 설정 버튼이 숨으므로 가로 메뉴에 설정을 넣는다 */}
        <button
          type="button"
          onClick={() => navigate({ name: "settings" })}
          className={`hidden items-center gap-[10px] whitespace-nowrap rounded-[10px] px-3 py-[10px] text-[14px] max-[760px]:flex ${
            route.name === "settings"
              ? "bg-[#eef2ff] font-semibold text-[#4f6ef7]"
              : "font-medium text-[#667085] hover:bg-[#f7f8fa]"
          }`}
        >
          <span className="text-[15px]">⚙</span>설정
        </button>
      </nav>
      <button
        type="button"
        onClick={() => navigate({ name: "settings" })}
        className={`mt-auto flex items-center gap-[10px] rounded-[10px] px-3 py-[10px] text-[14px] max-[760px]:hidden ${
          route.name === "settings"
            ? "bg-[#eef2ff] font-semibold text-[#4f6ef7]"
            : "font-medium text-[#667085]"
        }`}
      >
        <span className="text-[15px]">⚙</span>설정
      </button>
      {/* 처리방침은 로그인 없이 여는 페이지라 화면 이동(navigate)이 아니라 링크다. 그래서 첫 화면("/")의 HTML에도 들어가
          Google 인증 플랫폼에 적는 홈페이지에서 처리방침으로 갈 수 있다. 좁은 화면에서는 설정 화면의 링크를 쓴다 */}
      <Link
        href="/privacy"
        className="mt-1 px-3 text-[12px] text-[#667085] underline-offset-2 hover:text-[#4f6ef7] hover:underline max-[760px]:hidden"
      >
        개인정보 처리방침
      </Link>
    </aside>
  );
}
