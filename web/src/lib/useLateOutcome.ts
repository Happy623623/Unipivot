import { useCallback, useLayoutEffect, useRef } from "react";
import { ApiError } from "@/api/client";
import useToast, { type ToastHold, type ToastState } from "@/lib/useToast";

// 창 안의 일(저장·해제·탈퇴 등)이 끝났을 때 창이 그새 닫혔으면 결과를 화면 아래 안내로 띄운다.
// 진행 중인 창은 15초까지만 안 닫혀서(lib/useCloseLock.ts) 그 뒤에 닫으면, 창 안에 그리는 오류·완료 글이 보이지 않는다.
// report(글): 창이 아직 열려 있으면 아무것도 안 하고 false(창 안에 보인다), 닫혔으면 안내를 띄우고 true.
// 성공한 뒤 창을 스스로 닫는 곳은 닫기 **전에** 부른다(그래야 평소 성공에는 안내가 뜨지 않는다).
// announce(글): 창이 열려 있어도 띄운다. 창을 다시 열어 새로 시작해서 지난 결과를 창 안에 그리지 않는 곳에 쓴다.
// 안내는 부르는 쪽이 <Toast toast={…} onHold={…} />로 그린다(창은 닫혀 있어도 이 자리는 남아 있다).
// 이 안내가 그 일의 유일한 결과라 평소 안내보다 오래 두고, 마우스·초점이 있는 동안은 닫지 않는다
export default function useLateOutcome(open: boolean): {
  report: (text: string) => boolean;
  announce: (text: string) => void;
  toast: ToastState;
  hold: ToastHold;
} {
  const openRef = useRef(open);
  useLayoutEffect(() => {
    openRef.current = open;
  }, [open]);
  const [toast, show, , hold] = useToast(6000);
  const announce = useCallback((text: string) => show(text), [show]);
  const report = useCallback(
    (text: string) => {
      if (openRef.current) return false;
      show(text);
      return true;
    },
    [show],
  );
  return { report, announce, toast, hold };
}

// 닫힌 창의 실패 안내 글. 창 안 글("잠시 후 다시 눌러 주세요")은 닫힌 창의 버튼을 가리키고 무엇이 실패했는지 말하지 않아서,
// 무엇이 실패했는지(lead) 앞에 붙이고 서버가 준 까닭(4xx 문구)이 있으면 그것을, 없으면 다시 할 방법(retry)을 붙인다.
// 서버에 닿지 못한 것(NETWORK_ERROR)·5xx는 까닭 대신 다시 할 방법을 쓴다(오래 걸린 요청이 흔히 그렇게 끝난다)
export function lateFailure(caught: unknown, lead: string, retry: string): string {
  const told = caught instanceof ApiError && caught.status >= 400 && caught.status < 500 ? caught.message : "";
  return `${lead} ${told || retry}`;
}
