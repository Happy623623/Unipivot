import { useState } from "react";
import { connectLms } from "@/api/client";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import type { LmsConnection } from "@/types/api";

interface LmsConnectModalProps {
  open: boolean;
  onClose: () => void;
  onConnected: (connection: LmsConnection) => void;
}

type ConnectStatus = "idle" | "checking" | "success" | "failure";

export default function LmsConnectModal({
  open,
  onClose,
  onConnected,
}: LmsConnectModalProps) {
  const [step, setStep] = useState(1);
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<ConnectStatus>("idle");
  const [connected, setConnected] = useState<LmsConnection | null>(null);

  const close = () => {
    setStep(1);
    setToken("");
    setStatus("idle");
    setConnected(null);
    onClose();
  };

  const connect = async () => {
    setStatus("checking");
    try {
      const result = await connectLms(token);
      setConnected(result);
      setStatus("success");
      onConnected(result);
    } catch {
      setStatus("failure");
    } finally {
      setToken("");
    }
  };

  return (
    <Modal open={open} title="LearningX 연결" onClose={close}>
      <div className="mb-5 flex gap-2">
        {[1, 2, 3].map((item) => (
          <div
            key={item}
            className={`h-1.5 flex-1 rounded-full ${
              item <= step ? "bg-[#4f6ef7]" : "bg-[#e5e7eb]"
            }`}
          />
        ))}
      </div>
      {step === 1 && (
        <>
          <p className="text-[14px] font-semibold">액세스 토큰을 발급해 주세요.</p>
          <p className="mt-2 rounded-[10px] bg-[#eef2ff] p-3 text-[13px] leading-6 text-[#344054]">
            LearningX &gt; 계정 &gt; 설정 &gt; 승인된 통합 &gt; + 새 액세스 토큰
          </p>
          <div className="mt-4 grid grid-cols-3 gap-2">
            {[1, 2, 3].map((item) => (
              <div
                key={item}
                className="flex aspect-[4/3] items-center justify-center rounded-[10px] bg-[#e5e7eb] text-[12px] font-semibold text-[#667085]"
              >
                안내 {item}
              </div>
            ))}
          </div>
          <div className="mt-6 flex justify-end">
            <Button onClick={() => setStep(2)}>토큰 입력하기</Button>
          </div>
        </>
      )}
      {step === 2 && (
        <>
          <label>
            <span className="mb-2 block text-[14px] font-semibold">발급한 토큰 붙여넣기</span>
            <input
              type="password"
              autoComplete="off"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="토큰은 가려서 표시해요"
              className="h-[44px] w-full rounded-[10px] border border-[#e5e7eb] px-3 text-[14px] outline-none focus:border-[#4f6ef7]"
            />
          </label>
          <p className="mt-2 text-[12px] text-[#667085]">
            토큰 원문은 화면에 다시 표시하지 않아요.
          </p>
          <div className="mt-6 flex justify-between">
            <Button secondary onClick={() => setStep(1)}>이전</Button>
            <Button onClick={() => setStep(3)} disabled={!token.trim()}>다음</Button>
          </div>
        </>
      )}
      {step === 3 && status === "idle" && (
        <>
          <p className="text-[14px] leading-6 text-[#344054]">
            입력한 토큰으로 LearningX 과목과 과제를 불러올게요.
          </p>
          <div className="mt-6 flex justify-between">
            <Button secondary onClick={() => setStep(2)}>이전</Button>
            <Button onClick={connect}>연결하기</Button>
          </div>
        </>
      )}
      {step === 3 && status === "checking" && (
        <div className="py-10 text-center">
          <div className="mx-auto size-8 animate-spin rounded-full border-4 border-[#e5e7eb] border-t-[#4f6ef7]" />
          <p className="mt-4 text-[14px] font-semibold">토큰을 확인하고 있어요</p>
        </div>
      )}
      {step === 3 && status === "success" && connected && (
        <div className="py-6 text-center">
          <p className="text-[20px] font-bold text-[#15803d]">8개 과목을 불러왔어요</p>
          <p className="mt-2 text-[12px] text-[#667085]">
            연결된 토큰 끝 4자리 {connected.token_last4}
          </p>
          <div className="mt-6"><Button onClick={close}>완료</Button></div>
        </div>
      )}
      {step === 3 && status === "failure" && (
        <div className="py-6 text-center">
          <p className="text-[16px] font-bold text-[#c53030]">
            토큰을 확인할 수 없어요. 복사할 때 앞뒤 공백이 들어갔는지 확인해 주세요
          </p>
          <div className="mt-6">
            <Button onClick={() => {
              setStep(2);
              setStatus("idle");
            }}>
              다시 입력하기
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
