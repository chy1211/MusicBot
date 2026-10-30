"use strict";
const {test,before,after}=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs");
const {chromium}=require("playwright");
const base=process.env.ROUND31_BASE_URL||"http://localhost:18310";
const shots=process.env.ROUND9_SHOTS||"/tmp/musicbot-round9-shots";
let browser;
before(async()=>{fs.mkdirSync(shots,{recursive:true});browser=await chromium.launch({headless:true});});
after(async()=>{await browser?.close();});
async function open(t,width=1280,height=900,setup=()=>{}){
 const context=await browser.newContext({viewport:{width,height},locale:"zh-TW",colorScheme:"dark",isMobile:width<900,hasTouch:width<900,serviceWorkers:"block"});
 t.after(()=>context.close());const page=await context.newPage(),errors=[];
 page.on("pageerror",error=>errors.push(String(error)));
 await page.addInitScript(()=>{
  const worker=new EventTarget();worker.controller={scriptURL:location.origin+"/sw.js",postMessage(){}};
  worker.register=async()=>({update:async()=>{}});
  Object.defineProperty(navigator,"serviceWorker",{configurable:true,value:worker});window.__worker=worker;
 });
 await setup(page);
 await page.goto(base+"/?demo-queue=filled&demo-lyrics=synced");
 await page.waitForFunction(()=>document.querySelector("#dashboard")?.getClientRects().length||document.querySelector("#discord-login")?.getClientRects().length);
 if(await page.locator("#discord-login").isVisible().catch(()=>false))await page.locator("#discord-login").click();
 await page.waitForFunction(()=>document.querySelectorAll("#queue>li").length===4);
 return {context,page,errors};
}
test("admin section actions expand locally without changing the hash route",async t=>{
 const {page,errors}=await open(t);
 await page.locator("#nav-admin").click();
 await page.locator(".admin-jump-links button").first().waitFor();
 const url=page.url();assert.ok(url.endsWith("#/admin"));
 for(const id of ["admin-apl-group","admin-permissions-group","admin-maintenance-group"]){
  await page.locator(`.admin-jump-links button[aria-controls="${id}"]`).click();
  assert.equal(await page.locator(`#${id}`).evaluate(el=>el.open),true);
  assert.equal(page.url(),url);
 }
 assert.deepEqual(errors,[]);
});
test("requester and expandable audience share the now-playing card",async t=>{
 const {page,errors}=await open(t);
 assert.equal(await page.locator(".listening-stage #listeners-list").count(),1);
 assert.equal(await page.locator("section.card.listeners").count(),0);
 assert.equal(await page.locator("#listeners-list .listener").count(),8);
 await page.locator("#listeners-list button").click();
 assert.ok(await page.locator("#listeners-list .listener").count()>8);
 assert.equal(await page.locator(".stage-request .listener img").count(),1);
 assert.deepEqual(errors,[]);
});
for(const [width,height] of [[390,844],[844,390],[768,1024]]){
 test(`touch layout and update button are reachable at ${width}x${height}`,async t=>{
  const {page,errors}=await open(t,width,height);
  await page.evaluate(()=>{
   document.documentElement.style.setProperty("--safe-top","24px");
   document.documentElement.style.setProperty("--safe-bottom","20px");
   window.__worker.dispatchEvent(new Event("controllerchange"));
  });
  await page.locator("#pwa-refresh").waitFor({state:"visible"});
  const m=await page.locator("#pwa-refresh").evaluate(el=>{
   const r=el.getBoundingClientRect(),top=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
   return {reachable:el===top||el.contains(top),top:r.top,bottom:r.bottom,height:innerHeight,scroll:document.documentElement.scrollWidth,width:innerWidth,sidebar:getComputedStyle(document.querySelector(".sidebar")).position};
  });
  assert.ok(m.reachable&&m.top>=24&&m.bottom<=m.height,JSON.stringify(m));
  assert.ok(m.scroll<=m.width+1,JSON.stringify(m));
  if(height<560)assert.notEqual(m.sidebar,"fixed");
  await page.screenshot({path:`${shots}/update-${width}x${height}.png`});
  await Promise.all([page.waitForEvent("load"),page.locator("#pwa-refresh").click()]);
  assert.deepEqual(errors,[]);
 });
}
test("health polling is visible-route only and cannot overlap a pending sample",async t=>{
 let count=0,release,block=false;
 const {page,errors}=await open(t,1280,900,async page=>{
  await page.clock.install();
  await page.route("**/admin/maintenance",async route=>{
   count++;if(block)await new Promise(resolve=>release=resolve);
   await route.fulfill({json:{audio:{state:"playing",capacity_ms:1000,buffered_ms:count*20,underrun_frames:0}}});
  });
 });
 await page.locator("#nav-admin").click();
 await page.locator("#admin-health-updated").waitFor();
 const old=count;block=true;await page.clock.fastForward(10000);
 await page.waitForFunction(()=>document.querySelector("#maintenance-refresh")?.disabled);
 assert.equal(count,old+1);
 await page.clock.fastForward(30000);assert.equal(count,old+1);
 block=false;release();
 await page.waitForFunction(()=>!document.querySelector("#maintenance-refresh")?.disabled);
 await page.locator("#nav-play").click();const stopped=count;
 await page.clock.fastForward(30000);assert.equal(count,stopped);
 await page.locator("#nav-admin").click();
 await page.waitForFunction(()=>document.querySelector("#admin-health-updated")?.textContent?.trim());
 const hiddenAt=count;
 await page.evaluate(()=>Object.defineProperty(document,"hidden",{configurable:true,value:true}));
 await page.clock.fastForward(20000);assert.equal(count,hiddenAt);
 assert.deepEqual(errors,[]);
});
