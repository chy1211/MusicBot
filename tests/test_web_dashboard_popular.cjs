"use strict";
const {test}=require("node:test"), assert=require("node:assert/strict");
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const code=fs.readFileSync(path.join(__dirname,"../musicbot/web/popular.js"),"utf8");
class El {
 constructor(){this.children=[];this.listeners={};this.value="";this.textContent="";}
 append(...children){this.children.push(...children);}
 replaceChildren(){this.children=[];}
 setAttribute(key,value){this[key]=value;}
 addEventListener(key,fn){this.listeners[key]=fn;}
}
function setup(api) {
 const nodes=new Map(),requests=[],previews=[],views=[],saved=[];
 const node=id=>{if(!nodes.has(id))nodes.set(id,new El());return nodes.get(id);};
 const ctx=vm.createContext({generation:1,selected:"1",connected:true,$:node,
 document:{createElement:()=>new El()},api:async url=>{requests.push(url);return api?api(url):{tracks:[{title:"<img onerror=x>",url:"https://example.test/song",duration:83,count:12}]};},
 duration:s=>"1:23",safeURL:s=>s,libraryView:p=>views.push(p),
 previewHistorySong:(...args)=>previews.push(args),
 librarySaveButton:s=>{const el=new El();el.song=s;saved.push(s);return el;}});
 vm.runInContext(code,ctx);
 return {ctx,node,requests,previews,views,saved,run:s=>vm.runInContext(s,ctx)};
}
test("popular lists rank, count and duration through member API", async()=>{
 const app=setup();app.node("popular-period").value="30";await app.run("popularLoad()");
 assert.equal(app.requests[0],"/api/guilds/1/popular?period=30");
 const row=app.node("popular-list").children[0];
 assert.equal(row.children[0].textContent,"1");
 assert.equal(row.children[1].children[0].textContent,"<img onerror=x>");
 assert.equal(row.children[1].children[1].textContent,"12 次 · 1:23");
 assert.equal(app.saved.length,1);
});
test("popular add reuses normal preview and playlist save action",async()=>{
 const app=setup();await app.run("popularLoad()");
 await app.node("popular-list").children[0].children[2].children[0].listeners.click();
 assert.deepEqual(app.views,["play"]);assert.equal(app.previews.length,1);
 assert.equal(app.previews[0][1],"1");
});
test("period changes discard obsolete responses",async()=>{
 let done;const app=setup(()=>new Promise(resolve=>{done=resolve;}));
 const pending=app.run("popularLoad()");app.ctx.generation=2;
 done({tracks:[{title:"stale"}]});await pending;
 assert.equal(app.node("popular-list").children.length,0);
});
test("popular failures show safe error without disconnecting playback",async()=>{
 const app=setup(()=>{throw Error("暫時無法取得熱門點播。");});
 await app.run("popularLoad()");assert.equal(app.ctx.connected,true);
 assert.equal(app.node("popular-status").textContent,"暫時無法取得熱門點播。");
});
test("reset clears popularity and invalidates stale buttons",async()=>{
 const app=setup();await app.run("popularLoad()");
 const button=app.node("popular-list").children[0].children[2].children[0];
 app.ctx.generation=2;app.run("popularClear()");
 await button.listeners.click();assert.equal(app.previews.length,0);
 assert.equal(app.node("popular-list").children.length,0);
});
test("popular view uses top 20 and handles empty period",async()=>{
 const app=setup(()=>({tracks:[]}));await app.run("popularLoad()");
 assert.match(app.node("popular-status").textContent,/還沒有/);
 assert.match(code,/slice\(0, 20\)/);
});
