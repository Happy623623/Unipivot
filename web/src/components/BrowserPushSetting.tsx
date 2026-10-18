import Toggle from "@/components/Toggle";
import usePushSubscription, { DENIED_HELP } from "@/lib/usePushSubscription";

// 설정 > 알림의 "이 브라우저에서 알림 받기" 줄 (F-33, API 명세 10장).
//
// 위의 "푸시 알림 켜기"는 계정 전체 설정이고(서버가 그 값을 보고 보낸다), 이 줄은 기기 하나의
// 구독이다. 둘을 한 스위치로 묶으면 다른 기기에서는 "켜짐"인데 알림이 오지 않는다.
//
// 웹 푸시를 못 하는 브라우저나 공개 키가 없는 배포에서는 줄을 아예 그리지 않는다 — 켤 수 없는
// 스위치를 보여 줄 까닭이 없다. 그 경우에도 알림함은 그대로 쌓인다.
export default function BrowserPushSetting({ pushEnabled }: { pushEnabled: boolean }) {
  const { state, ready, busy, error, enable, disable } = usePushSubscription();
  if (!ready || !state.supported || !state.configured) return null;
  const denied = state.permission === "denied";
  return (
    <div className="mt-4 border-t border-[#f2f4f7] pt-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-[14px] font-semibold">이 브라우저에서 알림 받기</p>
          <p className="mt-1 text-[12px] text-[#667085]">
            기기마다 따로 켜요. 켜지 않은 기기에서는 알림함에서 확인해요.
          </p>
        </div>
        <Toggle
          checked={state.subscribed}
          disabled={busy || denied}
          label="이 브라우저에서 알림 받기"
          onChange={(checked) => void (checked ? enable() : disable())}
        />
      </div>
      {denied && <p className="mt-2 text-[12px] text-[#667085]">{DENIED_HELP}</p>}
      {!denied && !pushEnabled && (
        <p className="mt-2 text-[12px] text-[#b7791f]">
          위의 “푸시 알림 켜기”가 꺼져 있어요. 켜야 이 브라우저로도 알림이 와요.
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-[13px] text-[#c53030]">
          {error}
        </p>
      )}
    </div>
  );
}
