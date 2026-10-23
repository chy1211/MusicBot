#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

function parseArgs(argv) {
  const values = {};
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i];
    if (!["--url", "--output", "--round"].includes(key) || i + 1 >= argv.length) {
      throw new Error("Usage: node tools/test_dashboard_round27.cjs --url URL --output DIR --round 1..4");
    }
    values[key.slice(2)] = argv[i + 1];
  }
  const round = Number(values.round);
  if (!values.url || !values.output || !Number.isInteger(round) || round < 1 || round > 4) {
    throw new Error("Usage: node tools/test_dashboard_round27.cjs --url URL --output DIR --round 1..4");
  }
  const url = new URL(values.url);
  if (url.protocol !== "http:" || url.hostname !== "localhost" || url.username || url.password) throw new Error("Only isolated http://localhost is allowed");
  return { url: url.href, output: path.resolve(values.output), round };
}

const matrix = [
  { name: "mobile390", width: 390, height: 844, mobile: true, standalone: false },
  { name: "standalone393", width: 393, height: 852, mobile: true, standalone: true },
  { name: "desktop1440", width: 1440, height: 1000, mobile: false, standalone: false }
];
const themes = ["light", "dark"];
const results = { round: null, url: null, screenshots: [], assertions: [], errors: [] };
let assertionCount = 0;

function check(scope, name, condition, details = null) {
  const pass = Boolean(condition);
  assertionCount++;
  const item = { scope, name, pass, ...(details === null ? {} : { details }) };
  results.assertions.push(item);
  if (!pass) throw new Error(scope + ": " + name + (details ? " " + JSON.stringify(details) : ""));
}

async function waitVisible(locator, label, timeout = 15000) {
  await locator.waitFor({ state: "visible", timeout });
  check("setup", label + " visible", await locator.isVisible());
}

async function capture(page, output, scope, scene, standalone, errorLog) {
  await page.waitForTimeout(250);
  const layout = await page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const height = document.documentElement.clientHeight;
    const rect = element => {
      const box = element.getBoundingClientRect();
      return { x: box.x, y: box.y, right: box.right, bottom: box.bottom, width: box.width, height: box.height };
    };
    const nav = [...document.querySelectorAll("#nav-play, #nav-library, #nav-popular, #nav-admin")]
      .filter(el => !el.hidden && el.getClientRects().length);
    const targets = nav.map(el => ({ id: el.id, ...rect(el) }));
    const overlays = [...document.querySelectorAll(
      "#lyrics-panel:not([hidden]), #song-choices:not([hidden]), #shortcuts-dialog[open], #library-save-dialog[open], #permission-confirm-dialog[open], #notice.visible"
    )].filter(el => el.getClientRects().length).map(el => ({ id: el.id, ...rect(el) }));
    return {
      width, height, scrollWidth: document.documentElement.scrollWidth,
      targets, overlays,
      playback: document.querySelector("#playback-bar")?.getClientRects().length
        ? rect(document.querySelector("#playback-bar")) : null,
      pageTabs: document.querySelector(".page-tabs")?.getClientRects().length
        ? rect(document.querySelector(".page-tabs")) : null,
      notice: document.querySelector("#notice")?.classList.contains("visible")
        ? rect(document.querySelector("#notice")) : null
    };
  });
  check(scope, scene + " has no horizontal page overflow", layout.scrollWidth <= layout.width,
    { scrollWidth: layout.scrollWidth, viewport: layout.width });
  check(scope, scene + " visible navigation targets are at least 44px high",
    (scene === "offline" || layout.targets.length > 0) && layout.targets.every(target => target.height >= 44),
    layout.targets.map(({ id, height }) => ({ id, height })));
  check(scope, scene + " visible overlays stay inside viewport",
    layout.overlays.every(box => box.x >= -1 && box.y >= -1 && box.right <= layout.width + 1 && box.bottom <= layout.height + 1),
    layout.overlays);
  check(scope, scene + " has no pageerror or console.error",
    errorLog.page.length === 0 && errorLog.console.length === 0,
    { page: errorLog.page, console: errorLog.console });
  if (standalone && scene === "toast") {
    check(scope, "standalone toast respects the 59px safe top inset",
      layout.notice !== null && layout.notice.y >= 71,
      layout.notice);
    check(scope, "standalone playback bar sits above bottom navigation",
      layout.playback !== null && layout.pageTabs !== null &&
      layout.playback.bottom <= layout.pageTabs.y + 2 && layout.pageTabs.bottom <= 818,
      { playback: layout.playback, pageTabs: layout.pageTabs });
  }
  const filename = "round" + results.round + "-" + scope + "-" + scene + ".png";
  const full = path.join(output, filename);
  await page.screenshot({ path: full, fullPage: false, animations: "disabled" });
  results.screenshots.push(full);
}

