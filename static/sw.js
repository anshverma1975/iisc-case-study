// EduTracker service worker placeholder.
//
// This file is a no-op for now. It exists so the PWA manifest link in
// base.html has a valid registration target and so offline caching can be
// implemented in a future iteration (e.g. caching static assets and queuing
// session log submissions made while offline).
//
// TODO: implement install/activate/fetch handlers and a cache strategy
// (e.g. cache-first for static assets, network-first for API/data routes)
// once offline support is prioritized.

self.addEventListener("install", (event) => {
  // No caching yet - just take over immediately.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  // Pass-through for now; no offline cache implemented yet.
});
