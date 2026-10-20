import { useState } from "react";
import { getSettings } from "@/api/client";
import Button from "@/components/Button";
import { bannerDismissed, dismissBanner } from "@/lib/push";
import usePushSubscription from "@/lib/usePushSubscription";

// 알림함 맨 위의 "이 브라우저에서 알림 받기" 안내 (F-33).
//
// 알림함을 보러 왔다는 것은 알림을 기다린다는 뜻이다 — 켤 수 있는데 꺼져 있을 때만 보여 준다.
// 권한을 막아 둔 브라우저에는 띄우지 않는다(여기서 되돌릴 수 없다. 설정 화면에서 방법을 안내한다).
// 접으면 이번 방문 동안만 숨긴다.
export default function PushEnableBanner({ onDone }: { onDone: (message: string) => void }) {
  const { state, ready, busy, enable } = usePushSubscription();
  const [hidden, setHidden] = useState(false);
  if (!ready || hidden || bannerDismissed()) return null;
  if (!state.supported || !state.configured || state.subscribed) return null;
  if (state.permission === "denied") return null;

  const turnOn = async () => {
    if (!(await enable())) {
      onDone("알림을 켜지 못했어요. 설정에서 다시 시도해 주세요.");
      return;
    }
    setHidden(true);
    // 계정 전체 스위치가 꺼져 있으면 구독을 해도 아무것도 오지 않는다. 그때만 설정으로 안내한다
    const settings = await getSettings().catch(() => null);
    onDone(
      settings && !settings.push_enabled
        ? "이 브라우저를 등록했어요. 설정에서 푸시 알림도 켜 주세요"
        : "이제 이 브라우저로 알림을 받아요",
    );
  };

  const hide = () => {
    dismissBanner();
    setHidden(true);
  };

  return (
    <section className="flex items-center justify-between gap-4 rounded-[14px] border border-[#cfd7ff] bg-[#eef2ff] p-4 max-[700px]:flex-col max-[700px]:items-start">
      <div>
        <p className="text-[14px] font-semibold">이 브라우저에서 알림 받기</p>
        <p className="mt-1 text-[12px] text-[#344054]">
          마감이 가까운 공고와 새 과제를 바로 알려 줘요. 기기마다 한 번만 켜면 돼요.
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Button secondary onClick={hide}>나중에</Button>
        <Button busy={busy} onClick={() => void turnOn()}>알림 켜기</Button>
      </div>
    </section>
  );
}
