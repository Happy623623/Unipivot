import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage, removePushSubscription, savePushSubscription } from "@/api/client";
import {
  currentSubscription,
  ensureServiceWorker,
  PushDeniedError,
  readState,
  subscribeHere,
  UNAVAILABLE,
  unsubscribeHere,
  type PushState,
} from "@/lib/push";

// "이 브라우저에서 알림 받기" 상태와 켜기·끄기 (F-33, API 명세 10장).
// 설정 화면의 줄과 알림함 배너가 각각 하나씩 쓴다.
//
// 켜짐 = 브라우저 구독이 있고 서버에도 올라갔다는 뜻이다. 그래서 올리기에 실패하면 구독을
// 도로 지운다 — 켜 놓고 아무것도 오지 않는 쪽이 더 나쁘다.

const SAVE_FAILED = "알림을 켜지 못했어요. 잠시 후 다시 눌러 주세요.";
const STOP_FAILED = "알림을 끄지 못했어요. 잠시 후 다시 눌러 주세요.";
export const DENIED_HELP =
  "브라우저에서 이 사이트의 알림을 막아 뒀어요. 주소창 왼쪽 아이콘에서 알림을 허용해 주세요.";

export interface PushSubscriptionState {
  state: PushState;
  ready: boolean; // 브라우저 상태를 다 읽었나 (읽기 전에는 줄을 그리지 않는다)
  busy: boolean;
  error: string | null;
  enable: () => Promise<boolean>;
  disable: () => Promise<boolean>;
}

/**
 * 앱을 열 때 한 번: 서비스 워커를 등록하고, 이미 있는 구독을 서버에 다시 올린다.
 *
 * 브라우저가 구독을 스스로 바꾸거나(주소 교체) 같은 브라우저로 다른 사람이 로그인하면 서버의
 * 주인이 어긋난다. 올리기는 같은 주소면 키만 갱신하는 덮어쓰기라 몇 번을 해도 안전하다.
 */
export async function syncPushSubscription(): Promise<void> {
  await ensureServiceWorker();
  try {
    const found = await currentSubscription();
    if (found) await savePushSubscription(found);
  } catch {
    // 올리지 못해도 화면은 그대로 돈다. 다음에 앱을 열 때 다시 맞춘다
  }
}

export default function usePushSubscription(): PushSubscriptionState {
  const [state, setState] = useState<PushState>(UNAVAILABLE);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    readState().then((found) => {
      if (!alive.current) return;
      setState(found);
      setReady(true);
    });
    return () => {
      alive.current = false;
    };
  }, []);

  const enable = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const subscription = await subscribeHere();
      try {
        await savePushSubscription(subscription);
      } catch (cause) {
        await unsubscribeHere().catch(() => null); // 서버가 모르는 구독은 남기지 않는다
        throw cause;
      }
      setState(await readState());
      return true;
    } catch (cause) {
      setState(await readState());
      setError(cause instanceof PushDeniedError ? DENIED_HELP : errorMessage(cause, SAVE_FAILED));
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  const disable = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const endpoint = await unsubscribeHere();
      // 브라우저에서는 이미 지웠다. 서버가 남아도 보낼 때 404·410으로 스스로 지운다(명세 10장)
      if (endpoint) await removePushSubscription(endpoint);
      setState(await readState());
      return true;
    } catch (cause) {
      setState(await readState());
      setError(errorMessage(cause, STOP_FAILED));
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  return { state, ready, busy, error, enable, disable };
}
