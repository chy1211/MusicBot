"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright");

const publicDir = path.resolve(__dirname, "../frontend/public");
const catalogs = {
  en: JSON.parse(fs.readFileSync(path.join(publicDir, "i18n/en.json"), "utf8")),
  "zh-TW": JSON.parse(fs.readFileSync(path.join(publicDir, "i18n/zh-TW.json"), "utf8"))
};
const files = {
  "/offline.html": ["offline.html", "text/html; charset=utf-8"],
  "/offline.css": ["offline.css", "text/css; charset=utf-8"],
  "/offline.js": ["offline.js", "text/javascript; charset=utf-8"]
};

async function startServer(t) {
  const requests = { i18n: 0, uiConfig: 0 };
  const server = http.createServer((request, response) => {
    const pathname = new URL(request.url, "http://localhost").pathname;
    if (pathname === "/ui-config") requests.uiConfig++;
    if (pathname.startsWith("/i18n/")) requests.i18n++;
    if (files[pathname]) {
      const [name, type] = files[pathname];
      response.writeHead(200, { "content-type": type, "cache-control": "no-store" });
      response.end(fs.readFileSync(path.join(publicDir, name)));
      return;
    }
    if (pathname === "/") {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end("<!doctype html><title>Seed</title>");
      return;
    }
    if (pathname.startsWith("/i18n/")) {
      const locale = pathname.split("/").pop().replace(".json", "");
      if (catalogs[locale]) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify(catalogs[locale]));
        return;
      }
    }
    response.writeHead(404);
    response.end();
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  return { url: "http://localhost:" + server.address().port, requests };
}

async function newPage(browser, url, locale, theme, requests) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    locale,
    colorScheme: theme,
    isMobile: true,
    hasTouch: true,
    serviceWorkers: "block"
  });
  await context.route("**/*", async route => {
    const target = new URL(route.request().url());
    if (target.origin !== new URL(url).origin) {
      await route.abort("blockedbyclient");
      return;
    }
    await route.continue();
  });
  const page = await context.newPage();
  await page.goto(url + "/", { waitUntil: "domcontentloaded" });
  await page.evaluate(async language => {
    const english = await (await fetch("/i18n/en.json")).json();
    const chinese = await (await fetch("/i18n/zh-TW.json")).json();
    const cache = await caches.open("offline-test-catalogs");
    await cache.put("/i18n/en.json", new Response(JSON.stringify(english), {
      headers: { "content-type": "application/json" }
    }));
    await cache.put("/i18n/zh-TW.json", new Response(JSON.stringify(chinese), {
      headers: { "content-type": "application/json" }
    }));
    localStorage.setItem("musicbot-language", language);
  }, locale.toLowerCase().startsWith("zh") ? "zh-TW" : "en");
  const i18nAtOfflineStart = requests.i18n;
  await page.goto(url + "/offline.html", { waitUntil: "domcontentloaded" });
  return { context, page, i18nAtOfflineStart };
}

test("offline shell translates from cached catalogs only and keeps the canonical retry URL", async t => {
  const browser = await chromium.launch({ headless: true });
  t.after(() => browser.close());
  const server = await startServer(t);
  const themeColors = {};
  for (const theme of ["light", "dark"]) {
    for (const locale of ["en-US", "zh-TW"]) {
      const { context, page, i18nAtOfflineStart } = await newPage(browser, server.url, locale, theme, server.requests);
      try {
        await page.waitForFunction(language => document.documentElement.lang === language,
          locale === "zh-TW" ? "zh-TW" : "en", { timeout: 5000 });
        const expectedHeading = locale === "zh-TW" ? catalogs["zh-TW"]["offline.heading"] : catalogs.en["offline.heading"];
        assert.equal(await page.locator("#offline-heading").textContent(), expectedHeading);
        assert.equal(await page.locator("#offline-language").inputValue(), locale === "zh-TW" ? "zh-TW" : "en");
        assert.equal(await page.locator(".offline-retry").getAttribute("href"), "/");
        assert.equal(new URL(page.url()).pathname, "/offline.html");
        assert.equal(await page.locator("style").count(), 0);
        assert.equal(server.requests.i18n, i18nAtOfflineStart, "offline page must read catalogs only from Cache Storage");
        assert.equal(server.requests.uiConfig, 0);
        const color = await page.locator(".offline-card").evaluate(el => getComputedStyle(el).backgroundColor);
        assert.ok(color.startsWith("rgb("));
        themeColors[theme] = color;
        await page.locator("#offline-language").selectOption(locale === "zh-TW" ? "en" : "zh-TW");
        const changed = locale === "zh-TW" ? "en" : "zh-TW";
        await page.waitForFunction(language => document.documentElement.lang === language, changed, { timeout: 5000 });
        assert.equal(new URL(page.url()).pathname, "/offline.html", "language switching must not redirect");
      } finally {
        await context.close();
      }
    }
  }
  assert.notEqual(themeColors.light, themeColors.dark, "light and dark themes should use distinct card surfaces");
});

test("offline layout honors simulated safe areas and keeps retry target at least 44px", async t => {
  const browser = await chromium.launch({ headless: true });
  t.after(() => browser.close());
  const server = await startServer(t);
  for (const theme of ["light", "dark"]) {
    const { context, page } = await newPage(browser, server.url, "en-US", theme, server.requests);
    try {
      await page.addStyleTag({ content: ":root{--safe-top:59px;--safe-right:12px;--safe-bottom:34px;--safe-left:8px}" });
      const layout = await page.evaluate(() => {
        const shell = document.querySelector(".offline-shell").getBoundingClientRect();
        const retry = document.querySelector(".offline-retry").getBoundingClientRect();
        return {
          width: document.documentElement.clientWidth,
          scrollWidth: document.documentElement.scrollWidth,
          shellTop: shell.top,
          shellPaddingTop: parseFloat(getComputedStyle(document.querySelector(".offline-shell")).paddingTop),
          shellPaddingBottom: parseFloat(getComputedStyle(document.querySelector(".offline-shell")).paddingBottom),
          retryHeight: retry.height,
          retryLeft: retry.left,
          retryRight: retry.right
        };
      });
      assert.ok(layout.shellPaddingTop >= 87);
      assert.ok(layout.shellPaddingBottom >= 62);
      assert.ok(layout.retryHeight >= 44);
      assert.ok(layout.retryLeft >= 0 && layout.retryRight <= layout.width);
      assert.ok(layout.scrollWidth <= layout.width);
    } finally {
      await context.close();
    }
  }
});