async function installStandaloneInit(context) {
  await context.addInitScript(() => {
    const registration = navigator.serviceWorker.register.bind(navigator.serviceWorker);
    navigator.serviceWorker.register = async (...args) => {
      if (sessionStorage.getItem("r27-sw-tested")) return registration(...args);
      await new Promise(resolve => {window.__r27ReleaseSW = resolve});
      return registration(...args);
    };
    const original = window.matchMedia.bind(window);
    window.matchMedia = query => {
      const value = original(query);
      if (query.includes("display-mode: standalone")) {
        try { Object.defineProperty(value, "matches", { configurable: true, value: true }); } catch {}
      }
      return value;
    };
    const install = () => {
      if (!document.documentElement) return;
      const root=document.documentElement;
      for(const [name,value] of Object.entries({top:'59px',bottom:'34px',left:'0px',right:'0px'})) root.style.setProperty('--safe-'+name,value);
    };
    if (document.documentElement) install();
    else document.addEventListener("DOMContentLoaded", install, { once: true });
  });
}

async function runPwaAssertions(page, routeGate, releaseServiceWorker) {
  await page.waitForFunction(() => typeof window.__r27ReleaseSW === "function");
  await page.evaluate(async () => {
    const cache = await caches.open("musicbot-dashboard-r26-round27-seed");
    await cache.put("/legacy-cache-seed.txt", new Response("old installed version"));
    window.__r27ReleaseSW();
    sessionStorage.setItem("r27-sw-tested","1");
  });
  await page.waitForFunction(()=>!!navigator.serviceWorker.controller,null,{timeout:20000});
  const ready = await page.evaluate(async () => {
    const registration = await Promise.race([navigator.serviceWorker.ready,new Promise((_,reject)=>setTimeout(()=>reject(new Error("PWA activation timed out")),15000))]);
    return {
      scope: registration.scope,
      active: Boolean(registration.active && registration.active.state === "activated")
    };
  });
  check("standalone393-light", "PWA registration reaches activated state", ready.active, ready);
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => Boolean(navigator.serviceWorker && navigator.serviceWorker.controller), null, { timeout: 15000 });
  const state = await page.evaluate(async () => {
    const registration = await Promise.race([navigator.serviceWorker.ready,new Promise((_,reject)=>setTimeout(()=>reject(new Error("PWA activation timed out")),15000))]);
    await registration.update();
    const names = await caches.keys();
    const currentCaches = names.filter(name => name.startsWith("musicbot-dashboard-"));
    const entries = [];
    for (const name of currentCaches) {
      const cache = await caches.open(name);
      for (const request of await cache.keys()) entries.push(new URL(request.url).pathname);
    }
    return {
      controlled: Boolean(navigator.serviceWorker.controller),
      scope: registration.scope,
      names,
      currentCaches,
      entries
    };
  });
  check("standalone393-light", "PWA page is controlled by installed worker", state.controlled, state.scope);
  check("standalone393-light", "old installed PWA cache is removed",
    !state.names.includes("musicbot-dashboard-r26-round27-seed"), state.names);
  check("standalone393-light", "service worker caches contain no auth or API data",
    state.entries.every(name => name !== "/api" && !name.startsWith("/api/") &&
      name !== "/auth" && !name.startsWith("/auth/") && !/(^|\/)events(\/|$)/.test(name)),
    state.entries);
}

