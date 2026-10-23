#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

function parseArgs(argv) {
  const args = {};
  for (let index = 2; index < argv.length; index += 2) {
    const key = argv[index];
    if (!["--url", "--output"].includes(key) || index + 1 >= argv.length) {
      throw new Error("Usage: NODE_PATH=/tmp/musicbot-r26-tools/node_modules node tools/test_dashboard_round27_upgrade.cjs --url http://localhost:18270 [--output result.json]");
    }
    args[key.slice(2)] = argv[index + 1];
  }
  if (!args.url) {
    throw new Error("Usage: NODE_PATH=/tmp/musicbot-r26-tools/node_modules node tools/test_dashboard_round27_upgrade.cjs --url http://localhost:18270 [--output result.json]");
  }
  const url = new URL(args.url);
  if (url.protocol !== "http:" ||
      !["localhost", "127.0.0.1", "[::1]", "::1"].includes(url.hostname) ||
      url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("--url must be a clean HTTP root URL on localhost, 127.0.0.1, or ::1");
  }
  return { url: url.href, output: args.output ? path.resolve(args.output) : null };
}

const OLD_WORKER_PATH = "/demo-worker/legacy.js";
const NEW_WORKER_PATH = "/sw.js";
const OLD_CACHE = "musicbot-dashboard-r26-lyrics-popular";
const NEW_CACHE = "musicbot-dashboard-r27-vue-rebuild";
const report = { url: null, checks: [], controllerChanges: [], caches: [], offline: null };

function check(name, condition, details) {
  const result = { name, pass: Boolean(condition) };
  if (details !== undefined) result.details = details;
  report.checks.push(result);
  if (!result.pass) throw new Error(name + (details === undefined ? "" : ": " + JSON.stringify(details)));
}

async function waitFor(page, label, expression, options = {}) {
  try {
    await page.waitForFunction(expression, null, { timeout: options.timeout || 15000 });
  } catch (error) {
    throw new Error("Timed out waiting for " + label + ": " + error.message);
  }
}

