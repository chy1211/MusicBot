"use strict";
const {test} = require("node:test"), assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../frontend/src/sw.ts"), "utf8");
const injected = [
  {url:"/"}, {url:"/offline.html"}, {url:"/index.html"}, {url:"/icon-192.png"},
  {url:"/icon-512.png"}, {url:"/assets/app.js"}, {url:"/assets/app.css"},
  {url:"/catalog.json"}
];
const versionSource = fs.readFileSync(path.join(__dirname, "../frontend/src/version.ts"), "utf8");
const version = versionSource.match(/export const SW_VERSION = "([^"]+)"/)[1];
const code = source.replace('import {SW_VERSION as VERSION} from "./version";', `const VERSION = ${JSON.stringify(version)};`).replace("self.__WB_MANIFEST", JSON.stringify(injected));
function setup() {
  const handlers = {}, cache = new Map(), puts = [], fetches = [], deleted = [];
  let offline = false, skipped = 0, claimed = 0, failPath = null, quota = false;
  const cacheNames = ["musicbot-dashboard-old", "unrelated", version];
  const store = {
    put: async (key,response) => {
      puts.push(key);
      if (quota) throw new Error("quota exceeded");
      cache.set(key,response);
    },
    match: async key => cache.get(key)
  };
  const context = {
    URL, Request: class { constructor(url,options) {this.url = url;Object.assign(this,options);} }, Response,
    self: {location:{origin:"https://music.example.test"}, __WB_MANIFEST:injected,
      addEventListener:(name,fn)=>handlers[name]=fn,
      skipWaiting:async()=>skipped++, clients:{claim:async()=>claimed++}},
    caches:{
      open:async()=>store, match:async key=>cache.get(key),
      keys:async()=>cacheNames.slice(),
      delete:async key=>{deleted.push(key);const index=cacheNames.indexOf(key);if(index>=0)cacheNames.splice(index,1);return true;}
    },
    fetch:async request=>{
      fetches.push(request);
      if (offline || request.url === failPath || "https://music.example.test" + request.url === failPath) throw new Error("network failure");
      return new Response("network",{status:200});
    }
  };
  vm.runInNewContext(code,context);
  async function event(name, request) {
    let result, intercept = false; const pending = [];
    handlers[name]({request,waitUntil:p=>pending.push(p),respondWith:p=>{intercept=true;result=p;}});
    if (result) result = await result;
    await Promise.all(pending);
    return {intercept,result};
  }
  const request = (pathname, extra={}) => ({url:"https://music.example.test"+pathname,method:"GET",
    headers:{get:()=>""},...extra});
  return {
    event,request,cache,puts,fetches,deleted,cacheNames,
    setOffline:v=>offline=v,setFailPath:v=>failPath=v,setQuota:v=>quota=v,
    counts:()=>[skipped,claimed]
  };
}

test("install precaches injected public assets and activation removes old app caches",async()=>{
  const a=setup();await a.event("install");await a.event("activate");
  assert.ok(a.puts.includes("/")&&a.puts.includes("/icon-512.png"));
  assert.ok(a.puts.includes("/offline.html"));
  assert.ok(a.puts.every(key=>!key.startsWith("/api")&&!key.startsWith("/auth")&&!key.includes("events")&&!key.includes("secret")));
  assert.deepEqual(a.deleted,["musicbot-dashboard-old"]);assert.deepEqual(a.counts(),[1,1]);
  assert.ok(a.fetches.every(r=>r.credentials==="omit"));
});
test("never intercept API, auth, events, nonstatic, foreign origin, secrets or writes",async()=>{
  const a=setup();
  for(const url of ["/api","/api/guilds","/api/guilds/1/events","/auth","/auth/session","/auth/callback?code=secret","/events","/demo-login/owner","/other","/?code=secret","/assets/app.js?token=secret","/unknown.js"]) {
    assert.equal((await a.event("fetch",a.request(url))).intercept,false,url);
  }
  assert.equal((await a.event("fetch",a.request("/assets/app.js",{method:"POST"}))).intercept,false);
  assert.equal((await a.event("fetch",a.request("/assets/app.js",{headers:{get:()=>"text/event-stream"}}))).intercept,false);
  assert.equal((await a.event("fetch",a.request("/assets/app.js",{url:"https://foreign.test/assets/app.js"}))).intercept,false);
  assert.equal(a.fetches.length,0);assert.equal(a.puts.length,0);
});
test("HTML network first and offline fallback is the installed offline page",async()=>{
  const a=setup();a.cache.set("/",new Response("old shell"));a.cache.set("/offline.html",new Response("currently offline"));
  let result=await a.event("fetch",a.request("/"));
  assert.equal(await result.result.text(),"network");
  a.setOffline(true);result=await a.event("fetch",a.request("/"));
  assert.equal(await result.result.text(),"currently offline");
});
test("static stale while revalidate serves cache and refreshes versioned asset",async()=>{
  const a=setup();a.cache.set("/assets/app.js",new Response("cached"));
  const result=await a.event("fetch",a.request("/assets/app.js?v=r7-2"));
  assert.equal(await result.result.text(),"cached");
  assert.equal(await a.cache.get("/assets/app.js").text(),"network");
  a.setOffline(true);a.cache.set("/assets/app.css",new Response("offline css"));
  const offline=await a.event("fetch",a.request("/assets/app.css"));
  assert.equal(await offline.result.text(),"offline css");
});
test("failed install deletes the incomplete new cache and does not replace working version",async()=>{
  const a=setup();a.setFailPath("https://music.example.test/assets/app.css");
  await assert.rejects(a.event("install"),/network failure/);
  assert.ok(a.deleted.includes(version));
  assert.deepEqual(a.counts(),[0,0]);
});
test("cache quota failures do not hide successful network responses",async()=>{
  const a=setup();a.setQuota(true);
  const result=await a.event("fetch",a.request("/assets/app.js"));
  assert.equal(result.intercept,true);
  assert.equal(await result.result.text(),"network");
  const html=await a.event("fetch",a.request("/"));
  assert.equal(await html.result.text(),"network");
});


test("acknowledged cache sweep removes stale caches recreated after activation",async()=>{
  const a=setup();await a.event("activate");
  a.cacheNames.push("musicbot-dashboard-r26-lyrics-popular");
  let acknowledgement;const pending=[];const handlers={};
  const ctx={URL,Request:class {constructor(url,options){this.url=url;Object.assign(this,options);}},Response,
    self:{location:{origin:"https://music.example.test"},__WB_MANIFEST:injected,
      addEventListener:(name,fn)=>handlers[name]=fn,skipWaiting:async()=>{},clients:{claim:async()=>{}}},
    caches:{open:async()=>({put:async()=>{},match:async()=>undefined}),match:async()=>undefined,
      keys:async()=>a.cacheNames.slice(),delete:async key=>{a.deleted.push(key);const i=a.cacheNames.indexOf(key);if(i>=0)a.cacheNames.splice(i,1);return true;}},
    fetch:async()=>new Response("ok")};
  vm.runInNewContext(code,ctx);
  handlers.message({data:{type:"musicbot-cache-sweep"},ports:[{postMessage:value=>acknowledgement=value}],
    waitUntil:promise=>pending.push(promise)});
  await Promise.all(pending);
  assert.deepEqual(a.deleted,["musicbot-dashboard-old","musicbot-dashboard-r26-lyrics-popular"]);
  assert.equal(acknowledgement.type,"musicbot-cache-sweep-complete");
  assert.equal(acknowledgement.version,version);
  assert.ok(!a.cacheNames.some(name=>name.startsWith("musicbot-dashboard-")&&name!==version));
});