async function runScenario(baseUrl, output, viewport, theme) {
  const scope = viewport.name + "-" + theme;
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: 1,
    isMobile: viewport.mobile,
    hasTouch: viewport.mobile,
    locale: "zh-TW",
    colorScheme: theme,
    serviceWorkers: "allow"
  });
  if (viewport.standalone) await installStandaloneInit(context);
  const page = await context.newPage();
  const errorLog = { page: [], console: [] };
  page.on("pageerror", error => errorLog.page.push(String(error && error.stack || error)));
  page.on("console", message => {
    if (message.type() === "error") errorLog.console.push(message.text());
  });

  let releaseServiceWorker = () => {};
  let gateRequestedResolve = null;
  const routeGate = { requested: new Promise(resolve => { gateRequestedResolve = resolve; }), requestedOnce: false };
  const gate = new Promise(resolve => { releaseServiceWorker = resolve; });
  let workerGateEnabled = false;
  await page.route("**/*", async route => {
    const requestUrl = new URL(route.request().url());
    const origin = new URL(baseUrl).origin;
    if (requestUrl.origin !== origin) {
      if (route.request().resourceType() === "image") {
        await route.fulfill({
          status: 200,
          contentType: "image/svg+xml",
          body: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="#73876a"/><stop offset="1" stop-color="#202b29"/></linearGradient></defs><rect width="256" height="256" fill="url(#g)"/><circle cx="128" cy="128" r="76" fill="#d4d9b0" opacity=".7"/><circle cx="128" cy="128" r="24" fill="#34443e"/></svg>'
        });
      } else {
        await route.abort("blockedbyclient");
      }
      return;
    }
    if (workerGateEnabled && requestUrl.pathname === "/sw.js") {
      workerGateEnabled = false;
      routeGate.requestedOnce = true;
      gateRequestedResolve();
      await gate;
    }
    await route.continue();
  });

  try {
    await page.goto(new URL("/?demo-queue=filled&demo-lyrics=synced", baseUrl).href, { waitUntil: "domcontentloaded", timeout: 30000 });
    if (viewport.standalone) await runPwaAssertions(page, routeGate, releaseServiceWorker);
    await page.waitForFunction(()=>document.querySelector("#dashboard") && (!document.querySelector("#dashboard").hidden || !document.querySelector("#discord-login").hidden));
    if(await page.locator("#discord-login").isVisible()) await page.locator("#discord-login").click();
    await page.waitForFunction(() => {
      const app = document.querySelector("#dashboard");
      const button = document.querySelector("#nav-play");
      return app && !app.hidden && button && !button.hidden && !button.disabled;
    }, null, { timeout: 20000 });
    await waitVisible(page.locator("#nav-play"), scope + " dashboard enabled");
    await page.waitForFunction(()=>!document.querySelector("#notice")?.classList.contains("visible"));
    await capture(page, output, scope, "main-top", viewport.standalone, errorLog);

    await page.locator("#queue").scrollIntoViewIfNeeded();
    await capture(page, output, scope, "queue", viewport.standalone, errorLog);

    const lyricsButton = page.locator("#lyrics-toggle");
    await page.waitForFunction(() => {
      const button = document.querySelector("#lyrics-toggle");
      return button && !button.disabled && !button.hidden;
    }, null, { timeout: 15000 });
    await lyricsButton.click();
    await waitVisible(page.locator("#lyrics-panel"), scope + " lyrics panel");
    const timing = page.locator("#lyrics-timing-controls");
    await timing.waitFor({ state: "visible", timeout: 15000 });
    await page.locator("#lyrics-timing-toggle").click();
    await waitVisible(page.locator("#lyrics-timing-menu"), scope + " expanded lyrics timing");
    await capture(page, output, scope, "lyrics-timing", viewport.standalone, errorLog);
    await page.locator("#lyrics-close").click();

    await page.locator("#nav-play").click();
    const query = page.locator("#query");
    await query.fill("Sunset");
    await page.locator("#enqueue").click();
    await waitVisible(page.locator("#preview-panel"), scope + " search preview");
    check(scope, "search preview contains observable results",
      await page.locator("#preview-results").locator(":scope > *").count() > 0);
    await capture(page, output, scope, "search-preview", viewport.standalone, errorLog);
    await page.locator("#preview-close").click().catch(() => {});

    await page.locator("#nav-popular").click();
    await waitVisible(page.locator("#popular-panel"), scope + " popular view");
    await capture(page, output, scope, "popular", viewport.standalone, errorLog);

    await page.locator("#nav-play").click();
    const favorite = page.locator("#favorite");
    await favorite.waitFor({ state: "visible", timeout: 10000 });
    await page.waitForFunction(() => {
      const button = document.querySelector("#favorite");
      return button && !button.disabled;
    }, null, { timeout: 15000 });
    if (await favorite.getAttribute("aria-pressed") === "true") {
      await favorite.click();
      await page.waitForFunction(() => document.querySelector("#favorite")?.getAttribute("aria-pressed") === "false",
        null, { timeout: 15000 });
    }
    await favorite.click();
    await page.waitForFunction(() => document.querySelector("#favorite")?.getAttribute("aria-pressed") === "true",
      null, { timeout: 15000 });
    await page.waitForFunction(() => document.querySelector("#notice")?.classList.contains("visible"),
      null, { timeout: 10000 });
    const notice = await page.locator("#notice").textContent();
    check(scope, "saving the current favorite shows a toast", Boolean(notice && notice.trim()), notice);
    await capture(page, output, scope, "toast", viewport.standalone, errorLog);

    await page.locator("#nav-library").click();
    await waitVisible(page.locator("#library-panel"), scope + " library view");
    await page.waitForFunction(() => document.querySelectorAll("#library-playlists .playlist-cover img[src]").length > 0,
      null, { timeout: 15000 });
    const cover = await page.locator("#library-playlists .playlist-cover img[src]").count();
    check(scope, "saved favorite playlist cover has an image", cover > 0, { images: cover });
    await capture(page, output, scope, "library-cover", viewport.standalone, errorLog);

    await page.locator("#nav-admin").waitFor({ state: "visible", timeout: 10000 });
    await page.locator("#nav-admin").click();
    await waitVisible(page.locator("#admin-panel"), scope + " admin view");
    await page.waitForSelector("#admin-permissions details");
    await page.locator("#admin-permissions details").first().evaluate(e=>e.open=true);
    await page.locator("#admin-permissions").evaluate(e=>e.scrollIntoView({block:"start"}));
    check(scope, "admin permissions section is rendered",
      await page.locator("#admin-permissions").isVisible());
    await capture(page, output, scope, "admin-permissions", viewport.standalone, errorLog);

    await page.goto(new URL("/?demo-queue=empty&demo-lyrics=synced",baseUrl).href);
    await page.waitForSelector("#queue-empty:visible");
    await page.locator("#queue-empty").evaluate(e=>e.scrollIntoView({block:"center"}));
    check(scope,"empty queue has no track rows",await page.locator("#queue > li").count()===0);
    await capture(page,output,scope,"empty-queue",viewport.standalone,errorLog);
    await page.waitForFunction(()=>!!navigator.serviceWorker.controller,null,{timeout:20000});
    await context.setOffline(true);
    await page.goto(new URL("/",baseUrl).href,{waitUntil:"domcontentloaded"});
    await page.waitForSelector(".offline-card");
    check(scope,"offline fallback has a visible retry link",await page.locator('a[href="/"]').isVisible());
    await capture(page,output,scope,"offline",viewport.standalone,errorLog);
    await context.setOffline(false);
    await page.waitForTimeout(300);
    check(scope, "scenario finishes without uncaught browser errors",
      errorLog.page.length === 0 && errorLog.console.length === 0,
      { page: errorLog.page, console: errorLog.console });
  } finally {
    await context.close();
    await browser.close();
  }
}

