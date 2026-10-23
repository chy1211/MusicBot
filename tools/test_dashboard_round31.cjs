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
