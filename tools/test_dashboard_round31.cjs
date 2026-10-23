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
  await page.route("**/api/guilds/*/spotify", route => route.fulfill({json: {url: "https://open.spotify.com/track/Fixture", mode: "track"}}));
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
  const sessionResponse = page.waitForResponse(response => new URL(response.url()).pathname === "/auth/session");
  await page.goto(baseURL + "/?demo-queue=filled&demo-lyrics=synced", { waitUntil: "domcontentloaded" });
  await (await sessionResponse).finished();
  await page.waitForFunction(skip => document.querySelector("#dashboard")?.getClientRects().length || document.querySelector(skip ? "#login-screen" : "#discord-login")?.getClientRects().length, options.authenticate === false);
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
  await app.page.locator("#queue-empty").waitFor({ state: "visible" });
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


test("recent history title remains wide and compact on desktop", async t => {
  const app = await openDashboard({ width: 1440, height: 900 });
  t.after(() => app.context.close());
  const row = app.page.locator("#history-list > li").first();
  await row.waitFor({ state: "visible" });
  const measured = await row.evaluate(el => ({
    titleWidth: el.querySelector(".history-info").getBoundingClientRect().width,
    rowHeight: el.getBoundingClientRect().height
  }));
  console.log("R28_HISTORY_DESKTOP=" + JSON.stringify(measured));
  assert.ok(measured.titleWidth >= 500, "history title width must be >= 500px: " + JSON.stringify(measured));
  assert.ok(measured.rowHeight <= 80, "history row height must be <= 80px: " + JSON.stringify(measured));
  assert.deepEqual(app.errors, []);
});

test("mobile recent-history action labels stay on one line without overlap", async t => {
  const app = await openDashboard({ width: 390, height: 844 });
  t.after(() => app.context.close());
  const row = app.page.locator("#history-list > li").first();
  await row.waitFor({ state: "visible" });
  const measured = await row.evaluate(el => {
    const buttons = [...el.querySelectorAll(".history-actions button")];
    const boxes = buttons.map(button => {
      const rect = button.getBoundingClientRect();
      const range = document.createRange();
      range.selectNodeContents(button);
      const textRects = [...range.getClientRects()].filter(item => item.width > 0 && item.height > 0);
      return { text: button.innerText, x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom,
        whiteSpace: getComputedStyle(button).whiteSpace, textLineCount: textRects.length };
    });
    let overlaps = 0;
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      if (Math.min(boxes[i].right, boxes[j].right) - Math.max(boxes[i].x, boxes[j].x) > .5 &&
          Math.min(boxes[i].bottom, boxes[j].bottom) - Math.max(boxes[i].y, boxes[j].y) > .5) overlaps++;
    }
    return { buttons: boxes, overlaps };
  });
  console.log("R28_HISTORY_MOBILE=" + JSON.stringify(measured));
  assert.ok(measured.buttons.length >= 1);
  assert.ok(measured.buttons.every(button => button.whiteSpace === "nowrap" && button.textLineCount <= 1),
    "action labels must be single-line: " + JSON.stringify(measured));
  assert.equal(measured.overlaps, 0, "history action overlap count: " + JSON.stringify(measured));
  assert.deepEqual(app.errors, []);
});

