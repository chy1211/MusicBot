"use strict";
const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const { spawn, spawnSync } = require("node:child_process");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const { chromium } = require("playwright");
const http = require("node:http");
const frontend = path.join(root, "frontend");
const baseURL = process.env.ROUND31_BASE_URL || "http://localhost:18310";
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
  await app.page.locator("#admin-permissions-group > summary").click();
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
  await app.page.locator("#admin-permissions-group > summary").click();
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
  await app.page.locator("#admin-permissions-group > summary").click();
  const toggle = app.page.locator("#admin-vote-skip-enabled");
  await toggle.waitFor({ state: "visible" });
  await app.page.waitForFunction(() => !document.querySelector("#admin-vote-skip-enabled")?.disabled);
  const enabled = !(await toggle.isChecked());
  await toggle.setChecked(enabled);
  await app.page.locator("#admin-vote-skip-save").click();
  await app.page.waitForFunction(() => Boolean(document.querySelector("#admin-vote-skip-status")?.textContent));
  const save = app.requests.find(r => r.method === "POST" && r.url.endsWith("/admin/vote-skip"));
  assert.ok(save);
  assert.equal(JSON.parse(save.body).enabled, enabled);
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
          if (data.authenticated) data.user = { ...data.user, name: "DemoUser", avatar: baseURL + "/demo-cover/0.svg" };
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


test("R31 theme toggle sits before the language label and select", async t => {
  for (const scenario of [
    { width: 1440, height: 900, mode: "dark" },
    { width: 1440, height: 900, mode: "light" },
    { width: 390, height: 844, mode: "dark", mobile: true }
  ]) {
    const { width, height, mode, mobile = false } = scenario;
    const app = await openDashboard({ width, height }, {
      context: { colorScheme: mode, isMobile: mobile, hasTouch: mobile },
      setup: async page => {
        await page.route("**/auth/session", async route => {
          const response = await route.fetch();
          const data = await response.json();
          if (data.authenticated) data.user = { ...data.user, name: "DemoUser" };
          await route.fulfill({ response, json: data });
        });
      }
    });
    t.after(() => app.context.close());
    const button = app.page.locator("#theme-toggle");
    const select = app.page.locator("#dashboard-language");
    const label = app.page.locator('label[for="' + await select.getAttribute("id") + '"]');
    assert.equal(await label.count(), 1);
    assert.equal(await label.evaluate(el => el.control === document.querySelector("#dashboard-language")), true);
    assert.equal(await label.isVisible(), !mobile);
    const b = await button.boundingBox(), s = await select.boundingBox();
    const centers = [b.y + b.height / 2, s.y + s.height / 2];
    assert.ok(b.x + b.width <= s.x, JSON.stringify({ b, s }));
    if (!mobile) {
      const l = await label.boundingBox();
      assert.ok(b.x + b.width <= l.x, JSON.stringify({ b, l }));
      assert.ok(l.x + l.width <= s.x, JSON.stringify({ l, s }));
      centers.push(l.y + l.height / 2);
      const headerGap = await app.page.locator(".user-profile").evaluate(el => parseFloat(getComputedStyle(el).gap));
      assert.ok(Math.abs(l.x - b.x - b.width - headerGap) <= 1);
      assert.ok(Math.abs(s.x - l.x - l.width - headerGap) <= 1);
    }
    assert.ok(Math.max(...centers) - Math.min(...centers) <= 2, JSON.stringify(centers));
    await select.evaluate(el => el.blur());
    if (mobile) await label.evaluate(el => el.click());
    else await label.click();
    assert.equal(await select.evaluate(el => document.activeElement === el), true);
    await select.evaluate(el => el.blur());
    assert.equal(await app.page.locator("html").getAttribute("data-theme"), mode);
    assert.deepEqual(app.errors, []);
    console.log("R31_ORDER_" + width + "_" + mode + "=" + JSON.stringify({ button: b, select: s, centers, labelFocus: true }));
    const dir = process.env.R31_SCREENSHOTS_DIR;
    if (dir) {
      require("node:fs").mkdirSync(dir, { recursive: true });
      const x = Math.max(0, b.x - 12), y = Math.max(0, Math.min(b.y, s.y) - 12);
      await app.page.screenshot({
        path: path.join(dir, "r31-header-" + width + "-" + mode + ".png"),
        clip: { x, y, width: Math.min(width - x, s.x + s.width + 12 - x), height: Math.max(b.y + b.height, s.y + s.height) + 12 - y }
      });
    }
  }
});


