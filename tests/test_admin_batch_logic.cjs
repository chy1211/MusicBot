"use strict";
const {test}=require("node:test"),assert=require("node:assert/strict");
const vue=require("vue"),load=require("./dashboard_ts_fixture.cjs");
const flush=async()=>{for(let i=0;i<10;i++)await Promise.resolve();await vue.nextTick();};

function fixture(handler) {
 const dashboard=vue.reactive({authenticated:true,guildId:"1",snapshot:{guild_id:"1",lyrics_available:true}});
 const calls=[],cleanups=[];
 const request=async(path,options={})=>{calls.push([path,options]);return handler(path,options);};
 class APIError extends Error {constructor(status){super("safe failure");this.status=status;}}
 const module=load("frontend/src/composables/useAdmin.ts",{
  vue:{...vue,onBeforeUnmount:fn=>cleanups.push(fn)},"../api":{APIError,request},"../store":{dashboard},
  "./useLocale":{t:key=>key},"./useDashboard":{notice:()=>{}},"./useLyrics":{toggleLyrics:()=>{}}
 },{Error});
 const scope=vue.effectScope();let admin;scope.run(()=>admin=module.useAdmin());
 return {admin,dashboard,calls,close:()=>{for(const fn of cleanups)fn();scope.stop();}};
}
function defaults(path) {
 if(path==="/api/library")return {owner:true};
 if(path.endsWith("lyrics")||path.endsWith("vote-skip"))return {enabled:true};
 if(path.endsWith("notification-channel"))return {channel_id:null,channels:[]};
 if(path.endsWith("empty-queue"))return {empty_queue:"off",radio_min_seconds:0,radio_max_seconds:0};
 if(path.includes("autoplaylist?"))return {tracks:[],page:1,revision:"example"};
 return {};
}
test("failed independent loads do not permit saves or hide successful settings",async()=>{
 const f=fixture(path=>{if(path.endsWith("lyrics"))throw new Error("lyrics unavailable");return defaults(path);});
 try {
  await flush();assert.equal(f.admin.loading.value,false);assert.equal(f.admin.lyricsLoaded.value,false);
  assert.ok(f.admin.notify.value);assert.equal(f.admin.voteSkipLoaded.value,true);
  assert.match(f.admin.lyricsStatus.value,/lyrics unavailable/);
  await f.admin.saveLyrics(false);assert.equal(f.calls.filter(([,o])=>o.method==="POST").length,0);
 }finally{f.close();}
});
test("late old guild responses cannot repopulate the selected guild",async()=>{
 let release;
 const blocked=new Promise(resolve=>release=resolve);
 const f=fixture(path=>path.includes("/guilds/1/")?blocked.then(()=>defaults(path)):defaults(path));
 try {
  await flush();f.dashboard.guildId="2";f.dashboard.snapshot={guild_id:"2"};await flush();
  assert.equal(f.admin.lyricsLoaded.value,true);assert.equal(f.admin.loading.value,false);
  release({enabled:false,channel_id:"stale",channels:[]});await flush();
  assert.equal(f.admin.lyricsEnabled.value,true);assert.equal(f.admin.notify.value.channel_id,null);
  assert.equal(f.admin.voteSkip.value,true);
 }finally{release?.({});f.close();}
});
test("logout immediately invalidates loaded settings and prevents writes",async()=>{
 const f=fixture(defaults);
 try {
  await flush();assert.equal(f.admin.lyricsLoaded.value,true);
  f.dashboard.authenticated=false;await flush();
  assert.equal(f.admin.lyricsLoaded.value,false);assert.equal(f.admin.voteSkipLoaded.value,false);
  assert.equal(f.admin.notify.value,null);await f.admin.saveVoteSkip(false);
  assert.equal(f.calls.filter(([,o])=>o.method==="POST").length,0);
 }finally{f.close();}
});
