"use strict";
// Change VERSION on every static release; never intercept authentication/data.
const VERSION = "musicbot-dashboard-r8-1";
const STATIC = ["/", "/offline.html", "/dashboard.css", "/dashboard.js", "/library.js",
  "/admin.js", "/permissions.js", "/pwa.js", "/favicon.svg", "/manifest.webmanifest",
  "/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"];
const ASSETS = new Set(STATIC);
self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(VERSION);
    for (const path of STATIC) {
      const response = await fetch(new Request(path, {cache: "reload", credentials: "omit"}));
      if (!response.ok || response.redirected) throw new Error("Static install failed");
      await cache.put(path, response);
    }
    await self.skipWaiting();
  })());
});
self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => name.startsWith("musicbot-dashboard-") && name !== VERSION)
      .map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", event => {
  const request = event.request, url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin ||
      url.pathname === "/api" || url.pathname.startsWith("/api/") ||
      url.pathname === "/auth" || url.pathname.startsWith("/auth/") ||
      request.headers.get("Accept")?.includes("text/event-stream") ||
      /(?:^|\/)events(?:\/|$)/.test(url.pathname) || !ASSETS.has(url.pathname)) return;
  // Only canonical static requests or an explicit static version parameter.
  if (url.search && (url.pathname === "/" || [...url.searchParams.keys()].some(key => key !== "v"))) return;
  const key = url.pathname;
  if (key === "/") {
    event.respondWith((async () => {
      try {
        const response = await fetch(request);
        if (!response.ok || response.redirected) return response;
        try {
          const cache = await caches.open(VERSION);
          await cache.put("/", response.clone());
        } catch { /* Cache quota must not hide a successful network response. */ }
        return response;
      } catch {
        return (await caches.match("/offline.html")) || new Response("目前離線", {
          status: 503, headers: {"Content-Type": "text/plain; charset=utf-8"}});
      }
    })());
    return;
  }
  const update = (async () => {
    const response = await fetch(request);
    if (response.ok && !response.redirected) {
      const cache = await caches.open(VERSION);
      await cache.put(key, response.clone());
    }
    return response;
  })();
  event.waitUntil(update.catch(() => {}));
  event.respondWith((async () => {
    const cached = await caches.match(key);
    if (cached) return cached;
    try { return await update; } catch { return new Response("", {status: 503}); }
  })());
});
