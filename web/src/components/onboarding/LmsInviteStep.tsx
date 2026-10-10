import { useState } from "react";
import Button from "@/components/Button";
import LmsConnectModal from "@/components/LmsConnectModal";

export default function LmsInviteStep({ onFinish }: { onFinish: () => void }) {
  const [open, setOpen] = useState(false);
  const [connected, setConnected] = useState(false);

  return (
    <div>
      <h2 className="text-[22px] font-bold">LearningX도 연결할까요?</h2>
      <p className="mt-2 text-[14px] leading-6 text-[#667085]">
        과제 마감과 새 자료를 알려드려요. 토큰은 서버에 암호화해 보관하고, 연결을 해제하면 바로 지워요.
      </p>
      <div className="mt-8 flex justify-end gap-2">
        <Button secondary onClick={onFinish}>나중에</Button>
        <Button onClick={() => setOpen(true)}>연결하기</Button>
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
