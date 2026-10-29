"use strict";
const {test,before,after}=require("node:test"),assert=require("node:assert/strict");
const {chromium}=require("playwright"),fs=require("node:fs");
const base=process.env.ROUND31_BASE_URL||"http://localhost:18310";
const shots=process.env.ADMIN_BATCH_SHOTS||"/tmp/musicbot-admin-batch-shots";
let browser;
before(async()=>{fs.mkdirSync(shots,{recursive:true});browser=await chromium.launch({headless:true});});
after(async()=>{await browser?.close();});
async function open(t,width=1280,height=1000,setup=()=>{}) {
 const context=await browser.newContext({viewport:{width,height},colorScheme:"dark",locale:"zh-TW",serviceWorkers:"block"});
 t.after(()=>context.close());const page=await context.newPage(),errors=[];
 page.on("pageerror",error=>errors.push(String(error)));
 await setup(page);
 await page.goto(base+"/?demo-queue=filled&demo-lyrics=synced");
 await page.waitForFunction(()=>document.querySelector("#dashboard")?.getClientRects().length||document.querySelector("#discord-login")?.getClientRects().length);
 if(await page.locator("#discord-login").isVisible().catch(()=>false))await page.locator("#discord-login").click();
 await page.waitForFunction(()=>document.querySelectorAll("#queue>li").length===4);
 await page.locator("#nav-admin").click();
 await page.locator("#admin-playback-group").waitFor({state:"visible"});
 return {page,errors};
}
function boolRoutes(page) {
 return page.route("**/api/guilds/*/admin/*",route=>{
  const path=new URL(route.request().url()).pathname;
  if(route.request().method()==="GET"&&(path.endsWith("/lyrics")||path.endsWith("/vote-skip")))return route.fulfill({json:{enabled:true}});
  return route.continue();
 });
}
test("guild switch clears unsaved lyrics and vote drafts even when saved values are equal",async t=>{
 const {page,errors}=await open(t,1280,1000,boolRoutes);
 await page.waitForFunction(()=>!document.querySelector("#admin-loading")?.textContent?.trim());
 await page.waitForFunction(()=>document.querySelector("#admin-lyrics-enabled")?.value==="true");
 await page.locator("#admin-permissions-group > summary").click();
 await page.waitForFunction(()=>document.querySelector("#admin-vote-skip-enabled")?.checked&&!document.querySelector("#admin-vote-skip-enabled")?.disabled);
 assert.equal(await page.locator("#admin-vote-skip-save").isDisabled(),true);
 assert.equal(await page.locator("#admin-lyrics-save").isDisabled(),true);
 await page.locator("#admin-vote-skip-enabled").uncheck();
 await page.locator("#admin-lyrics-enabled").selectOption("false");
 assert.equal(await page.locator("#admin-vote-skip-save").isEnabled(),true);
 assert.equal(await page.locator("#admin-lyrics-save").isEnabled(),true);
 await page.locator("#guild").selectOption("2");
 await page.waitForFunction(()=>document.querySelector("#admin-lyrics-enabled")?.value==="true");
 await page.locator("#admin-permissions-group > summary").click();
 await page.waitForFunction(()=>document.querySelector("#admin-vote-skip-enabled")?.checked&&!document.querySelector("#admin-vote-skip-enabled")?.disabled);
 assert.equal(await page.locator("#admin-vote-skip-save").isDisabled(),true);
 assert.equal(await page.locator("#admin-lyrics-save").isDisabled(),true);
 assert.deepEqual(errors,[]);
});
test("failed lyrics load disables only that save and presents an error",async t=>{
 const {page,errors}=await open(t,1280,1000,page=>page.route("**/admin/lyrics",route=>route.fulfill({status:503,json:{error:"Fixture lyrics unavailable"}})));
 await page.waitForFunction(()=>document.querySelector("#admin-lyrics-status")?.textContent?.includes("Fixture lyrics unavailable"));
 assert.equal(await page.locator("#admin-lyrics-save").isDisabled(),true);
 const channel=page.locator("#admin-notify-channel"),current=await channel.inputValue();
 const values=await channel.locator("option:not(:disabled)").evaluateAll(options=>options.map(option=>option.value));
 await channel.selectOption(values.find(value=>value!==current));
 await page.waitForFunction(()=>!document.querySelector("#admin-notify-save")?.disabled);
 assert.deepEqual(errors,[]);
});
test("live buffer metrics appear only when a source is present",async t=>{
 let present=true;
 const {page,errors}=await open(t,1280,1000,page=>page.route("**/admin/maintenance",route=>route.fulfill({
  json:{audio:{state:present?"playing":"stopped",buffered_ms:present?400:0,capacity_ms:present?1000:0,underrun_frames:present?3:0}}
 })));
 await page.waitForFunction(()=>document.querySelector(".admin-health-summary")?.textContent?.includes("400 ms"));
 present=false;await page.locator("#maintenance-refresh").click();
 await page.waitForFunction(()=>!document.querySelector(".admin-health-summary")?.textContent?.includes(" ms"));
 assert.deepEqual(errors,[]);
});
for(const width of [390,810,1280]) {
 test(`all owner groups remain usable at ${width}px`,async t=>{
  const {page,errors}=await open(t,width,1050);
  assert.equal(await page.locator("#admin-maintenance-group").evaluate(el=>el.open),false);
  for(const name of ["maintenance","apl","permissions"]) {
   await page.locator(`#admin-${name}-group > summary`).click();
  }
  await page.waitForFunction(()=>document.querySelectorAll("#admin-apl-list>li").length>0);
  const dimensions=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
  assert.ok(dimensions.scroll<=dimensions.width+1,JSON.stringify(dimensions));
  await page.screenshot({path:`${shots}/admin-${width}.png`,fullPage:true});
  assert.deepEqual(errors,[]);
 });
}
