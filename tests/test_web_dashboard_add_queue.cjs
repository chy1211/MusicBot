"use strict";
const {test}=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vue=require("vue");
const {compile}=require("@vue/compiler-dom"),load=require("./dashboard_ts_fixture.cjs");
const track={title:"A",url:"https://example.test/a"};
const candidate={...track,kind:"track",allowed:true,preview_id:"scoped-token"};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}};
const settle=async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve()};
function runtime(handler=async()=>({results:[candidate]}),commandHandler=async()=>({})){
 const dashboard={guildId:"1",authenticated:true,connected:true,busy:false,epoch:0,resolutionState:"queued"},calls=[],commands=[],notices=[];
 const c=load("frontend/src/composables/useAddToQueue.ts",{
  vue, "../store":{dashboard},
  "../api":{request:async(path,options)=>{calls.push({path,options});return handler(path,options)}},
  "./useDashboard":{command:async(action,body)=>{commands.push({action,body});return commandHandler(action,body)},notice:(...args)=>notices.push(args)},
  "./useLocale":{t:key=>key},
  "./useTrack":{safeURL:value=>{try{const u=new URL(value);return /^https?:$/.test(u.protocol)&&!u.username&&!u.password?value:""}catch{return""}}}
 },{Error});
 const error=vue.ref("");
 return{queue:c.useAddToQueue(error),other:c.useAddToQueue(),error,dashboard,calls,commands,notices};
}
test("one-click queue add resolves then plays only an allowed scoped track",async()=>{
 const canonical={...candidate,url:"https://example.test/canonical"};
 const a=runtime(async()=>({results:[{...candidate,allowed:false},{...candidate,kind:"playlist"},canonical]}));
 a.dashboard.guildId="guild/1";await a.queue.add(track);
 assert.equal(a.calls.length,1);assert.equal(a.calls[0].path,"/api/guilds/guild%2F1/resolve");
 assert.equal(a.calls[0].options.method,"POST");
 assert.deepEqual({...a.calls[0].options.body},{query:track.url,action:"play"});
 assert.deepEqual(JSON.parse(JSON.stringify(a.commands)),[{action:"play",body:{query:canonical.url,preview_id:canonical.preview_id}}]);
 assert.equal(a.queue.adding.value,null);assert.equal(a.error.value,"");assert.deepEqual(a.notices,[["m0121"]]);
});
test("unavailable or unusable candidates explain the failure without playing",async()=>{
 for(const results of [[],[{...candidate,allowed:false,reason:"blocked by policy"}],[{...candidate,kind:"playlist"}],[{...candidate,preview_id:""}],[{...candidate,url:"javascript:alert(1)"}]]){
  const a=runtime(async()=>({results}));await a.queue.add(track);
  assert.equal(a.commands.length,0);assert.equal(a.queue.adding.value,null);
  assert.equal(a.error.value,results[0]?.reason||"m0613");assert.deepEqual(a.notices,[["m0121"],[a.error.value,true]]);
 }
});
test("resolve and play failures use the existing error notice and release the lock",async()=>{
 for(const failAt of ["resolve","play"]){
  const fail=async()=>{throw new Error("fixture "+failAt+" denied")};
  const a=runtime(failAt==="resolve"?fail:undefined,failAt==="play"?fail:undefined);
  await a.queue.add(track);assert.equal(a.queue.adding.value,null);assert.equal(a.error.value,"fixture "+failAt+" denied");
  assert.deepEqual(a.notices,[["m0121"],[a.error.value,true]]);assert.equal(a.commands.length,failAt==="play"?1:0);
 }
});
test("all consumers share one lock through both resolve and play",async()=>{
 const resolve=deferred(),play=deferred(),a=runtime(()=>resolve.promise,()=>play.promise);
 const first=a.queue.add(track);
 assert.equal(a.other.adding.value,track.url);assert.equal(a.queue.resolutionState.value,"queued");
 await a.queue.add(track);await a.other.add({...track,url:"https://example.test/b"});assert.equal(a.calls.length,1);
 a.calls[0].options.onResolutionState("resolving");assert.equal(a.other.resolutionState.value,"resolving");
 resolve.resolve({results:[candidate]});await settle();
 assert.equal(a.commands.length,1);assert.equal(a.queue.adding.value,track.url);
 await a.other.add(track);assert.equal(a.calls.length,1);
 play.resolve({});await first;assert.equal(a.other.adding.value,null);
 await a.other.add(track);assert.equal(a.calls.length,2);assert.equal(a.commands.length,2);
});
test("inactive sessions, busy commands, missing guilds and unsafe URLs cannot enqueue",async()=>{
 for(const state of [{authenticated:false},{connected:false},{busy:true},{guildId:""}]){
  const a=runtime();Object.assign(a.dashboard,state);await a.queue.add(track);assert.equal(a.calls.length,0);
 }
 for(const url of ["","javascript:alert(1)","https://user:secret@example.test/a"]){
  const a=runtime();await a.queue.add({url});assert.equal(a.calls.length,0);
 }
});
test("session, guild, authentication or connection changes discard delayed resolves",async()=>{
 for(const state of [{epoch:1},{guildId:"2"},{authenticated:false},{connected:false}]){
  const pending=deferred(),a=runtime(()=>pending.promise),first=a.queue.add(track);
  Object.assign(a.dashboard,state);pending.resolve({results:[candidate]});await first;
  assert.equal(a.commands.length,0);assert.deepEqual(a.notices,[["m0121"]]);assert.equal(a.queue.adding.value,null);
 }
});
test("stale progress and stale resolve failures do not update the new session",async()=>{
 for(const state of [{epoch:1},{guildId:"2"}]){
  const pending=deferred(),a=runtime(()=>pending.promise),first=a.queue.add(track);
  Object.assign(a.dashboard,state);a.calls[0].options.onResolutionState("resolving");
  pending.reject(new Error("old failure"));await first;
  assert.equal(a.queue.resolutionState.value,"queued");assert.deepEqual(a.notices,[["m0121"]]);assert.equal(a.error.value,"");
 }
});
test("a command becoming busy during resolve reports the existing retry notice",async()=>{
 const pending=deferred(),a=runtime(()=>pending.promise),first=a.queue.add(track);
 a.dashboard.busy=true;pending.resolve({results:[candidate]});await first;
 assert.equal(a.commands.length,0);assert.deepEqual(a.notices,[["m0121"],["m0614",true]]);assert.equal(a.queue.adding.value,null);
});

