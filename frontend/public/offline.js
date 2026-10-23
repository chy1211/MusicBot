"use strict";
(() => {
  const languages = ["en", "zh-TW"];
  const selector = document.getElementById("offline-language");
  if (!selector) return;

  function preferredLanguage() {
    try {
      const saved = localStorage.getItem("musicbot-language");
      if (languages.includes(saved)) return saved;
    } catch {}
    const requested = [...(navigator.languages || []), navigator.language || ""];
    return requested.some(value => String(value).toLowerCase().startsWith("zh")) ? "zh-TW" : "en";
  }

  async function readCachedCatalog(language) {
    if (!("caches" in window)) return null;
    try {
      const url = new URL("/i18n/" + language + ".json", location.origin).href;
      const response = await caches.match(url);
      if (!response || !response.ok) return null;
      const catalog = await response.json();
      return catalog && typeof catalog === "object" ? catalog : null;
    } catch {
      return null;
    }
  }

  function applyCatalog(language, catalog) {
    document.documentElement.lang = language;
    for (const element of document.querySelectorAll("[data-i18n]")) {
      const value = catalog[element.dataset.i18n];
      if (typeof value === "string") element.textContent = value;
    }
    for (const element of document.querySelectorAll("[data-i18n-aria-label]")) {
      const value = catalog[element.dataset.i18nAriaLabel];
      if (typeof value === "string") element.setAttribute("aria-label", value);
    }
    selector.value = language;
    const title = catalog["offline.title"];
    if (typeof title === "string") document.title = title;
    try { localStorage.setItem("musicbot-language", language); } catch {}
  }

  async function selectLanguage(language) {
    if (!languages.includes(language)) return;
    const catalog = await readCachedCatalog(language);
    if (catalog) applyCatalog(language, catalog);
  }

  selector.addEventListener("change", () => { void selectLanguage(selector.value); });
  void selectLanguage(preferredLanguage());
})();
