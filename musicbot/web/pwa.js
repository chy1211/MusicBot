"use strict";
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js", {scope: "/", updateViaCache: "none"})
    .then(registration => {
      registration.update().catch(() => {});
      navigator.serviceWorker.addEventListener("controllerchange", () => {
        notice("控制台已更新，重新整理後使用新版。");
        $("pwa-refresh").hidden = false;
      });
    }).catch(() => {});
}
$("pwa-refresh").addEventListener("click", () => window.location.reload());
