"use strict";
// Real browser regressions against a network-isolated, credential-free demo only.
const {chromium}=require("playwright"),assert=require("node:assert/strict"),fs=require("node:fs/promises"),path=require("node:path");
const args=process.argv.slice(2),opt=(k,d)=>args.includes(k)?args[args.indexOf(k)+1]:d;
const origin=new URL(opt("--url","http://localhost:18260")),out=opt("--output","/tmp/musicbot-r26-shots");
assert.equal(origin.hostname,"localhost");assert.equal(origin.protocol,"http:");
(async()=>{
 await fs.mkdir(out,{recursive:true});const browser=await chromium.launch({args:["--no-sandbox"]}),results=[];
 try{for(const mobile of [true,false]){
  const device=mobile?"iphone":"desktop",ctx=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1000},isMobile:mobile,hasTouch:mobile,locale:"zh-TW"});
  await ctx.route(u=>u.origin!==origin.origin,r=>r.abort());
  await ctx.addInitScript(()=>localStorage.setItem("musicbot-language","zh-TW"));
  const p=await ctx.newPage(),errors=[];p.on("pageerror",e=>errors.push(e.message));
  const click=async selector=>mobile?p.locator(selector).tap():p.locator(selector).click();
  await p.goto(new URL("/?demo-queue=filled&demo-lyrics=synced",origin).href);
  await p.waitForTimeout(500);if(await p.locator("#discord-login").isVisible())await click("#discord-login");
  await p.waitForSelector("#lyrics-toggle:enabled");
  // Actual short timed lines advance solely from playback's shared clock.
  await p.route("**/api/guilds/1/lyrics",async route=>{
    const response=await route.fetch();assert.equal(response.status(),200,"demo lyrics must be available, not rate limited");const data=await response.json();
    const current=await p.evaluate(()=>localProgress());
    data.lines=Array.from({length:45},(_,i)=>({time:current-12+i*.75,text:"\u540c\u6b65\u6b4c\u8a5e \u00b7 "+(i+1)}));data.offset=0;data.offset_source="matched";
    await route.fulfill({response,json:data});
  });
  await p.route("**/api/guilds/1/lyrics/offset",async route=>{
    if(route.request().method()==="POST")return route.continue();
    await route.fulfill({json:{offset:0,offset_source:"matched"}});
  });
  await click("#lyrics-toggle");await p.waitForSelector("#lyrics-content .active");
  const first=await p.locator("#lyrics-content .active").textContent();
  await p.waitForFunction(initial=>document.querySelector("#lyrics-content .active")?.textContent!==initial,first);
  await p.waitForTimeout(450);
  const geometry=await p.locator("#lyrics-content").evaluate(e=>{
    const r=e.getBoundingClientRect(),a=e.querySelector(".active"),line=a.getBoundingClientRect();
    return {text:a.textContent,error:Math.abs(line.y+line.height/2-r.y-r.height/2),scroll:e.scrollTop,height:r.height,current:a.getAttribute("aria-current")};
  });
  assert.ok(geometry.error<8,JSON.stringify(geometry));assert.ok(geometry.scroll>0);assert.equal(geometry.current,"true");
  assert.equal(await p.locator("#lyrics-offset").count(),0);
  assert.equal(await p.locator("#lyrics-timing-menu").isVisible(),false);
  await p.screenshot({path:path.join(out,device+"-lyrics-collapsed.png")});
  await click("#lyrics-timing-toggle");assert.equal(await p.locator("#lyrics-timing-toggle").getAttribute("aria-expanded"),"true");
  const timingResponses=[];p.on("response",response=>{if(response.url().endsWith("/lyrics/offset")&&response.request().method()==="POST")timingResponses.push(response.status());});
  for(const id of ["lyrics-minus","lyrics-plus","lyrics-sync","lyrics-sync","lyrics-reset"]){
    await p.waitForSelector("#"+id+":enabled");await click("#"+id);
    await p.waitForSelector("#"+id+":enabled");assert.equal(await p.locator("#lyrics-timing-menu").isVisible(),true,id);
  }
  assert.deepEqual(timingResponses,[200,200,200,200]);
  await p.waitForTimeout(450);await p.waitForSelector("#lyrics-content .active");
  await p.screenshot({path:path.join(out,device+"-lyrics-expanded.png")});
  const targets=await p.locator("#lyrics-timing-menu button").evaluateAll(es=>es.map(e=>{const r=e.getBoundingClientRect();return {w:r.width,h:r.height};}));
  assert.ok(targets.every(r=>r.w>=44&&r.h>=44));
  await click("#lyrics-timing-toggle");assert.equal(await p.locator("#lyrics-timing-menu").isVisible(),false);
  await click("#lyrics-timing-toggle");await (mobile?p.touchscreen.tap(5,180):p.mouse.click(5,180));assert.equal(await p.locator("#lyrics-timing-menu").isVisible(),false);
  await click("#lyrics-timing-toggle");await p.keyboard.press("Escape");assert.equal(await p.locator("#lyrics-timing-menu").isVisible(),false);
  await click("#lyrics-timing-toggle");await click("#lyrics-close");await click("#lyrics-toggle");assert.equal(await p.locator("#lyrics-timing-menu").isVisible(),false);
  await click("#bar-title");assert.equal(await p.locator("#lyrics-panel").isVisible(),false);
  await click("#bar-title");assert.equal(await p.locator("#lyrics-panel").isVisible(),true);
  await p.setViewportSize(mobile?{width:412,height:915}:{width:1280,height:900});await p.waitForTimeout(500);
  await p.setViewportSize(mobile?{width:390,height:844}:{width:1440,height:1000});await p.waitForTimeout(300);
  await p.evaluate(()=>{ document.dispatchEvent(new Event("visibilitychange"));window.dispatchEvent(new Event("pageshow")); });
  await p.waitForTimeout(300);
  await click("#lyrics-close");
  await click("#nav-popular");await p.waitForSelector("#popular-list li button");
  const button=p.locator("#popular-list li").first().locator("button").first();
  assert.match(await button.textContent(),/Add to Queue|\u52a0\u5165\u4f47\u5217/);
  await p.screenshot({path:path.join(out,device+"-popular.png")});
  const getState=()=>p.evaluate(async()=>await (await fetch("/api/guilds/1/state",{headers:{"X-MusicBot-Dashboard":"1"}})).json());
  const before=await getState(),posts=[];
  p.on("request",r=>{if(r.method()==="POST")posts.push({url:new URL(r.url()).pathname,body:r.postDataJSON()});});
  let release;const gate=new Promise(resolve=>release=resolve);
  await p.route("**/api/guilds/1/resolve",async route=>{await gate;await route.continue();});
  await (mobile?button.tap():button.click());
  assert.equal(await button.getAttribute("aria-busy"),"true");assert.equal(await button.isDisabled(),true);
  release();await p.waitForFunction(()=>document.querySelector("#popular-list li button")?.getAttribute("aria-busy")==="false");
  const after=await getState();assert.equal(after.queue.length,before.queue.length+1);
  assert.equal(posts.filter(r=>r.url.endsWith("/resolve")).length,1);assert.equal(posts.filter(r=>r.url.endsWith("/play")).length,1);
  const resolved=posts.find(r=>r.url.endsWith("/play"));assert.ok(resolved.body.preview_id);assert.equal(await p.locator("#preview-panel").isVisible(),false);
  assert.equal(await p.locator("#queue > li").count(),after.queue.length);
  assert.ok((await p.locator("#notice").textContent()).trim());
  // Exercise real resolve failure, then real queue rejection through the standard act path.
  await p.unroute("**/api/guilds/1/resolve");
  await p.route("**/api/guilds/1/resolve",r=>r.fulfill({status:502,json:{error:"Resolve failed"}}));
  await (mobile?button.tap():button.click());await p.waitForFunction(()=>document.querySelector("#notice").textContent.includes("Resolve failed"));assert.equal(await button.isDisabled(),false);
  await p.unroute("**/api/guilds/1/resolve");
  await p.route("**/api/guilds/1/play",r=>r.fulfill({status:409,json:{error:"Queue rejected"}}));
  await (mobile?button.tap():button.click());await p.waitForFunction(()=>document.querySelector("#notice").textContent.includes("Queue rejected"));
  await p.waitForFunction(()=>document.querySelector("#popular-list li button")?.getAttribute("aria-busy")==="false");assert.equal(await button.isDisabled(),false);
  assert.deepEqual(errors,[]);
  results.push({device,status:"PASS",geometry,targets,queueBefore:before.queue.length,queueAfter:after.queue.length,scenarios:9});
  console.log(JSON.stringify(results.at(-1)));await ctx.close();
 }
 await fs.writeFile(path.join(out,"round26-results.json"),JSON.stringify(results,null,2));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});