// 웹 푸시 서비스 워커 (F-33, API 명세 10장). 번들을 타지 않는 평범한 자바스크립트다 —
// public/에 그대로 놓여 /sw.js 주소로 나가고, 그래야 범위(scope)가 사이트 전체가 된다.
//
// 하는 일은 둘뿐이다: 푸시를 받아 알림을 띄우고, 누르면 그 화면으로 보낸다.
// 캐시·오프라인은 하지 않는다 — 우리 화면은 로그인한 사용자의 최신 자료만 보여 준다.

// 받은 본문이 우리 모양이 아니면(푸시 서비스 점검 메시지 등) 알림함으로 보낸다
const FALLBACK = { title: "새 알림이 있어요", body: null, url: "/notifications", notification_id: "" };

function payloadOf(event) {
  if (!event.data) return FALLBACK;
  try {
    const data = event.data.json();
    if (!data || typeof data.title !== "string") return FALLBACK;
    return {
      title: data.title,
      body: typeof data.body === "string" ? data.body : null,
      url: typeof data.url === "string" && data.url.startsWith("/") ? data.url : "/",
      notification_id: typeof data.notification_id === "string" ? data.notification_id : "",
      type: typeof data.type === "string" ? data.type : "",
    };
  } catch {
    return FALLBACK;
  }
}

// 설치하자마자 새 워커가 일한다. 고친 워커가 다음 방문까지 기다리면 사용자는 옛 동작을 본다
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  const payload = payloadOf(event);
  // tag를 알림 id로 두면 같은 알림이 두 번 와도 하나만 쌓인다(id가 없으면 겹치지 않게 둔다)
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body ?? undefined,
      data: { url: payload.url, notification_id: payload.notification_id },
      tag: payload.notification_id || undefined,
      lang: "ko",
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      // 이미 열어 둔 탭이 있으면 그 탭을 쓴다. 누를 때마다 새 창이 생기면 성가시다
      for (const client of windows) {
        if (new URL(client.url).origin !== self.location.origin) continue;
        return client.focus().then((focused) => {
          // navigate는 워커가 아직 그 탭을 맡지 않았으면 거절한다. 그때는 새 창으로 연다
          if (!focused.navigate) return self.clients.openWindow(url);
          return focused.navigate(url).catch(() => self.clients.openWindow(url));
        });
      }
      return self.clients.openWindow(url);
    }),
  );
});
