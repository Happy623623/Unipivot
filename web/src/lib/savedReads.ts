import { USE_MOCKS } from "@/api/http";

// 저장된 알림 읽음 처리를 같은 탭의 목록들(헤더 패널·알림함 화면)과 **같은 브라우저의 다른 탭**에 알린다.
// 다른 탭에는 BroadcastChannel로 보낸다(로그인 맞추기와 같은 방식, lib/useSessionWatch.ts). 받은 탭은 자기 탭 안에만
// 다시 알린다(되돌려 보내지 않는다). 목 모드는 탭마다 목 상태가 따로라 다른 탭에 보내지 않는다.
// 다른 탭의 목록이 받던 중이던 쪽에 다시 입히는 것은 useNotifications가 같은 탭에서처럼 한다.

// ids가 "all"이면 전체 읽음이다. 서버는 그때 보낼 때가 된 알림만 읽음으로 하므로, 누른 시각(readAt) 뒤에 보낼 때가 된
// 알림(그사이 받은 첫 쪽에 섞여 올 수 있다)에는 입히지 않는다
export interface SavedRead {
  ids: string[] | "all";
  readAt: string; // 누를 때 시각(nowIso). 다른 탭도 같은 기기라 같은 시계다
  unread: number; // 서버가 센 안 읽은 수
}

const CHANNEL_NAME = "unipivot-notifications";
const listeners = new Set<(saved: SavedRead) => void>();
let channel: BroadcastChannel | null = null;
// 이 탭이 그린 사용자(AppFrame이 내 정보를 받으면 정한다). 다른 계정의 탭이 보낸 것은 버린다 — 다른 탭에서 다른 계정으로
// 로그인한 직후, 아직 옮겨 가지 않은 옛 탭(lib/useSessionWatch.ts)이 남의 수를 보이지 않게
let account: string | null = null;

export function setSavedReadsAccount(userId: string | null): void {
  account = userId;
}

// 다른 탭이 보낸 것만 받는다. 모양이 다르면 버린다(다른 판의 앱이 같은 이름으로 보낼 수 있다)
function parse(data: unknown): SavedRead | null {
  if (!data || typeof data !== "object") return null;
  const { ids, readAt, unread, user } = data as Record<string, unknown>;
  if (typeof user !== "string" || (account !== null && user !== account)) return null;
  const idsOk = ids === "all" || (Array.isArray(ids) && ids.every((id) => typeof id === "string"));
  if (!idsOk || typeof readAt !== "string" || Number.isNaN(Date.parse(readAt))) return null;
  if (typeof unread !== "number" || !Number.isInteger(unread) || unread < 0) return null;
  return { ids: ids as SavedRead["ids"], readAt, unread };
}

function tell(saved: SavedRead): void {
  listeners.forEach((listener) => listener(saved));
}

// 듣는 쪽이 있는 동안만 채널을 연다
function openChannel(): void {
  if (channel || USE_MOCKS || typeof BroadcastChannel === "undefined") return;
  channel = new BroadcastChannel(CHANNEL_NAME);
  channel.addEventListener("message", (event: MessageEvent) => {
    const saved = parse(event.data);
    if (saved) tell(saved);
  });
}

function closeChannel(): void {
  channel?.close();
  channel = null;
}

// 들을 것을 붙이고, 떼는 함수를 돌려준다(effect의 정리 함수로 쓴다)
export function onSavedRead(listener: (saved: SavedRead) => void): () => void {
  listeners.add(listener);
  openChannel();
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) closeChannel();
  };
}

// 서버에 저장된 읽음 처리를 이 탭(자기 포함)과 다른 탭에 알린다
export function announceSavedRead(saved: SavedRead): void {
  tell(saved);
  if (account !== null) channel?.postMessage({ ...saved, user: account }); // 누구 것인지 모르면 보내지 않는다
}
