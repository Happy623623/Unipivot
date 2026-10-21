import { useEffect, useRef, useState } from "react";
import Button from "@/components/Button";
import LmsConnectModal from "@/components/LmsConnectModal";
import { focusIfLost } from "@/lib/useFocusHandoff";

export default function LmsInviteStep({ onFinish }: { onFinish: () => void }) {
  const [open, setOpen] = useState(false);
  const [connected, setConnected] = useState(false);
  const actions = useRef<HTMLDivElement>(null);
  // 창을 닫은 뒤에 연결되면 초점이 있던 "연결하기"가 "시작하기"로 바뀌어 사라진다. 그린 뒤에 그 자리로 옮긴다
  // (창이 열려 있으면 초점은 창 안이라 그대로 둔다)
  useEffect(() => {
    if (connected) focusIfLost(() => [actions.current?.querySelector("button")]);
  }, [connected]);

  return (
    <div>
      {/* 확인이 15초를 넘겨 창을 닫은 뒤에 연결되면 창은 닫혀 있다. 그때도 연결됐다고 보여 주고 다음으로 넘긴다 */}
      <h2 className="text-[22px] font-bold">{connected ? "LearningX를 연결했어요" : "LearningX도 연결할까요?"}</h2>
      <p className="mt-2 text-[14px] leading-6 text-[#667085]">
        과제 마감과 새 자료를 알려드려요. 토큰은 서버에 암호화해 보관하고, 연결을 해제하면 바로 지워요.
      </p>
      <div ref={actions} className="mt-8 flex justify-end gap-2">
        {connected ? (
          <Button onClick={onFinish}>시작하기</Button>
        ) : (
          <>
            <Button secondary onClick={onFinish}>나중에</Button>
            <Button onClick={() => setOpen(true)}>연결하기</Button>
          </>
        )}
      </div>
      <LmsConnectModal
        open={open}
        onClose={() => {
          setOpen(false);
          if (connected) onFinish();
        }}
        onConnected={() => setConnected(true)}
      />
    </div>
  );
}
