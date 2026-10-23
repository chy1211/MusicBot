"use strict";
const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const { spawn, spawnSync } = require("node:child_process");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const { chromium } = require("playwright");
const http = require("node:http");
const frontend = path.join(root, "frontend");
const baseURL = "http://localhost:18310";
let serverProcess;
let browser;

function waitForHealth(timeoutMs = 30000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const probe = () => {
      const req = http.get(baseURL + "/healthz", res => {
        res.resume();
        if (res.statusCode === 200) return resolve();
        if (Date.now() - started > timeoutMs) return reject(new Error("Round31 fixture health check failed"));
        setTimeout(probe, 250);
      });
      req.on("error", () => {
        if (Date.now() - started > timeoutMs) return reject(new Error("Round31 fixture did not start"));
        setTimeout(probe, 250);
      });
    };
    probe();
  });
}

async function openDashboard(viewport = { width: 1440, height: 1000 }, options = {}) {
  const context = await browser.newContext({ viewport, locale: "zh-TW", colorScheme: "light", serviceWorkers: "block", ...options.context });
  const page = await context.newPage();
  const requests = [];
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/")) {
      requests.push({ method: request.method(), url: url.pathname + url.search, body: request.postData() });
    }
  });
  const errors = [];
  page.on("pageerror", error => errors.push(String(error)));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  if (options.setup) await options.setup(page);
  await page.goto(baseURL + "/?demo-queue=filled&demo-lyrics=synced", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelector("#dashboard")?.getClientRects().length || document.querySelector("#discord-login")?.getClientRects().length);
  if (options.authenticate === false) return { context, page, requests, errors };
  if (await page.locator("#discord-login").isVisible().catch(() => false)) await page.locator("#discord-login").click();
  await page.waitForFunction(() => {
    const dashboard = document.querySelector("#dashboard");
    return dashboard && !dashboard.hidden && document.querySelector("#nav-play") && !document.querySelector("#nav-play").hidden;
  }, null, { timeout: 20000 });
  await page.waitForFunction(() => document.querySelectorAll("#queue > li").length === 4 && !document.querySelector("#enqueue")?.disabled);
  return { context, page, requests, errors };
}

before(async () => {
  const build = spawnSync(process.platform === "win32" ? "npm.cmd" : "npm", ["run", "build"], {
    cwd: frontend, encoding: "utf8", timeout: 180000
  });
  if (build.status !== 0) throw new Error("npm run build failed\n" + (build.stdout || "") + "\n" + (build.stderr || ""));
  if (!process.env.ROUND31_EXTERNAL_FIXTURE) serverProcess = spawn("python3", ["-m", "tools.dashboard_round31_fixture", "--host", "127.0.0.1", "--port", "18310"], {
    cwd: root, stdio: ["ignore", "pipe", "pipe"]
  });
  let bootLog = "";
  serverProcess?.stdout.on("data", chunk => { bootLog += chunk; });
  serverProcess?.stderr.on("data", chunk => { bootLog += chunk; });
  await waitForHealth().catch(error => { throw new Error(error.message + "\n" + bootLog); });
  browser = await chromium.launch({ headless: true });
});

after(async () => {
  if (browser) await browser.close();
  if (serverProcess && serverProcess.exitCode === null) {
    serverProcess.kill("SIGTERM");
    await new Promise(resolve => serverProcess.once("exit", resolve));
  }
});

test("Vue build bundle mounts real dashboard and loads deterministic guild state", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  assert.equal(await app.page.locator("#queue > li").count(), 4);
  assert.ok(Number(await app.page.locator("#progress").inputValue()) >= 0);
  assert.equal(await app.page.locator("#guild").inputValue(), "1");
  assert.ok(app.requests.some(request => request.url.includes("/auth/session")));
  assert.deepEqual(app.errors, []);
});

test("playback control changes the rendered state and posts to the selected guild", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  const toggle = app.page.locator("#toggle");
  await toggle.click();
  await app.page.waitForFunction(() => /繼續|Resume/i.test(document.querySelector("#toggle")?.textContent || ""));
  assert.ok(app.requests.some(request => request.method === "POST" && /\/api\/guilds\/1\/(pause|resume)$/.test(request.url)));
});

test("search preview requires explicit confirmation before queue mutation", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  await app.page.locator("#query").fill("Sunset");
  await app.page.locator("#enqueue").click();
  await app.page.locator("#preview-panel").waitFor({ state: "visible" });
  assert.ok(await app.page.locator("#preview-results > *").count() > 0);
  assert.equal(app.requests.some(request => /\/play$/.test(request.url)), false);
  const selectedTitle = await app.page.locator("#preview-results article h3").first().innerText();
  await app.page.locator("#preview-results button.primary").first().click();
  await app.page.waitForFunction(title => [...document.querySelectorAll("#queue > li")].some(row => row.textContent.includes(title)), selectedTitle);
  assert.ok(app.requests.some(request => request.method === "POST" && /\/api\/guilds\/1\/play$/.test(request.url)));
});

