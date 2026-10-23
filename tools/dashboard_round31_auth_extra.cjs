"use strict";
const {session, snapshot, json, setup} = require("./dashboard_round31_auth_fixture.cjs");
module.exports = ({test, assert, openDashboard, baseURL}) => {
  const appWith = (value = session) => openDashboard(undefined, {setup: page => setup(page, value)});
  test("owner credentials stay in memory and Authorization and forget removes them", async t => {
    const app = await appWith({auth_mode: "owner", authenticated: true}); t.after(() => app.context.close());
    assert.equal(await app.page.locator("#auth").isVisible(), true);
    assert.equal(await app.page.locator("#user-profile").isVisible(), false);
    assert.equal(await app.page.locator("#logout").isVisible(), false);
    await app.page.locator("#auth summary").click();
    await app.page.locator("#secret").fill("fixture-owner-secret");
    await app.page.locator("#auth-form button[type=submit]").click();
    await app.page.waitForFunction(() => window.__authAudit.some(call => call.url === "/api/guilds" && call.authorization === "Bearer fixture-owner-secret"));
    await app.page.waitForFunction(() => !document.querySelector("#enqueue").disabled);
    if (!await app.page.locator("#forget").isVisible()) await app.page.locator("#auth summary").click();
    assert.equal(await app.page.locator("#secret").inputValue(), "");
    const stored = await app.page.evaluate(() => [...Object.values(localStorage), ...Object.values(sessionStorage)]);
    assert.equal(stored.some(value => String(value).includes("fixture-owner-secret")), false);
    await app.page.locator("#forget").click();
    await app.page.waitForFunction(() => window.__authAudit.filter(call => call.url === "/api/guilds").length >= 3);
    const guilds = await app.page.evaluate(() => window.__authAudit.filter(call => call.url === "/api/guilds"));
    assert.equal(guilds.at(-1).authorization, null);
    assert.ok(guilds.every(call => !call.url.includes("fixture-owner-secret")));
    assert.equal(app.requests.some(call => call.url.startsWith("/auth/logout")), false);
  });
  test("logout clears private content and late preview cannot restore it", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    let release;
    await app.page.route("**/api/guilds/1/resolve", route => new Promise(done => {
      release = async () => { await json(route, {results: [{title: "LATE PRIVATE RESULT", preview_id: "late", kind: "track", allowed: true}]}); done(); };
    }));
    const started = app.page.waitForRequest(r => r.url().endsWith("/resolve"));
    await app.page.locator("#query").fill("late query"); await app.page.locator("#enqueue").click(); await started;
    await app.page.locator(".account-actions > summary").click(); await app.page.locator("#logout").click();
    await app.page.locator("#login-screen").waitFor({state: "visible"}); await release();
    await app.page.waitForFunction(() => document.querySelectorAll("#queue > li").length === 0);
    assert.equal(await app.page.locator("#query").inputValue(), "");
    assert.equal(await app.page.locator("#preview-results article").count(), 0);
    assert.equal(await app.page.locator("#guild option").count(), 0);
    assert.equal(await app.page.locator("#user-name").textContent(), "");
  });
  test("late state cannot restore content after a concurrent API 401", {timeout: 20000}, async t => {
    const app = await appWith(); t.after(() => app.context.close());
    let release;
    await app.page.route("**/api/guilds/2/state", route => new Promise(done => {
      release = async () => { await json(route, snapshot("2")); done(); };
    }));
    const started = app.page.waitForRequest(r => r.url().endsWith("/api/guilds/2/state"));
    await app.page.route("**/api/library", async route => { await started; await json(route, {error: "expired"}, 401); });
    await app.page.locator("#guild").selectOption("2"); await started;
    await app.page.locator("#login-screen").waitFor({state: "visible"}); await release();
    await app.page.waitForFunction(() => document.querySelectorAll("#queue > li").length === 0);
    assert.equal(await app.page.locator("#dashboard").isVisible(), false);
    assert.equal(await app.page.locator("#queue > li").count(), 0);
    assert.equal(await app.page.locator("#guild option").count(), 0);
  });
};