async function run(url) {
  const origin = new URL(url).origin;
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    locale: "en",
    colorScheme: "light",
    serviceWorkers: "allow"
  });
  await context.route("**/*", async route => {
    const target = new URL(route.request().url());
    if (target.origin !== origin) {
      await route.abort("blockedbyclient");
      return;
    }
    await route.continue();
  });

  const page = await context.newPage();
  await page.addInitScript(() => {
    if (!("serviceWorker" in navigator)) return;
    const nativeRegister = navigator.serviceWorker.register.bind(navigator.serviceWorker);
    const gate = {
      pending: [],
      released: false,
      controllerAtBoot: Boolean(navigator.serviceWorker.controller),
      changes: [],
      nativeRegister,
      release() {
        this.released = true;
        for (const item of this.pending.splice(0)) {
          this.nativeRegister(item.scriptURL, item.options).then(item.resolve, item.reject);
        }
      }
    };
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      gate.changes.push(navigator.serviceWorker.controller?.scriptURL || "");
    });
    navigator.serviceWorker.register = function(scriptURL, options) {
      const target = new URL(scriptURL, location.href);
      if (target.pathname !== "/sw.js" || gate.released) return nativeRegister(scriptURL, options);
      return new Promise((resolve, reject) => gate.pending.push({ scriptURL, options, resolve, reject }));
    };
    Object.defineProperty(window, "__round27UpgradeGate", { configurable: false, value: gate });
  });

  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
    await waitFor(page,"session check",()=>document.querySelector('#dashboard') && (!document.querySelector('#dashboard').hidden || !document.querySelector('#discord-login').hidden));
    if(await page.locator('#discord-login').isVisible())await page.locator('#discord-login').click();
    await waitFor(page,"authenticated dashboard",()=>document.querySelector('#dashboard')?.hidden===false);
    await waitFor(page, "the app's automatic /sw.js registration to be held", () =>
      window.__round27UpgradeGate?.pending.some(item => new URL(item.scriptURL, location.href).pathname === "/sw.js"));

    const oldRegistration = await page.evaluate(async oldWorkerPath => {
      const gate = window.__round27UpgradeGate;
      const registration = await gate.nativeRegister(
        new URL(oldWorkerPath, location.origin).href,
        { scope: "/" }
      );
      return {
        scope: registration.scope,
        scriptURL: registration.installing?.scriptURL ||
          registration.waiting?.scriptURL || registration.active?.scriptURL || ""
      };
    }, OLD_WORKER_PATH);
    check("legacy worker was registered for the root scope",
      oldRegistration.scope === origin + "/" &&
      oldRegistration.scriptURL.endsWith(OLD_WORKER_PATH), oldRegistration);

    await waitFor(page, "the actual r26 worker to control the app", () => {
      const controller = navigator.serviceWorker?.controller;
      return Boolean(controller && new URL(controller.scriptURL).pathname === "/demo-worker/legacy.js");
    }, { timeout: 30000 });
    const initialController = await page.evaluate(() => navigator.serviceWorker.controller.scriptURL);
    check("initial controlling worker is the actual legacy worker",
      new URL(initialController).pathname === OLD_WORKER_PATH, initialController);

    await page.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
    await waitFor(page, "the app to hold its automatic registration on an old-controlled load", () =>
      window.__round27UpgradeGate?.controllerAtBoot === true &&
      window.__round27UpgradeGate?.pending.some(item => new URL(item.scriptURL, location.href).pathname === "/sw.js"),
      { timeout: 20000 });
    const hadOldController = await page.evaluate(() => window.__round27UpgradeGate.controllerAtBoot);
    check("second app load started with an existing controller", hadOldController);

    await page.evaluate(() => window.__round27UpgradeGate.release());
    await waitFor(page, "controllerchange to the new /sw.js worker", () => {
      const controller = navigator.serviceWorker?.controller;
      return Boolean(controller && new URL(controller.scriptURL).pathname === "/sw.js");
    }, { timeout: 45000 });
    const newController = await page.evaluate(() => navigator.serviceWorker.controller.scriptURL);
    report.controllerChanges = await page.evaluate(() => window.__round27UpgradeGate.changes.slice());
    check("controller changed from the legacy worker to /sw.js",
      new URL(newController).pathname === NEW_WORKER_PATH, {
        old: initialController, current: newController, changes: report.controllerChanges
      });

    await waitFor(page, "the visible refresh-to-update control", () => {
      const button = document.querySelector("#pwa-refresh");
      return Boolean(button && !button.hidden && button.getClientRects().length);
    }, { timeout: 15000 });
    check("controllerchange exposes the existing PWA refresh button",
      await page.locator("#pwa-refresh").isVisible());

    await page.locator("#pwa-refresh").click();
    await page.waitForLoadState("domcontentloaded", { timeout: 20000 });
    await waitFor(page, "the refreshed app to remain controlled by /sw.js", () =>
      Boolean(navigator.serviceWorker?.controller &&
        new URL(navigator.serviceWorker.controller.scriptURL).pathname === "/sw.js"));
    check("the PWA refresh control reloads into the new app",
      new URL(page.url()).origin === origin &&
      await page.locator("#app").count() === 1 &&
      await page.locator("#pwa-refresh").count() === 1,
      { url: page.url() });

    const sweepAck = await page.evaluate(() => new Promise((resolve, reject) => {
      const worker = navigator.serviceWorker.controller;
      if (!worker || new URL(worker.scriptURL).pathname !== "/sw.js") return reject(new Error("new worker does not control refreshed page"));
      const channel = new MessageChannel();
      const timeout = setTimeout(() => { channel.port1.close(); reject(new Error("cache sweep acknowledgement timed out")); }, 10000);
      channel.port1.onmessage = event => { clearTimeout(timeout); channel.port1.close(); resolve(event.data); };
      worker.postMessage({type: "musicbot-cache-sweep"}, [channel.port2]);
    }));
    check("refreshed app receives acknowledged stale-cache cleanup",
      sweepAck.type === "musicbot-cache-sweep-complete" &&
      sweepAck.version === "musicbot-dashboard-r27-vue-rebuild", sweepAck);
    const workerState = await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.ready;
      const names = await caches.keys();
      const appCaches = names.filter(name => name.startsWith("musicbot-dashboard-"));
      const entries = [];
      for (const name of appCaches) {
        const cache = await caches.open(name);
        for (const request of await cache.keys()) {
          entries.push({ cache: name, pathname: new URL(request.url).pathname });
        }
      }
      return {
        scope: registration.scope,
        active: registration.active?.scriptURL || "",
        names,
        appCaches,
        entries
      };
    });
    report.caches = workerState;
    check("new worker is active at the root scope",
      workerState.scope === origin + "/" &&
      new URL(workerState.active).pathname === NEW_WORKER_PATH, workerState);
    check("legacy r26 cache was removed by actual worker activation",
      !workerState.names.includes(OLD_CACHE), workerState.names);
    check("new r27 cache exists after actual worker activation",
      workerState.names.includes(NEW_CACHE), workerState.names);
    check("new worker cache contains no API, auth, or event data",
      workerState.entries.every(item =>
        item.pathname !== "/api" && !item.pathname.startsWith("/api/") &&
        item.pathname !== "/auth" && !item.pathname.startsWith("/auth/") &&
        !/(^|\/)events(\/|$)/.test(item.pathname)),
      workerState.entries);

    await context.setOffline(true);
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
    await page.locator("#offline-heading").waitFor({ state: "visible", timeout: 10000 });
    const offline = await page.evaluate(() => ({
      title: document.querySelector("#offline-heading")?.textContent?.trim() || "",
      path: location.pathname,
      retry: document.querySelector(".offline-retry")?.getAttribute("href") || ""
    }));
    report.offline = offline;
    check("offline canonical root resolves to the cached new offline page",
      offline.title === "You are offline" && offline.retry === "/", offline);
  } finally {
    await context.close();
    await browser.close();
  }
}

(async () => {
  let args;
  try {
    args = parseArgs(process.argv);
    report.url = args.url;
    await run(args.url);
    const result = { ...report, checkCount: report.checks.length };
    if (args.output) {
      fs.mkdirSync(path.dirname(args.output), { recursive: true });
      fs.writeFileSync(args.output, JSON.stringify(result, null, 2));
    }
    process.stdout.write(JSON.stringify(result, null, 2) + "\n");
  } catch (error) {
    report.error = String(error && error.stack || error);
    if (args?.output) {
      fs.mkdirSync(path.dirname(args.output), { recursive: true });
      fs.writeFileSync(args.output, JSON.stringify({
        ...report, checkCount: report.checks.length
      }, null, 2));
    }
    process.stderr.write(report.error + "\n");
    process.exitCode = 1;
  }
})();

