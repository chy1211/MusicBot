'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),vue=require('vue');
const load=require('./dashboard_ts_fixture.cjs');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}};
const flush=async()=>{for(let n=0;n<12;n++)await Promise.resolve()};

test('a timed-out resolution poll retries with a new signal and POST completion stops all polls',async()=>{
 let now=0,id=0;const timers=new Map(),polls=[],post=deferred();let postSignal;
 const setTimeout=(fn,delay)=>{const key=++id;timers.set(key,{at:now+delay,fn});return key};
 const clearTimeout=key=>timers.delete(key);
 const advance=async duration=>{const until=now+duration;for(;;){const entry=[...timers].filter(([,v])=>v.at<=until).sort((a,b)=>a[1].at-b[1].at)[0];if(!entry)break;now=entry[1].at;timers.delete(entry[0]);entry[1].fn();await flush()}now=until;await flush()};
 const fetch=async(path,options)=>{
  if(!path.includes('/resolution-status')){postSignal=options.signal;return post.promise}
  polls.push(options.signal);return new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')),{once:true}));
 };
 const api=load('frontend/src/api.ts',{'./store':{dashboard:{authMode:'discord'},expireSession:()=>{}},'./composables/useLocale':{t:x=>x,locale:{value:'en'}}},
  {AbortController,DOMException,fetch,setTimeout,clearTimeout,crypto:require('node:crypto').webcrypto});
 const result=api.request('/api/guilds/1/resolve',{method:'POST',body:{query:'fixture'},onResolutionState:()=>{}});
 await advance(100);assert.equal(polls.length,1);
 await advance(3000);assert.equal(polls[0].aborted,true);assert.equal(postSignal.aborted,false);
 await advance(200);assert.equal(polls.length,2);assert.notEqual(polls[0],polls[1]);assert.equal(polls[1].aborted,false);
 post.resolve({ok:true,json:async()=>({results:[]})});await result;await flush();
 assert.equal(polls[1].aborted,true);assert.equal(timers.size,0);
 await advance(10000);assert.equal(polls.length,2);
});

test('playback clock runs only when visible and playing and removes every listener on unmount',()=>{
 const mounted=[],unmounted=[],watchers=[],timers=new Map();let id=0,now=1000;
 function target(){const listeners=new Map();return{listeners,addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:(name,fn)=>{if(listeners.get(name)===fn)listeners.delete(name)},emit:name=>listeners.get(name)?.()}}
 const document={...target(),hidden:false,body:{classList:{remove:()=>{},add:()=>{}}}},window=target();
 const dashboard={connected:false,snapshot:{status:'stopped',progress:10,current:{duration:300}},stateAt:1000};
 const runtime=load('frontend/src/composables/usePlayback.ts',{
  vue:{...vue,watch:(_,fn)=>{watchers.push(fn);return()=>{}},onMounted:fn=>mounted.push(fn),onBeforeUnmount:fn=>unmounted.push(fn)},
  '../store':{dashboard,currentTrackKey:vue.ref('track'),usable:vue.ref(true)},'./useDashboard':{run:()=>{}}
 },{document,window,Date:{now:()=>now},setInterval:fn=>{const key=++id;timers.set(key,fn);return key},clearInterval:key=>timers.delete(key)});
 runtime.usePlayback();mounted.forEach(fn=>fn());assert.equal(timers.size,0);
 dashboard.connected=true;dashboard.snapshot.status='playing';watchers[2]();assert.equal(timers.size,1);
 document.hidden=true;now=5000;document.emit('visibilitychange');assert.equal(timers.size,0);
 document.hidden=false;now=9000;document.emit('visibilitychange');assert.equal(timers.size,1);assert.equal(runtime.clock.value,9000);
 dashboard.snapshot.status='paused';watchers[2]();assert.equal(timers.size,0);
 dashboard.snapshot.status='playing';watchers[2]();assert.equal(timers.size,1);
 unmounted.forEach(fn=>fn());assert.equal(timers.size,0);assert.equal(document.listeners.size,0);assert.equal(window.listeners.size,0);
});

test('binary lyric lookup preserves last equal timestamp and offset/seek semantics',()=>{
 const progress=vue.ref(0),clock=vue.ref(0),player=vue.reactive({preview:null});
 const runtime=load('frontend/src/composables/useLyrics.ts',{
  vue:{...vue,watch:()=>{},nextTick:async()=>{}},'../api':{request:()=>{},APIError:class extends Error{}},
  '../store':{dashboard:{},currentTrackKey:vue.ref('track')},'./usePlayback':{progress,clock,player},
  './useDashboard':{notice:()=>{}},'./useLocale':{t:x=>x}
 },{setTimeout:()=>0,clearTimeout:()=>{}});
 const times=[0,1,1,2,7,7,10];runtime.lyrics.lines=times.map((time,index)=>({time,text:'line '+index}));
 for(const offset of [0,2,-3])for(const position of [-1,0,1,1.5,7,20]){
  runtime.lyrics.offset=offset;progress.value=position;player.preview=null;
  let expected=-1;times.forEach((time,index)=>{if(time<=position-offset)expected=index});
  assert.equal(runtime.activeLine.value,expected);
  player.preview=position+2;expected=-1;times.forEach((time,index)=>{if(time<=position+2-offset)expected=index});
  assert.equal(runtime.activeLine.value,expected);
 }
 runtime.lyrics.lines=[];assert.equal(runtime.activeLine.value,-1);
});

test('leaving popular invalidates an in-flight result without cancelling queue actions',async()=>{
 const pending=deferred(),dashboard={guildId:'1',authenticated:true,connected:true,epoch:0};
 const state=load('frontend/src/composables/usePopular.ts',{
  vue:{...vue,watch:()=>{}},'../store':{dashboard},'../api':{request:()=>pending.promise},
  './useDashboard':{notice:()=>{}},'./useLocale':{t:x=>x},'./useTrack':{safeURL:x=>x},
  './useAddToQueue':{useAddToQueue:()=>({adding:vue.ref(null),resolutionState:vue.ref(null),add:()=>{}})}
 },{Error});
 const popular=state.usePopular(),first=popular.load();popular.cancelLoad();
 pending.resolve({tracks:[{title:'Old view result',url:'https://example.test/old'}]});await first;
 assert.equal(popular.tracks.value.length,0);assert.equal(popular.loading.value,false);
});