test("R32 notice dot blinks and respects reduced motion", async t => {
  for (const scenario of [
    { width: 1440, height: 900 },
    { width: 390, height: 844, mobile: true }
  ]) {
    const { width, height, mobile = false } = scenario;
    const app = await openDashboard({ width, height }, {
      context: { colorScheme: "dark", isMobile: mobile, hasTouch: mobile }
    });
    t.after(() => app.context.close());
    const notice = app.page.locator("#notice");
    if (await notice.isVisible()) await app.page.locator("#notice-dismiss").click();

    const successResponse = app.page.waitForResponse(response => ["/api/guilds/1/pause", "/api/guilds/1/resume"].includes(new URL(response.url()).pathname));
    await app.page.locator("#toggle").click();
    assert.ok((await successResponse).ok());
    await notice.waitFor({ state: "visible" });
    let style = await app.page.evaluate(() => {
      const dot = getComputedStyle(document.querySelector("#notice"), "::before");
      return { animationName: dot.animationName, iterationCount: dot.animationIterationCount, width: dot.width, height: dot.height };
    });
    assert.notEqual(style.animationName, "none");
    assert.equal(style.iterationCount, "infinite");
    assert.equal(style.width, "6px");
    assert.equal(style.height, "6px");

    const screenshotDir = process.env.R32_SCREENSHOTS_DIR;
    if (screenshotDir) {
      require("node:fs").mkdirSync(screenshotDir, { recursive: true });
      await notice.evaluate(el => { const animation = el.getAnimations().find(item => item.effect?.pseudoElement === "::before"); if (animation) animation.currentTime = 0; });
      await app.page.waitForTimeout(30);
      const box = await notice.boundingBox();
      await app.page.screenshot({ path: path.join(screenshotDir, "r32-notice-dark-" + width + ".png"), clip: box });
    }

    await app.page.route("**/api/guilds/1/pause", route => route.fulfill({ status: 500, json: { error: "fixture failure" } }));
    await app.page.route("**/api/guilds/1/resume", route => route.fulfill({ status: 500, json: { error: "fixture failure" } }));
    const failedResponse = app.page.waitForResponse(response => ["/api/guilds/1/pause", "/api/guilds/1/resume"].includes(new URL(response.url()).pathname));
    await app.page.locator("#toggle").click();
    assert.equal((await failedResponse).status(), 500);
    await app.page.locator("#notice.error").waitFor({ state: "visible" });
    style = await app.page.evaluate(() => {
      const dot = getComputedStyle(document.querySelector("#notice"), "::before");
      return { animationName: dot.animationName, iterationCount: dot.animationIterationCount, width: dot.width, height: dot.height };
    });
    assert.notEqual(style.animationName, "none");
    assert.equal(style.iterationCount, "infinite");
    assert.equal(style.width, "6px");
    assert.equal(style.height, "6px");

    await app.page.emulateMedia({ reducedMotion: "reduce" });
    const reduced = await app.page.evaluate(() => {
      const dot = getComputedStyle(document.querySelector("#notice"), "::before");
      return { animationName: dot.animationName, duration: dot.animationDuration };
    });
    assert.ok(reduced.animationName === "none" || reduced.duration === "0s", JSON.stringify(reduced));
    assert.deepEqual(app.errors.filter(error => !error.includes("Failed to load resource: the server responded with a status of 500")), []);
  }
});