(async () => {
  let args;
  try {
    args = parseArgs(process.argv);
    results.round = args.round;
    results.url = args.url;
    fs.mkdirSync(args.output, { recursive: true });
    for (const viewport of matrix) {
      for (const theme of themes) await runScenario(args.url, args.output, viewport, theme);
    }
    check("matrix", "at least 30 observable assertion scenarios were recorded", assertionCount >= 30,
      { count: assertionCount });
    const resultFile = path.join(args.output, "round" + args.round + "-dashboard-matrix.json");
    fs.writeFileSync(resultFile, JSON.stringify({
      ...results, assertionCount, resultFile
    }, null, 2));
    process.stdout.write(JSON.stringify({
      round: args.round,
      assertionCount,
      screenshots: results.screenshots.length,
      resultFile,
      output: args.output
    }, null, 2) + "\n");
  } catch (error) {
    results.errors.push(String(error && error.stack || error));
    if (args) {
      const resultFile = path.join(args.output, "round" + args.round + "-dashboard-matrix.json");
      fs.mkdirSync(args.output, { recursive: true });
      fs.writeFileSync(resultFile, JSON.stringify({ ...results, assertionCount, resultFile }, null, 2));
    }
    process.stderr.write(String(error && error.stack || error) + "\n");
    process.exitCode = 1;
  }
})();

