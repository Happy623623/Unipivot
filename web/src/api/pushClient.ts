import { apiFetch, USE_MOCKS } from "@/api/http";
import * as mock from "@/api/mockClient";
import type { PushSubscriptionRequest } from "@/types/api";

// 웹 푸시 구독 (F-33, API 명세 10장). 브라우저 쪽 일은 `lib/push.ts`가 하고 여기서는 서버에만 올린다.
// 응답으로 오는 `{ subscribed: true }`는 쓸 곳이 없어 버린다 — 키는 브라우저가 이미 갖고 있다

// POST /push/subscriptions. 같은 주소를 다시 보내면 키만 갱신한다(201 그대로)
export async function savePushSubscription(subscription: PushSubscriptionRequest): Promise<void> {
  if (USE_MOCKS) return mock.savePushSubscription(subscription);
  await apiFetch<{ subscribed: boolean }>("/push/subscriptions", {
    method: "POST",
    body: JSON.stringify(subscription),
  });
}

// DELETE /push/subscriptions. 없는 주소여도 204다(브라우저가 이미 지웠을 수 있다)
export async function removePushSubscription(endpoint: string): Promise<void> {
  if (USE_MOCKS) return mock.removePushSubscription(endpoint);
  await apiFetch<void>("/push/subscriptions", {
    method: "DELETE",
    body: JSON.stringify({ endpoint }),
  });
}
