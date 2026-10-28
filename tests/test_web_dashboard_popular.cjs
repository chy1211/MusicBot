"use strict";
const {test}=require("node:test"),assert=require("node:assert/strict"),vue=require("vue");
const load=require("./dashboard_ts_fixture.cjs");
const song={title:"A",url:"https://example.test/a",count:5,duration:123};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve}};
const settle=async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve()};
function runtime(handler=async()=>({tracks:[song]})){
 const dashboard={guildId:"1",authenticated:true,connected:true,busy:false,epoch:0},requests=[],commands=[],notices=[];let changed;
 const imports={vue:{ref:vue.ref,computed:vue.computed,watch:(_,fn)=>changed=fn},
 '../store':{dashboard},'../api':{request:async(path,options)=>{requests.push({path,options});return handler(path,options)}},
 './useDashboard':{command:async(action,body)=>{commands.push({action,body});return{}},notice:(...args)=>notices.push(args)},
 './useLocale':{t:key=>key},'./useTrack':{safeURL:value=>{try{const u=new URL(value);return /^https?:$/.test(u.protocol)&&!u.username&&!u.password?value:""}catch{return""}}}};
 imports["./useAddToQueue"]=load("frontend/src/composables/useAddToQueue.ts",imports,{Error});
 const c=load("frontend/src/composables/usePopular.ts",imports,{Error});
 return{popular:c.usePopular(),dashboard,requests,commands,notices,changed:()=>changed()};
}
test("popular lists rank, count and duration through member API",async()=>{
 const a=runtime();await a.popular.load();assert.equal(a.requests[0].path,"/api/guilds/1/popular?period=7");
 assert.deepEqual({...a.popular.tracks.value[0]},song);assert.equal(a.popular.loading.value,false);
});
test("popular add resolves and confirms queue in one click",async()=>{
 const a=runtime(async()=>({results:[{kind:"track",allowed:true,url:song.url,preview_id:"token"}]}));await a.popular.add(song);
 assert.equal(a.requests[0].path,"/api/guilds/1/resolve");assert.deepEqual({...a.requests[0].options.body},{query:song.url,action:"play"});
 assert.deepEqual(JSON.parse(JSON.stringify(a.commands)),[{action:"play",body:{query:song.url,preview_id:"token"}}]);assert.equal(a.popular.adding.value,null);
});
test("period changes discard obsolete responses",async()=>{
 const pending=[];const a=runtime(()=>{const d=deferred();pending.push(d);return d.promise});const first=a.popular.load();a.popular.setPeriod("30");
 pending[1].resolve({tracks:[{...song,title:"new"}]});await settle();pending[0].resolve({tracks:[{...song,title:"obsolete"}]});await first;
 assert.equal(a.popular.period.value,"30");assert.equal(a.popular.tracks.value[0].title,"new");assert.equal(a.requests[1].path,"/api/guilds/1/popular?period=30");
});
test("popular failures show safe error without disconnecting playback",async()=>{
 const a=runtime(async()=>{throw new Error("safe fixture error")});await a.popular.load();assert.equal(a.popular.error.value,"safe fixture error");
 assert.equal(a.dashboard.connected,true);assert.equal(a.popular.tracks.value.length,0);assert.equal(a.commands.length,0);
});
test("reset clears popularity and invalidates stale buttons",async()=>{
 const pending=deferred(),a=runtime(()=>pending.promise);const add=a.popular.add(song);
 a.dashboard.authenticated=false;a.dashboard.epoch++;a.changed();await settle();pending.resolve({results:[{kind:"track",allowed:true,url:song.url,preview_id:"old"}]});await add;
 assert.equal(a.popular.tracks.value.length,0);assert.equal(a.commands.length,0);assert.equal(a.popular.adding.value,null);
});
test("popular view uses top 20 and handles empty period",async()=>{
 let empty=false;const a=runtime(async()=>({tracks:empty?[]:Array.from({length:25},(_,i)=>({...song,title:String(i)}))}));
 await a.popular.load();assert.equal(a.popular.tracks.value.length,20);assert.equal(a.popular.tracks.value[19].title,"19");
 empty=true;await a.popular.load();assert.equal(a.popular.empty.value,true);assert.equal(a.popular.tracks.value.length,0);
});
test("popular pending resolve prevents duplicate clicks and stale guild enqueue",async()=>{
 const pending=deferred(),a=runtime(()=>pending.promise);const first=a.popular.add(song);await a.popular.add(song);assert.equal(a.requests.length,1);
 a.dashboard.guildId="2";pending.resolve({results:[{kind:"track",allowed:true,url:song.url,preview_id:"old"}]});await first;
 assert.equal(a.commands.length,0);assert.equal(a.popular.adding.value,null);
});
test("popular resolve rejection and unavailable tracks restore button and explain error",async()=>{
 for(const handler of [async()=>{throw new Error("rejected")},async()=>({results:[{kind:"track",allowed:false,reason:"unavailable",url:song.url}]})]){
  const a=runtime(handler);await a.popular.add(song);assert.ok(a.popular.error.value);assert.equal(a.popular.adding.value,null);assert.equal(a.commands.length,0);assert.equal(a.notices.length,1);
 }
});