test("queue, recommendation, popular and library rows fit four viewport widths", async t => {
  const app = await openDashboard({ width: 1440, height: 900 });
  t.after(() => app.context.close());
  const widths = [1440, 1024, 768, 390];
  const fits = async selector => app.page.locator(selector).evaluateAll((rows, width) => rows.map(row => {
    const rect = row.getBoundingClientRect();
    return { left: rect.left, right: rect.right, width: rect.width,
      scrollWidth: row.scrollWidth, clientWidth: row.clientWidth,
      fits: rect.left >= -1 && rect.right <= width + 1 && row.scrollWidth <= row.clientWidth + 1 };
  }), await app.page.evaluate(() => document.documentElement.clientWidth));
  const checkFits = (label, rows) => assert.ok(rows.length > 0 && rows.every(row => row.fits), label + ": " + JSON.stringify(rows));
  for (const width of widths) {
    await app.page.setViewportSize({ width, height: 900 });
    checkFits("queue at " + width, await fits("#queue > li"));
  }
  await app.page.goto(baseURL + "/?demo-queue=empty");
  await app.page.locator("#queue-empty").waitFor({ state: "visible" });
  for (const width of widths) {
    await app.page.setViewportSize({ width, height: 900 });
    checkFits("recommendation at " + width, await fits("#recommendation-list > li"));
  }
  await app.page.locator("#nav-popular").click();
  await app.page.locator("#popular-list > li").first().waitFor({ state: "visible" });
  for (const width of widths) {
    await app.page.setViewportSize({ width, height: 900 });
    checkFits("popular at " + width, await fits("#popular-list > li"));
  }
  await app.page.setViewportSize({ width: 1440, height: 900 });
  await app.page.locator("#nav-library").click();
  await app.page.locator("#library-panel").waitFor({ state: "visible" });
  await app.page.locator("#library-playlists .library-choice").first().waitFor({ state: "visible" });
  await app.page.locator("#library-playlists .library-choice").nth(1).click();
  await app.page.locator("#library-list > li").first().waitFor({ state: "visible" });
  for (const width of widths) {
    await app.page.setViewportSize({ width, height: 900 });
    checkFits("library at " + width, await fits("#library-list > li"));
  }
  assert.deepEqual(app.errors, []);
});

require("./dashboard_round31_regressions.cjs")({test, assert, openDashboard, baseURL});
require("./dashboard_round31_async.cjs")({test, assert, openDashboard, baseURL});
require("./dashboard_round31_auth_cases.cjs")({test, assert, openDashboard, baseURL});
require("./dashboard_round31_auth_extra.cjs")({test, assert, openDashboard, baseURL});
require("./dashboard_round31_controls.cjs")({test, assert, openDashboard, baseURL});
require("./dashboard_round31_sse.cjs")({test, assert, openDashboard, baseURL});
require("./dashboard_round31_spotify.cjs")({test, assert, openDashboard, baseURL});
require("./dashboard_round31_media_gestures.cjs")({test, assert, openDashboard, baseURL});
require("./dashboard_round31_sse_fallback.cjs")({test, assert, openDashboard, baseURL});

test("search preview actions stay in the action column on desktop and mobile", async t => {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const app = await openDashboard(viewport);
    t.after(() => app.context.close());
    assert.equal(await app.page.locator("#request-action").count(), 0, "request purpose select must be removed");
    await app.page.locator("#query").fill("Sunset");
    await app.page.locator("#enqueue").click();
    await app.page.locator("#preview-panel").waitFor({ state: "visible" });
    const measured = await app.page.locator("#preview-results .preview-item").evaluateAll(items => items.map(item => {
      const art = item.firstElementChild.getBoundingClientRect();
      const buttons = [...item.querySelectorAll(".preview-actions button")].map(button => {
        const rect = button.getBoundingClientRect();
        const range = document.createRange();
        range.selectNodeContents(button);
        const lines = new Set([...range.getClientRects()].filter(r => r.width > 0 && r.height > 0).map(r => Math.round(r.top))).size;
        return { text: button.innerText, x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom, lines };
      });
      let overlaps = 0;
      for (let i = 0; i < buttons.length; i++) for (let j = i + 1; j < buttons.length; j++) {
        if (Math.min(buttons[i].right, buttons[j].right) - Math.max(buttons[i].x, buttons[j].x) > .5 &&
            Math.min(buttons[i].bottom, buttons[j].bottom) - Math.max(buttons[i].y, buttons[j].y) > .5) overlaps++;
      }
      return { artRight: art.right, buttons, overlaps };
    }));
    console.log("R28_PREVIEW_" + viewport.width + "=" + JSON.stringify(measured));
    assert.ok(measured.length > 0);
    for (const item of measured) {
      assert.ok(item.buttons.length >= 1);
      assert.equal(item.overlaps, 0, JSON.stringify(item));
      for (const button of item.buttons) {
        assert.equal(button.lines, 1, "button label must stay on one line: " + JSON.stringify(button));
        assert.ok(button.x >= item.artRight, "button must not sit in the cover column: " + JSON.stringify(item));
      }
    }
    assert.deepEqual(app.errors, []);
  }
});

