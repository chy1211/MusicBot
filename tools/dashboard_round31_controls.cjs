"use strict";
const {session, snapshot, json, setup} = require("./dashboard_round31_auth_fixture.cjs");
module.exports = ({test, assert, openDashboard}) => {
  const appWith = () => openDashboard(undefined, {setup: page => setup(page, session)});
  test("failed focused volume control reconciles with the actual server value", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    await app.page.route("**/api/guilds/1/volume", route => json(route, {error: "volume denied"}, 403));
    const response = app.page.waitForResponse(r => r.url().endsWith("/volume"));
    await app.page.locator("#volume").focus();
    assert.equal(await app.page.evaluate(() => document.activeElement.id), "volume");
    await app.page.keyboard.press("End"); await response;
    await app.page.waitForFunction(() => document.querySelector("#volume").value === "35");
    assert.equal(await app.page.locator("#volume").isDisabled(), false);
    assert.match(await app.page.locator("#notice").textContent(), /volume denied/);
  });
  test("failed guild switch clears old songs and disables playback and enqueue", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    await app.page.route("**/api/guilds/2/state", route => json(route, {error: "server unavailable"}, 503));
    await app.page.locator("#guild").selectOption("2");
    await app.page.waitForFunction(() => document.querySelectorAll("#queue > li").length === 0);
    assert.equal(await app.page.locator("#toggle").isDisabled(), true);
    assert.equal(await app.page.locator("#enqueue").isDisabled(), true);
    assert.doesNotMatch(await app.page.locator("#bar-title").textContent(), /Private current track/);
    assert.match(await app.page.locator("#notice").textContent(), /server unavailable/);
  });
  test("pending mutation blocks duplicate input and polling until it completes", {timeout: 20000}, async t => {
    const app = await appWith(); t.after(() => app.context.close());
    await app.page.clock.install();
    let release;
    await app.page.route("**/api/guilds/1/pause", route => new Promise(done => {
      release = async () => { await json(route, {state: {...snapshot(), status: "paused"}, message: "Paused"}); done(); };
    }));
    const started = app.page.waitForRequest(r => r.url().endsWith("/pause"));
    await app.page.locator("#toggle").click(); await started;
    assert.equal(await app.page.locator("#toggle").isDisabled(), true);
    assert.equal(await app.page.locator("#enqueue").isDisabled(), true);
    const box = await app.page.locator("#toggle").boundingBox();
    await app.page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    const reads = app.requests.filter(r => r.url.endsWith("/state")).length;
    await app.page.clock.fastForward(6000);
    assert.equal(app.requests.filter(r => r.url.endsWith("/state")).length, reads);
    assert.equal(app.requests.filter(r => r.url.endsWith("/pause")).length, 1);
    await app.page.route("**/api/guilds/1/state", route => json(route, {...snapshot(), status: "paused"}));
    await release();
    await app.page.waitForFunction(() => !document.querySelector("#toggle").disabled);
    assert.match(await app.page.locator("#toggle").textContent(), /Resume|\u7e7c\u7e8c/);
  });
  test("slow resolve disables only lookup and accepts exactly one lookup", {timeout: 20000}, async t => {
    const app = await appWith(); t.after(() => app.context.close());
    let release;
    await app.page.route("**/api/guilds/1/resolve", route => new Promise(done => {
      release = async () => { await json(route, {results: [{title: "Resolved", url: "https://example.test/resolved", allowed: true, kind: "track", preview_id: "token"}]}); done(); };
    }));
    const started = app.page.waitForRequest(r => r.url().endsWith("/resolve"));
    await app.page.locator("#query").fill("slow"); await app.page.locator("#enqueue").click(); await started;
    assert.equal(await app.page.locator("#enqueue").isDisabled(), true);
    assert.equal(await app.page.locator("#enqueue").getAttribute("aria-busy"), "true");
    assert.equal(await app.page.locator("#toggle").isDisabled(), false);
    const box = await app.page.locator("#enqueue").boundingBox(); await app.page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    assert.equal(app.requests.filter(r => r.url.endsWith("/resolve")).length, 1);
    await release(); await app.page.locator("#preview-results article").waitFor();
    assert.equal(await app.page.locator("#enqueue").isDisabled(), false);
    assert.equal(app.requests.some(r => r.url.endsWith("/play")), false);
  });
};
