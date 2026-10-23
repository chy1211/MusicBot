"use strict";
const {session, snapshot, json, setup} = require("./dashboard_round31_auth_fixture.cjs");
module.exports = ({test, assert, openDashboard}) => {
  test("Spotify prefetch enables a matched real href without opening a popup", async t => {
    const app = await openDashboard(undefined, {setup: async page => {
      await setup(page, session);
      await page.route("**/api/guilds/1/spotify", route => json(route, {url: "https://open.spotify.com/track/Matched", track_token: "track-1"}));
    }}); t.after(() => app.context.close());
    await app.page.waitForFunction(() => document.querySelector("#song-spotify").getAttribute("href")?.endsWith("/Matched"));
    assert.equal(await app.page.locator("#song-spotify").getAttribute("aria-disabled"), "false");
    assert.equal(await app.page.locator("#song-spotify").evaluate(el => el.classList.contains("is-loading")), false);
    assert.equal(app.context.pages().length, 1);
    const request = app.requests.find(r => r.url.endsWith("/spotify")); assert.equal(request.method, "GET"); assert.equal(request.body, null);
  });
  test("Spotify loading suppresses clicks until its lookup completes", {timeout: 20000}, async t => {
    let release, arrived;
    const started = new Promise(resolve => { arrived = resolve; });
    const app = await openDashboard(undefined, {setup: async page => {
      await setup(page, session);
      await page.route("**/api/guilds/1/spotify", route => new Promise(done => {
        release = async () => { await json(route, {url: "https://open.spotify.com/track/Ready", track_token: "track-1"}); done(); }; arrived();
      }));
    }}); t.after(() => app.context.close()); await started;
    await app.page.locator("#bar-title").click();
    assert.equal(await app.page.locator("#song-spotify").getAttribute("href"), null);
    assert.equal(await app.page.locator("#song-spotify").getAttribute("aria-disabled"), "true");
    await app.page.locator("#song-spotify").click();
    assert.equal(app.context.pages().length, 1);
    await release();
    await app.page.waitForFunction(() => document.querySelector("#song-spotify").href.endsWith("/Ready"));
  });
  test("Spotify older reply cannot replace the next guild's matched result", {timeout: 20000}, async t => {
    let release, arrived; const started = new Promise(resolve => { arrived = resolve; });
    const app = await openDashboard(undefined, {setup: async page => {
      await setup(page, session);
      await page.route("**/api/guilds/1/spotify", route => new Promise(done => {
        release = async () => { await json(route, {url: "https://open.spotify.com/track/Old", track_token: "track-1"}); done(); }; arrived();
      }));
      await page.route("**/api/guilds/2/spotify", route => json(route, {url: "https://open.spotify.com/track/New", track_token: "track-2"}));
    }}); t.after(() => app.context.close()); await started;
    await app.page.locator("#guild").selectOption("2");
    await app.page.waitForFunction(() => document.querySelector("#song-spotify").getAttribute("href")?.endsWith("/New"));
    await release(); await app.page.waitForTimeout(50);
    assert.equal(await app.page.locator("#song-spotify").getAttribute("href"), "https://open.spotify.com/track/New");
  });
  test("Spotify no-current state clears the href and hides the old link", {timeout: 20000}, async t => {
    let release, arrived; const started = new Promise(resolve => { arrived = resolve; });
    const app = await openDashboard(undefined, {setup: async page => {
      await setup(page, session);
      await page.route("**/api/guilds/1/spotify", route => new Promise(done => {
        release = async () => { await json(route, {url: "https://open.spotify.com/track/Old", track_token: "track-1"}); done(); }; arrived();
      }));
      await page.route("**/api/guilds/2/state", route => json(route, {...snapshot("2"), current: null}));
    }}); t.after(() => app.context.close()); await started;
    await app.page.locator("#guild").selectOption("2"); await release();
    await app.page.waitForFunction(() => document.querySelector("#bar-title").disabled);
    assert.equal(await app.page.locator("#song-spotify").getAttribute("href"), null);
    assert.equal(await app.page.locator("#song-spotify").evaluate(el => el.hidden), true);
  });
  test("Spotify lookup failure offers an encoded title search", async t => {
    const app = await openDashboard(undefined, {setup: async page => {
      await setup(page, session); await page.route("**/api/guilds/1/spotify", route => json(route, {error: "unavailable"}, 503));
    }}); t.after(() => app.context.close());
    await app.page.waitForFunction(() => document.querySelector("#song-spotify").getAttribute("href")?.includes("/search/"));
    assert.equal(await app.page.locator("#song-spotify").getAttribute("href"), "https://open.spotify.com/search/Private%20current%20track");
    assert.equal(await app.page.locator("#song-spotify").getAttribute("aria-disabled"), "false");
  });
};