test("mobile queue long-press drag follows the finger without re-rendering rows", async t => {
  const app = await openDashboard({ width: 390, height: 844 }, { context: { hasTouch: true, isMobile: true } });
  t.after(() => app.context.close());
  await app.page.locator("#queue > li").nth(2).waitFor({ state: "visible" });
  await app.page.locator("#queue").scrollIntoViewIfNeeded();
  const cdp = await app.context.newCDPSession(app.page);
  const touch = (type, x, y) => cdp.send("Input.dispatchTouchEvent", { type, touchPoints: type === "touchEnd" ? [] : [{ x, y, id: 1, radiusX: 3, radiusY: 3, force: 1 }] });
  const handle = await app.page.locator("#queue > li:first-child .drag-handle").boundingBox();
  const third = await app.page.locator("#queue > li:nth-child(3)").boundingBox();
  await app.page.evaluate(() => {
    window.__r28 = { added: 0, removed: 0, samples: [] };
    new MutationObserver(list => { for (const m of list) { window.__r28.added += [...m.addedNodes].filter(n => n.nodeName === "LI").length; window.__r28.removed += [...m.removedNodes].filter(n => n.nodeName === "LI").length; } })
      .observe(document.querySelector("#queue"), { childList: true });
    const tick = () => { const row = document.querySelector("#queue > li.drag-active"); if (row) window.__r28.samples.push(row.getBoundingClientRect().top); if (!window.__r28.stop) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  });
  const x = handle.x + handle.width / 2, y0 = handle.y + handle.height / 2, y1 = third.y + Math.min(third.height / 2, 50);
  await touch("touchStart", x, y0);
  await app.page.waitForTimeout(520);
  assert.equal(await app.page.locator("body").evaluate(e => e.classList.contains("queue-dragging")), true, "long press should activate");
  for (let i = 1; i <= 16; i++) { await touch("touchMove", x, y0 + (y1 - y0) * i / 16); await app.page.waitForTimeout(32); }
  await app.page.waitForTimeout(100);
  const result = await app.page.evaluate(() => { window.__r28.stop = true; return window.__r28; });
  await touch("touchEnd");
  await app.page.waitForFunction(() => !document.body.classList.contains("queue-dragging"));
  let backJumps = 0, maxBack = 0;
  for (let i = 1; i < result.samples.length; i++) { const d = result.samples[i] - result.samples[i - 1]; if (d < -8) { backJumps++; } maxBack = Math.min(maxBack, d); }
  console.log("R28_DRAG=" + JSON.stringify({ samples: result.samples.length, added: result.added, removed: result.removed, backJumps, maxBack }));
  assert.ok(result.samples.length >= 10, "dragged row should be sampled while moving");
  assert.equal(result.added + result.removed, 0, "queue rows must not be replaced during drag");
  assert.equal(backJumps, 0, "dragged row must not jump back more than 8px");
  await app.page.waitForFunction(() => true);
  await app.page.waitForTimeout(650);
  assert.equal(app.requests.filter(r => /\/queue\/move$/.test(r.url)).length, 1);
  assert.deepEqual(app.errors, []);
});

test("recent operations show translated sources in separate columns", async t => {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const app = await openDashboard(viewport);
    t.after(() => app.context.close());
    const rows = app.page.locator("#activity-list > li");
    await rows.first().waitFor({ state: "visible" });
    const measured = await rows.evaluateAll(items => items.map(li => {
      const parts = [...li.children].map(el => { const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, right: r.right, bottom: r.bottom }; });
      let overlaps = 0;
      for (let i = 0; i < parts.length; i++) for (let j = i + 1; j < parts.length; j++) {
        if (Math.min(parts[i].right, parts[j].right) - Math.max(parts[i].x, parts[j].x) > .5 &&
            Math.min(parts[i].bottom, parts[j].bottom) - Math.max(parts[i].y, parts[j].y) > .5) overlaps++;
      }
      return { source: li.querySelector("small")?.textContent || "", overlaps };
    }));
    console.log("R28_ACTIVITY_" + viewport.width + "=" + JSON.stringify(measured.slice(0, 4)));
    assert.ok(measured.length > 0);
    for (const row of measured) {
      assert.doesNotMatch(row.source, /discord_|^text$|^slash$|^web$/, "activity source must be translated: " + row.source);
      assert.equal(row.overlaps, 0, "activity columns must not overlap: " + JSON.stringify(row));
    }
    assert.deepEqual(app.errors, []);
  }
});


