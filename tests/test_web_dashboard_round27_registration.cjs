"use strict";
const {test}=require("node:test"),assert=require("node:assert/strict");
const load=require("./dashboard_ts_fixture.cjs");
async function run(controlled){
 const handlers={},messages=[],dashboard={updateAvailable:false};let observed=false,unmount;
 const serviceWorker={controller:controlled?{}:null,addEventListener:(name,fn)=>handlers[name]=fn,
 removeEventListener:(name,fn)=>{assert.equal(handlers[name],fn);delete handlers[name]},
 register:(url,options)=>{assert.equal(url,"/sw.js");assert.equal(options.updateViaCache,"none");
 observed=typeof handlers.controllerchange==="function";handlers.controllerchange?.();return Promise.resolve({update:()=>Promise.resolve()})}};
 const c=load("frontend/src/composables/usePwa.ts",{vue:{ref:value=>({value}),onMounted:fn=>fn(),onBeforeUnmount:fn=>unmount=fn},
 '../store':{dashboard},'./useDashboard':{notice:value=>messages.push(value)},'./useLocale':{t:key=>key}},
 {navigator:{serviceWorker}});
 c.usePwa();await Promise.resolve();await Promise.resolve();unmount();
 assert.equal(handlers.controllerchange,undefined);return {observed,dashboard,messages};
}
test("already controlled PWA observes even an immediate registration update",async()=>{
 const result=await run(true);assert.equal(result.observed,true);assert.equal(result.dashboard.updateAvailable,true);assert.deepEqual(result.messages,["m0222"]);
});
test("first install does not show an unnecessary update prompt",async()=>{
 const result=await run(false);assert.equal(result.observed,true);assert.equal(result.dashboard.updateAvailable,false);assert.deepEqual(result.messages,[]);
});
