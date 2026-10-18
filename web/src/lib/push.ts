import { USE_MOCKS } from "@/api/http";
import type { PushSubscriptionRequest } from "@/types/api";

// 브라우저 쪽 웹 푸시 (F-33, API 명세 10장). 화면은 `window`·`navigator`를 직접 만지지 않고
// 이 파일만 쓴다. 서버로 보내는 일은 `api/pushClient.ts`가 한다.
//
// 공개 키가 없는 배포에서는 아무것도 보여 주지 않는다 — 서버도 키가 없으면 푸시를 건너뛰고
// 알림함에만 쌓는다(명세 10장). 목 모드는 브라우저 권한창을 띄우지 않고 흉내만 낸다.

export const VAPID_PUBLIC_KEY = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY ?? "";

const SW_URL = "/sw.js";
const DISMISS_KEY = "unipivot.push.banner";

export type PushPermission = "default" | "granted" | "denied";

export interface PushState {
  supported: boolean; // 이 브라우저가 서비스 워커·푸시를 할 수 있나
  configured: boolean; // 공개 키가 설정에 있나
  permission: PushPermission;
  subscribed: boolean; // 이 브라우저가 지금 구독을 들고 있나
}

export const UNAVAILABLE: PushState = {
  supported: false,
  configured: false,
  permission: "default",
  subscribed: false,
};

// 목 모드의 가짜 구독. 메모리에만 있어 새로고침하면 초기화된다(다른 목 데이터와 같다)
let mockSubscription: PushSubscriptionRequest | null = null;

export function pushSupported(): boolean {
  if (USE_MOCKS) return true;
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

function permissionNow(): PushPermission {
  if (USE_MOCKS) return mockSubscription ? "granted" : "default";
  if (typeof window === "undefined" || !("Notification" in window)) return "default";
  return Notification.permission as PushPermission;
}

/** base64url 공개 키를 `PushManager.subscribe()`가 받는 바이트로 바꾼다(패딩이 빠져 있다).
 *
 * 버퍼를 먼저 만들어 넘긴다 — `new Uint8Array(길이)`는 타입이 `ArrayBufferLike`여서
 * `applicationServerKey`(ArrayBuffer만 받는다)에 들어가지 않는다. */
function keyBytes(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (value.length % 4)) % 4);
  const raw = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index);
  return bytes;
}

function base64url(buffer: ArrayBuffer | null): string {
  if (!buffer) return "";
  const bytes = new Uint8Array(buffer);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** 사용자가 기기를 알아보게 적는 값(명세 10장, 200자 제한). 못 알아보면 보내지 않는다. */
export function deviceLabel(): string | undefined {
  if (USE_MOCKS) return "목 브라우저 / 미리보기";
  if (typeof navigator === "undefined") return undefined;
  const agent = navigator.userAgent;
  const browser =
    /Edg\//.test(agent) ? "Edge"
    : /OPR\//.test(agent) ? "Opera"
    : /Chrome\//.test(agent) ? "Chrome"
    : /Safari\//.test(agent) ? "Safari"
    : /Firefox\//.test(agent) ? "Firefox"
    : null;
  const system =
    /Windows/.test(agent) ? "Windows"
    : /Android/.test(agent) ? "Android"
    : /iPhone|iPad/.test(agent) ? "iOS"
    : /Mac OS X/.test(agent) ? "macOS"
    : /Linux/.test(agent) ? "Linux"
    : null;
  const label = [browser, system].filter(Boolean).join(" / ");
  return label ? label.slice(0, 200) : undefined;
}

async function registration(): Promise<ServiceWorkerRegistration> {
  await navigator.serviceWorker.register(SW_URL);
  return navigator.serviceWorker.ready;
}

/** 앱을 열 때 서비스 워커를 등록해 둔다. 실패해도 화면은 그대로 돈다(푸시만 안 온다). */
export async function ensureServiceWorker(): Promise<void> {
  if (USE_MOCKS || !pushSupported() || !VAPID_PUBLIC_KEY) return;
  try {
    await navigator.serviceWorker.register(SW_URL);
  } catch {
    // 등록에 실패하는 환경(비보안 출처, 사생활 보호 창)이 있다. 알림함은 그대로 쓸 수 있다
  }
}

function toRequest(subscription: PushSubscription): PushSubscriptionRequest {
  return {
    endpoint: subscription.endpoint,
    keys: {
      p256dh: base64url(subscription.getKey("p256dh")),
      auth: base64url(subscription.getKey("auth")),
    },
    user_agent: deviceLabel(),
  };
}

/** 지금 이 브라우저가 들고 있는 구독. 없으면 null이다. */
export async function currentSubscription(): Promise<PushSubscriptionRequest | null> {
  if (USE_MOCKS) return mockSubscription;
  if (!pushSupported() || !VAPID_PUBLIC_KEY || Notification.permission !== "granted") return null;
  try {
    const found = await (await registration()).pushManager.getSubscription();
    return found ? toRequest(found) : null;
  } catch {
    return null;
  }
}

export async function readState(): Promise<PushState> {
  const supported = pushSupported();
  const configured = Boolean(VAPID_PUBLIC_KEY);
  if (!supported || !configured) {
    return { supported, configured, permission: permissionNow(), subscribed: false };
  }
  return {
    supported,
    configured,
    permission: permissionNow(),
    subscribed: (await currentSubscription()) !== null,
  };
}

export class PushDeniedError extends Error {}

/**
 * 권한을 묻고 구독을 만든다. 이미 있으면 그것을 그대로 준다.
 *
 * 권한창은 사용자가 단추를 누른 그 자리에서만 띄운다 — 화면을 열자마자 묻는 사이트는
 * 브라우저가 다음부터 아예 막아 버린다.
 */
export async function subscribeHere(): Promise<PushSubscriptionRequest> {
  if (USE_MOCKS) {
    mockSubscription = {
      endpoint: `https://mock.push.example/${Math.random().toString(36).slice(2)}`,
      keys: { p256dh: "mock-p256dh", auth: "mock-auth" },
      user_agent: deviceLabel(),
    };
    return mockSubscription;
  }
  const granted = await Notification.requestPermission();
  if (granted !== "granted") throw new PushDeniedError(granted);
  const manager = (await registration()).pushManager;
  const found = await manager.getSubscription();
  if (found) return toRequest(found);
  const made = await manager.subscribe({
    userVisibleOnly: true, // 조용한 푸시는 크롬이 거절한다
    applicationServerKey: keyBytes(VAPID_PUBLIC_KEY),
  });
  return toRequest(made);
}

/** 이 브라우저의 구독을 지운다. 지운 주소를 돌려준다(서버에서도 지워야 한다). */
export async function unsubscribeHere(): Promise<string | null> {
  if (USE_MOCKS) {
    const endpoint = mockSubscription?.endpoint ?? null;
    mockSubscription = null;
    return endpoint;
  }
  if (!pushSupported()) return null;
  const found = await (await registration()).pushManager.getSubscription();
  if (!found) return null;
  const endpoint = found.endpoint;
  await found.unsubscribe();
  return endpoint;
}

/** 알림함 배너를 이번 방문 동안 접어 둔다(탭을 닫으면 다시 보인다). */
export function dismissBanner(): void {
  try {
    sessionStorage.setItem(DISMISS_KEY, "1");
  } catch {
    // 사생활 보호 창에서는 저장이 막힌다. 그러면 접힘이 안 남을 뿐이다
  }
}

export function bannerDismissed(): boolean {
  try {
    return sessionStorage.getItem(DISMISS_KEY) === "1";
  } catch {
    return false;
  }
}