test("R34 mobile playlist detail back button and row alignment", async t => {
  for (const { width, height, mode, mobile } of [
    { width: 390, height: 844, mode: "dark", mobile: true },
    { width: 390, height: 844, mode: "light", mobile: true },
    { width: 1440, height: 900, mode: "dark", mobile: false }
  ]) {
    const longTitle = "\u9577".repeat(80);
    const app = await openDashboard({ width, height }, {
      context: { colorScheme: mode, isMobile: mobile, hasTouch: mobile, reducedMotion: "reduce" },
      setup: async page => {
        await r30Library(page);
        await page.route("**/auth/session", async route => {
          const response = await route.fetch();
          const data = await response.json();
          if (data.authenticated) data.user = { ...data.user, name: "DemoUser" };
          await route.fulfill({ response, json: data });
        });
        await page.route("**/api/library", async route => {
          await route.fulfill({ json: { revision: "r34-1", owner: true, playlists: [
            { id: "favorites", name: "Favorites", tracks: [
              { title: longTitle, url: "https://youtu.be/demo0000001", duration: 296 },
              { title: "DemoUser track", url: "https://youtu.be/demo0000002", duration: 216 },
              { title: "Owner track without artwork", url: "https://soundcloud.com/example/no-art", duration: 60 }
            ] }
          ] } });
        });
        await page.route("**/api/guilds/1/resolve", route => route.fulfill({ json: { results: [
          { kind: "playlist", title: "Owner import preview", url: "https://example.com/playlist", thumbnail: baseURL + "/demo-cover/2.svg",
            allowed: true, preview_id: "r34-preview", count: 2, checked_count: 2, eligible_count: 2,
            entries: [
              { item_id: "one", title: longTitle, url: "https://example.com/one", duration: 120, allowed: true },
              { item_id: "two", title: "DemoUser preview track", url: "https://example.com/two", duration: 60, allowed: true, default_selected: false }
            ] }
        ] } }));
      }
    });
    t.after(() => app.context.close());
    if (await app.page.locator(".notice-dismiss").isVisible()) await app.page.locator(".notice-dismiss").click();
    await app.page.locator("#nav-library").click();
    await app.page.locator(".library-choice").first().click();
    await app.page.locator("#library-list > li").first().waitFor({ state: "visible" });
    await app.page.locator('#library-list input[type="checkbox"]').first().check();
    await app.page.locator("#library-detail").scrollIntoViewIfNeeded();
    const result = await app.page.evaluate(() => {
      const rect = el => {
        const b = el.getBoundingClientRect();
        return { left: b.left, right: b.right, top: b.top, bottom: b.bottom, width: b.width, height: b.height, cx: (b.left + b.right) / 2, cy: (b.top + b.bottom) / 2 };
      };
      const clippedBy = el => {
        const b = el.getBoundingClientRect(), clipped = [];
        for (let p = el.parentElement; p; p = p.parentElement) {
          const s = getComputedStyle(p), r = p.getBoundingClientRect();
          if (/(hidden|clip|auto|scroll)/.test(s.overflowX) && (b.left < r.left + p.clientLeft - .5 || b.right > r.left + p.clientLeft + p.clientWidth + .5)) clipped.push(p.id || p.className);
        }
        return clipped;
      };
      const back = document.querySelector("#library-back"), range = document.createRange();
      range.selectNodeContents(back);
      const b = range.getBoundingClientRect();
      return {
        back: rect(back), content: { cx: (b.left + b.right) / 2, cy: (b.top + b.bottom) / 2 },
        cover: rect(document.querySelector(".playlist-cover-hero")), play: rect(document.querySelector("#library-play-all")),
        backRadius: getComputedStyle(back).borderRadius, playRadius: getComputedStyle(document.querySelector("#library-play-all")).borderRadius,
        rows: [...document.querySelectorAll("#library-list > li")].map(row => {
          const [check, art, song, remove] = row.children, s = getComputedStyle(check), p = song.querySelector("p");
          return { row: rect(row), boxes: [check, art, song, remove].map(rect), checked: check.checked,
            border: parseFloat(s.borderTopWidth), shadow: s.boxShadow, borderColor: s.borderTopColor, background: s.backgroundColor,
            clipped: clippedBy(remove), title: p.textContent, titleHeight: p.getBoundingClientRect().height,
            lineHeight: parseFloat(getComputedStyle(p).lineHeight), ellipsis: getComputedStyle(p).textOverflow,
            nowrap: getComputedStyle(p).whiteSpace, textOverflow: p.scrollWidth > p.clientWidth };
        })
      };
    });
    console.log("R34_LAYOUT_" + width + "_" + mode + "=" + JSON.stringify(result));
    if (mobile) {
      assert.ok(Math.abs(result.back.cx - result.content.cx) <= 2, "back horizontal center");
      assert.ok(Math.abs(result.back.cy - result.content.cy) <= 2, "back vertical center");
      assert.ok(Math.abs(result.back.left - result.cover.left) <= 2, "back and cover left edge");
      assert.ok(Math.abs(result.back.left - result.play.left) <= 2, "back and toolbar left edge");
      assert.ok(Math.abs(result.back.height - result.play.height) <= 2, "back and toolbar height");
      assert.equal(result.backRadius, result.playRadius);
    }
    for (const row of result.rows) {
      for (let i = 0; i < 3; i++) assert.ok(row.boxes[i].right <= row.boxes[i + 1].left, "overlap: " + JSON.stringify(row));
      const centers = row.boxes.map(b => b.cy);
      assert.ok(Math.max(...centers) - Math.min(...centers) <= 2, "row vertical centers");
      assert.ok(row.boxes[0].left >= row.row.left && row.boxes[3].right <= row.row.right, "row containment");
      assert.deepEqual(row.clipped, [], "delete button clipped by ancestor");
      if (!row.checked) {
        assert.ok(row.border > 0 || row.shadow !== "none", "unchecked checkbox outline");
        const luminance = color => {
          const rgb = color.match(/[\d.]+/g).slice(0, 3).map(v => Number(v) / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
          return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
        };
        const a = luminance(row.borderColor), b = luminance(row.background);
        const contrast = (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
        assert.ok(contrast >= 3, "checkbox contrast " + contrast);
        console.log("R34_CHECKBOX_CONTRAST_" + width + "_" + mode + "=" + contrast.toFixed(2));
      }
    }
    const long = result.rows[0];
    assert.equal(long.title.length, 80);
    assert.equal(long.nowrap, "nowrap");
    assert.equal(long.ellipsis, "ellipsis");
    assert.ok(long.textOverflow && long.titleHeight <= long.lineHeight + 1, "80-character title stays on one truncated line");
    const dir = process.env.R34_SCREENSHOTS_DIR;
    if (dir) {
      require("node:fs").mkdirSync(dir, { recursive: true });
      await app.page.screenshot({ path: path.join(dir, "r34-playlist-" + width + "-" + mode + ".png") });
    }
    // Import preview has one article cover, and text-only selectable entries (no per-entry cover).
    await app.page.locator("#nav-play").click();
    await app.page.locator("#query").fill("https://example.com/playlist");
    await app.page.locator("#enqueue").click();
    await app.page.locator(".playlist-selection input").first().waitFor({ state: "visible" });
    const preview = await app.page.locator(".playlist-selection label").evaluateAll(labels => labels.map(label => {
      const [check, text] = label.children, a = check.getBoundingClientRect(), b = text.getBoundingClientRect(), r = label.getBoundingClientRect();
      return { checkRight: a.right, textLeft: b.left, textRight: b.right, rowRight: r.right, centerDelta: Math.abs((a.top + a.bottom - b.top - b.bottom) / 2), width: a.width, height: a.height };
    }));
    assert.equal(preview.length, 2);
    for (const row of preview) assert.ok(row.checkRight <= row.textLeft && row.textRight <= row.rowRight && row.centerDelta <= 2 && row.width === 24 && row.height === 24, JSON.stringify(row));
    console.log("R34_IMPORT_PREVIEW_" + width + "_" + mode + "=" + JSON.stringify(preview));
    assert.deepEqual(app.errors, []);
    await app.context.close();
  }
});


test("R36 favorites menu shows a hint instead of rename", async t => {
  const key = "library.favorites.builtinHint";
  const en = require(path.join(frontend, "public", "i18n", "en.json"));
  const zh = require(path.join(frontend, "public", "i18n", "zh-TW.json"));
  assert.equal(en[key], "Favorites is a built-in playlist and can't be renamed or deleted.");
  assert.equal(zh[key], "\u6536\u85cf\u662f\u5167\u5efa\u6b4c\u55ae\uff0c\u4e0d\u80fd\u6539\u540d\u6216\u522a\u9664\u3002");
  for (const width of [390, 1440]) {
    const mobile = width === 390;
    const app = await openDashboard({ width, height: mobile ? 844 : 900 }, {
      context: mobile ? { isMobile: true, hasTouch: true, colorScheme: "dark" } : {},
      setup: r30Library
    });
    t.after(() => app.context.close());
    await app.page.locator("#nav-library").click();
    await app.page.locator(".library-choice").first().click();
    await app.page.locator("#library-actions>summary").click();
    assert.equal(await app.page.locator("#library-name").count(), 0);
    assert.equal(await app.page.locator("#library-rename").count(), 0);
    assert.equal(await app.page.locator('label[for="library-name"]').count(), 0);
    const hint = app.page.locator(".library-favorites-hint");
    await hint.waitFor({ state: "visible" });
    assert.equal((await hint.textContent()).trim(), zh[key]);
    if (mobile) {
      const dir = process.env.R36_SCREENSHOTS_DIR;
      if (dir) {
        require("node:fs").mkdirSync(dir, { recursive: true });
        await app.page.evaluate(() => {
          const menu = document.querySelector("#library-actions");
          if (menu) window.scrollBy(0, menu.getBoundingClientRect().top - 190);
        });
        await app.page.screenshot({ path: path.join(dir, "r36-favorites-menu-mobile-dark.png") });
      }
    }
    await app.page.locator("#library-actions>summary").click();
    if (mobile) await app.page.locator("#library-back").click();
    await app.page.locator(".library-choice").nth(1).click();
    await app.page.locator("#library-actions>summary").click();
    const input = app.page.locator("#library-name");
    const button = app.page.locator("#library-rename");
    await input.waitFor({ state: "visible" });
    assert.equal(await input.isEnabled(), true);
    await button.waitFor({ state: "visible" });
    assert.equal(await button.isEnabled(), true);
    assert.deepEqual(app.errors, []);
  }
});

test('R37 track list select-all toggle uses select and deselect labels', async t => {
  const key = 'library.deselectAll';
  const en = require(path.join(frontend, 'public', 'i18n', 'en.json'));
  const zh = require(path.join(frontend, 'public', 'i18n', 'zh-TW.json'));
  assert.equal(en[key], 'Deselect all');
  assert.equal(zh[key], '\u53d6\u6d88\u5168\u9078');
  for (const width of [390, 1440]) {
    const mobile = width === 390;
    const app = await openDashboard({ width, height: mobile ? 844 : 900 }, {
      context: mobile ? { isMobile: true, hasTouch: true, colorScheme: 'dark' } : {},
      setup: r30Library
    });
    t.after(() => app.context.close());
    await app.page.locator('#nav-library').click();
    await app.page.locator('.library-choice').first().click();
    const tracks = app.page.locator('#library-list input[type=checkbox]');
    const count = await tracks.count();
    assert.ok(count > 0, 'favorites track list has songs');
    const playSelected = app.page.locator('#library-play-selected');
    const toggle = app.page.locator('.library-track-tools button');
    assert.equal((await toggle.textContent()).trim(), '\u5168\u9078');
    assert.equal(await toggle.getAttribute('aria-pressed'), 'false');
    if (mobile && await app.page.locator('#notice-dismiss').isVisible()) await app.page.locator('#notice-dismiss').click();
    if (mobile && process.env.R37_SCREENSHOTS_DIR) {
      await toggle.scrollIntoViewIfNeeded();
      require('node:fs').mkdirSync(process.env.R37_SCREENSHOTS_DIR, { recursive: true });
      await app.page.screenshot({ path: path.join(process.env.R37_SCREENSHOTS_DIR, 'r37-select-all-mobile-dark.png'), fullPage: true });
    }
    await toggle.click();
    await app.page.waitForFunction(() => document.querySelectorAll('#library-list input[type=checkbox]:checked').length > 0);
    assert.equal(await tracks.evaluateAll(items => items.filter(item => item.checked).length), count);
    assert.equal((await toggle.textContent()).trim(), zh[key]);
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true');
    assert.match((await playSelected.textContent()).trim(), new RegExp('\\u00b7\\s*' + count + '$'));
    if (mobile && process.env.R37_SCREENSHOTS_DIR) {
      await app.page.screenshot({ path: path.join(process.env.R37_SCREENSHOTS_DIR, 'r37-deselect-all-mobile-dark.png'), fullPage: true });
    }
    await toggle.click();
    assert.equal(await tracks.evaluateAll(items => items.filter(item => item.checked).length), 0);
    assert.equal((await toggle.textContent()).trim(), '\u5168\u9078');
    assert.equal(await toggle.getAttribute('aria-pressed'), 'false');
    assert.deepEqual(app.errors, []);
  }
});


test('R38 resolve queue shows queued then resolving', async t => {
  const zh = require(path.join(frontend, 'public', 'i18n', 'zh-TW.json'));
  for (const width of [390, 1440]) {
    const mobile = width === 390;
    let state = 'queued', statusSupported = true, release, postSeen, requestId;
    const hold = () => new Promise(done => { release = done; postSeen = true; });
    const track = {kind:'track', title:'Demo queue result', url:'https://soundcloud.com/example/demo',
      duration:120, allowed:true, preview_id:'r38-preview'};
    const app = await openDashboard({width, height:mobile?844:900}, {
      context: {colorScheme:'dark', ...(mobile?{isMobile:true,hasTouch:true}:{})},
      setup: async page => {
        // Exercise the real HTTP fallback with no EventSource support on mobile,
        // and an EventSource that disconnects immediately on desktop.
        await page.addInitScript(disconnected => {
          if (!disconnected) Object.defineProperty(window,'EventSource',{value:undefined});
          else window.EventSource = class {
            constructor(){setTimeout(()=>this.onerror?.(new Event('error')),0)}
            addEventListener(){} close(){}
          };
        }, !mobile);
        await page.route('**/api/guilds/1/resolution-status?*', route => {
          assert.equal(new URL(route.request().url()).searchParams.get('request_id'), requestId);
          return statusSupported?route.fulfill({json:{state}}):route.fulfill({status:503,json:{error:'Status temporarily unavailable'}});
        });
        await page.route('**/api/guilds/1/resolve', async route => {
          requestId=route.request().headers()['x-musicbot-request-id'];
          assert.match(requestId,/^[a-z0-9]{32}$/);
          await hold();
          await route.fulfill({json:{results:[track],expires_in:600}});
        });
        await page.route('**/api/guilds/1/play', async route => {
          requestId=route.request().headers()['x-musicbot-request-id'];
          await hold();
          await route.fulfill({json:{message:'Added demo track'}});
        });
      }
    });
    t.after(()=>app.context.close());
    const page=app.page, query=page.locator('#enqueue');
    await page.locator('#query').fill('Demo queue');
    await query.click();
    await page.waitForFunction(text=>document.querySelector('#enqueue')?.textContent.trim()===text,zh['resolve.queued']);
    assert.equal(await query.getAttribute('aria-busy'),'true');
    assert.ok(postSeen);
    assert.equal(await query.evaluate(button=>getComputedStyle(button,'::before').animationName),'resolution-spin');
    const assertNoProgressCopy=async()=>{
      assert.equal(await page.locator('.request-loading').count(),0);
      assert.doesNotMatch((await page.locator('#notice span').textContent())||'',new RegExp([zh['resolve.queued'],zh['resolve.resolving'],zh['resolve.adding'],zh.m0079,zh.m0120].join('|')));
    };
    await assertNoProgressCopy();
    if(mobile&&process.env.R38_SCREENSHOTS_DIR){
      require('node:fs').mkdirSync(process.env.R38_SCREENSHOTS_DIR,{recursive:true});
      await query.scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(process.env.R38_SCREENSHOTS_DIR,'r38-queued-mobile-dark.png')});
    }
    state='resolving';
    await page.waitForFunction(text=>document.querySelector('#enqueue')?.textContent.trim()===text,zh['resolve.resolving']);
    await assertNoProgressCopy();
    if(mobile&&process.env.R38_SCREENSHOTS_DIR)await page.screenshot({path:path.join(process.env.R38_SCREENSHOTS_DIR,'r38-resolving-mobile-dark.png')});
    release();
    await page.locator('#preview-panel').waitFor({state:'visible'});
    assert.match(await page.locator('#preview-results').textContent(),/Demo queue result/);
    assert.equal(await query.getAttribute('aria-busy'),'false');
    const add=page.locator('.preview-actions button.primary').first();
    state='queued';postSeen=false;
    await add.click();
    await page.waitForFunction(text=>document.querySelector('.preview-actions button.primary')?.textContent.trim()===text,zh['resolve.queued']);
    await assertNoProgressCopy();
    assert.equal(await add.getAttribute('aria-busy'),'true');
    assert.ok(postSeen);
    state='resolving';
    await page.waitForFunction(text=>document.querySelector('.preview-actions button.primary')?.textContent.trim()===text,zh['resolve.adding']);
    await assertNoProgressCopy();
    release();
    await page.locator('#preview-panel').waitFor({state:'hidden'});
    await query.waitFor({state:'visible'});
    // A queue timeout reaches the original POST response and displays its new key.
    await page.unroute('**/api/guilds/1/resolve');
    state='queued';postSeen=false;
    await page.route('**/api/guilds/1/resolve',async route=>{
      requestId=route.request().headers()['x-musicbot-request-id'];await hold();
      await route.fulfill({status:429,json:{error:zh['resolve.queueTimeout']}});
    });
    await page.locator('#query').fill('Timeout demo');await query.click();
    await page.waitForFunction(text=>document.querySelector('#enqueue')?.textContent.trim()===text,zh['resolve.queued']);
    release();
    await page.locator('.request > [role=alert]').waitFor({state:'visible'});
    assert.equal((await page.locator('.request > [role=alert]').textContent()).trim(),zh['resolve.queueTimeout']);
    assert.equal((await page.locator('#notice span').textContent()).trim(),zh['resolve.queueTimeout']);
    await page.waitForFunction(()=>!document.querySelector('#enqueue').disabled);
    // Unavailable status updates still leave a busy button, and the POST settles.
    await page.unroute('**/api/guilds/1/resolve');statusSupported=false;
    await page.route('**/api/guilds/1/resolve',async route=>{
      requestId=route.request().headers()['x-musicbot-request-id'];await hold();
      await route.fulfill({json:{results:[track]}});
    });
    await page.locator('#query').fill('Fallback demo');await query.click();
    await page.waitForFunction(()=>document.querySelector('#enqueue').getAttribute('aria-busy')==='true');
    await page.waitForTimeout(350);release();
    await page.locator('#preview-panel').waitFor({state:'visible'});
    await page.waitForFunction(()=>!document.querySelector('#enqueue').disabled);
    assert.deepEqual(app.errors.filter(error=>!error.includes('429')&&!error.includes('503')),[]);
    console.log('R38_VIEWPORT_'+width+'=queued -> resolving -> result; add queued -> adding; timeout; SSE/status fallback OK');
    await app.context.close();
  }
});


