'use strict';
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const base=process.env.PATCH1014_BASE||'http://localhost:18310';
let browser;
before(async()=>{browser=await chromium.launch({headless:true});});
after(async()=>{await browser?.close();});
async function open(t){
 const context=await browser.newContext({viewport:{width:1440,height:900},locale:'zh-TW',serviceWorkers:'block'});
 const page=await context.newPage(),errors=[];
 t.after(async()=>context.close());
 page.on('pageerror',error=>errors.push(String(error)));
 await page.goto(base+'/?demo-queue=filled&demo-lyrics=synced');
 await page.locator('#discord-login').click();
 await page.locator('#stage-title').waitFor();
 return {page,errors};
}
test('desktop stage-wave fits all 12 bars before the unchanged title column',async t=>{
 const {page,errors}=await open(t);
 for(const width of [1440,1001]){
  await page.setViewportSize({width,height:900});
  const m=await page.evaluate(()=>{
   const wave=document.querySelector('#play-view > .listening-stage .stage-copy > .stage-wave');
   const title=document.querySelector('#stage-title');
   const rect=wave.getBoundingClientRect(),bars=[...wave.querySelectorAll('i')].map(bar=>bar.getBoundingClientRect());
   return {count:bars.length,width:rect.width,gap:getComputedStyle(wave).gap,
    allVisible:bars.every(bar=>bar.width===2&&bar.height>0&&bar.right<=rect.right+1),
    titleStartsAfter: title.getBoundingClientRect().left>=rect.right-1,
    overflow:document.documentElement.scrollWidth>innerWidth+1};
  });
  assert.equal(m.count,12);assert.equal(m.gap,'1px');assert.ok(m.width<=44,m.width);
  assert.ok(m.allVisible,JSON.stringify(m));assert.ok(m.titleStartsAfter,JSON.stringify(m));assert.equal(m.overflow,false);
 }
 await page.setViewportSize({width:1000,height:900});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
 assert.deepEqual(errors,[]);
});
test('playlist modal has visible footer and a single scroll region on desktop and phones',async t=>{
 const {page,errors}=await open(t);
 await page.locator('#header-query').fill('https://soundcloud.com/demo/playlist');
 await page.locator('#header-query').press('Enter');
 await page.locator('.header-result>button').first().click();
 await page.locator('.header-playlist-modal').waitFor({state:'visible'});
 for(const [width,height] of [[1440,900],[768,950],[390,844]]){
  await page.setViewportSize({width,height});
  const m=await page.evaluate(()=>{
   const dialog=document.querySelector('.header-playlist-modal'),entries=dialog.querySelector('.playlist-modal-entries');
   const body=dialog.querySelector('.playlist-modal-body'),footer=dialog.querySelector('.playlist-modal-footer');
   const d=dialog.getBoundingClientRect(),f=footer.getBoundingClientRect();
   return {bounds:[d.left,d.right,d.top,d.bottom],footer:[f.top,f.bottom],
    entriesCount:entries.children.length,entriesOverflow:getComputedStyle(entries).overflowY,
    bodyOverflow:getComputedStyle(body).overflowY,entriesScrollable:entries.scrollHeight>entries.clientHeight+20,
    bodyScrollable:body.scrollHeight>body.clientHeight+20,
    importButtonCount:dialog.querySelectorAll('footer .import-submit').length,
    scrollableDialog:dialog.scrollHeight>dialog.clientHeight+2,
    overflow:document.documentElement.scrollWidth>innerWidth+1};
  });
  assert.ok(m.entriesCount>10,JSON.stringify(m));
  assert.equal(m.importButtonCount,1);assert.equal(m.scrollableDialog,false,JSON.stringify({width,...m}));
  assert.ok(m.bounds[0]>=-1 && m.bounds[1]<=width+1 && m.bounds[2]>=-1 && m.bounds[3]<=height+1,JSON.stringify({width,...m}));
  assert.ok(m.footer[0]>=0 && m.footer[1]<=height+1,JSON.stringify({width,...m}));
  assert.equal(m.overflow,false);
  if(width>800){assert.equal(m.entriesOverflow,'auto');assert.equal(m.entriesScrollable,true);}
  else {assert.equal(m.bodyOverflow,'auto');assert.equal(m.entriesOverflow,'visible');assert.equal(m.bodyScrollable,true);}
 }
 assert.deepEqual(errors,[]);
});
