"use strict";
if ("serviceWorker" in navigator) {
  // The first install also fires controllerchange (clients.claim); only an
  // already-controlled page has an older version to replace.
  const hadController = Boolean(navigator.serviceWorker.controller);
  navigator.serviceWorker.register("/sw.js", {scope: "/", updateViaCache: "none"})
    .then(registration => {
      registration.update().catch(() => {});
      navigator.serviceWorker.addEventListener("controllerchange", () => {
        if (!hadController) return;
        notice(t("m0222"));
        $("pwa-refresh").hidden = false;
      });
    }).catch(() => {});
}
$("pwa-refresh").addEventListener("click", () => window.location.reload());
