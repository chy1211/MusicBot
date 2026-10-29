"use strict";
module.exports = ({test, assert, openDashboard, baseURL}) => {
  const headers = {"X-MusicBot-Dashboard": "1"};
  test("library play applies returned state immediately without waiting for SSE or a poll", async t => {
    const app = await openDashboard(undefined, {setup: page => page.addInitScript(() => {
      window.EventSource = class { addEventListener() {} close() {} };
    })});
    t.after(() => app.context.close());
    const state = await (await app.page.request.get(baseURL + "/api/guilds/1/state", {headers})).json();
    const returned = structuredClone(state);
    returned.current.title = "Library returned state";
    returned.revision = "library-returned-state";
    await app.page.route("**/api/guilds/1/state", route => route.fulfill({json: state}));
    await app.page.route("**/api/guilds/1/library/*/play", route => route.fulfill({json: {state: returned, message: "Saved queue"}}));
    await app.page.locator("#nav-library").click();
    await app.page.locator("#library-playlists .library-choice").nth(1).click();
    await app.page.locator("#library-enqueue-all").click();
    await app.page.waitForFunction(() => document.querySelector("#bar-title")?.textContent === "Library returned state");
    const play = app.requests.find(r => /\/library\/.*\/play$/.test(r.url));
    assert.ok(play);
    assert.ok(JSON.parse(play.body).revision);
    assert.equal(await app.page.locator("#bar-title").textContent(), "Library returned state");
  });
  test("admin search ignores the older response after a newer search completes", async t => {
    const app = await openDashboard(); t.after(() => app.context.close());
    await app.page.locator("#nav-admin").click();
    await app.page.locator("#admin-apl-group > summary").click();
    await app.page.locator("#admin-apl-list > li").first().waitFor();
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    let oldArrived;
    const started = new Promise(resolve => { oldArrived = resolve; });
    await app.page.route("**/admin/autoplaylist?*", async route => {
      const query = new URL(route.request().url()).searchParams.get("q");
      if (query === "older") { oldArrived(); await gate; }
      await route.fulfill({json: {total: 1, matched: 1, page: 1, page_size: 20, revision: 1,
        tracks: [{index: 0, title: query === "older" ? "OLDER RESULT" : "LATEST RESULT", url: "https://example.test/" + query}]}});
    });
    await app.page.locator("#admin-apl-query").fill("older");
    await app.page.locator("#admin-apl-search-button").click(); await started;
    await app.page.locator("#admin-apl-query").fill("newer");
    await app.page.locator("#admin-apl-search-button").click();
    await app.page.waitForFunction(() => document.querySelector("#admin-apl-list")?.textContent.includes("example.test/newer"));
    const oldResponse = app.page.waitForResponse(r => new URL(r.url()).searchParams.get("q") === "older");
    release(); await oldResponse;
    await app.page.waitForTimeout(50);
    assert.match(await app.page.locator("#admin-apl-list").innerText(), /example.test\/newer/);
    assert.doesNotMatch(await app.page.locator("#admin-apl-list").innerText(), /example.test\/older/);
  });
  test("logged-out bootstrap performs no guild, library or song reads", async t => {
    const app = await openDashboard(undefined, {authenticate: false});
    t.after(() => app.context.close());
    await app.page.waitForTimeout(1200);
    assert.ok(app.requests.some(r => r.url === "/auth/session"));
    assert.equal(app.requests.some(r => r.url.startsWith("/api/")), false);
    assert.equal(await app.page.locator("#discord-login").getAttribute("href"), "/auth/login");
    assert.equal(await app.page.locator("#dashboard").isVisible(), false);
  });
};