const r46Palettes = {
  mint: { dark: ["#1e2226", "#8fd6c4"], light: ["#f3f5f7", "#1f7a68"] },
  amber: { dark: ["#1b1b1b", "#ffa31a"], light: ["#f5f5f5", "#9a5800"] },
  ocean: { dark: ["#141b26", "#7aa7ff"], light: ["#f2f5fa", "#2f5fcf"] },
  rose: { dark: ["#1f1a1d", "#f29bb8"], light: ["#faf4f6", "#b03a66"] }
};
async function r46Select(page, palette) {
  await page.locator('#palette-toggle').click();
  await page.locator('.palette-swatch[data-palette="'+palette+'"]').click();
  assert.equal(await page.locator('#palette-toggle').getAttribute('aria-expanded'),'false');
  assert.equal(await page.locator('#palette-toggle').evaluate(el=>document.activeElement===el),true);
}
async function r46State(page) {
  return page.evaluate(() => {
    const root = document.documentElement, css = getComputedStyle(root);
    return {palette:root.dataset.palette, mode:root.dataset.theme, bg:css.getPropertyValue("--bg").trim(), green:css.getPropertyValue("--green").trim(), meta:document.querySelector('meta[name="theme-color"]').content};
  });
}
function r46Expected(palette, mode) {
  const [bg, green] = r46Palettes[palette][mode];
  return {palette,mode,bg,green,meta:bg};
}
async function r46Setup(page) {
  await page.route("**/auth/session", async route => {
    const response = await route.fetch(), data = await response.json();
    if(data.authenticated) data.user = {...data.user,name:"DemoUser"};
    await route.fulfill({response,json:data});
  });
}
test("R46 palette default mint preserves all original day/night tokens", async t => {
  const expected = {
    dark: ["#1e2226","#252a2f","#2c3238","#343b42","#eef1f4","#a9b3bd","#8fd6c4","#12201c","rgba(200,214,228,.16)","rgba(37,42,47,.78)","rgba(34,39,44,.92)","rgba(34,39,44,.97)","#1e2226","#ff9b8a","#f2c46d"],
    light: ["#f3f5f7","#ffffff","#fbfcfd","#e6eaee","#1e2226","#55606b","#1f7a68","#ffffff","rgba(30,34,38,.14)","rgba(255,255,255,.82)","rgba(255,255,255,.94)","rgba(255,255,255,.98)","#f3f5f7","#b3261e","#8a5a00"]
  };
  for(const mode of ["dark","light"]){
    const app = await openDashboard(undefined,{context:{colorScheme:mode}}); t.after(()=>app.context.close());
    assert.deepEqual(await r46State(app.page),r46Expected("mint",mode));
    const tokens = await app.page.evaluate(()=>{
      const css = getComputedStyle(document.documentElement);
      return ["bg","flat","opaque","raised","text","muted","green","accent-ink","line","surface","panel","popover","wall-shade","error","warning"].map(key=>css.getPropertyValue("--"+key).trim());
    });
    assert.deepEqual(tokens,expected[mode]);
    // The old blue focus halo/selection/badge RGB stays byte-equivalent for mint.
    assert.equal(await app.page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue("--legacy-accent").trim()),"#64d2ff");
    assert.deepEqual(app.errors,[]);
  }
});
test("R46 palette selections persist and day/night stays independent", async t => {
  const app = await openDashboard({width:1280,height:1000},{context:{colorScheme:"dark"},setup:r46Setup}); t.after(()=>app.context.close());
  const select = app.page.locator("#palette-toggle");
  assert.equal(await select.getAttribute("aria-label"),"\u914d\u8272");
  assert.equal(await app.page.locator('#dashboard-palette').count(),0);
  for(const palette of Object.keys(r46Palettes)){
    await r46Select(app.page,palette);
    for(const mode of ["dark","light"]){
      if((await r46State(app.page)).mode!==mode)await app.page.locator("#theme-toggle").click();
      assert.deepEqual(await r46State(app.page),r46Expected(palette,mode));
      await app.page.reload(); await select.waitFor();
      assert.deepEqual(await r46State(app.page),r46Expected(palette,mode));
      await select.click();
      assert.equal(await app.page.locator('.palette-swatch[aria-checked="true"]').getAttribute('data-palette'),palette);
      await app.page.keyboard.press('Escape');
      assert.equal(await app.page.evaluate(()=>localStorage.getItem("musicbot-palette")),palette);
      if(process.env.R46_SCREENSHOTS_DIR){
        require("node:fs").mkdirSync(process.env.R46_SCREENSHOTS_DIR,{recursive:true});
        await app.page.locator("#nav-play").click(); await app.page.waitForTimeout(400);
        await app.page.screenshot({path:path.join(process.env.R46_SCREENSHOTS_DIR,palette+"-"+mode+"-1280-play.png"),fullPage:true});
      }
    }
    await app.page.locator("#theme-toggle").click();
  }
  assert.deepEqual(app.errors,[]);
});
test("R46 palette invalid or blocked storage falls back to mint", async t => {
  for(const blocked of [false,true]){
    const app = await openDashboard(undefined,{context:{colorScheme:"dark"},setup:async page=>{
      await page.addInitScript(block=>{
        if(block) Object.defineProperty(window,"localStorage",{get(){throw new DOMException("blocked","SecurityError");}});
        else localStorage.setItem("musicbot-palette","\uFFFDgarbage");
      },blocked);
    }}); t.after(()=>app.context.close());
    assert.deepEqual(await r46State(app.page),r46Expected("mint","dark"));
    await r46Select(app.page,"amber");
    assert.deepEqual(await r46State(app.page),r46Expected("amber","dark"));
    assert.deepEqual(app.errors,[]);
  }
});
test("R46 palette mobile controls fit and opaque fallbacks follow the palette", async t => {
  const app = await openDashboard({width:390,height:844},{context:{colorScheme:"dark",hasTouch:true,isMobile:true},setup:r46Setup});t.after(()=>app.context.close());
  await r46Select(app.page,"amber");
  for(const selector of ["#theme-toggle","#dashboard-language","#palette-toggle"]){
    const box = await app.page.locator(selector).boundingBox();
    assert.ok(box.width>=44 && box.height>=44 && box.x>=0 && box.x+box.width<=390,JSON.stringify({selector,box}));
  }
  const bar = await app.page.locator(".language-preference").boundingBox(), brand = await app.page.locator(".sidebar .brand").boundingBox();
  assert.ok(bar.y+bar.height<=brand.y || bar.x>=brand.x+brand.width);
  for(const palette of Object.keys(r46Palettes))for(const mode of ["dark","light"]){
    await r46Select(app.page,palette);
    if((await r46State(app.page)).mode!==mode)await app.page.locator("#theme-toggle").click();
    await app.page.emulateMedia({contrast:"more"});
    assert.equal(await app.page.locator(".playback-bar").evaluate(el=>getComputedStyle(el).backgroundColor),await app.page.evaluate(()=>{const el=document.createElement("div");el.style.color="var(--opaque)";document.body.append(el);const color=getComputedStyle(el).color;el.remove();return color;}));
    await app.page.emulateMedia({contrast:"no-preference"});
    await app.page.evaluate(()=>document.documentElement.dataset.glass="opaque");
    assert.equal(await app.page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue("--surface").trim()),await app.page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue("--opaque").trim()));
    await app.page.evaluate(()=>delete document.documentElement.dataset.glass);
  }
  await r46Select(app.page,"amber");
  if((await r46State(app.page)).mode!=="dark")await app.page.locator("#theme-toggle").click();
  if(process.env.R46_SCREENSHOTS_DIR){
    await app.page.locator("#nav-play").click();await app.page.waitForTimeout(400);
    await app.page.screenshot({path:path.join(process.env.R46_SCREENSHOTS_DIR,"amber-dark-390-play.png"),fullPage:true});
    await app.page.locator("#nav-library").click();await app.page.locator("#library-panel").waitFor();await app.page.waitForTimeout(400);
    await app.page.screenshot({path:path.join(process.env.R46_SCREENSHOTS_DIR,"amber-dark-390-library.png"),fullPage:true});
  }
  assert.deepEqual(app.errors,[]);
});


