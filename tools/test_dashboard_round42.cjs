"use strict";
const {test,before,after}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs/promises");
const {chromium}=require("playwright");
const origin="http://localhost:18310";
let browser;
before(async()=>{browser=await chromium.launch({headless:true,args:["--no-sandbox"]});await fs.mkdir("/tmp/r42-shots",{recursive:true});});
after(async()=>{await browser?.close();});
async function open(t,{width=1440,language="en",theme="light",info,workers="block"}={}){
 const context=await browser.newContext({viewport:{width,height:1000},locale:language,colorScheme:theme,serviceWorkers:workers,isMobile:width===390,hasTouch:width===390});
 t.after(()=>context.close());
 await context.addInitScript(({language,theme})=>{localStorage.setItem("musicbot-language",language);localStorage.setItem("musicbot-theme",theme);},{language,theme});
 const page=await context.newPage(),errors=[];
 page.on("pageerror",e=>errors.push(String(e)));
 await context.route(url=>url.origin!==origin,route=>route.abort());
 if(info)await page.route("**/api/guilds/1/admin/maintenance",async route=>{
   const response=await route.fetch();const data=await response.json();
   await route.fulfill({json:{...data,build_info:info,dashboard_version:info.commit}});
 });
 await page.goto(origin+"/?demo-queue=filled&demo-lyrics=synced");
 await page.waitForFunction(()=>document.querySelector("#dashboard")?.getClientRects().length||document.querySelector("#discord-login")?.getClientRects().length);
 if(await page.locator("#discord-login").isVisible())await page.locator("#discord-login").click();
 await page.locator("#nav-admin").click();
 await page.waitForFunction(()=>document.querySelectorAll("#maintenance-details dt").length>5);
 return {page,errors,context};
}
async function rows(page){return page.locator("#maintenance-details").evaluate(el=>Object.fromEntries([...el.querySelectorAll("dt")].map(dt=>[dt.textContent,dt.nextElementSibling.textContent])));}
for(const width of [390,1440])for(const [language,theme] of [["zh-TW","dark"],["en","light"]]){
 test("maintenance build metadata "+language+" "+theme+" "+width,async t=>{
  const info={commit:"3aeb06fb",time:"2026-10-26T05:00:00+00:00",branch:"feature/round42-real-version"};
  const {page,errors}=await open(t,{width,language,theme,info});
  const data=await rows(page),values=Object.values(data);
  for(const value of Object.values(info))assert.ok(values.includes(value),value);
  assert.ok(values.includes("musicbot-dashboard-r42-real-version"));
  assert.equal(data[language==="en"?"Active service worker version":"目前控制頁面的 service worker 版本"],"unknown");
  assert.equal(await page.locator("html").getAttribute("data-theme"),theme);
  assert.equal(await page.locator("html").getAttribute("lang"),language);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  const overflow=await page.locator("#maintenance-details dd").evaluateAll(els=>els.filter(e=>e.scrollWidth>e.clientWidth+1).map(e=>e.textContent));
  assert.deepEqual(overflow,[]);
  await page.locator("#maintenance-heading").scrollIntoViewIfNeeded();
  await page.screenshot({path:"/tmp/r42-shots/maintenance-"+language+"-"+theme+"-"+width+".png",fullPage:true});
  assert.deepEqual(errors,[]);
 });
}
test("maintenance real API without build arguments shows unknown and refresh works",async t=>{
 const {page,errors}=await open(t);
 const data=await rows(page);
 for(const key of ["Build commit","Built at (UTC)","Build branch"])assert.equal(data[key],"unknown");
 await page.locator("#maintenance-refresh").click();
 await page.waitForFunction(()=>!document.querySelector("#maintenance-refresh").disabled);
 assert.equal((await rows(page))["Build commit"],"unknown");
 assert.deepEqual(errors,[]);
});
test("maintenance reports the actual controlling service worker version",async t=>{
 const {page,errors}=await open(t,{workers:"allow"});
 await page.evaluate(async()=>{await navigator.serviceWorker.ready;if(!navigator.serviceWorker.controller)await new Promise(resolve=>navigator.serviceWorker.addEventListener("controllerchange",resolve,{once:true}));});
 await page.reload();
 await page.locator("#nav-admin").click();
 await page.waitForFunction(()=>[...document.querySelectorAll("#maintenance-details dt")].some(dt=>dt.textContent==="Active service worker version"&&dt.nextElementSibling.textContent==="musicbot-dashboard-r42-real-version"));
 assert.equal((await rows(page))["Frontend service worker version"],"musicbot-dashboard-r42-real-version");
 assert.deepEqual(errors,[]);
});
