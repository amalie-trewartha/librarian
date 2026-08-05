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
