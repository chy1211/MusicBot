"use strict";
const {test} = require("node:test"), assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const code = fs.readFileSync(path.join(__dirname, "../musicbot/web/sw.js"), "utf8");
function setup() {
  const handlers = {}, cache = new Map(), puts = [], fetches = [], deleted = [];
  let offline = false, skipped = 0, claimed = 0;
  const store = {put: async (key,response) => {puts.push(key);cache.set(key,response);}, match: async key => cache.get(key)};
  const context = {URL, Request: class { constructor(url,options) {this.url = url;Object.assign(this,options);} }, Response,
    self: {location:{origin:"https://music.example.com"}, addEventListener:(name,fn)=>handlers[name]=fn,
      skipWaiting:async()=>skipped++, clients:{claim:async()=>claimed++}},
    caches:{open:async()=>store, match:async key=>cache.get(key),
      keys:async()=>["musicbot-dashboard-old","unrelated","musicbot-dashboard-r7-1"], delete:async key=>deleted.push(key)},
    fetch:async request=>{fetches.push(request);if(offline)throw new Error("offline");return new Response("network",{status:200});}};
  vm.runInNewContext(code,context);
  async function event(name, request) {
    let result, intercept = false; const pending = [];
    handlers[name]({request,waitUntil:p=>pending.push(p),respondWith:p=>{intercept=true;result=p;}});
    if (result) result = await result;
    await Promise.all(pending);
    return {intercept,result};
  }
  const request = (pathname, extra={}) => ({url:"https://music.example.com"+pathname,method:"GET",
    headers:{get:()=>""},...extra});
  return {event,request,cache,puts,fetches,deleted,setOffline:v=>offline=v,counts:()=>[skipped,claimed]};
}
test("install precaches only explicit static assets and activates version cleanup",async()=>{
  const a=setup();await a.event("install");await a.event("activate");
  assert.ok(a.puts.includes("/")&&a.puts.includes("/icon-512.png"));
  assert.ok(a.puts.every(key=>!key.startsWith("/api")&&!key.startsWith("/auth")&&!key.includes("events")));
  assert.deepEqual(a.deleted,["musicbot-dashboard-old"]);assert.deepEqual(a.counts(),[1,1]);
  assert.ok(a.fetches.every(r=>r.credentials==="omit"));
});
test("never intercept API, auth, events, nonstatic, foreign origin or writes",async()=>{
  const a=setup();
  for(const url of ["/api","/api/guilds","/api/guilds/1/events","/auth","/auth/session","/auth/callback?code=secret","/events","/demo-login/owner","/other","/?code=secret","/dashboard.js?token=secret"]) {
    assert.equal((await a.event("fetch",a.request(url))).intercept,false,url);
  }
  assert.equal((await a.event("fetch",a.request("/dashboard.js",{method:"POST"}))).intercept,false);
  assert.equal((await a.event("fetch",a.request("/dashboard.js",{headers:{get:()=>"text/event-stream"}}))).intercept,false);
  assert.equal((await a.event("fetch",a.request("/dashboard.js",{url:"https://other.test/dashboard.js"}))).intercept,false);
  assert.equal(a.fetches.length,0);assert.equal(a.puts.length,0);
});
test("HTML network first and offline fallback is a simple offline page",async()=>{
  const a=setup();a.cache.set("/",new Response("old shell"));a.cache.set("/offline.html",new Response("currently offline"));
  let result=await a.event("fetch",a.request("/"));
  assert.equal(await result.result.text(),"network");
  a.setOffline(true);result=await a.event("fetch",a.request("/"));
  assert.equal(await result.result.text(),"currently offline");
});
test("static stale while revalidate returns cache and refreshes versioned asset",async()=>{
  const a=setup();a.cache.set("/dashboard.js",new Response("cached"));
  const result=await a.event("fetch",a.request("/dashboard.js?v=r7-1"));
  assert.equal(await result.result.text(),"cached");
  assert.equal(await a.cache.get("/dashboard.js").text(),"network");
  a.setOffline(true);a.cache.set("/dashboard.css",new Response("offline css"));
  const offline=await a.event("fetch",a.request("/dashboard.css"));
  assert.equal(await offline.result.text(),"offline css");
});
