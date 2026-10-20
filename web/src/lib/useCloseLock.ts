import { useEffect, useState } from "react";

// 창 안의 일(저장·탈퇴·연결 해제 등)이 진행 중이면 창을 닫지 못하게 잠근다(components/Modal.tsx의 busy).
// 닫힌 뒤에 실패하면 오류가 닫힌 창 안에 그려져 보이지 않아서다. 다만 요청에는 시간 제한이 없어, 응답이 멈추면 창에
// 갇힌다. 그래서 같은 일이 15초를 넘기면 잠금을 푼다(그 뒤에 닫으면 결과는 볼 수 없다 — 진행 중 버튼은 그대로 busy다).
// 15초는 busy가 켜진 때부터 센다(창을 닫았다 열어도 새로 세지 않는다)
export const CLOSE_LOCK_MS = 15_000;

export default function useCloseLock(busy: boolean, ms: number = CLOSE_LOCK_MS): boolean {
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    if (!busy) {
      setExpired(false); // 다음 일은 다시 잠근다
      return;
    }
    const timer = setTimeout(() => setExpired(true), ms);
    return () => clearTimeout(timer);
  }, [busy, ms]);

  return busy && !expired;
}
