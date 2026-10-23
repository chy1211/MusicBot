"use strict";
const {test}=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const source=fs.readFileSync("musicbot/web/pwa.js","utf8");
async function run(controlled){
 const handlers={},button={hidden:true,addEventListener(){}},messages=[];let observed=false;
 const serviceWorker={controller:controlled?{}:null,addEventListener:(name,fn)=>handlers[name]=fn,
 register:()=>{observed=typeof handlers.controllerchange==="function";handlers.controllerchange?.();return Promise.resolve({update:()=>Promise.resolve()})}};
 vm.runInNewContext(source,{navigator:{serviceWorker},$:()=>button,notice:value=>messages.push(value),t:key=>key,dashboardI18nReady:Promise.resolve(),window:{location:{reload(){}}}});
 await Promise.resolve();await Promise.resolve();return {observed,button,messages};
}
test("already controlled PWA observes even an immediate registration update",async()=>{
 const result=await run(true);assert.equal(result.observed,true);assert.equal(result.button.hidden,false);assert.deepEqual(result.messages,["m0222"]);
});
test("first install does not show an unnecessary update prompt",async()=>{
 const result=await run(false);assert.equal(result.observed,true);assert.equal(result.button.hidden,true);assert.deepEqual(result.messages,[]);
});
