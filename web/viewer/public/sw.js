// Minimal pass-through service worker. Exists so the app is installable (and
// as the future hook for web push). Deliberately caches nothing: stale chat
// responses are far worse than no offline mode, and /assets is content-hashed
// anyway. All fetches go straight to the network.
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

// Straight to the network — the handler's existence (not its behavior) is
// what some Chrome versions check before offering a real install.
self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    // opaque payload — show a generic notification below
  }
  const url = data.url || "/talk";
  event.waitUntil(
    (async () => {
      // Skip the banner when that conversation is already open and focused.
      const wins = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });
      if (wins.some((w) => w.focused && new URL(w.url).pathname === url)) {
        return;
      }
      await self.registration.showNotification(data.title || "shellm", {
        body: data.body || "New message",
        icon: "/icons/icon-192.png",
        badge: "/icons/icon-192.png",
        tag: data.tag || url,
        data: { url },
      });
    })()
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/talk";
  event.waitUntil(
    (async () => {
      const wins = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });
      for (const w of wins) {
        if (new URL(w.url).pathname.startsWith("/talk")) {
          await w.focus();
          if ("navigate" in w) await w.navigate(url);
          return;
        }
      }
      await self.clients.openWindow(url);
    })()
  );
});
