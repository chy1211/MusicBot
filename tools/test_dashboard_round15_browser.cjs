"use strict";
const {test,before,after}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const base=process.env.PATCH1014_BASE||'http://localhost:18310';
const shots=process.env.PATCH1014_SHOTS||'/work/round15-shots';
let browser;
before(async()=>{fs.mkdirSync(shots,{recursive:true});browser=await chromium.launch({headless:true});});
after(async()=>{await browser?.close();});
async function open(t,width=1440,height=900){
 const context=await browser.newContext({viewport:{width,height},locale:'zh-TW',isMobile:width<900,hasTouch:width<900,serviceWorkers:'block'});
 const page=await context.newPage(),errors=[],calls=[];
 t.after(async()=>{await page.unrouteAll({behavior:'wait'});await context.close();});
 page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{if(r.method()==='POST')calls.push({url:r.url(),body:r.postDataJSON()});});
 await page.goto(base+'/?demo-queue=filled&demo-lyrics=synced');
 await page.waitForFunction(()=>document.querySelector('#dashboard')?.getClientRects().length||document.querySelector('#discord-login')?.getClientRects().length);
 if(await page.locator('#discord-login').isVisible().catch(()=>false))await page.locator('#discord-login').click();
 await page.waitForFunction(()=>document.querySelectorAll('#queue>li').length===4);
 return {page,context,errors,calls};
}

test('search restores without provider calls and modal preserves failed submissions',async t=>{
 const {page,calls,errors}=await open(t);
 await page.locator('#header-query').fill('sunset');assert.equal(calls.filter(c=>c.url.endsWith('/resolve')).length,0);
 await page.locator('#header-query').press('Enter');await page.locator('.header-result').first().waitFor();
 const count=calls.filter(c=>c.url.endsWith('/resolve')).length;
 await page.locator('.page-heading h1').click();await page.locator('#header-query').click();await page.locator('.header-result').first().waitFor();
 assert.equal(calls.filter(c=>c.url.endsWith('/resolve')).length,count);
 await page.locator('#header-query').fill('https://soundcloud.com/demo/playlist');await page.locator('#header-query').press('Enter');await page.locator('.header-result>button').first().click();
 await page.locator('dialog[open]').waitFor();assert.ok(await page.locator('dialog input[type=checkbox]').count()>1);
 await page.route('**/api/guilds/*/play',r=>r.fulfill({status:403,contentType:'application/json',body:JSON.stringify({error:'fixture denied'})}));
 await page.locator('dialog footer .primary').click();await page.locator('dialog [role=alert]').waitFor();assert.equal(await page.locator('dialog[open]').count(),1);
 await page.keyboard.press('Escape');await page.waitForFunction(()=>document.activeElement?.id==='header-query');
 await page.locator('#header-query').fill('changed');assert.equal(await page.locator('.header-result').count(),0);assert.deepEqual(errors,[]);
});
for(const [width,height] of [[1440,900],[390,844],[768,1024],[844,390]])test(`navigation palette and layout ${width}`,async t=>{
 const {page,errors}=await open(t,width,height);
 if(await page.locator('.mobile-landscape').isVisible())await page.locator('.landscape-top button').click();
 for(const value of ['library','popular','admin','play']){await page.locator('#nav-'+value).click();await page.waitForURL('**#/'+value);}
 await page.locator('#palette-toggle').click();const rect=await page.locator('#palette-panel').boundingBox();assert.ok(rect.x>=0&&rect.x+rect.width<=width+1,JSON.stringify(rect));
 await page.locator('.palette-swatch[data-palette=noir]').click();
 for(const id of ['toggle','skip','repeat']){const icon=await page.locator('#'+id+' svg.transport-icon').evaluate(el=>({w:el.getBoundingClientRect().width,h:el.getBoundingClientRect().height,mask:getComputedStyle(el).maskImage,shapes:el.querySelectorAll('path,rect').length}));assert.ok(icon.w>=20&&icon.h>=20&&icon.shapes>0&&icon.mask==='none',JSON.stringify(icon));}
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:shots+'/layout-'+width+'.png',fullPage:true});assert.deepEqual(errors,[]);
});

