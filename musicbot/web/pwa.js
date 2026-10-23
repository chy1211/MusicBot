"use strict";
if ("serviceWorker" in navigator) {
  const hadController = Boolean(navigator.serviceWorker.controller);
  // Subscribe before registration: a cached update can claim clients immediately.
  const sweepStaleCaches = worker => {
    if (!worker || typeof MessageChannel !== "function") return Promise.resolve(false);
    return new Promise(resolve => {
      const channel = new MessageChannel();
      const timeout = setTimeout(() => { channel.port1.close(); resolve(false); }, 5000);
      channel.port1.onmessage = event => {
        clearTimeout(timeout);
        channel.port1.close();
        resolve(event.data?.type === "musicbot-cache-sweep-complete" &&
          event.data.version === "musicbot-dashboard-r27-vue-rebuild");
      };
      worker.postMessage({type: "musicbot-cache-sweep"}, [channel.port2]);
    });
  };
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    const controller = navigator.serviceWorker.controller;
    sweepStaleCaches(controller);
    if (!hadController) return;
    Promise.resolve(dashboardI18nReady).then(() => {
      notice(t("m0222"));
      $("pwa-refresh").hidden = false;
    });
  });
  navigator.serviceWorker.register("/sw.js", {scope: "/", updateViaCache: "none"})
    .then(registration => {
      registration.update().catch(() => {});
      const controller = navigator.serviceWorker.controller;
      if (controller && new URL(controller.scriptURL).pathname === "/sw.js") sweepStaleCaches(controller);
    }).catch(() => {});
}
$("pwa-refresh").addEventListener("click", () => window.location.reload());
