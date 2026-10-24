"use strict";
const {test}=require("node:test"),assert=require("node:assert/strict"),vue=require("vue"),load=require("./dashboard_ts_fixture.cjs");
function runtime(mode,status=200,nonJSON=false) {
 const dashboard={authMode:mode,secret:"fixture-secret"},calls=[],expired=[];
 const response={ok:status<400,status,json:async()=>{
  if(nonJSON)throw new Error("not JSON");
  return status<400?{ok:true}:{error:"safe fixture error"};
 }};
 const api=load("frontend/src/api.ts",{
  './store':{dashboard,expireSession:message=>expired.push(message)},
  './composables/useLocale':{t:key=>key,locale:{value:"en"}}
 },{
  Error,AbortController,DOMException,Uint8Array,setTimeout:()=>1,clearTimeout(){},
  fetch:async(url,options)=>{calls.push({url,options});return response}
 });
 return{api,dashboard,calls,expired};
}
test("owner secret stays in headers while Discord requests send no bearer credential",async()=>{
 for(const mode of ["owner","discord"]){const a=runtime(mode);await a.api.request('/api/guilds/1/state');const call=a.calls[0];assert.equal(call.url,'/api/guilds/1/state');assert.equal(call.options.credentials,"same-origin");assert.equal(call.options.cache,"no-store");assert.equal(call.options.headers.Authorization,mode==='owner'?'Bearer fixture-secret':undefined);assert.equal(call.url.includes('fixture-secret'),false);}
});
test("JSON and non-JSON Discord 401 responses expire the session",async()=>{
 for(const nonJSON of [false,true]){const a=runtime("discord",401,nonJSON);await assert.rejects(a.api.request('/api/guilds'),error=>error.status===401);assert.equal(a.expired.length,1);}
});
test("permission 403 preserves the Discord session and safe server reason",async()=>{
 const a=runtime("discord",403);await assert.rejects(a.api.request('/api/guilds'),error=>error.status===403&&error.message==='safe fixture error');assert.equal(a.expired.length,0);
});
test("expireSession clears private Vue state and invalidates pending generations",()=>{
 const c=load('frontend/src/store.ts',{vue});Object.assign(c.dashboard,{epoch:10,stateSequence:20,authenticated:true,connected:true,guilds:[{id:'1'}],guildId:'1',snapshot:{queue:[{}]},me:{id:'fixture'},secret:'fixture-secret',history:[{}],busy:true,toast:'old',undoToken:'old'});
 c.expireSession('expired');assert.equal(c.dashboard.epoch,11);assert.equal(c.dashboard.stateSequence,21);
 for(const key of ['authenticated','connected','busy'])assert.equal(c.dashboard[key],false,key);
 for(const key of ['guildId','secret','toast','undoToken'])assert.equal(c.dashboard[key],'',key);
 for(const key of ['guilds','history'])assert.equal(c.dashboard[key].length,0,key);
 assert.equal(c.dashboard.snapshot,null);assert.equal(c.dashboard.me,null);assert.equal(c.dashboard.loginStatus,'expired');
});
