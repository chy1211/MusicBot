"use strict";
const {test}=require("node:test"),assert=require("node:assert/strict"),vue=require("vue");
const load=require("./dashboard_ts_fixture.cjs");
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();await vue.nextTick();};
test("health refresh is single-flight, timestamps successful samples and clears failed samples",async()=>{
 const dashboard=vue.reactive({authenticated:true,guildId:"1",snapshot:{guild_id:"1"}});
 let release,blocking=false,failed=false,count=0;const callbacks=[];
 const request=async path=>{
  if(path==="/api/library")return {owner:true};
  if(path.includes("maintenance")){
   count++;if(failed)throw new Error("health unavailable");
   if(blocking)await new Promise(resolve=>release=resolve);
   return {audio:{state:"playing",capacity_ms:1000}};
  }
  if(path.includes("autoplaylist"))return {tracks:[]};
  if(path.includes("notification-channel"))return {channels:[],channel_id:null};
  if(path.includes("empty-queue"))return {empty_queue:"off"};
  return {enabled:true};
 };
 const module=load("frontend/src/composables/useAdmin.ts",{vue:{...vue,onBeforeUnmount:fn=>callbacks.push(fn)},"../api":{request,APIError:class extends Error{}},"../store":{dashboard},"./useLocale":{t:key=>key},"./useDashboard":{notice:()=>{}},"./useLyrics":{toggleLyrics:()=>{}}},{Error});
 const scope=vue.effectScope();let a;scope.run(()=>a=module.useAdmin());
 try{
  await flush();assert.ok(a.maintenanceUpdatedAt.value>0);
  blocking=true;const before=count,pending=a.loadMaintenance();await flush();
  await a.loadMaintenance();assert.equal(count,before+1);
  release();await pending;blocking=false;failed=true;
  await assert.rejects(a.loadMaintenance());assert.equal(a.maintenanceUpdatedAt.value,0);assert.equal(a.maintenance.value,null);
  dashboard.authenticated=false;await flush();assert.equal(a.maintenanceUpdatedAt.value,0);
 }finally{for(const fn of callbacks)fn();scope.stop();}
});
