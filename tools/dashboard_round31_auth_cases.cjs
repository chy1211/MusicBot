"use strict";
const {session, json, setup} = require("./dashboard_round31_auth_fixture.cjs");
module.exports = ({test, assert, openDashboard}) => {
  async function appWith(value = session, options = {}) {
    return openDashboard(undefined, {...options, setup: page => setup(page, value, options.status || 200)});
  }
  test("Discord profile renders literal text and same-origin requests without Authorization", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    assert.equal(await app.page.locator("#user-name").innerText(), session.user.name);
    assert.equal(await app.page.locator("#user-name img").count(), 0);
    assert.equal(await app.page.locator("#auth").isVisible(), false);
    const calls = await app.page.evaluate(() => window.__authAudit.filter(call => call.url.startsWith("/api/") || call.url.startsWith("/auth/")));
    assert.ok(calls.length > 0);
    assert.ok(calls.every(call => call.credentials === "same-origin" && call.authorization === null));
  });
  for (const [label, value, status] of [
    ["server failure", {error: "unavailable"}, 503],
    ["missing fields", {}, 200],
    ["unauthenticated owner", {auth_mode: "owner", authenticated: false}, 200],
    ["unknown auth mode", {auth_mode: "unknown", authenticated: true}, 200],
    ["missing Discord user", {auth_mode: "discord", authenticated: true, user: null}, 200]
  ]) test("session bootstrap fails closed for " + label, async t => {
    const app = await appWith(value, {authenticate: false, status}); t.after(() => app.context.close());
    await app.page.waitForTimeout(100);
    assert.equal(await app.page.locator("#dashboard").isVisible(), false);
    assert.equal(app.requests.some(r => r.url.startsWith("/api/")), false);
    assert.equal(await app.page.locator("#queue > li").count(), 0);
  });
  test("unsafe avatar is omitted while safe profile text remains", async t => {
    const app = await appWith({...session, user: {...session.user, avatar: "javascript:evil()"}});
    t.after(() => app.context.close());
    assert.equal(await app.page.locator("#user-avatar").count(), 0);
    assert.equal(await app.page.locator("#user-name").innerText(), session.user.name);
  });
  for (const html of [false, true]) test((html ? "non-JSON" : "JSON") + " state 401 clears all private UI and stops polling", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    await app.page.locator("#query").fill("private query");
    await app.page.locator("#enqueue").click();
    await app.page.locator("#preview-results article").first().waitFor();
    await app.page.route("**/api/guilds/2/state", route => html
      ? route.fulfill({status: 401, contentType: "text/html", body: "<html>expired</html>"})
      : json(route, {error: "expired"}, 401));
    await app.page.locator("#guild").selectOption("2");
    await app.page.locator("#login-screen").waitFor({state: "visible"});
    await app.page.waitForFunction(() => document.querySelectorAll("#queue > li").length === 0);
    assert.equal(await app.page.locator("#preview-results article").count(), 0);
    assert.equal(await app.page.locator("#query").inputValue(), "");
    assert.equal(await app.page.locator("#guild option").count(), 0);
    assert.equal(await app.page.locator("#user-name").textContent(), "");
    assert.equal(await app.page.locator("#user-avatar").count(), 0);
    assert.equal(await app.page.locator("#toggle").isDisabled(), true);
    const count = app.requests.length; await app.page.waitForTimeout(1200);
    assert.equal(app.requests.length, count);
  });
  test("403 mutation retains the session and shows the bot reason", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    await app.page.route("**/api/guilds/1/skip", route => json(route, {error: "join voice channel"}, 403));
    await app.page.locator("#skip").click();
    await app.page.locator("#notice.error.visible").waitFor();
    assert.match(await app.page.locator("#notice").innerText(), /join voice channel/);
    assert.equal(await app.page.locator("#dashboard").isVisible(), true);
    await app.page.waitForFunction(() => !document.querySelector("#toggle").disabled);
    assert.equal(await app.page.locator("#user-profile").isVisible(), true);
  });
  test("rejected logout is retryable and preserves the session until success", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    let attempts = 0;
    await app.page.route("**/auth/logout", route => ++attempts === 1
      ? json(route, {error: "try logout again"}, 502) : json(route, {}));
    await app.page.locator(".account-actions > summary").click();
    await app.page.locator("#logout").click();
    await app.page.locator("#notice.error.visible").waitFor();
    assert.equal(await app.page.locator("#dashboard").isVisible(), true);
    assert.equal(await app.page.locator("#logout").isDisabled(), false);
    await app.page.locator("#logout").click();
    await app.page.locator("#login-screen").waitFor({state: "visible"});
    assert.equal(attempts, 2);
    const call = await app.page.evaluate(() => window.__authAudit.find(row => row.url === "/auth/logout"));
    assert.equal(call.dashboardHeader, "1"); assert.equal(call.credentials, "same-origin"); assert.equal(call.authorization, null);
  });
};
