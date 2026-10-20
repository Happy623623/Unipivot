import { useEffect, useRef, useState } from "react";
import { ApiError, connectLms, errorMessage } from "@/api/client";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import type { LmsConnectResult, LmsConnection } from "@/types/api";

interface LmsConnectModalProps {
  open: boolean;
  onClose: () => void;
  onConnected: (connection: LmsConnection) => void;
}

type ConnectStatus = "idle" | "checking" | "success" | "failure";

const TOKEN_FAILURE = "토큰을 확인할 수 없어요. 복사할 때 앞뒤 공백이 들어갔는지 확인해 주세요";
const RETRY_FAILURE = "지금은 LearningX에서 받아올 수 없어요. 잠시 후 다시 시도해 주세요";

export default function LmsConnectModal({
  open,
  onClose,
  onConnected,
}: LmsConnectModalProps) {
  const [step, setStep] = useState(1);
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<ConnectStatus>("idle");
  const [connected, setConnected] = useState<LmsConnectResult | null>(null);
  const [failure, setFailure] = useState(TOKEN_FAILURE);
  // 닫을 때마다 늘린다. 확인이 15초를 넘겨 잠금이 풀린 뒤 닫으면, 늦게 온 결과는 이 창(다시 연 창)에 그리지 않는다
  const attempt = useRef(0);
  const checkingRef = useRef<HTMLDivElement>(null);

  // "연결하기"를 누르면 그 버튼이 확인 화면으로 바뀌어 초점이 <body>로 빠진다. 창이 키를 듣지 못해 15초 뒤에도
  // Esc로 닫을 수 없고 화면 읽기 프로그램도 무엇이 진행 중인지 모른다. 확인 화면으로 초점을 옮긴다
  useEffect(() => {
    if (status === "checking") checkingRef.current?.focus({ preventScroll: true });
  }, [status]);

  const close = () => {
    attempt.current += 1;
    setStep(1);
    setToken("");
    setStatus("idle");
    setConnected(null);
    setFailure(TOKEN_FAILURE);
    onClose();
  };

  const connect = async () => {
    const mine = attempt.current;
    setStatus("checking");
    try {
      const result = await connectLms(token);
      // 연결은 됐으니 바깥(연결 상태)에는 늘 알린다. 창 안 결과는 닫지 않았을 때만
      if (mine === attempt.current) {
        setConnected(result);
        setStatus("success");
      }
      onConnected({
        status: result.status,
        token_last4: result.token_last4,
        last_synced_at: null, // 방금 받았다. 정확한 시각은 다음에 연결 상태를 받을 때 온다
        last_error: null,
      });
    } catch (caught) {
      // 토큰이 틀린 것(422)과 LearningX가 멈춘 것(502)·서버에 닿지 못한 것은 다른 일이다.
      // 명세 13장의 문구를 그대로 쓰고, 토큰 문제일 때만 공백 안내를 붙인다
      if (mine !== attempt.current) return;
      const invalid = caught instanceof ApiError && caught.code === "LMS_TOKEN_INVALID";
      setFailure(invalid ? TOKEN_FAILURE : errorMessage(caught, RETRY_FAILURE));
      setStatus("failure");
    } finally {
      if (mine === attempt.current) setToken("");
    }
  };

  return (
    <Modal open={open} title="LearningX 연결" onClose={close} busy={status === "checking"}>
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
        <div ref={checkingRef} tabIndex={-1} role="status" className="py-10 text-center outline-none">
          <div className="mx-auto size-8 animate-spin rounded-full border-4 border-[#e5e7eb] border-t-[#4f6ef7]" />
          <p className="mt-4 text-[14px] font-semibold">토큰을 확인하고 과제를 받아오고 있어요</p>
          <p className="mt-1 text-[12px] text-[#667085]">조금 걸릴 수 있어요. 창을 닫지 말아 주세요.</p>
        </div>
      )}
      {step === 3 && status === "success" && connected && (
        <div className="py-6 text-center">
          <p className="text-[20px] font-bold text-[#15803d]">
            {connected.courses}개 과목을 불러왔어요
          </p>
          <p className="mt-2 text-[12px] text-[#667085]">
            연결된 토큰 끝 4자리 {connected.token_last4}
          </p>
          <div className="mt-6"><Button onClick={close}>완료</Button></div>
        </div>
      )}
      {step === 3 && status === "failure" && (
        <div className="py-6 text-center">
          <p className="text-[16px] font-bold text-[#c53030]">{failure}</p>
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
