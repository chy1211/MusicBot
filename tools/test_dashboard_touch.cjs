"use strict";
// Standalone browser suite (NOT part of node --test tests/*.cjs).
// Install outside the repo: npm install --prefix /tmp/musicbot-webtest-touch playwright@1.58.2
// Then: /tmp/musicbot-webtest-touch/node_modules/.bin/playwright install chromium
// Run a credential-free tools.dashboard_demo with --fake-login owner first.
// NODE_PATH=/tmp/musicbot-webtest-touch/node_modules node tools/test_dashboard_touch.cjs --url http://localhost:18091 --output /tmp/musicbot-r21-shots --phase after
const {chromium}=require("playwright");
const assert=require("node:assert/strict");
const fs=require("node:fs/promises"),path=require("node:path");
const args=process.argv.slice(2), option=(name,fallback)=>args.includes(name)?args[args.indexOf(name)+1]:fallback;
const origin=new URL(option("--url","http://localhost:18091"));
assert.equal(origin.hostname,"localhost","Only an isolated localhost demo is allowed");
assert.equal(origin.protocol,"http:");
assert.ok(!origin.username&&!origin.password);
const output=path.resolve(option("--output","/tmp/musicbot-r21-shots")),phase=option("--phase","after");
assert.match(phase,/^[a-z0-9-]+$/);
const core=args.includes("--core"),results=[];
const devices=[{name:"iphone",width:390,height:844},{name:"android",width:412,height:915}];
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function rect(p,selector){return p.locator(selector).first().boundingBox();}
async function tap(p,selector){await p.locator(selector).first().tap();}
async function touch(cdp,type,x,y){
  await cdp.send("Input.dispatchTouchEvent",{type,touchPoints:type==="touchEnd"||type==="touchCancel"?[]:[{x,y,id:1,radiusX:3,radiusY:3,force:1}]});
}
async function swipe(cdp,a,b,hold=0){
  await touch(cdp,"touchStart",a.x,a.y);await sleep(hold);
  for(let i=1;i<=12;i++){await touch(cdp,"touchMove",a.x+(b.x-a.x)*i/12,a.y+(b.y-a.y)*i/12);await sleep(20);}
  await touch(cdp,"touchEnd");
}
async function state(p){return p.evaluate(async()=>{const r=await fetch("/api/guilds/1/state",{headers:{"X-MusicBot-Dashboard":"1"}});if(!r.ok)throw Error(await r.text());return r.json();});}
async function ready(p){
  await p.goto(new URL("/?demo-queue=filled&demo-lyrics=synced",origin).href);
  await p.waitForFunction(()=>!document.querySelector("#dashboard").hidden||!document.querySelector("#discord-login").hidden);
  if(await p.locator("#discord-login").isVisible()) await tap(p,"#discord-login");
  await p.waitForFunction(()=>!document.querySelector("#progress").disabled&&document.querySelector("#queue > li"));
  await p.waitForFunction(()=>window.touchSnapshots?.length>0);
  await p.evaluate(async()=>{
    const headers={"X-MusicBot-Dashboard":"1","Content-Type":"application/json"};
    const current=await (await fetch("/api/guilds/1/state",{headers})).json();
    const response=await fetch("/api/guilds/1/seek",{method:"POST",headers,body:JSON.stringify({position:37,track_token:current.current.track_token})});
    if(!response.ok)throw Error(await response.text());
  });
  await p.waitForFunction(()=>Math.abs(Number(document.querySelector("#progress").value)-37)<3);
  await p.waitForTimeout(350);
}
async function positionQueue(p){
  await p.locator("#queue").evaluate(e=>window.scrollTo(0,e.getBoundingClientRect().top+scrollY-125));
  await p.waitForTimeout(350);
}
async function screenshot(p,name,device){if(device.name==="iphone")await p.screenshot({path:path.join(output,phase+"-"+name+"-iphone.png")});}
async function audit(p,label){
  const data=await p.evaluate(()=>{
    const entries=[...document.querySelectorAll("button,a[href],input,select,summary,[role=button],[tabindex='0']")].filter(e=>
      e.checkVisibility({checkVisibilityCSS:true,checkOpacity:true})&&!e.closest("[hidden]")&&
      !e.closest("details:not([open]) :not(summary):not(summary *)"));
    return entries.map(e=>{const target=e.matches("input[type=checkbox],input[type=radio]")?e.closest("label")||e.labels?.[0]||e:e;
      const r=target.getBoundingClientRect();return {element:e.id?"#"+e.id:e.tagName.toLowerCase()+(e.className?"."+String(e.className).trim().split(/\s+/).join("."):""),width:+r.width.toFixed(2),height:+r.height.toFixed(2)};})
      .filter(e=>e.width<43.9||e.height<43.9);
  });
  return data.map(e=>({view:label,...e}));
}
(async()=>{
 await fs.mkdir(output,{recursive:true});
 const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
 try{
 for(const device of devices){
  const pointerAudit=[];
  const context=await browser.newContext({viewport:{width:device.width,height:device.height},deviceScaleFactor:3,hasTouch:true,isMobile:true});
  await context.exposeBinding("__touchAudit",(_,event)=>pointerAudit.push(event));
  // Keep real EventSource; record server snapshots and trusted pointer types.
  await context.addInitScript(()=>{
    window.touchSnapshots=[];
    for(const key of Object.keys(localStorage))if(key.startsWith("musicbot-lyrics:"))localStorage.removeItem(key);
    const Native=window.EventSource;
    window.EventSource=class extends Native{constructor(...args){super(...args);this.addEventListener("snapshot",e=>window.touchSnapshots.push(JSON.parse(e.data).state.progress));}};
    document.addEventListener("pointerdown",e=>window.__touchAudit({type:e.pointerType,trusted:e.isTrusted}),true);
  });
  // This demo must never fetch remote artwork, links, or production services.
  await context.route(url=>url.origin!==origin.origin,route=>route.abort());
  const p=await context.newPage(),cdp=await context.newCDPSession(p),requests=[];
  p.on("request",r=>{if(r.method()==="POST"&&r.url().includes("/api/"))requests.push({url:new URL(r.url()).pathname,body:r.postDataJSON()});});
  const run=async(name,fn)=>{
    if(option("--only","")&&option("--only","")!==name)return;
    const row={device:device.name,scenario:name};
    try{await ready(p);requests.length=0;row.evidence=await fn();row.status="PASS";}
    catch(e){row.status="FAIL";row.error=e.message;await screenshot(p,"failure-"+name.replace(/[^a-z0-9-]/g,"-"),device);}
    finally{await touch(cdp,"touchCancel").catch(()=>{});}
    results.push(row);console.log(JSON.stringify(row));
  };
  if(!args.includes("--extras-only")){
  await run("baseline",async()=>{
    await screenshot(p,"home",device);
    assert.deepEqual(await p.evaluate(()=>({touch:navigator.maxTouchPoints>0,dpr:devicePixelRatio,width:innerWidth})),{touch:true,dpr:3,width:device.width});
    return {viewport:device.width+"x"+device.height,deviceScaleFactor:3,hasTouch:true,isMobile:true};
  });
  await run("lyrics-service-unavailable-and-retry",async()=>{
    const endpoint="**/api/guilds/1/lyrics";
    await p.route(endpoint,route=>route.fulfill({status:200,contentType:"application/json",
      body:JSON.stringify({status:"unavailable",title:"Demo",artist:"",lines:[]})}));
    try{
      await tap(p,"#lyrics-toggle");
      await p.waitForFunction(()=>!document.querySelector("#lyrics-retry").hidden&&!document.querySelector("#lyrics-retry").disabled);
      assert.match(await p.locator("#lyrics-status").textContent(),/unavailable|temporar|暫時/i);
      await screenshot(p,"lyrics-unavailable",device);
      await p.unroute(endpoint);
      await tap(p,"#lyrics-retry");
      await p.waitForFunction(()=>document.querySelectorAll("#lyrics-content p").length>0);
      assert.equal(await p.locator("#lyrics-retry").isVisible(),false);
      await screenshot(p,"lyrics-found",device);
      return {temporaryFailure:true,manualRetry:true,lyricLines:await p.locator("#lyrics-content p").count()};
    }finally{await p.unroute(endpoint);}
  });
  await run("queue-long-press",async()=>{
    await positionQueue(p);
    const initial=await state(p),a=await rect(p,"#queue>li:first-child .drag-handle"),b=await rect(p,"#queue>li:nth-child(2)");
    await touch(cdp,"touchStart",a.x+a.width/2,a.y+a.height/2);await sleep(520);
    assert.equal(await p.locator("body").evaluate(e=>e.classList.contains("queue-dragging")),true,"long press should activate");
    await touch(cdp,"touchMove",a.x+a.width/2,b.y+Math.min(b.height/2,50));await sleep(70);
    await screenshot(p,"queue-drag",device);
    await touch(cdp,"touchEnd");
    await p.waitForFunction(()=>!document.body.classList.contains("queue-dragging"));
    await p.waitForTimeout(650);
    const move=requests.filter(r=>r.url.endsWith("/queue/move"));
    assert.equal(move.length,1);assert.deepEqual(move[0].body,{from:1,to:2,revision:initial.revision});
    const next=await state(p);assert.equal(next.queue[0].url,initial.queue[1].url);assert.equal(next.queue[1].url,initial.queue[0].url);
    assert.deepEqual(await p.locator("#queue>li").evaluateAll(es=>es.map(e=>e.querySelector(".song-title")?.textContent)),next.queue.map(e=>e.title));
    return move[0];
  });
  await run("queue-tap-and-early-swipe",async()=>{
    await positionQueue(p);const before=await state(p);
    await tap(p,"#queue>li:first-child .drag-handle");
    const a=await rect(p,"#queue>li:first-child .drag-handle");
    await swipe(cdp,{x:a.x+22,y:a.y+22},{x:a.x+23,y:a.y+2},50);
    await sleep(500);
    assert.equal(requests.filter(r=>r.url.endsWith("/queue/move")).length,0);
    assert.deepEqual((await state(p)).queue.map(e=>e.url),before.queue.map(e=>e.url));
    assert.equal(await p.locator("body").evaluate(e=>e.classList.contains("queue-dragging")),false);
    return {moveRequests:0};
  });
  await run("queue-scroll",async()=>{
    await positionQueue(p);const initial=await p.evaluate(()=>scrollY);
    await swipe(cdp,{x:70,y:470},{x:70,y:240},30);await sleep(350);
    const down=await p.evaluate(()=>scrollY);assert.ok(down>initial+50,"upward swipe must scroll down");
    await swipe(cdp,{x:70,y:240},{x:70,y:470},30);await sleep(350);
    const up=await p.evaluate(()=>scrollY);assert.ok(up<down-50,"downward swipe must scroll up");
    assert.equal(requests.filter(r=>r.url.endsWith("/queue/move")).length,0);
    return {initial,down,up,moveRequests:0};
  });
  await run("seek-middle-sse",async()=>{
    const r=await rect(p,"#progress"),total=(await state(p)).current.duration;
    // Native range thumb has an 8px inset; use a geometry-based independent oracle.
    const x=r.x+8+(r.width-16)*.65,y=r.y+r.height/2;
    const before=await p.evaluate(()=>window.touchSnapshots.length);
    await touch(cdp,"touchStart",r.x+r.width*.3,y);
    await touch(cdp,"touchMove",x,y);await sleep(150);
    const preview=await p.locator("#progress").inputValue();
    assert.ok(Math.abs(Number(preview)-total*.65)<=3,"touch should preview the requested second");
    await p.evaluate(async volume=>{const r=await fetch("/api/guilds/1/volume",{method:"POST",headers:{"X-MusicBot-Dashboard":"1","Content-Type":"application/json"},body:JSON.stringify({volume})});if(!r.ok)throw Error(await r.text());},(await state(p)).volume===36?37:36);
    await p.waitForFunction(n=>window.touchSnapshots.length>n,before,{timeout:10000});
    assert.equal(await p.locator("#progress").inputValue(),preview,"SSE must preserve active preview");
    assert.equal(requests.filter(r=>r.url.endsWith("/seek")).length,0,"no seek before release");
    await touch(cdp,"touchEnd");await sleep(600);
    const seeks=requests.filter(r=>r.url.endsWith("/seek"));assert.equal(seeks.length,1);
    assert.ok(Math.abs(seeks[0].body.position-total*.65)<=3);assert.ok(seeks[0].body.track_token);
    return {position:seeks[0].body.position,expected:total*.65,snapshotsDuringDrag:await p.evaluate(n=>window.touchSnapshots.length-n,before)};
  });
  for(const end of ["left","right"])await run("seek-outside-"+end,async()=>{
    const initial=await state(p),r=await rect(p,"#progress"),y=r.y+r.height/2;
    await touch(cdp,"touchStart",r.x+r.width/2,y);
    await touch(cdp,"touchMove",end==="left"?2:device.width-2,y-65);await sleep(120);
    await touch(cdp,"touchEnd");await sleep(600);
    const seeks=requests.filter(r=>r.url.endsWith("/seek"));
    assert.equal(seeks.length,1,"outside release must commit exactly once");
    assert.equal(seeks[0].body.position,end==="left"?0:initial.current.duration);
    return {position:seeks[0].body.position};
  });
  await run("pwa",async()=>{
    const manifest=await p.evaluate(async()=>await (await fetch(document.querySelector('link[rel=manifest]').href)).json());
    assert.ok(manifest.name);assert.equal(manifest.display,"standalone");assert.equal(manifest.start_url,"/");assert.equal(manifest.scope,"/");
    for(const size of [192,512]){
      const icon=manifest.icons.find(i=>i.sizes===size+"x"+size);assert.ok(icon);
      const data=await p.evaluate(async src=>{const r=await fetch(src);if(!r.ok)throw Error("missing icon");const b=await createImageBitmap(await r.blob());return [b.width,b.height];},icon.src);
      assert.deepEqual(data,[size,size]);
    }
    assert.deepEqual(await p.evaluate(async()=>{const r=await fetch(document.querySelector('link[rel=apple-touch-icon]').href);const b=await createImageBitmap(await r.blob());return [b.width,b.height];}),[180,180]);
    for(const [name,value] of [["apple-mobile-web-app-capable","yes"],["apple-mobile-web-app-status-bar-style","black-translucent"]])
      assert.equal(await p.locator('meta[name="'+name+'"]').getAttribute("content"),value);
    assert.ok(await p.locator('meta[name="apple-mobile-web-app-title"]').getAttribute("content"));
    assert.match(await p.locator('meta[name="viewport"]').getAttribute("content"),/viewport-fit=cover/);
    await p.waitForFunction(()=>!!navigator.serviceWorker.controller);
    const sw=await p.evaluate(async()=>{const r=await navigator.serviceWorker.ready;return {active:r.active.state,scope:new URL(r.scope).pathname};});
    assert.deepEqual(sw,{active:"activated",scope:"/"});
    await context.setOffline(true);
    try{const response=await p.goto(origin.href);assert.equal(response.status(),200);assert.ok(await p.locator("h1").textContent());assert.equal(await p.locator("#dashboard").count(),0,"must load offline page, not shell");}
    finally{await context.setOffline(false);}
    return {display:manifest.display,icons:[192,512,180],serviceWorker:sw.active,offlineStatus:200};
  });

  }
  if(!core){
  await run("tabs-and-pills",async()=>{
    for(const key of ["library","popular","admin","play"]){
      await tap(p,"#nav-"+key);await sleep(450);
      assert.equal(await p.locator("#nav-"+key).getAttribute("aria-pressed"),"true");
      assert.equal(await p.locator(key==="play"?"#play-view":"#"+key+"-panel").isVisible(),true);
      const box=await p.locator(".page-tabs").evaluate(e=>{
        const s=getComputedStyle(e),b=e.querySelector('[aria-pressed=true]'),pseudo=getComputedStyle(e,"::before"),m=new DOMMatrix(pseudo.transform);
        return {x:m.m41,y:m.m42,w:parseFloat(pseudo.width),h:parseFloat(pseudo.height),width:e.clientWidth,height:e.clientHeight,padding:parseFloat(s.paddingLeft),buttonX:b.offsetLeft,buttonW:b.offsetWidth};
      });
      assert.ok(box.x>=box.padding-.5&&box.y>=box.padding-.5&&box.x+box.w<=box.width-box.padding+.5&&box.y+box.h<=box.height-box.padding+.5,JSON.stringify(box));
      assert.ok(Math.abs(box.x-box.buttonX)<2.1&&Math.abs(box.w-box.buttonW)<2.1,JSON.stringify(box));
    }
    await tap(p,"#queue-mine");assert.equal(await p.locator("#queue-mine").getAttribute("aria-pressed"),"true");
    await tap(p,"#queue-all");assert.equal(await p.locator("#queue-all").getAttribute("aria-pressed"),"true");
    await positionQueue(p);await swipe(cdp,{x:70,y:460},{x:70,y:260});await sleep(450);
    assert.equal(await p.locator(".page-tabs").evaluate(e=>e.classList.contains("nav-compact")),true);
    const compact=await p.locator(".page-tabs").evaluate(e=>{const s=getComputedStyle(e);return [...e.querySelectorAll("button:not([hidden])")].map(b=>({height:b.offsetHeight,bottom:b.offsetTop+b.offsetHeight,limit:e.clientHeight-parseFloat(s.paddingBottom)}));});
    assert.ok(compact.every(b=>b.height>=44&&b.bottom<=b.limit),JSON.stringify(compact));
    await tap(p,"#nav-library");assert.equal(await p.locator("#library-panel").isVisible(),true);
    await screenshot(p,"tabs",device);
    return {pages:4,queueFilters:2,compactTouch:true};
  });
  await run("lyrics-center-and-scroll",async()=>{
    await tap(p,"#lyrics-toggle");
    await p.waitForSelector("#lyrics-content .current-line");await sleep(900);
    const geometry=await p.locator("#lyrics-content").evaluate(e=>{
      const r=e.getBoundingClientRect(),line=e.querySelector(".current-line").getBoundingClientRect(),panel=e.closest("#lyrics-panel").getBoundingClientRect();
      return {centerError:Math.abs(line.y+line.height/2-r.y-r.height/2),panelCenterError:Math.abs(panel.x+panel.width/2-innerWidth/2),scroll:e.scrollTop,page:scrollY};
    });
    assert.ok(geometry.centerError<5,JSON.stringify(geometry));assert.ok(geometry.panelCenterError<1);
    await screenshot(p,"lyrics",device);
    const r=await rect(p,"#lyrics-content");
    await swipe(cdp,{x:r.x+r.width-15,y:r.y+r.height-8},{x:r.x+r.width-15,y:r.y+8});
    await sleep(350);
    const scrolled=await p.locator("#lyrics-content").evaluate(e=>({scroll:e.scrollTop,page:scrollY}));
    assert.ok(scrolled.scroll>geometry.scroll+10,JSON.stringify({geometry,scrolled}));
    assert.ok(Math.abs(scrolled.page-geometry.page)<2,"lyrics should not scroll the document");
    await sleep(500);
    assert.ok(await p.locator("#lyrics-content").evaluate((e,top)=>e.scrollTop>=top-2,scrolled.scroll),"manual scroll must not snap back");
    await tap(p,"#lyrics-close");assert.equal(await p.locator("#lyrics-panel").isVisible(),false);
    await tap(p,"#lyrics-toggle");assert.equal(await p.locator("#lyrics-panel").isVisible(),true);
    return {...geometry,manualScroll:scrolled.scroll};
  });
  await run("song-chooser-touch-close",async()=>{
    await tap(p,"#bar-title");assert.equal(await p.locator("#song-choices").isVisible(),true);
    assert.ok(await p.locator("#source-link").getAttribute("href"));
    assert.ok(await p.locator("#song-spotify").getAttribute("href"));
    await screenshot(p,"chooser",device);
    await tap(p,"#bar-title");assert.equal(await p.locator("#song-choices").isVisible(),false);
    await tap(p,"#bar-title");await p.touchscreen.tap(8,300);
    assert.equal(await p.locator("#song-choices").isVisible(),false);
    await tap(p,"#lyrics-toggle");await tap(p,"#bar-title");
    assert.equal(await p.locator("#lyrics-panel").isVisible(),false);
    await p.touchscreen.tap(8,300);assert.equal(await p.locator("#lyrics-panel").isVisible(),true);
    return {closeByTitle:true,closeByOutsideTouch:true,lyricsRestored:true};
  });
  await run("targets-44px",async()=>{
    const bad=[];
    bad.push(...await audit(p,"play"));
    await positionQueue(p);await screenshot(p,"queue",device);await swipe(cdp,{x:70,y:460},{x:70,y:260});await sleep(450);
    bad.push(...await audit(p,"compact"));
    await tap(p,"#bar-title");bad.push(...await audit(p,"chooser"));await tap(p,"#bar-title");
    await tap(p,"#lyrics-toggle");await p.waitForSelector("#lyrics-content .current-line");bad.push(...await audit(p,"lyrics"));
    await tap(p,"#lyrics-close");
    for(const key of ["library","popular","admin"]){await tap(p,"#nav-"+key);await sleep(450);bad.push(...await audit(p,key));await screenshot(p,key,device);}
    const unique=[...new Map(bad.map(e=>[JSON.stringify(e),e])).values()];
    await fs.writeFile(path.join(output,phase+"-targets-"+device.name+".json"),JSON.stringify(unique,null,2)+"\n");
    assert.deepEqual(unique,[],"Touch targets below 44 CSS px: "+JSON.stringify(unique));
    return {minimum:"44x44 CSS px",views:7,nonconforming:[]};
  });
  await run("no-horizontal-scroll",async()=>{
    const widths=[];
    for(const key of ["play","library","popular","admin"]){
      await tap(p,"#nav-"+key);await sleep(200);
      const w=await p.evaluate(()=>({viewport:innerWidth,root:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
      widths.push({view:key,...w});assert.ok(w.root<=w.viewport&&w.body<=w.viewport,JSON.stringify(widths));
    }
    return widths;
  });
  await run("safe-area-playback",async()=>{
    await cdp.send("Emulation.setSafeAreaInsetsOverride",{insets:{top:47,bottom:34,left:24,right:24}});
    try{
      await sleep(450);
      const evidence=await p.evaluate(()=>{
        const probe=document.createElement("div");probe.style.cssText="position:fixed;height:env(safe-area-inset-bottom);width:env(safe-area-inset-left)";document.body.append(probe);
        const applied=[probe.offsetWidth,probe.offsetHeight];probe.remove();
        const bar=document.querySelector("#playback-bar").getBoundingClientRect(),nav=document.querySelector(".page-tabs").getBoundingClientRect();
        const controls=[...document.querySelectorAll("#playback-bar button,#playback-bar input")].filter(e=>e.checkVisibility({checkVisibilityCSS:true})).map(e=>{
          const r=e.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
          return {id:e.id,left:r.left,right:r.right,top:r.top,bottom:r.bottom,hit:e===hit||e.contains(hit)};
        });
        return {applied,bar:{left:bar.left,right:bar.right,top:bar.top,bottom:bar.bottom},navTop:nav.top,controls,width:innerWidth,height:innerHeight};
      });
      assert.deepEqual(evidence.applied,[24,34],"CDP must really set CSS env insets");
      assert.ok(evidence.bar.left>=24&&evidence.bar.right<=device.width-24,JSON.stringify(evidence));
      assert.ok(evidence.bar.bottom<=evidence.navTop&&evidence.bar.top>=47);
      for(const e of evidence.controls)assert.ok(e.hit&&e.top>=evidence.bar.top&&e.bottom<=evidence.bar.bottom&&e.left>=evidence.bar.left&&e.right<=evidence.bar.right,JSON.stringify(e));
      await screenshot(p,"safe-area",device);
      return evidence;
    }finally{await cdp.send("Emulation.setSafeAreaInsetsOverride",{insets:{top:0,bottom:0,left:0,right:0}});}
  });
  }

  const pointers=pointerAudit;
  assert.ok(pointers.length>0,"must observe trusted touch gestures");
  // Native touches were used throughout; no injected PointerEvent/MouseEvent.
  assert.ok(pointers.every(e=>e.type==="touch"&&e.trusted));
  await context.close();
 }
 }finally{await browser.close();await fs.writeFile(path.join(output,phase+"-results.json"),JSON.stringify(results,null,2)+"\n");}
 console.log(JSON.stringify({passed:results.filter(r=>r.status==="PASS").length,failed:results.filter(r=>r.status==="FAIL").length}));
 if(results.some(r=>r.status==="FAIL"))process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});
