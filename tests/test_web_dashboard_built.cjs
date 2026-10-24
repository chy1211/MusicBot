"use strict";
const {test}=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),built=path.join(root,"musicbot/web/dist");
test("real Vite output includes PWA registration, manifest and current public resources",()=>{
 const html=fs.readFileSync(path.join(built,"index.html"),"utf8");assert.match(html,/type="module"/);
 const scripts=[...html.matchAll(/src="(\/assets\/[^" ]+\.js)"/g)];assert.ok(scripts.length);
 const code=scripts.map(m=>fs.readFileSync(path.join(built,m[1]),"utf8")).join("\n");
 assert.match(code,/serviceWorker/);assert.match(code,/\/sw\.js/);
 const manifest=JSON.parse(fs.readFileSync(path.join(built,"manifest.webmanifest"),"utf8"));
 assert.equal(manifest.name,"Music dashboard");assert.deepEqual([manifest.start_url,manifest.scope,manifest.display],["/","/","standalone"]);
 assert.deepEqual(new Set(manifest.icons.map(i=>i.sizes)),new Set(["any","192x192","512x512"]));
 for(const file of ["i18n.js","pwa.js","dashboard.css","offline.html","offline.css","offline.js","favicon.svg","icon-192.png","icon-512.png","apple-touch-icon.png","i18n/en.json","i18n/zh-TW.json"])
  assert.deepEqual(fs.readFileSync(path.join(built,file)),fs.readFileSync(path.join(root,"frontend/public",file)),file);
 assert.ok(fs.statSync(path.join(built,"sw.js")).size>0);
});
test("installed legacy shell stubs redirect to the canonical Vue entry only when needed",()=>{
 for(const file of ["i18n.js","pwa.js"]){const code=fs.readFileSync(path.join(built,file),"utf8");
  for(const app of [null,{}])for(const upgraded of [false,true]){const redirects=[],storage=new Map(upgraded?[["musicbot-shell-upgrade","1"]]:[]);vm.runInNewContext(code,{document:{getElementById:id=>{assert.equal(id,"app");return app}},sessionStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},location:{replace:url=>redirects.push(url)}});
   assert.deepEqual(redirects,app||upgraded?[]:["/"]);}
 }
});