test("mobile form controls use at least 16px text to avoid iOS focus zoom", async t => {
  const app = await openDashboard({ width: 390, height: 844 }, { context: { hasTouch: true, isMobile: true } });
  t.after(() => app.context.close());
  const checkVisibleControls = async label => {
    const sizes = await app.page.evaluate(() => [...document.querySelectorAll("input,select,textarea")]
      .filter(el => {
        const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      })
      .map(el => ({ tag: el.tagName.toLowerCase(), id: el.id, type: el.type || "", fontSize: parseFloat(getComputedStyle(el).fontSize) })));
    const small = sizes.filter(control => control.fontSize < 16);
    console.log("R29_CONTROL_SIZES_" + label + "=" + JSON.stringify({ count: sizes.length, small }));
    assert.ok(sizes.length > 0, label + " should contain visible form controls");
    assert.deepEqual(small, [], label + " controls below 16px");
  };
  const viewport = await app.page.locator('meta[name="viewport"]').getAttribute("content");
  assert.match(viewport, /maximum-scale=1/);
  assert.doesNotMatch(viewport, /user-scalable\s*=\s*no/i);
  await checkVisibleControls("play");
  await app.page.locator("#nav-admin").click();
  await app.page.locator("#admin-panel").waitFor({ state: "visible" });
  await checkVisibleControls("admin");
  assert.deepEqual(app.errors, []);
});

