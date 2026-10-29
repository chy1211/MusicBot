"use strict";
const {test, before, after} = require("node:test");
const assert = require("node:assert/strict");
const {chromium} = require("playwright");
const fs = require("node:fs");
const base = process.env.ROUND31_BASE_URL || "http://localhost:18310";
const shots = process.env.PATCH345_SHOTS || "/tmp/musicbot-patch345-shots";
let browser;
before(async () => { fs.mkdirSync(shots, {recursive:true}); browser=await chromium.launch({headless:true}); });
after(async () => { await browser?.close(); });

async function open(viewport, locale="zh-TW") {
  const context=await browser.newContext({viewport, locale, colorScheme:"dark", serviceWorkers:"block"});
  const page=await context.newPage();
  await page.addInitScript(() => {
    window.__streams=[];
    window.EventSource=class extends EventTarget {
      constructor() { super(); window.__streams.push(this); }
      close() {}
    };
  });
  await page.goto(base+"/?demo-queue=filled&demo-lyrics=synced");
  await page.waitForFunction(()=>document.querySelector("#dashboard")?.getClientRects().length ||
    document.querySelector("#discord-login")?.getClientRects().length);
  if(await page.locator("#discord-login").isVisible().catch(()=>false)) await page.locator("#discord-login").click();
  await page.waitForFunction(()=>document.querySelectorAll("#queue>li").length===4);
  await page.waitForFunction(()=>window.__streams.length>0);
  return {context,page};
}

async function state(page,value) {
  await page.evaluate(value=>window.__streams.at(-1).dispatchEvent(
    new MessageEvent("snapshot",{data:JSON.stringify({state:value})})),value);
}

async function separated(page) {
  await page.waitForFunction(()=>{
    const side=document.querySelector(".sidebar"),bar=document.querySelector("#playback-bar");
    return getComputedStyle(side).position!=="fixed" || side.getBoundingClientRect().bottom+12<=bar.getBoundingClientRect().top;
  },null,{timeout:3000}).catch(()=>{});
  const metrics=await page.evaluate(()=>({
    side:document.querySelector(".sidebar").getBoundingClientRect().toJSON(),
    bar:document.querySelector("#playback-bar").getBoundingClientRect().toJSON(),
    width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
    fixed:getComputedStyle(document.querySelector(".sidebar")).position==="fixed",
    bottom:getComputedStyle(document.querySelector(".sidebar")).bottom,
    measured:document.documentElement.style.getPropertyValue("--dock-player-height")
  }));
  assert.ok(!metrics.fixed || metrics.side.bottom+12<=metrics.bar.top,JSON.stringify(metrics));
  assert.ok(metrics.scroll<=metrics.width+1,JSON.stringify(metrics));
}

for(const [width,height] of [[768,1024],[810,1080],[834,1112],[1024,768],[1080,810],[1112,834],[1440,900],[390,844]]) {
  test(`sidebar clears live playback bar at ${width}x${height}`, async t=>{
    const {context,page}=await open({width,height}); t.after(()=>context.close());
    await separated(page);
    await page.screenshot({path:`${shots}/${width}x${height}.png`});
    if(width>760) {
      await page.locator(".bar-center").evaluate(el=>{
        const extra=document.createElement("div");
        extra.style.height="48px";
        el.append(extra);
      });
      await separated(page);
    }
  });
}

test("next track remains visible through SSE preparing, playing and stop", async t=>{
  const {context,page}=await open({width:810,height:1080}); t.after(()=>context.close());
  const response=await page.request.get(base+"/api/guilds/1/state",{
    headers:{"X-MusicBot-Dashboard":"1","Origin":base}
  });
  assert.equal(response.status(),200);
  const live=await response.json();
  const next={...live.queue[0],title:"Preparing fixture track",seekable:false,track_token:""};
  await state(page,{...live,status:"preparing",current:next,progress:0,queue:live.queue.slice(1)});
  await page.waitForFunction(()=>document.querySelector("#stage-title")?.textContent==="Preparing fixture track");
  assert.match(await page.locator(".listening-stage .eyebrow").innerText(),/正在準備播放下一首歌/);
  assert.match(await page.locator("#bar-status").innerText(),/正在準備播放下一首歌/);
  assert.equal(await page.locator("#toggle").isDisabled(),true);
  assert.equal(await page.locator("#progress").isDisabled(),true);
  assert.equal(await page.locator(".stage-wave").evaluate(el=>el.classList.contains("is-playing")),false);
  await page.waitForTimeout(1100);
  assert.equal(await page.locator("#elapsed").innerText(),"0:00");
  await separated(page);
  await page.screenshot({path:`${shots}/preparing-tablet.png`});
  await state(page,{...live,status:"playing",current:{...next,seekable:true,track_token:"fixture"},progress:2});
  await page.waitForFunction(()=>document.querySelector(".stage-wave")?.classList.contains("is-playing"));
  assert.equal(await page.locator("#toggle").isEnabled(),true);
  await state(page,{...live,status:"stopped",current:null,progress:0});
  await page.waitForFunction(()=>!document.querySelector(".listening-stage"));
  assert.doesNotMatch(await page.locator("#bar-status").innerText(),/正在準備/);
});