test("R46 palette follows system day/night and reduced transparency", async t => {
  const app=await openDashboard(undefined,{context:{colorScheme:"dark"}});t.after(()=>app.context.close());
  const cdp=await app.context.newCDPSession(app.page);
  for(const palette of Object.keys(r46Palettes)){
    await r46Select(app.page,palette);
    for(const mode of ["light","dark"]){
      await app.page.emulateMedia({colorScheme:mode});
      await app.page.waitForFunction(value=>document.documentElement.dataset.theme===value,mode);
      assert.deepEqual(await r46State(app.page),r46Expected(palette,mode));
      await app.page.evaluate(()=>document.documentElement.dataset.glass="clear");
      const clear=await app.page.evaluate(()=>{const c=getComputedStyle(document.documentElement);return [c.getPropertyValue("--surface").trim(),c.getPropertyValue("--legacy-accent").trim()];});
      if(mode==="light")assert.equal(clear[0],"rgba(255,255,255,.82)");
      else assert.equal(clear[0],{mint:"rgba(37,42,47,.78)",amber:"rgba(41,41,41,.8)",ocean:"rgba(27,36,51,.8)",rose:"rgba(42,35,39,.8)"}[palette]);
      assert.equal(clear[1],palette==="mint"?"#64d2ff":r46Palettes[palette][mode][1]);
      await cdp.send("Emulation.setEmulatedMedia",{features:[{name:"prefers-color-scheme",value:mode},{name:"prefers-reduced-transparency",value:"reduce"}]});
      assert.equal(await app.page.evaluate(()=>matchMedia("(prefers-reduced-transparency: reduce)").matches),true);
      const fallback=await app.page.evaluate(()=>{
        const el=document.createElement("div");el.style.color="var(--opaque)";document.body.append(el);const opaque=getComputedStyle(el).color;el.remove();
        const bar=getComputedStyle(document.querySelector(".playback-bar"));return {opaque,background:bar.backgroundColor,filter:bar.backdropFilter};
      });
      assert.equal(fallback.background,fallback.opaque);assert.equal(fallback.filter,"none");
      await cdp.send("Emulation.setEmulatedMedia",{features:[{name:"prefers-color-scheme",value:mode},{name:"prefers-reduced-transparency",value:"no-preference"}]});
      await app.page.evaluate(()=>delete document.documentElement.dataset.glass);
    }
  }
  assert.equal(await app.page.evaluate(()=>localStorage.getItem("musicbot-theme")),null);
  assert.deepEqual(app.errors,[]);
});