test("queue guild switch and progress read use rendered values", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  const progress = app.page.locator("#progress");
  const initial = Number(await progress.inputValue());
  await app.page.waitForTimeout(1100);
  const advanced = Number(await progress.inputValue());
  assert.ok(Number.isFinite(advanced) && advanced >= initial);
  await app.page.locator("#guild").selectOption("2");
  await app.page.waitForFunction(() => document.querySelector("#guild")?.value === "2" && document.querySelector("#queue > li"));
  assert.ok(app.requests.some(request => request.url.includes("/api/guilds/2/state")));
});

test("popular, lyrics, library cover and admin controls render in the built app", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  await app.page.locator("#nav-popular").click();
  await app.page.locator("#popular-panel").waitFor({ state: "visible" });
  assert.ok(await app.page.locator("#popular-list > *").count() > 0);
  await app.page.locator("#nav-play").click();
  await app.page.locator("#lyrics-toggle").click();
  await app.page.locator("#lyrics-panel").waitFor({ state: "visible" });
  await app.page.locator("#lyrics-content > p").first().waitFor({ state: "visible" });
  assert.ok(await app.page.locator("#lyrics-content > p").count() > 0);
  await app.page.locator("#lyrics-close").click();
  await app.page.locator("#nav-library").click();
  await app.page.locator("#library-panel").waitFor({ state: "visible" });
  assert.ok(await app.page.locator("#library-playlists .playlist-cover").count() > 0);
  await app.page.locator("#nav-admin").click();
  await app.page.locator("#admin-panel").waitFor({ state: "visible" });
});

test("mobile safe-area keeps rendered notice and playback controls inside the viewport", async t => {
  const app = await openDashboard({ width: 393, height: 852 });
  t.after(() => app.context.close());
  await app.page.evaluate(() => { document.documentElement.style.setProperty("--safe-top", "59px"); document.documentElement.style.setProperty("--safe-bottom", "34px"); });
  await app.page.locator("#favorite").click();
  await app.page.locator("#notice.visible").waitFor({ state: "visible" });
  const notice = await app.page.locator("#notice").boundingBox();
  const viewport = app.page.viewportSize();
  assert.ok(notice && notice.y >= 59 && notice.y + notice.height <= viewport.height);
  assert.deepEqual(app.errors, []);
});


test("queue filters and search keep the displayed count aligned with visible rows", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  const queue = app.page.locator("#queue > li");
  const initial = await queue.count();
  assert.equal(initial, 4);
  await app.page.locator("#queue-mine").click();
  await app.page.waitForFunction(() => document.querySelectorAll("#queue > li").length < 4);
  const mine = await queue.count();
  assert.ok(mine > 0 && mine < initial);
  assert.equal(await app.page.locator("#queue-mine").getAttribute("aria-pressed"), "true");
  await app.page.locator("#queue-search").fill("夜色");
  await app.page.waitForFunction(() => document.querySelectorAll("#queue > li").length <= 1);
  assert.ok(await app.page.locator("#queue-match-count").textContent());
});

test("queue estimates show indeterminate timing after a live item", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  const rows = app.page.locator("#queue > li");
  assert.equal(await rows.count(), 4);
  assert.ok(await app.page.locator("#queue-total").textContent());
  assert.ok((await rows.allTextContents()).some(text => /未知|直播|unknown|live/i.test(text)));
  assert.ok(app.errors.length === 0, app.errors.join("\n"));
});

test("lyrics timing controls change offset and sync against the active track", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  await app.page.locator("#lyrics-toggle").click();
  await app.page.locator("#lyrics-panel").waitFor({ state: "visible" });
  await app.page.locator("#lyrics-timing-toggle").click();
  await app.page.locator("#lyrics-timing-menu").waitFor({ state: "visible" });
  assert.ok(await app.page.locator("#lyrics-content > *").count() > 0);
  await app.page.locator("#lyrics-plus").click();
  await app.page.waitForTimeout(250);
  assert.ok(app.requests.some(r => r.method === "POST" && r.url.endsWith("/lyrics/offset")));
  await app.page.locator("#lyrics-sync").click();
  assert.ok(await app.page.locator("#lyrics-sync-prompt").isVisible());
  await app.page.locator("#lyrics-sync").click();
  assert.ok(app.requests.filter(r => r.method === "POST" && r.url.endsWith("/lyrics/offset")).length >= 2);
});

