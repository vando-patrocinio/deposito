/* Service Worker do app de Ponto — Web Push */
self.addEventListener("install", (e) => { self.skipWaiting(); });
self.addEventListener("activate", (e) => { e.waitUntil(self.clients.claim()); });

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { title: "Alerta", body: event.data ? event.data.text() : "" }; }
  const title = data.title || "Alerta de campo";
  const opts = {
    body: data.body || "",
    tag: data.tag || "ponto-alert",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    data: { url: data.url || "/", alert_id: data.alert_id, level: data.level },
    requireInteraction: data.level === "danger",
    vibrate: data.level === "danger" ? [200, 100, 200] : [100],
  };
  event.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if ("focus" in w) { w.focus(); try { w.navigate(url); } catch (e) {} return; }
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    }),
  );
});