test("R46 palette popup supports radios, focus, dismissal and icon-only labels", async t => {
  const app=await openDashboard({width:1280,height:900},{context:{colorScheme:'dark'},setup:r46Setup});t.after(()=>app.context.close());
  const page=app.page,toggle=page.locator('#palette-toggle'),panel=page.locator('#palette-panel');
  assert.equal(await toggle.getAttribute('aria-haspopup'),'true');
  for(const locale of ['zh-TW','en']){
    await page.locator('#dashboard-language').selectOption(locale);
    await toggle.click();
    assert.equal(await panel.getAttribute('role'),'radiogroup');
    assert.equal(await panel.getAttribute('aria-label'),locale==='en'?'Color theme':'\u914d\u8272');
    assert.doesNotMatch(await page.locator('body').innerText(),/\u914d\u8272|Color theme/);
    const radios=panel.locator('[role=radio]');assert.equal(await radios.count(),4);
    for(let i=0;i<4;i++){
      const radio=radios.nth(i),box=await radio.boundingBox();assert.ok(box.width>=44&&box.height>=44);
      assert.ok(await radio.getAttribute('aria-label'));assert.equal(await radio.getAttribute('title'),await radio.getAttribute('aria-label'));
      assert.equal(await radio.getAttribute('tabindex'),i===0?'0':'-1');
      assert.equal(await radio.getAttribute('aria-checked'),String(i===0));
      assert.equal(await radio.locator('span').evaluate(el=>el.getBoundingClientRect().width),28);
      assert.equal(await radio.locator('span').evaluate(el=>el.getBoundingClientRect().height),28);
      assert.equal(await radio.locator('span').evaluate(el=>el.style.backgroundColor),{mint:'rgb(143, 214, 196)',amber:'rgb(255, 163, 26)',ocean:'rgb(122, 167, 255)',rose:'rgb(242, 155, 184)'}[Object.keys(r46Palettes)[i]]);
    }
    for(const [key,expected] of [['ArrowLeft','rose'],['ArrowRight','mint'],['ArrowRight','amber'],['ArrowRight','ocean'],['ArrowRight','rose'],['ArrowRight','mint']]){
      await page.keyboard.press(key);
      const checked=panel.locator('[aria-checked="true"]');assert.equal(await checked.count(),1);
      assert.equal(await checked.getAttribute('data-palette'),expected);
      assert.equal(await checked.getAttribute('tabindex'),'0');
      assert.equal(await checked.evaluate(el=>document.activeElement===el),true);
      assert.equal(await panel.locator('[tabindex="0"]').count(),1);
      assert.equal((await r46State(page)).palette,expected);
    }
    await page.keyboard.press('Escape');assert.equal(await panel.count(),0);
    assert.equal(await toggle.getAttribute('aria-expanded'),'false');assert.equal(await toggle.evaluate(el=>document.activeElement===el),true);
    await toggle.click();await page.locator('.page-heading h1').click();assert.equal(await panel.count(),0);
    assert.equal(await toggle.evaluate(el=>document.activeElement===el),true);
  }
  assert.deepEqual(app.errors,[]);
});

