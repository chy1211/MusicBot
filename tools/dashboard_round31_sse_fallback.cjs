"use strict";
const {session, snapshot} = require("./dashboard_round31_auth_fixture.cjs");
const {streamSetup} = require("./dashboard_round31_stream_fixture.cjs");
module.exports = ({test, assert, openDashboard}) => {
  async function appWith(available = true, value = session) {
    return openDashboard(undefined, {setup: page => streamSetup(page, value, available)});
  }
  test("SSE absent browser support retains fallback polling at least five seconds apart", async t => {
    const app = await appWith(false); t.after(() => app.context.close());
    await app.page.clock.runFor(16000);
    await app.page.waitForFunction(() => window.__stateReads.length >= 3);
    const reads = await app.page.evaluate(() => window.__stateReads);
    assert.ok(reads.length >= 3);
    assert.ok(reads.slice(1).every((read, i) => read.time - reads[i].time >= 5000), JSON.stringify(reads));
    assert.equal(await app.page.locator("#dashboard").isVisible(), true);
    assert.equal(await app.page.locator("#queue > li").count(), 4);
  });
  test("SSE initial watchdog closes an unresponsive stream while fallback stays usable", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    await app.page.waitForFunction(() => window.__streams.length === 1);
    await app.page.clock.fastForward(21000);
    await app.page.waitForFunction(() => window.__streams[0].closed);
    assert.equal(await app.page.locator("#dashboard").isVisible(), true);
    assert.ok(await app.page.evaluate(() => window.__stateReads.length > 1));
    assert.equal(await app.page.locator("#toggle").isDisabled(), false);
  });
  test("SSE exponential backoff survives foreground changes and recovers", {timeout: 25000}, async t => {
    const app = await appWith(); t.after(() => app.context.close());
    await app.page.waitForFunction(() => window.__streams.length === 1);
    for (const [index, delay] of [[0, 1050], [1, 2050], [2, 4050]]) {
      await app.page.evaluate(index => window.__streams[index].fail(), index);
      await app.page.clock.fastForward(delay);
      await app.page.waitForFunction(count => window.__streams.length === count, index + 2);
    }
    await app.page.evaluate(() => window.__streams[3].fail());
    await app.page.waitForTimeout(50);
    await app.page.evaluate(() => { document.dispatchEvent(new Event("visibilitychange")); document.dispatchEvent(new Event("visibilitychange")); });
    await app.page.clock.fastForward(59000);
    assert.equal(await app.page.evaluate(() => window.__streams.length), 4);
    await app.page.clock.fastForward(1200);
    await app.page.waitForFunction(() => window.__streams.length === 5);
    const state = snapshot(); state.current.title = "RECOVERED STREAM";
    await app.page.evaluate(state => window.__streams[4].emit("snapshot", {state}), state);
    await app.page.waitForFunction(() => document.querySelector("#bar-title").textContent === "RECOVERED STREAM");
    const reads = app.requests.filter(r => r.url.endsWith("/state")).length;
    await app.page.clock.runFor(6000);
    assert.equal(app.requests.filter(r => r.url.endsWith("/state")).length, reads);
  });
  test("SSE owner shared secret is never put in a stream URL", async t => {
    const app = await appWith(true, {auth_mode: "owner", authenticated: true}); t.after(() => app.context.close());
    await app.page.waitForFunction(() => window.__streams.length === 1);
    await app.page.locator("#auth summary").click(); await app.page.locator("#secret").fill("fixture-stream-secret");
    await app.page.locator("#auth-form button[type=submit]").click();
    await app.page.waitForFunction(() => window.__authAudit.some(call => call.authorization === "Bearer fixture-stream-secret"));
    assert.equal(await app.page.evaluate(() => window.__streams.every(stream => !stream.url.includes("fixture-stream-secret"))), true);
    assert.equal(await app.page.evaluate(() => window.__streams[0].closed), true);
    assert.equal(await app.page.evaluate(() => window.__streams.length), 1);
  });
};