test("library renders saved covers and favorite stores the current track thumbnail", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  await app.page.locator("#nav-library").click();
  await app.page.locator("#library-panel").waitFor({ state: "visible" });
  const covers = app.page.locator("#library-playlists .playlist-cover");
  assert.ok(await covers.count() >= 2);
  assert.ok((await covers.first().getAttribute("aria-label"))?.length > 0);
  await app.page.locator("#library-playlists .library-choice").nth(1).click();
  await app.page.locator("#library-list .library-track-cover").first().waitFor({ state: "visible" });
  assert.ok(await app.page.locator("#library-list .library-track-cover").count() > 0);
  await app.page.locator("#nav-play").click();
  const headers = { "X-MusicBot-Dashboard": "1" };
  const state = await (await app.page.request.get(baseURL + "/api/guilds/1/state", { headers })).json();
  const saved = await (await app.page.request.get(baseURL + "/api/library", { headers })).json();
  if (saved.playlists[0].tracks.some(track => track.url === state.current.url)) {
    const removed = await app.page.request.patch(baseURL + "/api/library/favorites", {
      headers, data: { action: "remove_url", url: state.current.url, revision: saved.revision }
    });
    assert.equal(removed.status(), 200);
  }
  const save = app.page.waitForResponse(response => response.url().endsWith("/api/library/favorites/tracks") && response.request().method() === "POST");
  await app.page.locator("#favorite").click();
  assert.equal((await save).status(), 200);
  await app.page.locator("#notice.visible").waitFor({ state: "visible" });
  assert.ok(app.requests.some(r => r.url.includes("/api/library/favorites/tracks") && r.method === "POST"));
  assert.deepEqual(app.errors, []);
});

test("library track save requires a selected destination and persists through the dialog", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  await app.page.locator("#nav-library").click();
  await app.page.locator("#library-panel").waitFor({ state: "visible" });
  await app.page.locator("#nav-popular").click();
  await app.page.locator("#popular-list .save-to-library").first().click();
  await app.page.locator("#library-save-dialog").waitFor({ state: "visible" });
  assert.ok(await app.page.locator("#playlist-picker option").count() >= 2);
  await app.page.locator("#library-save-cancel").click();
  assert.equal(await app.page.locator("#library-save-dialog").evaluate(el => el.open), false);
  await app.page.locator("#nav-play").click();
  await app.page.locator("#favorite").click();
  await app.page.locator("#nav-library").click();
  await app.page.locator("#library-panel").waitFor({ state: "visible" });
  assert.ok(await app.page.locator("#library-playlists .playlist-cover").count() >= 2);
});

test("popular rankings render and period selection reloads the guild scoped list", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  await app.page.locator("#nav-popular").click();
  await app.page.locator("#popular-panel").waitFor({ state: "visible" });
  const rows = app.page.locator("#popular-list > li.popular-row");
  assert.ok(await rows.count() > 0);
  assert.ok(await rows.first().locator(".popular-rank").textContent());
  await app.page.locator("#popular-period").selectOption("30");
  await app.page.waitForFunction(() => document.querySelector("#popular-period")?.value === "30");
  assert.ok(app.requests.some(r => r.url.includes("/popular?period=30")));
  assert.deepEqual(app.errors, []);
});

test("owner permissions require confirmation and keep human readable field labels", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  await app.page.locator("#nav-admin").click();
  await app.page.locator("#admin-panel").waitFor({ state: "visible" });
  const field = app.page.locator("#permission-Default-AllowPlaylists");
  await app.page.locator("#admin-permissions summary").filter({ hasText: /^Default$/ }).click();
  await field.waitFor({ state: "visible" });
  assert.ok(await field.getAttribute("aria-label"));
  assert.ok(await app.page.locator("#maintenance-details dt").count() > 0);
  await field.selectOption("true");
  await app.page.locator("#permission-confirm-dialog").waitFor({ state: "visible" });
  assert.ok(await app.page.locator("#permission-confirm-text").textContent());
  await app.page.locator("#permission-cancel").click();
  assert.equal(await app.page.locator("#permission-confirm-dialog").evaluate(el => el.open), false);
  assert.equal(app.requests.filter(r => r.method === "PATCH" && r.url.endsWith("/admin/permissions")).length, 0);
});

test("confirmed permission edits send the old and new values to the selected guild", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  await app.page.locator("#nav-admin").click();
  const field = app.page.locator("#permission-Default-AllowPlaylists");
  await app.page.locator("#admin-permissions summary").filter({ hasText: /^Default$/ }).click();
  await field.waitFor({ state: "visible" });
  await field.selectOption("true");
  await app.page.locator("#permission-confirm").click();
  await app.page.locator("#permission-confirm-dialog").waitFor({ state: "hidden" });
  const change = app.requests.find(r => r.method === "PATCH" && r.url.endsWith("/admin/permissions"));
  assert.ok(change);
  assert.ok(change.body.includes('"old_value":false'));
  assert.ok(change.body.includes('"value":true'));
  assert.ok(change.url.startsWith("/api/guilds/1/"));
});

