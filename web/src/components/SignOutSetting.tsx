import { useState } from "react";
import { signOut } from "@/api/client";
import Button from "@/components/Button";

// 설정 > 계정의 로그아웃 (F-06). 이 기기의 로그인만 끝내고 로그인 화면으로 간다(다른 기기의 로그인과 데이터는 그대로).
// 끝나면 페이지가 바뀐다. 세션을 지우지 못하면(만료된 로그인을 갱신하다 연결이 끊긴 때 등) 그 자리에서 알리고 다시 누르게 한다
export default function SignOutSetting() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setPending(true);
    setError(null);
    try {
      await signOut();
    } catch {
      setError("로그아웃하지 못했어요. 인터넷 연결을 확인하고 다시 눌러 주세요.");
      setPending(false);
    }
  };

  return (
    <div className="mt-4 flex items-center justify-between gap-4 border-t border-[#f2f4f7] pt-4">
      <div>
        <p className="text-[14px] font-semibold">로그아웃</p>
        <p className="mt-1 text-[12px] text-[#667085]">이 기기에서만 로그아웃해요. 저장한 정보는 그대로 남아요.</p>
        {error && <p role="alert" className="mt-2 text-[12px] text-[#c53030]">{error}</p>}
      </div>
      <Button secondary busy={pending} onClick={run}>
        {pending ? "로그아웃하는 중" : "로그아웃"}
      </Button>
    </div>
  );
}
