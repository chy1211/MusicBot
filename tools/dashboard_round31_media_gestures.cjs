"use strict";
const {session, snapshot, setup, json} = require("./dashboard_round31_auth_fixture.cjs");
const {streamSetup} = require("./dashboard_round31_stream_fixture.cjs");
module.exports = ({test, assert, openDashboard}) => {
  const appWith = () => openDashboard(undefined, {setup: page => setup(page, session)});
  test("keyboard seek blur commits once with the captured track token", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    const posted = app.page.waitForRequest(r => r.url().endsWith("/seek") && r.method() === "POST");
    await app.page.locator("#progress").focus(); await app.page.keyboard.down("End");
    await app.page.locator("#query").focus();
    const request = await posted; await app.page.keyboard.up("End");
    assert.deepEqual(request.postDataJSON(), {position: 180, track_token: "track-1"});
    assert.equal(app.requests.filter(r => r.url.endsWith("/seek")).length, 1);
  });
  test("pointer seek blur cancels preview and sends no seek", async t => {
    const app = await appWith(); t.after(() => app.context.close());
    const box = await app.page.locator("#progress").boundingBox();
    await app.page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await app.page.mouse.down();
    await app.page.mouse.move(box.x + box.width * .75, box.y + box.height / 2);
    await app.page.locator("#query").focus(); await app.page.mouse.up();
    await app.page.waitForFunction(() => Number(document.querySelector("#progress").value) < 60);
    assert.equal(app.requests.some(r => r.url.endsWith("/seek")), false);
    assert.equal(await app.page.locator("body.no-selection").count(), 0);
  });
  test("lyrics missing scrollTo centers with scrollTop without scrolling the page", async t => {
    const app = await openDashboard(undefined, {context: {reducedMotion: "reduce"}, setup: async page => {
      await streamSetup(page);
      await page.route("**/api/guilds/1/lyrics", route => json(route, {status: "synced", video_id: "abcdefghijk", offset: 0,
        lines: Array.from({length: 60}, (_, i) => ({time: i, text: "Line " + i}))}));
    }}); t.after(() => app.context.close());
    await app.page.locator("#lyrics-toggle").click(); await app.page.locator("#lyrics-content p").first().waitFor();
    const pageTop = await app.page.evaluate(() => scrollY);
    await app.page.locator("#lyrics-content").evaluate(element => {
      Object.defineProperty(element, "scrollTo", {configurable: true, value: undefined}); element.scrollTop = 0;
    });
    await app.page.evaluate(state => window.__streams[0].emit("snapshot", {state}), {...snapshot(), status: "paused", progress: 40});
    await app.page.waitForFunction(() => document.querySelector("#lyrics-content").scrollTop > 100);
    const geometry = await app.page.locator("#lyrics-content").evaluate(element => {
      const box = element.getBoundingClientRect(), row = element.querySelector('[aria-current="true"]').getBoundingClientRect();
      return {error: Math.abs(row.y + row.height / 2 - box.y - box.height / 2), text: element.querySelector('[aria-current="true"]').textContent};
    });
    assert.equal(geometry.text, "Line 40"); assert.ok(geometry.error < 8, JSON.stringify(geometry));
    assert.equal(await app.page.evaluate(() => scrollY), pageTop);
    assert.deepEqual(app.errors, []);
  });
};