test("R46 palette layout fits phones and desktop with unobstructed popups", async t => {
  const fs=require('node:fs');const dir=process.env.R46B_SCREENSHOTS_DIR;if(dir)fs.mkdirSync(dir,{recursive:true});
  const overlaps=(a,b)=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;
  for(const width of [320,390,430,1280]){
    const app=await openDashboard({width,height:width===1280?900:844},{context:{colorScheme:'dark',hasTouch:width<761,isMobile:width<761},setup:r46Setup});t.after(()=>app.context.close());
    const page=app.page;
    for(const locale of ['en','zh-TW']){
      await page.locator('#dashboard-language').selectOption(locale);
      const controls=await page.locator('.language-preference').boundingBox(),brand=await page.locator('.sidebar .brand').boundingBox(),account=await page.locator('.account-actions>summary').boundingBox();
      assert.ok(!overlaps(controls,brand),JSON.stringify({width,locale,controls,brand}));
      assert.ok(!overlaps(controls,account),JSON.stringify({width,locale,controls,account}));
      for(const selector of ['#theme-toggle','#palette-toggle','#dashboard-language']){const r=await page.locator(selector).boundingBox();assert.ok(r.width>=44&&r.height>=44&&r.x>=0&&r.x+r.width<=width,JSON.stringify({width,selector,r}));}
      console.log('R46B_LAYOUT_'+width+'_'+locale+'='+JSON.stringify({controls,brand,account}));
    }
    const shot=async name=>{if(dir)await page.screenshot({path:path.join(dir,name),animations:'disabled',...(width===1280?{clip:{x:0,y:0,width,height:480}}:{})})};
    if(width===320||width===390)await shot('mint-dark-'+width+'-closed.png');
    for(const [palette,mode] of [['amber',width===1280?'dark':'light'],['mint','light']]){
      await r46Select(page,palette);if((await r46State(page)).mode!==mode)await page.locator('#theme-toggle').click();
      await page.locator('#palette-toggle').click();
      const panel=page.locator('#palette-panel'),r=await panel.boundingBox();assert.ok(r.x>=0&&r.x+r.width<=width&&r.y>=0&&r.y+r.height<=844);
      assert.equal(await panel.evaluate(el=>{const r=el.getBoundingClientRect();return [12,r.width-12].every(x=>el.contains(document.elementFromPoint(r.x+x,r.y+r.height/2)))}),true);
      if(width===1280||width===390&&palette==='amber')await shot(palette+'-'+mode+'-'+width+'-open.png');
      if(width===1280){
        await page.evaluate(()=>{const n=document.querySelector('#notice');n.classList.add('visible');Object.assign(n.style,{position:'fixed',top:'55px',right:'0',left:'auto',width:'250px',height:'100px'})});
        assert.equal(await panel.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}),true);
        await page.locator('#notice').evaluate(el=>{el.classList.remove('visible');el.removeAttribute('style')});
      }
      await page.keyboard.press('Escape');
    }
    assert.deepEqual(app.errors,[]);
  }
});
