'use strict';
const {test,before,after}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const base=process.env.PATCH1014_BASE||'http://localhost:18310';
const shots=process.env.PATCH1014_SHOTS||'/work/round1819-shots';
let browser;
before(async()=>{fs.mkdirSync(shots,{recursive:true});browser=await chromium.launch({headless:true})});
after(async()=>{await browser?.close()});
async function open(t){
 const context=await browser.newContext({viewport:{width:1440,height:900},locale:'zh-TW',serviceWorkers:'block'});
 const page=await context.newPage(),calls=[],errors=[];
 t.after(async()=>{await page.unrouteAll({behavior:'wait'});await context.close()});
 page.on('pageerror',error=>errors.push(String(error)));
 page.on('request',request=>calls.push({url:request.url(),method:request.method(),body:request.method()==='POST'?request.postDataJSON():null}));
 await page.goto(base+'/?demo-queue=filled&demo-lyrics=synced');
 await page.locator('#discord-login').click();await page.waitForFunction(()=>document.querySelectorAll('#queue>li').length===4);
 return {page,calls,errors};
}
test('initial play loads no admin/popular data and route entry initializes each view',async t=>{
 const {page,calls,errors}=await open(t);
 assert.equal(calls.filter(c=>c.url.includes('/admin/')||c.url.includes('/popular?')).length,0);
 await page.locator('#nav-admin').click();await page.locator('#admin-playback-group').waitFor();
 await page.waitForFunction(()=>!document.querySelector('#admin-playback-group')?.hasAttribute('hidden'));
 assert.ok(calls.some(c=>c.url.includes('/admin/')));
 const popularResponse=page.waitForResponse(r=>r.url().includes('/popular?')&&r.status()===200);
 await page.locator('#nav-popular').click();await page.locator('#popular-panel').waitFor();
 await popularResponse;
 assert.ok(calls.some(c=>c.url.includes('/popular?')));
 await page.locator('#nav-play').click();await page.locator('#play-view').waitFor();
 assert.deepEqual(errors,[]);
});
test('save-to-playlist works from play before visiting the lazy library route',async t=>{
 const {page,calls,errors}=await open(t);
 assert.equal(await page.locator('#library-panel').count(),0);
 await page.locator('.history .library-save').first().click();
 const dialog=page.locator('#library-save-dialog');await dialog.waitFor({state:'visible'});
 assert.ok(['','#/','#/play'].includes(new URL(page.url()).hash),page.url());
 await page.locator('#library-save-confirm').click();await dialog.waitFor({state:'hidden'});
 assert.ok(calls.some(c=>c.method==='POST'&&c.url.includes('/api/library/')&&c.url.endsWith('/tracks')));
 assert.deepEqual(errors,[]);
});
test('library import shortcut returns to the visible header search',async t=>{
 const {page,errors}=await open(t);
 await page.locator('#nav-library').click();await page.locator('#library-import-hint').click();
 await page.waitForURL('**#/play');await page.waitForFunction(()=>document.activeElement?.id==='header-query');
 assert.deepEqual(errors,[]);
});
test('desktop queue scrolls within compact left-column height and touch layout keeps normal flow',async t=>{
 const {page,errors}=await open(t);
 await page.route('**/events*',route=>route.abort());
 await page.route('**/api/guilds/*/state',async route=>{
  const response=await route.fetch(),state=await response.json(),sample=state.queue;
  state.queue=Array.from({length:70},(_,index)=>({...sample[index%sample.length],position:index+1,title:'Synthetic queue '+index,url:'https://example.test/track/'+index}));
  await route.fulfill({response,json:state});
 });
 await page.reload();await page.waitForFunction(()=>document.querySelectorAll('#queue>li').length===70);
 const metrics=await page.evaluate(()=>{
  const queue=document.querySelector('.card.queue').getBoundingClientRect(),history=document.querySelector('.card.history').getBoundingClientRect();
  const list=document.querySelector('#queue');return{height:queue.height,historyHeight:history.height,scroll:list.scrollHeight,client:list.clientHeight};
 });
 assert.ok(metrics.height<850,JSON.stringify(metrics));assert.ok(metrics.historyHeight<450,JSON.stringify(metrics));
 assert.ok(metrics.scroll>metrics.client+100,JSON.stringify(metrics));
 await page.screenshot({path:shots+'/desktop-long-queue.png'});
 await page.setViewportSize({width:390,height:844});
 const mobile=await page.evaluate(()=>({history:getComputedStyle(document.querySelector('#history-list')).maxHeight,queue:getComputedStyle(document.querySelector('#queue')).overflowY,overflow:document.documentElement.scrollWidth>innerWidth+1}));
 assert.deepEqual(mobile,{history:'none',queue:'visible',overflow:false});
 assert.deepEqual(errors,[]);
});