test('portrait restores bottom tabs and keeps heading near theme toolbar',async t=>{
 const {page,errors}=await open(t,390,844);
 assert.equal(await page.locator('#page-nav').count(),0);
 for(const id of ['play','library','popular','admin'])assert.equal(await page.locator('#nav-'+id).count(),1);
 const gap=await page.evaluate(()=>{
  const a=document.querySelector('.language-preference')?.getBoundingClientRect();
  const h=document.querySelector('.page-heading h1')?.getBoundingClientRect();
  return a&&h?h.top-a.bottom:Infinity;
 });
 assert.ok(gap>=-6&&gap<190,'portrait toolbar-heading gap '+gap);
 const b=await page.locator('.sidebar .page-tabs').boundingBox();
 assert.ok(b&&b.y>550,'mobile bottom nav should be fixed at screen bottom '+JSON.stringify(b));
 assert.deepEqual(errors,[]);
});
test('landscape has vector controls, requester avatar and favorite',async t=>{
 const {page,errors,calls}=await open(t,390,844);await page.setViewportSize({width:844,height:390});
 await page.locator('.mobile-landscape').waitFor({state:'visible'});
 for(const id of ['.landscape-favorite','.landscape-toggle','.landscape-skip']){
  const button=page.locator('.landscape-buttons '+id);
  assert.equal(await button.locator('svg').count(),1);
  assert.ok((await button.boundingBox()).width>=44);
 }
 assert.equal(await page.locator('.landscape-requester img').count(),1);
 assert.ok(await page.locator('.landscape-requester img').isVisible());
 assert.ok((await page.locator('.landscape-favorite').getAttribute('aria-label')).length>0);
 const favorite=page.locator('.landscape-favorite');
 const original=await favorite.getAttribute('aria-pressed');
 await favorite.click();
 await page.waitForFunction(previous=>document.querySelector('.landscape-favorite').getAttribute('aria-pressed')!==previous,original);
 await favorite.click();
 await page.waitForFunction(previous=>document.querySelector('.landscape-favorite').getAttribute('aria-pressed')===previous,original);
 assert.ok(calls.some(c=>c.url.endsWith('/api/library/favorites/tracks')));
 await page.screenshot({path:shots+'/landscape-controls.png'});

 assert.deepEqual(errors,[]);
});
test('admin uses only native expandable section menus',async t=>{
 const {page,errors}=await open(t);
 await page.locator('#nav-admin').click();
 await page.locator('#admin-playback-group').waitFor();
 assert.equal(await page.locator('.admin-jump-links button').count(),0);
 for(const id of ['admin-playback-group','admin-apl-group','admin-permissions-group','admin-maintenance-group']){
  assert.equal(await page.locator('details#'+id+' > summary').count(),1);
 }
 assert.deepEqual(errors,[]);
});

test('history precedes activity in every playback state',async t=>{
 const {page,errors}=await open(t);
 await page.route('**/events*',route=>route.abort());
 for(const status of ['playing','paused','stopped','disconnected']){
  await page.route('**/api/guilds/*/state',async route=>{
   const response=await route.fetch(),state=await response.json();
   state.status=status;if(['stopped','disconnected'].includes(status))state.current=null;
   await route.fulfill({response,json:state});
  });
  // A fresh page starts polling from the synthetic snapshot for each state.
  await page.reload();
  await page.waitForFunction(expected=>{
   const title=document.querySelector('.listening-stage');
   return !!document.querySelector('#history-heading')&&
    (['stopped','disconnected'].includes(expected)?!title:!!title);
  },status);
  assert.equal(await page.locator('#queue-recommendations').count(),0);
  assert.equal(await page.locator('#history-heading').count(),1);
  const order=await page.evaluate(()=>{
   const history=document.querySelector('.card.history'),activity=document.querySelector('.card.activity');
   return {dom:!!(history.compareDocumentPosition(activity)&Node.DOCUMENT_POSITION_FOLLOWING),
    above:history.getBoundingClientRect().bottom<=activity.getBoundingClientRect().top+1};
  });
  assert.deepEqual(order,{dom:true,above:true},status);
  await page.unrouteAll({behavior:'wait'});
  await page.route('**/events*',route=>route.abort());
 }
 assert.deepEqual(errors,[]);
});
