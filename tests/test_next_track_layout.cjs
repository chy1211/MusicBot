"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const component = fs.readFileSync(path.join(root, "frontend/src/components/NextTrack.vue"), "utf8");
const componentCss = component.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1];
const styleFiles = [
  "foundation.css",
  "dashboard-layout.css",
  "mobile-player.css",
  "dashboard-controls.css",
  "compact-playlist.css",
  "mobile-refinements.css",
  "r24-layout.css"
];
const css = styleFiles.map(name =>
  fs.readFileSync(path.join(root, "frontend/src/styles", name), "utf8")
).join("\n") + "\n" + componentCss;
const longTitle = "溫蒂漫步 Wendy Wander – 明白我的心 Angel Angel (Official Music Video)";
const artist = "溫蒂漫步 Wendy Wander";
const escapeHtml = text => text.replace(/[&<>"]/g, ch => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"
})[ch]);

function fixture(title) {
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
  <body><main><div id="play-view"><section class="card next-track-card" aria-label="下一首">
  <h2>下一首 <small>（即將播放）</small></h2>
  <div class="next-track-entry">
   <div class="next-track-row">
    <img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E" alt="">
    <div class="next-track-text"><strong>${escapeHtml(title)}</strong><small class="next-track-artist">${artist}</small></div>
   </div>
   <div class="next-track-footer">
    <small class="queue-requester next-track-requester"><span>點播：</span><img alt="" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E"><span>羿</span></small>
    <div class="next-track-actions"><time>5:26</time><button aria-label="往下移動">↓</button><button class="next-track-remove" aria-label="移除">×</button></div>
   </div>
  </div></section></div></main></body></html>`;
}

test("next card retains exactly one queue item and existing move/remove operations", () => {
  assert.match(component, /snapshot\?\.queue\?\.\[0\]/);
  assert.doesNotMatch(component, /v-for/);
  assert.match(component, /next\.title/);
  assert.match(component, /<small v-if="artist" class="next-track-artist">\{\{artist\}\}<\/small>/);
  assert.match(component, /run\('queue\/move',\{from:next\.position,to:2,revision:dashboard\.snapshot\?\.revision\}\)/);
  assert.match(component, /run\('queue\/'\+next\.position,\{revision:dashboard\.snapshot\?\.revision\},'DELETE'\)/);
  assert.match(component, /:disabled="!usable\|\|\(dashboard\.snapshot\?\.queue\.length\|\|0\)<2"/);
  assert.match(componentCss, /overflow-wrap:anywhere/);
  assert.match(componentCss, /white-space:normal/);
  assert.doesNotMatch(componentCss, /text-overflow:ellipsis|line-clamp|max-height/);
});

test("long titles grow naturally and do not collide with footer at phone and tablet widths", async t => {
  const browser = await chromium.launch({ headless: true });
  t.after(() => browser.close());
  for (const width of [320, 375, 390, 430, 760]) {
    const page = await browser.newPage({viewport: {width, height: 800}, isMobile: true, hasTouch: true});
    try {
      for (const title of [longTitle, longTitle.repeat(3), "無空白".repeat(100), "小幸運"]) {
        await page.setContent(fixture(title));
        await page.addStyleTag({content: css});
        const result = await page.evaluate(() => {
          const rect = selector => {
            const r = document.querySelector(selector).getBoundingClientRect();
            return {top:r.top, bottom:r.bottom, left:r.left, right:r.right, height:r.height};
          };
          return {
            titleText: document.querySelector(".next-track-text strong").textContent,
            title: rect(".next-track-text strong"),
            artist: rect(".next-track-artist"),
            row: rect(".next-track-row"),
            footer: rect(".next-track-footer"),
            card: rect(".next-track-card"),
            actions: rect(".next-track-actions"),
            requester: rect(".next-track-requester"),
            controls: Array.from(document.querySelectorAll(".next-track-actions button"), b => {
              const r = b.getBoundingClientRect(); return {width:r.width, height:r.height, right:r.right};
            }),
            documentWidth: document.documentElement.clientWidth,
            scrollWidth: document.documentElement.scrollWidth,
          };
        });
        assert.equal(result.titleText, title, `title must be complete at ${width}px`);
        assert.ok(result.artist.top >= result.title.bottom - 1, `artist follows title at ${width}px`);
        assert.ok(result.footer.top >= result.row.bottom, `footer follows song at ${width}px`);
        assert.ok(result.card.bottom >= result.footer.bottom, `card grows to fit content at ${width}px`);
        assert.ok(result.actions.left >= result.requester.right - 1 || result.actions.top >= result.requester.bottom - 1,
          `requester and controls must not overlap at ${width}px`);
        assert.ok(result.controls.every(b => b.width >= 44 && b.height >= 44 && b.right <= result.card.right),
          `touch controls must remain accessible at ${width}px`);
        assert.ok(result.scrollWidth <= result.documentWidth, `no horizontal page overflow at ${width}px`);
      }
    } finally {
      await page.close();
    }
  }
});
