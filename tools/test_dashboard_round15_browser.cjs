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
 t.after(()=>context.close());const page=await context.newPage(),errors=[],calls=[];
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
 for(const value of ['library','popular','admin','play']){await page.locator('#page-nav').selectOption(value);await page.waitForURL('**#/'+value);}
 await page.locator('#palette-toggle').click();const rect=await page.locator('#palette-panel').boundingBox();assert.ok(rect.x>=0&&rect.x+rect.width<=width+1,JSON.stringify(rect));
 await page.locator('.palette-swatch[data-palette=noir]').click();
 for(const id of ['toggle','skip','repeat']){const icon=await page.locator('#'+id+' svg.transport-icon').evaluate(el=>({w:el.getBoundingClientRect().width,h:el.getBoundingClientRect().height,mask:getComputedStyle(el).maskImage,shapes:el.querySelectorAll('path,rect').length}));assert.ok(icon.w>=20&&icon.h>=20&&icon.shapes>0&&icon.mask==='none',JSON.stringify(icon));}
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:shots+'/layout-'+width+'.png',fullPage:true});assert.deepEqual(errors,[]);
});
