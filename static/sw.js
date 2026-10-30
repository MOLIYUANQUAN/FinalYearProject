// Friday 的 Service Worker：只做一件事——把服务端推来的通知显示出来，点了就打开 Friday。
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "Friday", {
      body: data.body || "",
      tag: data.tag || undefined,
      icon: "/static/icon-192.png?v=ring1",
      badge: "/static/icon-192.png?v=ring1",
      data: { url: data.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ("focus" in client) {
          client.postMessage({ type: "nudge", url });
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});
