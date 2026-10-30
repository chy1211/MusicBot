"use strict";
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const base=process.env.PATCH1014_BASE||'http://localhost:18310';

for(const scenario of [
  {name:'desktop',width:1440,height:900,touch:false,shouldMove:true},
  {name:'tablet portrait',width:768,height:1024,touch:true,shouldMove:true},
  {name:'tablet landscape',width:1024,height:768,touch:true,shouldMove:true},
  {name:'phone portrait',width:390,height:844,touch:true,shouldMove:false},
  {name:'phone landscape',width:844,height:390,touch:true,shouldMove:false},
])test(`desktop/tablet notification positioning: ${scenario.name}`,async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const context=await browser.newContext({viewport:{width:scenario.width,height:scenario.height},isMobile:scenario.touch,hasTouch:scenario.touch,serviceWorkers:'block'});
  const page=await context.newPage();
  await page.goto(base+'/?demo-queue=filled&demo-lyrics=synced');
  await page.waitForSelector('#discord-login');
  await page.locator('#discord-login').click();
  await page.waitForFunction(()=>document.querySelectorAll('#queue>li').length===4);
  await page.waitForSelector('#notice',{state:'attached'});
  const actual=await page.evaluate(()=>{
    const n=document.querySelector('#notice');
    n.classList.add('visible');
    const span=n.querySelector('span');if(span)span.textContent='Preview expired: please search again to continue.';
    const rect=n.getBoundingClientRect();
    const dock=document.querySelector('#playback-bar')?.getBoundingClientRect();
    const input=document.querySelector('#header-query')?.getBoundingClientRect();
    return {
      moved:matchMedia('(min-width:761px) and (pointer:fine), (min-width:761px) and (min-height:561px)').matches,
      top:getComputedStyle(n).top,
      left:getComputedStyle(n).left,
      rightGap:innerWidth-rect.right,
      dockGap:dock?dock.top-rect.bottom:null,
      clearSearch:input?rect.top>=input.bottom+8:true,
    };
  });
  assert.equal(actual.moved,scenario.shouldMove,JSON.stringify(actual));
  if(scenario.shouldMove){
    assert.ok(actual.rightGap<=32,JSON.stringify(actual));
    assert.ok(actual.rightGap>=8,JSON.stringify(actual));
    assert.ok(actual.dockGap===null||actual.dockGap>=8,JSON.stringify(actual));
    assert.ok(actual.clearSearch,JSON.stringify(actual));
  }else{
    // Mobile must use the existing layout rather than desktop's right dock.
    assert.notEqual(actual.left,'auto',JSON.stringify(actual));
  }
  await context.close();
 }finally{await browser.close()}
});
