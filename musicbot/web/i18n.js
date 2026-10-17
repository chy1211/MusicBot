"use strict";
let dashboardLanguage = "en", dashboardZone = "UTC", dashboardCatalog = {}, dashboardEnglish = {};
const DASHBOARD_LANGUAGES = ["en", "zh-TW"];
function dashboardLocale() { return dashboardLanguage; }
function dashboardTimeZone() { return dashboardZone; }
function supportedLanguage(value) {
  const tag = String(value || "").toLowerCase().replaceAll("_", "-");
  return tag.startsWith("en") ? "en" : tag.startsWith("zh") ? "zh-TW" : null;
}
function chooseLanguage(saved, languages, fallback) {
  if (DASHBOARD_LANGUAGES.includes(saved)) return saved;
  for (const tag of languages || []) { const match = supportedLanguage(tag); if (match) return match; }
  return DASHBOARD_LANGUAGES.includes(fallback) ? fallback : "en";
}
function t(key, params = {}) {
  const text = dashboardCatalog[key] ?? dashboardEnglish[key] ?? key;
  return text.replace(/\{(p\d+)\}/g, (match, name) => String(params[name] ?? match));
}
function applyDashboardLanguage() {
  document.documentElement.lang = dashboardLanguage;
  for (const element of document.querySelectorAll("[data-i18n]"))
    element.textContent = t(element.dataset.i18n);
  for (const attr of ["aria-label", "title", "placeholder", "content"])
    for (const element of document.querySelectorAll("[data-i18n-" + attr + "]"))
      element.setAttribute(attr, t(element.getAttribute("data-i18n-" + attr)));
  const select = document.getElementById("dashboard-language");
  if (select) select.value = dashboardLanguage;
}
async function initDashboardLanguage() {
  // Unit harness supplies a catalog without browser/network bootstrap.
  if (typeof dashboardTestCatalog !== "undefined") {
    dashboardLanguage = "zh-TW"; dashboardCatalog = dashboardTestCatalog; return;
  }
  let config = {};
  try { const response = await fetch("/ui-config", {cache:"no-store"}); if (response.ok) config = await response.json(); } catch {}
  dashboardZone = config.time_zone || "UTC";
  let saved = null;
  try { saved = window.localStorage.getItem("musicbot-language"); } catch {}
  dashboardLanguage = chooseLanguage(saved, navigator.languages || [navigator.language], config.default_language);
  try {
    const names = [...new Set(["en", dashboardLanguage])];
    const values = await Promise.all(names.map(async name => {
      const response = await fetch("/i18n/" + name + ".json?v=r13-i18n", {cache:"no-cache"});
      if (!response.ok) throw new Error("Language catalog unavailable");
      return response.json();
    }));
    dashboardEnglish = values[0]; dashboardCatalog = values[names.indexOf(dashboardLanguage)];
  } catch {
    // Retry can recover a partial/offline install; no untranslated application is shown.
    if (!Object.keys(dashboardEnglish).length) throw new Error("Language catalog unavailable. Refresh to retry.");
    dashboardCatalog = dashboardEnglish; dashboardLanguage = "en";
  }
  applyDashboardLanguage();
  document.getElementById("dashboard-language")?.addEventListener("change", event => {
    if (!DASHBOARD_LANGUAGES.includes(event.target.value)) return;
    try { window.localStorage.setItem("musicbot-language", event.target.value); } catch {}
    // Reload also refreshes dynamic state, errors and a live event stream consistently.
    window.location.reload();
  });
}
const dashboardI18nReady = initDashboardLanguage();
