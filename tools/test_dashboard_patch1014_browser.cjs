"use strict";
const {test,before,after}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
const base=process.env.PATCH1014_BASE||'http://localhost:18310';
const shots=process.env.PATCH1014_SHOTS||'/work/patch1014-shots';
let browser;
before(async()=>{fs.mkdirSync(shots,{recursive:true});browser=await chromium.launch({headless:true});});
after(async()=>{await browser?.close();});
async function open(t,width=1440,height=900){
 const context=await browser.newContext({viewport:{width,height},locale:'zh-TW',isMobile:width<900,hasTouch:width<900,serviceWorkers:'block'});
 t.after(()=>context.close());const page=await context.newPage(),errors=[],calls=[];
 page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{if(r.method()==='POST')calls.push({url:r.url(),body:r.postDataJSON()});});
 await page.goto(base+'/?demo-queue=filled&demo-lyrics=synced');
 await page.waitForFunction(()=>document.querySelector('#dashboard')?.getClientRects().length||document.querySelector('#discord-login')?.getClientRects().length);
 if(await page.locator('#discord-login').isVisible().catch(()=>false))await page.locator('#discord-login').click();
 await page.waitForFunction(()=>document.querySelectorAll('#queue>li').length===4);
 return {page,context,errors,calls};
}
test('manual header search makes no request while typing; add and first-row remove work',async t=>{
 const {page,errors,calls}=await open(t);
 await page.locator('#header-query').fill('sunset');
 await page.waitForTimeout(250);assert.equal(calls.filter(r=>r.url.endsWith('/resolve')).length,0);
 assert.equal(await page.locator('#queue>li:visible').count(),3);
 await page.locator('#header-query').press('Enter');
 await page.locator('.header-result').first().waitFor();
 assert.equal(calls.filter(r=>r.url.endsWith('/resolve')).length,1);
 await page.locator('.header-result>button').first().click();
 await page.waitForFunction(()=>document.querySelectorAll('#queue>li').length===5);
 await page.waitForFunction(()=>document.querySelector('#header-query')?.value==='');
 await page.locator('.next-track-remove').click();
 await page.waitForFunction(()=>document.querySelectorAll('#queue>li').length===4);
 await page.screenshot({path:shots+'/desktop-1440.png',fullPage:true});assert.deepEqual(errors,[]);
});
test('playlist preview remains reachable from header results',async t=>{
 const {page,errors}=await open(t);
 await page.locator('#header-query').fill('https://soundcloud.com/demo/playlist');
 await page.locator('#header-query').press('Enter');
 await page.locator('.header-result').first().waitFor();
 await page.locator('.header-result>button').first().click();
 await page.locator('.playlist-selection').waitFor({state:'visible'});
 assert.ok(await page.locator('.playlist-selection input[type=checkbox]').count()>1);
 assert.deepEqual(errors,[]);
});
test('all palettes persist, preserve preferred mode and maintain readable text',async t=>{
 const {page,errors}=await open(t);
 await page.evaluate(()=>{localStorage.setItem('musicbot-theme','light')});await page.reload();await page.locator('#header-query').waitFor();
 for(const palette of ['mint','amber','ocean','rose','noir','iris']){
  await page.locator('#palette-toggle').click();await page.locator(`.palette-swatch[data-palette=${palette}]`).click();
  assert.equal(await page.evaluate(()=>document.documentElement.dataset.palette),palette);
  if(palette==='noir'||palette==='iris')assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),palette==='noir'?'dark':'light');
  const contrast=await page.evaluate(()=>{
   const s=getComputedStyle(document.documentElement),rgb=x=>{x=x.trim().replace('#','');if(x.length===3)x=x.split('').map(v=>v+v).join('');return [0,2,4].map(i=>parseInt(x.slice(i,i+2),16)/255)},l=x=>rgb(x).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0),a=l(s.getPropertyValue('--text')),b=l(s.getPropertyValue('--bg'));return(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
  });assert.ok(contrast>=4.5,palette+' contrast '+contrast);
  await page.screenshot({path:shots+'/palette-'+palette+'.png',fullPage:true});
 }
 await page.reload();await page.locator('#header-query').waitFor();assert.equal(await page.evaluate(()=>document.documentElement.dataset.palette),'iris');
 await page.locator('#palette-toggle').click();await page.locator('.palette-swatch[data-palette=mint]').click();
 assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),'light');assert.deepEqual(errors,[]);
});
test('portrait remains within viewport with readable navigation and dock',async t=>{
 const {page,errors}=await open(t,390,844);
 assert.equal(await page.locator('.mobile-landscape').isVisible(),false);
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:shots+'/portrait-390.png',fullPage:true});assert.deepEqual(errors,[]);
});
test('tablet sidebar remains above the dock and cards fit the viewport',async t=>{
 const {page,errors}=await open(t,768,1024);
 const metrics=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:innerWidth,side:document.querySelector('.sidebar').getBoundingClientRect().bottom,dock:document.querySelector('.playback-bar').getBoundingClientRect().top}));
 assert.ok(metrics.width<=metrics.viewport+1,JSON.stringify(metrics));assert.ok(metrics.side<=metrics.dock,JSON.stringify(metrics));
 const stage=await page.locator('.listening-stage').boundingBox(),listeners=await page.locator('#listeners-list').boundingBox();
 assert.ok(stage.height<650,JSON.stringify(stage));assert.ok(listeners.width>180,JSON.stringify(listeners));
 await page.screenshot({path:shots+'/tablet-768.png',fullPage:true});assert.deepEqual(errors,[]);
});
test('touch landscape controls, seek and return survive real orientation changes',async t=>{
 const {page,errors,calls}=await open(t,390,844);await page.setViewportSize({width:844,height:390});
 await page.locator('.mobile-landscape').waitFor({state:'visible'});
 const initial=(await page.locator('.landscape-buttons .primary').textContent()).trim();
 await page.locator('.landscape-buttons .primary').click();await page.waitForFunction(value=>document.querySelector('.landscape-buttons .primary')?.textContent.trim()===value,initial==='Ⅱ'?'▶':'Ⅱ');
 await page.locator('.landscape-buttons .primary').click();await page.waitForFunction(value=>document.querySelector('.landscape-buttons .primary')?.textContent.trim()===value,initial);
 await page.waitForFunction(()=>!document.querySelector('.landscape-progress input')?.disabled);
 const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/seek'));
 await page.locator('.landscape-progress input').evaluate(el=>{el.value='42';el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));});
 await response;
 assert.ok(calls.some(c=>c.url.endsWith('/seek')&&c.body.position===42));
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:shots+'/landscape-844.png'});
 await page.locator('.landscape-top button').click();await page.locator('#header-query').waitFor({state:'visible'});
 await page.setViewportSize({width:390,height:844});
 // Allow a portrait layout/resize event before rotating back, like a real rotation.
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 await page.setViewportSize({width:844,height:390});
 await page.locator('.mobile-landscape').waitFor({state:'visible'});assert.deepEqual(errors,[]);
});
