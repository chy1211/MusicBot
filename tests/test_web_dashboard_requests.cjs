"use strict";
const {test}=require("node:test"),assert=require("node:assert/strict"),vue=require("vue"),load=require("./dashboard_ts_fixture.cjs");
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}};
const track={kind:"track",title:"A",url:"https://example.test/a",allowed:true,preview_id:"token"};
class APIError extends Error{constructor(message,status,body={}){super(message);this.status=status;this.body=body}}
function runtime(handler=async()=>({results:[track]}),commandHandler=async()=>({})){const dashboard={epoch:0,guildId:"1",authenticated:true,connected:true,busy:false},calls=[],commands=[],notices=[];let changed;
 const c=load("frontend/src/composables/useRequests.ts",{vue:{reactive:vue.reactive,watch:(_,fn)=>changed=fn},
 '../api':{APIError,request:async(path,options)=>{calls.push({path,options});return handler(path,options)}},
 '../store':{dashboard,usable:{get value(){return dashboard.authenticated&&dashboard.connected&&!dashboard.busy}}},
 './useDashboard':{command:async(action,body)=>{commands.push({action,body});return commandHandler(action,body)},notice:(...args)=>notices.push(args)},
 './useTrack':{songIdentity:value=>value||"",safeURL:value=>/^https?:/.test(value||"")?value:""},'./useLocale':{t:key=>key}},{Error});
 c.requests.query="  fixture query  ";return{...c,dashboard,calls,commands,notices,changed:()=>changed()};}
test("Vue lookup waits for explicit confirmation and retains its scoped token",async()=>{
 const a=runtime();await a.resolveQuery();assert.equal(a.commands.length,0);assert.equal(a.calls[0].options.body.query,"fixture query");
 await a.confirmPreview(a.requests.results[0]);assert.deepEqual(JSON.parse(JSON.stringify(a.commands)),[{action:"play",body:{query:track.url,preview_id:"token"}}]);assert.equal(a.requests.query,"");
});
test("Vue denied results cannot confirm either play action",async()=>{
 const a=runtime(async()=>({results:[{...track,allowed:false}]}));await a.resolveQuery();const song=a.requests.results[0];
 await a.confirmPreview(song);await a.confirmPreview(song,"playnext");assert.equal(a.commands.length,0);
});
test("Vue pending lookup blocks duplicates without locking playback state",async()=>{
 const d=deferred(),a=runtime(()=>d.promise),first=a.resolveQuery();await a.resolveQuery();assert.equal(a.calls.length,1);assert.equal(a.dashboard.busy,false);
 d.resolve({results:[track]});await first;assert.equal(a.requests.loading,false);
});
test("clearing or expiring Vue previews discards delayed query replies",async()=>{
 for(const expire of [false,true]){const d=deferred(),a=runtime(()=>d.promise),first=a.resolveQuery();
  if(expire){a.dashboard.epoch++;a.changed()}else a.clearPreview();d.resolve({results:[track]});await first;
  assert.equal(a.requests.results.length,0);assert.equal(a.requests.loading,false);if(expire)assert.equal(a.requests.query,"");
 }
});
test("Vue duplicate confirmation is blocked and failed confirmation retains retry token",async()=>{
 const d=deferred(),a=runtime(undefined,()=>d.promise);await a.resolveQuery();const song=a.requests.results[0],first=a.confirmPreview(song);
 await a.confirmPreview(song);assert.equal(a.commands.length,1);d.reject(new Error("fixture rejected"));await first;
 assert.equal(song.pending,false);assert.equal(song.preview_id,"token");assert.equal(a.requests.results.length,1);
});
test("Vue playlist defaults and select-all omit denied rows and preserve payload order",async()=>{
 const entries=[{item_id:"a",allowed:true},{item_id:"b",allowed:false},{item_id:"c",allowed:true,default_selected:false}];
 const a=runtime(async()=>({results:[{...track,kind:"playlist",entries}]}));await a.resolveQuery();const song=a.requests.results[0];assert.deepEqual(Array.from(song.selected),["a"]);
 a.selectPreview(song,false);await a.confirmPreview(song);assert.equal(a.commands.length,0);a.selectPreview(song,true);assert.deepEqual(Array.from(song.selected),["a","c"]);
 song.selected.reverse();await a.confirmPreview(song);assert.deepEqual(Array.from(a.commands[0].body.selected_items),["a","c"]);
});
test("Vue playnext-only lookup retries a play permission denial with playnext",async()=>{
 const a=runtime(async(_,options)=>{if(options.body.action==="play")throw new APIError("denied",403);return{results:[{...track,can_playnext:true}]}});
 await a.resolveQuery();assert.deepEqual(a.calls.map(x=>x.options.body.action),["play","playnext"]);await a.confirmPreview(a.requests.results[0],"playnext");assert.equal(a.commands[0].action,"playnext");
});
test("Vue lookup errors preserve the entered query and release loading state",async()=>{
 const a=runtime(async()=>{throw new APIError("fixture unavailable",500)});await a.resolveQuery();assert.equal(a.requests.error,"fixture unavailable");assert.equal(a.requests.query,"  fixture query  ");assert.equal(a.requests.loading,false);assert.equal(a.commands.length,0);
});
