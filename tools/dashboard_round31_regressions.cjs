"use strict";
module.exports = ({test, assert, openDashboard, baseURL}) => {
  async function startDrag(app) {
    await app.page.locator("#queue").scrollIntoViewIfNeeded();
    const rows = app.page.locator("#queue > li");
    const start = await rows.nth(0).locator(".drag-handle").boundingBox();
    const target = await rows.nth(2).boundingBox();
    assert.ok(start && target);
    await app.page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
    await app.page.mouse.down();
    await app.page.mouse.move(start.x + start.width / 2, start.y + start.height / 2 + 12, {steps: 3});
    await app.page.waitForFunction(() => document.body.classList.contains("queue-dragging"));
    return {rows, target};
  }
  for (const reason of ["Escape", "blur", "pointercancel", "filter"]) {
    test("queue drag cancels on " + reason + " without mutating the queue", async t => {
      const app = await openDashboard(); t.after(() => app.context.close());
      const before = await app.page.locator("#queue > li .song p").allTextContents();
      await startDrag(app);
      if (reason === "Escape") await app.page.keyboard.press("Escape");
      else if (reason === "blur") await app.page.evaluate(() => window.dispatchEvent(new Event("blur")));
      else if (reason === "filter") await app.page.locator("#queue-search").fill("no-match");
      else await app.page.locator("#queue > li .drag-handle").first().dispatchEvent("pointercancel", {pointerId: 1});
      await app.page.mouse.up();
      assert.equal(await app.page.locator(".queue-dragging").count(), 0);
      assert.equal(app.requests.filter(r => r.url.endsWith("/queue/move")).length, 0);
      if (reason !== "filter") assert.deepEqual(await app.page.locator("#queue > li .song p").allTextContents(), before);
      assert.deepEqual(app.errors, []);
    });
  }
  test("queue drag survives unchanged SSE snapshots and posts its captured revision", async t => {
    const app = await openDashboard(); t.after(() => app.context.close());
    const revision = await (await app.page.request.get(baseURL + "/api/guilds/1/state", {headers: {"X-MusicBot-Dashboard": "1"}})).json();
    const before = await app.page.locator("#queue > li .song p").allTextContents();
    const {target} = await startDrag(app);
    await app.page.waitForTimeout(1600);
    assert.equal(await app.page.locator("body.queue-dragging").count(), 1);
    const response = app.page.waitForResponse(r => r.url().endsWith("/queue/move") && r.request().method() === "POST");
    await app.page.mouse.move(target.x + target.width / 2, target.y + target.height / 2, {steps: 8});
    await app.page.mouse.up();
    const moved = await response;
    assert.equal(moved.status(), 200);
    assert.deepEqual(moved.request().postDataJSON(), {from: 1, to: 3, revision: revision.revision});
    await app.page.waitForFunction(title => document.querySelector("#queue > li .song p")?.textContent !== title, before[0]);
    assert.notDeepEqual(await app.page.locator("#queue > li .song p").allTextContents(), before);
  });
  test("lyrics timing menu and armed sync survive same-track snapshots", async t => {
    const app = await openDashboard(); t.after(() => app.context.close());
    await app.page.locator("#lyrics-toggle").click();
    await app.page.locator("#lyrics-content > p").first().waitFor({state: "visible"});
    const reads = () => app.requests.filter(r => /\/lyrics$/.test(r.url)).length;
    const count = reads();
    await app.page.locator("#lyrics-timing-toggle").click();
    await app.page.locator("#lyrics-sync").click();
    await app.page.waitForTimeout(1600);
    assert.equal(await app.page.locator("#lyrics-timing-menu").isVisible(), true);
    assert.equal(await app.page.locator("#lyrics-sync-prompt").isVisible(), true);
    assert.equal(reads(), count);
    assert.deepEqual(app.errors, []);
  });
};