test("area around the floating player and nav stays transparent", async t => {
  const shotDir = process.env.R29_SCREENSHOTS_DIR;
  const inspect = async (viewport, mobile, screenshotName) => {
    const app = await openDashboard(viewport, { context: { colorScheme: "dark", ...(mobile ? { hasTouch: true, isMobile: true } : {}) } });
    t.after(() => app.context.close());
    await app.page.locator("#queue > li").nth(2).scrollIntoViewIfNeeded();
    const result = await app.page.evaluate(() => {
      const bar = document.querySelector(".playback-bar");
      const r = bar.getBoundingClientRect();
      const points = [{ label: "player-top-left-outside", x: Math.min(innerWidth - 1, r.left + 6), y: Math.max(1, r.top - 6) }];
      const nav = document.querySelector(".page-tabs.mobile-glass");
      if (nav) {
        const n = nav.getBoundingClientRect();
        const gapY = (n.top + r.bottom) / 2;
        if (n.top > r.bottom && gapY > r.bottom && gapY < n.top) points.push({ label: "nav-player-gap", x: n.left + n.width / 2, y: gapY });
      }
      const samples = points.map(point => {
        const stack = document.elementsFromPoint(point.x, point.y);
        const top = stack[0];
        const style = top ? getComputedStyle(top) : null;
        const rect = top?.getBoundingClientRect();
        const bg = style?.backgroundColor || "transparent";
        const alpha = bg === "transparent" ? 0 : bg.startsWith("rgba(") ? Number(bg.match(/,\s*([\d.]+)\s*\)$/)?.[1] ?? 1) : 1;
        return { ...point, top: top?.tagName.toLowerCase(), id: top?.id || "", className: String(top?.className || ""), background: bg,
          position: style?.position || "", width: rect?.width || 0, alpha };
      });
      const after = getComputedStyle(document.querySelector("#app"), "::after");
      return { samples, afterContent: after.content, afterBackground: after.backgroundColor, viewportWidth: innerWidth };
    });
    console.log("R29_DOCK_" + viewport.width + "=" + JSON.stringify(result));
    assert.ok(result.samples.length >= (mobile ? 2 : 1));
    for (const sample of result.samples) {
      assert.notEqual(sample.id, "app", "dock-adjacent sample hit #app: " + JSON.stringify(sample));
      assert.ok(!(sample.position === "fixed" && sample.width >= result.viewportWidth - 1 && sample.alpha >= 0.99),
        "dock-adjacent sample hit an opaque full-width fixed element: " + JSON.stringify(sample));
    }
    const afterAlpha = result.afterBackground === "transparent" ? 0 : Number(result.afterBackground.match(/rgba?\([^)]*[,/]\s*([\d.]+)\s*\)$/)?.[1] ?? 1);
    assert.ok(result.afterContent === "none" || afterAlpha === 0, "#app::after is still painting: " + JSON.stringify(result));
    if (shotDir && screenshotName) await app.page.screenshot({ path: path.join(shotDir, screenshotName) });
    return app;
  };
  await inspect({ width: 390, height: 844 }, true, "mobile-dark-play-mid.png");
  const light = await openDashboard({ width: 390, height: 844 }, { context: { colorScheme: "light", hasTouch: true, isMobile: true } });
  t.after(() => light.context.close());
  await light.page.locator("#queue > li").nth(2).scrollIntoViewIfNeeded();
  if (shotDir) await light.page.screenshot({ path: path.join(shotDir, "mobile-light-play-mid.png") });
  await inspect({ width: 1440, height: 900 }, false, "desktop-dark-play-mid.png");
});


// Round 30: focused regression cases. Synthetic data stays in the browser.
async function r30Library(page) {
  const payload = { revision: "r30-1", owner: true, sources: { youtube: true, spotify: true }, playlists: [
    { id: "favorites", name: "Favorites", tracks: [
      { title: "Saved YouTube track", url: "https://www.youtube.com/watch?v=demo0000001", duration: 195 },
      { title: "Saved external track", url: "https://soundcloud.com/example/saved", duration: 180, thumbnail: baseURL + "/demo-cover/2.svg" },
      { title: "Track without artwork", url: "https://soundcloud.com/example/no-art", duration: 60 }
    ] },
    { id: "a".repeat(24), name: "Editable playlist", tracks: [
      { title: "Editable YouTube track", url: "https://youtu.be/demo0000002", duration: 180 }
    ] }
  ] };
  await page.route("**/api/library{,/**}", async route => {
    if (route.request().method() === "PATCH") {
      const body = route.request().postDataJSON();
      payload.playlists[1].name = body.name;
      payload.revision = "r30-2";
    }
    await route.fulfill({ json: payload });
  });
  await page.route("https://i.ytimg.com/**", route => route.fulfill({
    contentType: "image/svg+xml",
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"><rect width="320" height="180" fill="#237b70"/><circle cx="160" cy="90" r="42" fill="#b2d9c3"/></svg>'
  }));
}

async function r30Shot(page, name) {
  const dir = process.env.R30_SCREENSHOTS_DIR;
  if (dir) {
    require("node:fs").mkdirSync(dir, { recursive: true });
    await page.screenshot({ path: path.join(dir, name) });
  }
}

