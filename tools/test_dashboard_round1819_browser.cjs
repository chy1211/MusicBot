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
