const {t,dashboardLocale,dashboardTimeZone,dashboardI18nReady}=require("./dashboard_i18n_fixture.cjs");
"use strict";
const {test}=require("node:test"), assert=require("node:assert/strict");
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const code=fs.readFileSync(path.join(__dirname,"../musicbot/web/popular.js"),"utf8");
class El {
 constructor(){this.children=[];this.listeners={};this.value="";this.textContent="";}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=[];this.append(...children);}
 setAttribute(key,value){this[key]=value;}
 addEventListener(key,fn){this.listeners[key]=fn;}
}
function setup(api) {
 const nodes=new Map(),requests=[],previews=[],views=[],saved=[],actions=[],notices=[];
 const node=id=>{if(!nodes.has(id))nodes.set(id,new El());return nodes.get(id);};
 const ctx=vm.createContext({t,dashboardLocale,dashboardTimeZone,dashboardI18nReady,generation:1,selected:"1",connected:true,busy:false,resolving:false,$:node,
 buttonLabel:(el,key)=>{el.textContent=t(key);},buttonBusy:(el,value)=>{el.disabled=value;el.loading=value;},
 notice:(...args)=>notices.push(args),act:async(...args)=>{actions.push(args);return true;},
 document:{createElement:()=>new El()},
 songLinkURL:s=>s,drag:null,suppressSongLinksUntil:0,api:async (url,method,data)=>{requests.push(url);return api?api(url,method,data):url.endsWith("/resolve")?{results:[{kind:"track",allowed:true,url:"https://example.test/song",preview_id:"preview-one"}]}:{tracks:[{title:"<img onerror=x>",url:"https://example.test/song",duration:83,count:12}]};},
 duration:s=>"1:23",safeURL:s=>s,libraryView:p=>views.push(p),
 previewHistorySong:(...args)=>previews.push(args),
 librarySaveButton:s=>{const el=new El();el.song=s;saved.push(s);return el;}});
 const dashboard=fs.readFileSync(path.join(__dirname,"../musicbot/web/dashboard.js"),"utf8");
 vm.runInContext(dashboard.slice(dashboard.indexOf("function songTitle"),dashboard.indexOf("function songIdentity")),ctx);
 vm.runInContext(code,ctx);
 return {ctx,node,requests,previews,views,saved,actions,notices,run:s=>vm.runInContext(s,ctx)};
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
test("popular add resolves and confirms queue in one click",async()=>{
 const app=setup();await app.run("popularLoad()");
 const button=app.node("popular-list").children[0].children[2].children[0];
 assert.equal(button.textContent,t("m0612"));await button.listeners.click();
 assert.equal(app.requests.at(-1),"api/guilds/1/resolve");
 assert.deepEqual(JSON.parse(JSON.stringify(app.actions)),[["play",{query:"https://example.test/song",preview_id:"preview-one"}]]);
 assert.equal(app.previews.length,0);assert.equal(button.disabled,false);assert.equal(button.loading,false);
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

test("popular pending resolve prevents duplicate clicks and stale guild enqueue",async()=>{
 let finish;const app=setup(url=>url.endsWith("/resolve")?new Promise(r=>finish=r):{tracks:[{title:"Demo",url:"https://example.test/song"}]});
 await app.run("popularLoad()");const button=app.node("popular-list").children[0].children[2].children[0];
 const pending=button.listeners.click();assert.equal(button.loading,true);
 await button.listeners.click();assert.equal(app.requests.filter(u=>u.endsWith("/resolve")).length,1);
 app.ctx.generation++;finish({results:[{kind:"track",allowed:true,preview_id:"x",url:"https://example.test/song"}]});await pending;
 assert.equal(app.actions.length,0);assert.equal(button.loading,false);assert.equal(button.disabled,true);
});
test("popular resolve rejection and unavailable tracks restore button and explain error",async()=>{
 for(const response of [new Error("resolve failed"),{results:[{allowed:false,reason:"Unavailable"}]}]){
 const app=setup(url=>{if(url.endsWith("/resolve")){if(response instanceof Error)throw response;return response;}return {tracks:[{title:"Demo",url:"https://example.test/song"}]};});
 await app.run("popularLoad()");const button=app.node("popular-list").children[0].children[2].children[0];await button.listeners.click();
 assert.equal(app.actions.length,0);assert.equal(button.disabled,false);assert.equal(app.notices.length,1);assert.equal(app.notices[0][1],true);
 }
});
