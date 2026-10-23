"use strict";
const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const { spawn, spawnSync } = require("node:child_process");
const { chromium } = require(path.join(root, "frontend", "node_modules", "playwright"));
const http = require("node:http");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
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

async function openDashboard(viewport = { width: 1440, height: 1000 }) {
  const context = await browser.newContext({ viewport, locale: "zh-TW", colorScheme: "light", serviceWorkers: "block" });
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
  await page.goto(baseURL + "/?demo-queue=filled&demo-lyrics=synced", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelector("#dashboard") || document.querySelector("#discord-login"));
  if (await page.locator("#discord-login").isVisible().catch(() => false)) await page.locator("#discord-login").click();
  await page.waitForFunction(() => {
    const dashboard = document.querySelector("#dashboard");
    return dashboard && !dashboard.hidden && document.querySelector("#nav-play") && !document.querySelector("#nav-play").hidden;
  }, null, { timeout: 20000 });
  return { context, page, requests, errors };
}

before(async () => {
  const build = spawnSync(process.platform === "win32" ? "npm.cmd" : "npm", ["run", "build"], {
    cwd: frontend, encoding: "utf8", timeout: 180000
  });
  if (build.status !== 0) throw new Error("npm run build failed\n" + (build.stdout || "") + "\n" + (build.stderr || ""));
  serverProcess = spawn("python3", ["-m", "tools.dashboard_round31_fixture", "--host", "0.0.0.0", "--port", "18310"], {
    cwd: root, stdio: ["ignore", "pipe", "pipe"]
  });
  let bootLog = "";
  serverProcess.stdout.on("data", chunk => { bootLog += chunk; });
  serverProcess.stderr.on("data", chunk => { bootLog += chunk; });
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
  await app.page.locator("#preview-results button").first().click();
  await app.page.waitForFunction(() => document.querySelector("#queue > li")?.textContent.includes("Sunset"));
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
  assert.ok(await app.page.locator("#lyrics-lines > *").count() > 0);
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
  await app.page.addStyleTag({ content: ":root{--safe-top:59px;--safe-right:0px;--safe-bottom:34px;--safe-left:0px}" });
  await app.page.locator("#favorite").click();
  await app.page.locator("#notice.visible").waitFor({ state: "visible" });
  const notice = await app.page.locator("#notice").boundingBox();
  const viewport = app.page.viewportSize();
  assert.ok(notice && notice.y >= 59 && notice.y + notice.height <= viewport.height);
  assert.deepEqual(app.errors, []);
});
