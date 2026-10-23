// Change VERSION on every static release; never intercept authentication or data.
const VERSION = "musicbot-dashboard-r27-vue-rebuild";
const PREFIX = "musicbot-dashboard-";
// vite-plugin-pwa injectManifest replaces this placeholder at build time.
const INJECTED = self.__WB_MANIFEST;
const ASSETS = new Set((Array.isArray(INJECTED) ? INJECTED : []).map(entry => {
  const value = typeof entry === "string" ? entry : entry && entry.url;
  if (typeof value !== "string" || value.includes("?") || value.includes("#")) return null;
  const url = new URL(value, self.location.origin);
  if (url.origin !== self.location.origin) return null;
  return url.pathname.startsWith("/") ? url.pathname : "/" + url.pathname;
}).filter(Boolean));
ASSETS.add(String.fromCharCode(47));

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(VERSION);
    try {
      for (const path of ASSETS) {
        const response = await fetch(new Request(path, {cache: "reload", credentials: "omit"}));
        if (!response.ok || response.redirected || response.type === "opaque") throw new Error("Static install failed");
        await cache.put(path, response);
      }
    } catch (error) {
      await caches.delete(VERSION);
      throw error;
    }
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => name.startsWith(PREFIX) && name !== VERSION)
      .map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener("message", event => {
  if (event.data?.type !== "musicbot-cache-sweep" || !event.ports?.[0]) return;
  event.waitUntil((async () => {
    const names = await caches.keys();
    const removed = await Promise.all(names
      .filter(name => name.startsWith(PREFIX) && name !== VERSION)
      .map(async name => ({name, deleted: await caches.delete(name)})));
    event.ports[0].postMessage({type: "musicbot-cache-sweep-complete", version: VERSION, removed});
  })().catch(error => {
    event.ports[0].postMessage({type: "musicbot-cache-sweep-failed", version: VERSION,
      error: String(error && error.message || error)});
  }));
});

self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin ||
      url.pathname === "/api" || url.pathname.startsWith("/api/") ||
      url.pathname === "/auth" || url.pathname.startsWith("/auth/") ||
      request.headers.get("Accept")?.includes("text/event-stream") ||
      /(?:^|\/)events(?:\/|$)/.test(url.pathname)) return;

  // Query-bearing navigation is never a cache key. Only a safe asset version
  // query is accepted so old clients can refresh static files by version.
  if (url.pathname === "/") {
    if (url.search) return;
    event.respondWith((async () => {
      try {
        const response = await fetch(request);
        if (!response.ok || response.redirected) return response;
        try {
          const cache = await caches.open(VERSION);
          await cache.put("/", response.clone());
        } catch { /* A quota failure must not hide a successful network response. */ }
        return response;
      } catch {
        return (await caches.match("/offline.html")) || new Response("Offline", {
          status: 503, headers: {"Content-Type": "text/plain; charset=utf-8"}});
      }
    })());
    return;
  }
  if (!ASSETS.has(url.pathname)) return;
  if (url.search && !/^\?v=[A-Za-z0-9._-]+$/.test(url.search)) return;

  const key = url.pathname;
  const update = (async () => {
    const response = await fetch(request);
    if (response.ok && !response.redirected) {
      try {
        const cache = await caches.open(VERSION);
        await cache.put(key, response.clone());
      } catch { /* Cache quota must not hide a successful network response. */ }
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