test('history icons have visible masks and accessible 44px targets across themes and touch widths',async t=>{
 const {page,errors}=await open(t);
 for(const [width,theme,palette] of [[1440,'dark','mint'],[1440,'light','amber'],[390,'dark','ocean'],[390,'light','rose'],[768,'dark','noir'],[768,'light','iris']]){
  await page.setViewportSize({width,height:900});
  await page.evaluate(({theme,palette})=>{document.documentElement.dataset.theme=theme;document.documentElement.dataset.palette=palette;},{theme,palette});
  const actions=page.locator('#history-list .history-actions').first();await actions.scrollIntoViewIfNeeded();
  const buttons=actions.locator('button');assert.equal(await buttons.count(),2);
  for(let index=0;index<2;index++){
   const button=buttons.nth(index),metrics=await button.evaluate(el=>{const r=el.getBoundingClientRect(),p=getComputedStyle(el,'::before');return{width:r.width,height:r.height,mask:p.maskImage||p.webkitMaskImage,color:p.backgroundColor,name:el.getAttribute('aria-label')||el.textContent};});
   assert.ok(metrics.width>=44&&metrics.height>=44,JSON.stringify(metrics));
   assert.match(metrics.mask,/history-(add|heart)\.svg/);assert.ok(metrics.name.trim());assert.notEqual(metrics.color,'rgba(0, 0, 0, 0)');
  }
  await page.locator('.card.history').screenshot({path:shots+`/r21-icons-${width}-${theme}.png`});
 }
 const response=await page.request.get(base+'/icons/history-heart.svg');assert.equal(response.status(),200);
 await page.locator('#history-list .library-save').first().focus();await page.keyboard.press('Enter');
 await page.locator('#library-save-dialog').waitFor({state:'visible'});
 assert.deepEqual(errors,[]);
});
test('manual search displays source and unverified version labels without input-triggered requests',async t=>{
 const {page,calls,errors}=await open(t);
 await page.route('**/api/guilds/*/resolve',route=>route.fulfill({json:{results:[{kind:'track',title:'Blue Sky (Official Audio)',artist:'Example Singer',url:'https://youtu.be/abcdefghijk',duration:120,source:'YouTube',version:'official_audio',allowed:true,preview_id:'synthetic-r21'}]}}));
 await page.locator('#header-query').fill('Blue Sky');
 assert.equal(calls.filter(c=>c.url.endsWith('/resolve')).length,0);
 await page.locator('#header-query').press('Enter');const row=page.locator('.header-result').first();await row.waitFor();
 await row.getByText('YouTube',{exact:true}).waitFor();
 await row.getByText(/標題標示：.*未驗證|Title tag:.*unverified/).waitFor();
 assert.equal(calls.filter(c=>c.url.endsWith('/resolve')).length,1);
 assert.deepEqual(errors,[]);
});

test('real service-worker installation precaches every icon without caching API data',async t=>{
 const context=await browser.newContext({serviceWorkers:'allow'});t.after(()=>context.close());
 const page=await context.newPage();await page.goto(base+'/offline.html');
 await page.evaluate(async()=>{const cache=await caches.open('musicbot-dashboard-r42-real-version');await cache.put('/old-static-placeholder',new Response('old'));});
 await page.goto(base);
 await page.waitForFunction(()=>navigator.serviceWorker.controller!==null,null,{timeout:20000});
 const state=await page.evaluate(async()=>{
  const names=(await caches.keys()).filter(name=>name.startsWith('musicbot-dashboard-'));
  const cache=await caches.open(names[0]),keys=await cache.keys();
  const icons=await Promise.all(['history-add','history-heart','transport-play','transport-pause','transport-skip','transport-repeat'].map(async name=>(await cache.match('/icons/'+name+'.svg'))?.status));
  return {names,icons,privateKeys:keys.map(key=>new URL(key.url).pathname).filter(path=>/^\/(api|auth|events)(\/|$)/.test(path))};
 });
 assert.deepEqual(state.names,['musicbot-dashboard-r18-21']);assert.deepEqual(state.icons,[200,200,200,200,200,200]);assert.deepEqual(state.privateKeys,[]);
});