test("R30 mobile playlist detail and browser back return to the list", async t => {
  const app = await openDashboard({ width: 390, height: 844 }, {
    context: { isMobile: true, hasTouch: true }, setup: r30Library
  });
  t.after(() => app.context.close());
  await app.page.locator("#nav-library").click();
  await app.page.locator(".library-choice").first().click();
  await app.page.locator("#library-list>li").first().waitFor({ state: "visible" });
  assert.ok(await app.page.locator("#library-list>li").count() > 0);
  assert.equal(await app.page.locator("#library-back").innerText(), "\u2190 \u8fd4\u56de\u6b4c\u55ae\u5217\u8868");
  await r30Shot(app.page, "issue1-mobile-detail.png");
  await app.page.locator("#library-back").click();
  await app.page.locator(".library-choice").first().waitFor({ state: "visible" });
  await r30Shot(app.page, "issue1-mobile-list.png");
  await app.page.locator(".library-choice").first().click();
  await app.page.locator("#library-list>li").first().waitFor({ state: "visible" });
  await app.page.goBack();
  await app.page.locator(".library-choice").first().waitFor({ state: "visible" });
  assert.match(app.page.url(), /#\/library$/);
  assert.equal(await app.page.locator("#library-detail").isVisible(), false);
  assert.deepEqual(app.errors, []);
});


test("R30 playlist rename keeps input width and saves on desktop and mobile", async t => {
  for (const width of [1440, 390]) {
    const app = await openDashboard({ width, height: width === 390 ? 844 : 1000 }, {
      context: width === 390 ? { isMobile: true, hasTouch: true } : {}, setup: r30Library
    });
    t.after(() => app.context.close());
    await app.page.locator("#nav-library").click();
    await app.page.locator(".library-choice").nth(1).click();
    await app.page.locator("#library-actions>summary").click();
    const sizes = await app.page.locator(".library-rename-row").evaluate(row => ({
      row: row.getBoundingClientRect().width,
      input: row.querySelector("input").getBoundingClientRect().width,
      button: row.querySelector("button").getBoundingClientRect().width
    }));
    console.log("R30_RENAME_" + width + "=" + JSON.stringify(sizes));
    assert.ok(sizes.input >= sizes.row * .6, JSON.stringify(sizes));
    const input = app.page.locator("#library-name");
    await input.click();
    assert.equal(await input.evaluate(el => document.activeElement === el), true);
    const name = "Renamed " + width;
    await input.fill(name);
    await r30Shot(app.page, "issue2-rename-" + width + ".png");
    await app.page.locator("#library-rename").click();
    await app.page.waitForFunction(name => document.querySelector("#library-detail-heading")?.textContent === name, name);
    assert.ok(app.requests.some(r => r.method === "PATCH" && JSON.parse(r.body).name === name));
    assert.deepEqual(app.errors, []);
  }
});


test("R30 account avatar name and action share a vertical center", async t => {
  for (const width of [1440, 390]) {
    const app = await openDashboard({ width, height: width === 390 ? 844 : 1000 }, {
      context: width === 390 ? { isMobile: true, hasTouch: true } : {},
      setup: async page => {
        await page.route("**/auth/session", async route => {
          const response = await route.fetch();
          const data = await response.json();
          if (data.authenticated) data.user = { ...data.user, name: "XiaoYi", avatar: baseURL + "/demo-cover/0.svg" };
          await route.fulfill({ response, json: data });
        });
      }
    });
    t.after(() => app.context.close());
    await app.page.locator("#user-avatar").waitFor({ state: "visible" });
    await app.page.waitForFunction(() => document.querySelector("#user-avatar")?.naturalWidth > 0);
    const boxes = await app.page.locator("#user-avatar,#user-name,.account-actions>summary").evaluateAll(els =>
      els.map(el => { const r = el.getBoundingClientRect(); return { id: el.id || el.tagName, center: r.top + r.height / 2, height: r.height }; }));
    console.log("R30_ACCOUNT_" + width + "=" + JSON.stringify(boxes));
    assert.equal(boxes.length, 3);
    assert.ok(Math.max(...boxes.map(r => r.center)) - Math.min(...boxes.map(r => r.center)) <= 2, JSON.stringify(boxes));
    await r30Shot(app.page, "issue3-account-" + width + ".png");
    await app.page.locator(".account-actions>summary").click();
    await app.page.locator("#logout").waitFor({ state: "visible" });
    assert.deepEqual(app.errors, []);
  }
});


test("R30 theme toggle persists overrides and tolerates blocked localStorage", async t => {
  const theme = page => page.evaluate(() => ({
    mode: document.documentElement.dataset.theme,
    background: getComputedStyle(document.body).backgroundColor,
    meta: document.querySelector('meta[name="theme-color"]').content,
    surface: getComputedStyle(document.documentElement).getPropertyValue("--surface").trim(),
    panel: getComputedStyle(document.documentElement).getPropertyValue("--panel").trim()
  }));
  for (const width of [1440, 390]) {
    const app = await openDashboard({ width, height: width === 390 ? 844 : 1000 }, {
      context: width === 390 ? { isMobile: true, hasTouch: true } : {}
    });
    t.after(() => app.context.close());
    const button = app.page.locator("#theme-toggle");
    const b = await button.boundingBox(), select = await app.page.locator("#dashboard-language").boundingBox();
    assert.ok(b.x + b.width <= select.x && Math.abs(b.y + b.height / 2 - select.y - select.height / 2) <= 2);
    assert.equal(b.width, 44); assert.equal(b.height, 44);
    assert.equal(await button.innerText(), "");
    assert.equal(await button.getAttribute("title"), null);
    assert.ok(await button.getAttribute("aria-label"));
    assert.equal(await button.locator("svg").count(), 2);
    const light = await theme(app.page);
    assert.deepEqual({mode:light.mode,background:light.background,meta:light.meta},
      {mode:"light",background:"rgb(243, 245, 247)",meta:"#f3f5f7"});
    await r30Shot(app.page, "issue4-light-" + width + ".png");
    await button.click();
    await app.page.waitForFunction(() => document.documentElement.dataset.theme === "dark");
    const dark = await theme(app.page);
    assert.deepEqual({mode:dark.mode,background:dark.background,meta:dark.meta},
      {mode:"dark",background:"rgb(30, 34, 38)",meta:"#1e2226"});
    await app.page.waitForFunction(() => getComputedStyle(document.querySelector("#theme-toggle .theme-moon")).opacity === "1");
    assert.equal(await button.locator(".theme-moon").evaluate(el => getComputedStyle(el).opacity), "1");
    await r30Shot(app.page, "issue4-dark-" + width + ".png");
    await app.page.reload({ waitUntil: "domcontentloaded" });
    await app.page.locator("#theme-toggle").waitFor();
    assert.deepEqual(await theme(app.page), dark);
    await app.page.emulateMedia({ colorScheme: "dark" });
    assert.deepEqual(await theme(app.page), dark);
    await app.page.locator("#theme-toggle").click();
    await app.page.waitForFunction(() => document.documentElement.dataset.theme === "light");
    assert.deepEqual(await theme(app.page), light);
    await app.page.emulateMedia({ reducedMotion: "reduce" });
    assert.equal(await app.page.locator("#theme-toggle svg").first().evaluate(el => getComputedStyle(el).transitionDuration), "0s");
    assert.deepEqual(app.errors, []);
    console.log("R30_THEME_" + width + "=" + JSON.stringify({light,dark}));
  }
  const blocked = await openDashboard({ width: 390, height: 844 }, {
    context: { isMobile: true, hasTouch: true, colorScheme: "dark" },
    setup: page => page.addInitScript(() => Object.defineProperty(window, "localStorage", {
      configurable: true, get() { throw new DOMException("Storage denied", "SecurityError"); }
    }))
  });
  t.after(() => blocked.context.close());
  assert.equal((await theme(blocked.page)).mode, "dark");
  await blocked.page.emulateMedia({ colorScheme: "light" });
  await blocked.page.waitForFunction(() => document.documentElement.dataset.theme === "light");
  await blocked.page.locator("#theme-toggle").click();
  assert.equal((await theme(blocked.page)).mode, "dark");
  await blocked.page.reload({ waitUntil: "domcontentloaded" });
  await blocked.page.locator("#theme-toggle").waitFor();
  assert.equal((await theme(blocked.page)).mode, "light");
  assert.deepEqual(blocked.errors, []);
  console.log("R30_STORAGE_BLOCKED_ERRORS=" + JSON.stringify(blocked.errors));
});


test("R30 saved YouTube tracks derive the same artwork as playlist covers", async t => {
  const app = await openDashboard({ width: 390, height: 844 }, {
    context: { isMobile: true, hasTouch: true }, setup: r30Library
  });
  t.after(() => app.context.close());
  await app.page.locator("#nav-library").click();
  await app.page.locator(".library-choice").first().click();
  const first = app.page.locator("#library-list>li").first();
  await first.waitFor({ state: "visible" });
  const expected = "https://i.ytimg.com/vi/demo0000001/mqdefault.jpg";
  assert.equal(await first.locator("img").getAttribute("src"), expected);
  await first.scrollIntoViewIfNeeded();
  await app.page.waitForFunction(() => document.querySelector("#library-list>li img")?.naturalWidth > 0);
  assert.ok(await app.page.locator(".playlist-cover-hero img").evaluateAll((els, src) => els.some(el => el.src === src), expected));
  assert.equal(await app.page.locator("#library-list>li").nth(1).locator("img").getAttribute("src"), baseURL + "/demo-cover/2.svg");
  assert.equal(await app.page.locator("#library-list>li").nth(2).locator("img").count(), 0);
  assert.equal(await app.page.locator("#library-list>li").nth(2).locator(".art>span").isVisible(), true);
  await app.page.locator("#library-list").evaluate(el => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 160));
  await r30Shot(app.page, "issue5-mobile-covers.png");
  await app.page.locator("#library-back").click();
  await app.page.locator(".library-choice").nth(1).click();
  assert.equal(await app.page.locator("#library-list img").first().getAttribute("src"), "https://i.ytimg.com/vi/demo0000002/mqdefault.jpg");
  await app.page.setViewportSize({ width: 1440, height: 1000 });
  await app.page.evaluate(() => window.scrollTo(0, 0));
  await app.page.locator(".library-choice").first().click();
  await app.page.waitForFunction(() => {
    const images = [...document.querySelectorAll("#library-list .art img,.playlist-cover-hero img")];
    return images.length === 4 && images.every(img => img.naturalWidth > 0);
  });
  await r30Shot(app.page, "issue5-desktop-covers.png");
  assert.deepEqual(app.errors, []);
});

test("R30 playlist counts use a single separator", async t => {
  const app = await openDashboard({ width: 1440, height: 900 }, { setup: r30Library });
  t.after(() => app.context.close());
  await app.page.locator("#nav-library").click();
  await app.page.locator(".library-choice").first().waitFor({ state: "visible" });
  await app.page.locator(".library-choice").first().click();
  await app.page.locator("#library-list>li").first().waitFor({ state: "visible" });
  const texts = await app.page.evaluate(() => [...document.querySelectorAll("#library-panel *")]
    .filter(el => el.children.length === 0 && /首/.test(el.textContent || ""))
    .map(el => el.textContent.replace(/\s+/g, " ").trim()));
  console.log("R30_SEPARATORS=" + JSON.stringify(texts));
  assert.ok(texts.length >= 2);
  for (const text of texts) {
    assert.doesNotMatch(text, /·\s*·/, "double separator: " + text);
    assert.doesNotMatch(text, /·\s*$/, "trailing separator: " + text);
  }
  assert.deepEqual(app.errors, []);
});
