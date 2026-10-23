"use strict";
const {snapshot} = require("./dashboard_round31_auth_fixture.cjs");
const {streamSetup} = require("./dashboard_round31_stream_fixture.cjs");
module.exports = ({test, assert, openDashboard}) => {
  async function appWith() {
    const app = await openDashboard(undefined, {setup: page => streamSetup(page)});
    await app.page.waitForFunction(() => window.__streams.length === 1);
    return app;
  }
  test("SSE snapshot updates songs, community and history without REST polling", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    const state = snapshot(); state.current.title = "STREAM TRACK"; state.queue[0].title = "<img onerror=evil>";
    state.listeners.members = [{id: "200", name: "<img onerror=evil>"}];
    state.activity.activity = [{actor: "Member", detail: "Added song", time: 1, source: "web", result: "ok"}];
    await app.page.evaluate(packet => window.__streams[0].emit("snapshot", packet), {state,
      history: {history: [{title: "Stream history", url: "https://example.test/history", duration: 60}]}});
    await app.page.waitForFunction(() => document.querySelector("#bar-title").textContent === "STREAM TRACK");
    await app.page.waitForFunction(() => document.querySelectorAll("#queue > li").length === 4 && document.querySelector("#queue .song p")?.textContent.includes("<img onerror=evil>"));
    assert.match(await app.page.locator("#queue > li .song p").first().textContent(), /<img onerror=evil>/);
    assert.equal(await app.page.locator("#queue .song p img").count(), 0);
    assert.equal(await app.page.locator("#listeners-list .listener").count(), 1);
    assert.equal(await app.page.locator("#history-list > li").count(), 1);
    assert.match(await app.page.locator("#activity-list").textContent(), /Added song/);
    const reads = app.requests.filter(r => /\/(state|history)$/.test(r.url)).length;
    await app.page.clock.runFor(6000);
    assert.equal(app.requests.filter(r => /\/(state|history)$/.test(r.url)).length, reads);
    const options = await app.page.evaluate(() => ({url: window.__streams[0].url, noOptions: window.__streams[0].options === undefined}));
    assert.equal(new URL(options.url, "http://localhost").pathname, "/api/guilds/1/events");
    assert.equal(options.noOptions, true);
  });
  test("SSE old guild stream closes and stale callbacks cannot replace the selected guild", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    await app.page.locator("#guild").selectOption("2");
    await app.page.waitForFunction(() => window.__streams.length === 2);
    const state = snapshot("2"); state.current.title = "SECOND GUILD";
    await app.page.evaluate(state => window.__streams[1].emit("snapshot", {state}), state);
    const stale = snapshot(); stale.current.title = "STALE FIRST GUILD";
    await app.page.evaluate(state => window.__streams[0].emit("snapshot", {state}), stale);
    await app.page.waitForFunction(() => document.querySelector("#bar-title").textContent === "SECOND GUILD");
    assert.equal(await app.page.evaluate(() => window.__streams[0].closed), true);
    assert.equal(await app.page.locator("#guild").inputValue(), "2");
  });
  test("SSE wrong-guild snapshot is rejected and falls back without exposing its songs", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    const state = snapshot("2"); state.current.title = "WRONG GUILD";
    await app.page.evaluate(state => window.__streams[0].emit("snapshot", {state}), state);
    await app.page.waitForFunction(() => window.__streams[0].closed);
    assert.doesNotMatch(await app.page.locator("#bar-title").textContent(), /WRONG GUILD/);
    assert.equal(await app.page.locator("#guild").inputValue(), "1");
  });
  test("SSE visibility suspension closes the stream and resumes with a new one", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    await app.page.evaluate(() => {
      Object.defineProperty(document, "hidden", {configurable: true, get: () => true});
      document.dispatchEvent(new Event("visibilitychange"));
    });
    assert.equal(await app.page.evaluate(() => window.__streams[0].closed), true);
    await app.page.evaluate(() => {
      Object.defineProperty(document, "hidden", {configurable: true, get: () => false});
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await app.page.waitForFunction(() => window.__streams.length === 2);
    assert.equal(await app.page.evaluate(() => window.__streams[1].closed), false);
  });
  test("SSE access 401 erases private content, closes its stream and stops polling", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    await app.page.evaluate(() => window.__streams[0].emit("access", {status: 401}));
    await app.page.locator("#login-screen").waitFor();
    await app.page.waitForFunction(() => document.querySelectorAll("#queue > li").length === 0);
    assert.equal(await app.page.locator("#guild option").count(), 0);
    assert.equal(await app.page.evaluate(() => window.__streams[0].closed), true);
    const count = app.requests.length; await app.page.clock.runFor(6000);
    assert.equal(app.requests.length, count);
    assert.equal(await app.page.evaluate(() => window.__streams.length), 1);
  });
};