test("vote skip setting posts one boolean and reports the saved state", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  await app.page.locator("#nav-admin").click();
  const toggle = app.page.locator("#admin-vote-skip-enabled");
  await toggle.waitFor({ state: "visible" });
  await toggle.check();
  await app.page.locator("#admin-vote-skip-save").click();
  await app.page.waitForFunction(() => Boolean(document.querySelector("#admin-vote-skip-status")?.textContent));
  const save = app.requests.find(r => r.method === "POST" && r.url.endsWith("/admin/vote-skip"));
  assert.ok(save);
  assert.ok(save.body.includes('"enabled":true'));
  assert.ok(await app.page.locator("#admin-vote-skip-enabled").getAttribute("aria-describedby"));
  assert.deepEqual(app.errors, []);
});

test("notification setting can select a text channel and save for the active guild", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  await app.page.locator("#nav-admin").click();
  const channel = app.page.locator("#admin-notify-channel");
  await channel.waitFor({ state: "visible" });
  assert.ok(await channel.locator("option").count() >= 2);
  await channel.selectOption({ index: 1 });
  await app.page.locator("#admin-notify-save").click();
  await app.page.waitForFunction(() => Boolean(document.querySelector("#admin-notify-status")?.textContent));
  assert.ok(app.requests.some(r => r.method === "POST" && r.url.endsWith("/admin/notification-channel")));
  assert.ok(await app.page.locator("#admin-notify-help").textContent());
});

test("language switch updates visible Vue labels without exposing translation keys", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  const before = await app.page.locator("#request-heading").innerText();
  await app.page.locator("#dashboard-language").selectOption("en");
  await app.page.waitForFunction(() => document.documentElement.lang === "en");
  const after = await app.page.locator("#request-heading").innerText();
  assert.notEqual(after, before);
  assert.doesNotMatch(await app.page.locator("#dashboard").innerText(), /\bm\d{4}\b/);
  assert.equal(await app.page.locator("#dashboard-language").inputValue(), "en");
  assert.deepEqual(app.errors, []);
});

test("mobile notice and dock avoid injected iPhone safe areas", async t => {
  const app = await openDashboard({ width: 393, height: 852 });
  t.after(() => app.context.close());
  await app.page.evaluate(() => { document.documentElement.style.setProperty("--safe-top", "59px"); document.documentElement.style.setProperty("--safe-bottom", "34px"); });
  await app.page.locator("#favorite").click();
  await app.page.locator("#notice").waitFor({ state: "visible" });
  const notice = await app.page.locator("#notice").boundingBox();
  const dock = await app.page.locator("#playback-bar").boundingBox();
  const size = app.page.viewportSize();
  assert.ok(notice && notice.y >= 59 && notice.y + notice.height <= size.height - 34);
  assert.ok(dock && dock.y + dock.height <= size.height - 34);
  assert.ok(await app.page.locator("#dashboard").isVisible());
  assert.deepEqual(app.errors, []);
});

test("queue empty state remains visible when the fixture has no queued tracks", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  await app.page.goto(baseURL + "/?demo-queue=empty");
  await app.page.waitForFunction(() => document.querySelectorAll("#queue > li").length === 0);
  assert.ok(await app.page.locator("#queue-empty").isVisible());
  assert.equal(await app.page.locator("#queue-count").textContent(), "0");
  assert.ok(await app.page.locator("#queue-heading").textContent());
  assert.deepEqual(app.errors, []);
});

test("session logout clears the rendered dashboard and sends the protected request", async t => {
  const app = await openDashboard();
  t.after(() => app.context.close());
  await app.page.locator(".account-actions > summary").click();
  await app.page.locator("#logout").click();
  await app.page.waitForFunction(() => document.querySelector("#dashboard")?.hidden === true);
  assert.ok(app.requests.some(r => r.url === "/auth/logout" && r.method === "POST"));
  await app.page.waitForFunction(() => document.querySelectorAll("#queue > li").length === 0);
  assert.equal(await app.page.locator("#queue > li").count(), 0);
  assert.ok(await app.page.locator("#discord-login").isVisible());
  assert.deepEqual(app.errors, []);
});

require("./dashboard_round31_regressions.cjs")({test, assert, openDashboard, baseURL});
require("./dashboard_round31_async.cjs")({test, assert, openDashboard, baseURL});