// Render the actual two list templates as VNodes so their click handlers and
// disabled/progress bindings are exercised without a browser or backend.
const source=fs.readFileSync(path.resolve(__dirname,"../frontend/src/views/PlayView.vue"),"utf8");
const lists=["history-list"].map(id=>{
 const start=source.indexOf('<ol id="'+id+'"');
 assert.ok(start>=0,id);return source.slice(start,source.indexOf("</ol>",start)+5);
});
const render=new Function("Vue",compile("<div>"+lists.join("")+"</div>").code)({...vue,resolveComponent:name=>name});
function nodes(value){
 if(!value||typeof value!=="object")return[];
 return[value,...(Array.isArray(value.children)?value.children.flatMap(nodes):[])];
}
function buttons(a,history=[track]){
 const context={
  dashboard:{...a.dashboard,history},historyQueue:a.queue,usable:!a.dashboard.busy,requests:{loading:false},
  t:key=>key,safeURL:value=>value,songLinkURL:value=>value,duration:()=>"",playedTime:()=>"",
  library:{busy:{value:false},openSave:()=>{},isSaved:()=>false}
 };
 return nodes(render(context,[])).filter(node=>node.type==="button"&&node.props?.["aria-label"]?.startsWith("m0612 "));
}
test("the single recently played list enqueues directly and exposes disabled progress",async()=>{
 const pending=deferred(),a=runtime(()=>pending.promise),history=[track,{title:"B",url:"https://example.test/b"}];
 let rows=buttons(a,history);assert.equal(rows.length,2);
 for(const row of rows){assert.equal(row.props.disabled,false);assert.equal(row.props["aria-busy"],false);assert.equal(row.children,"m0612")}
 const first=rows[0].props.onClick();
 rows=buttons(a,history);
 for(const row of rows)assert.equal(row.props.disabled,true);
 for(const row of [rows[0]]){assert.equal(row.props["aria-busy"],true);assert.equal(row.children,"resolve.queued")}
 await rows[0].props.onClick();assert.equal(a.calls.length,1);
 a.calls[0].options.onResolutionState("resolving");
 assert.equal(buttons(a,history)[0].children,"resolve.adding");
 pending.resolve({results:[candidate]});await first;assert.equal(a.commands.length,1);
 rows=buttons(a,history);for(const row of rows){assert.equal(row.props.disabled,false);assert.equal(row.children,"m0612")}
 await rows[0].props.onClick();assert.equal(a.commands.length,2);assert.equal(a.calls.length,2);
});
test("recently played buttons reuse the bilingual queue label",()=>{
 const en=require("../frontend/public/i18n/en.json"),zh=require("../frontend/public/i18n/zh-TW.json");
 assert.equal(en.m0612,"Add to queue");assert.equal(zh.m0612,"\u52a0\u5165\u4f47\u5217");
});
