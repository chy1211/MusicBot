"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const css = fs.readFileSync(path.join(__dirname, "../musicbot/web/dashboard.css"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "../musicbot/web/index.html"), "utf8");
test("brand centers icon and label as one flex group", () => {
  assert.match(html, /class="brand-icon"/); assert.match(html, /class="brand-label"/);
  assert.match(css, /\.sidebar \.brand\{display:flex;align-items:center;justify-content:center/);
  assert.match(css, /\.brand \.brand-icon\{display:block;line-height:1/);
});
test("phone brand spans the full navigation row", () => {
  assert.match(css, /\.sidebar \.brand\{grid-column:1\/-1;grid-row:1/);
});

test("page switches reserve scrollbar space and fixed tab geometry", () => {
  assert.match(css, /html\{overflow-y:scroll;scrollbar-gutter:stable\}/);
  assert.match(css, /\.page-tabs\{display:grid;grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(css, /\.page-tabs button\{[^}]*height:44px;[^}]*white-space:nowrap/);
  assert.match(css, /\.page-tabs button:hover:enabled\{transform:none\}/);
});
test("loading a navigation page preserves its label without inserting a spinner", () => {
  const vm = require("node:vm");
  const source = fs.readFileSync(path.join(__dirname, "../musicbot/web/dashboard.js"), "utf8");
  const snippet = source.slice(source.indexOf("function buttonBusy"), source.indexOf("function safeURL"));
  const active = {}, attrs = {};
  const button = {id: "nav-library", textContent: "我的歌單", dataset: {},
    classList: {toggle: (name, value) => { active[name] = value; }},
    setAttribute: (name, value) => { attrs[name] = value; }};
  const context = vm.createContext({button}); vm.runInContext(snippet, context);
  vm.runInContext("buttonBusy(button, true)", context);
  assert.equal(button.textContent, "我的歌單"); assert.equal(active["is-loading"], false);
  assert.equal(attrs["aria-busy"], "true");
  vm.runInContext("buttonBusy(button, false)", context);
  assert.equal(button.textContent, "我的歌單");
});

test("initial server respects URL, recommendation, browser and first choice", () => {
  const vm = require("node:vm");
  const source = fs.readFileSync(path.join(__dirname, "../musicbot/web/dashboard.js"), "utf8");
  const snippet = source.slice(source.indexOf("function rememberGuild"), source.indexOf("async function connect"));
  const data = {guilds:[{id:"1"},{id:"2"}], recommended_guild_id:"2"};
  const window = {location:{href:"https://music.example.com/?guild=1"},localStorage:{getItem:()=>"1",setItem(){}}};
  const c = vm.createContext({window,URL,manualGuild:"",data}); vm.runInContext(snippet,c);
  assert.equal(vm.runInContext("initialGuild(data)",c),"1");
  window.location.href="https://music.example.com/";
  assert.equal(vm.runInContext("initialGuild(data)",c),"2");
  data.recommended_guild_id=null;
  assert.equal(vm.runInContext("initialGuild(data)",c),"1");
  window.localStorage.getItem=()=>{throw new Error("blocked")};
  assert.equal(vm.runInContext("initialGuild(data)",c),"1");
  window.localStorage.setItem=()=>{throw new Error("blocked")};
  assert.doesNotThrow(()=>vm.runInContext('rememberGuild("2")',c));
  c.manualGuild="2"; window.location.href="https://music.example.com/?guild=1";
  assert.equal(vm.runInContext("initialGuild(data)",c),"2");
  c.manualGuild="99"; window.location.href="https://music.example.com/?guild=99";
  assert.equal(vm.runInContext("initialGuild(data)",c),"1");
});

test("glass provides both themes, prefixed blur and opaque accessibility fallbacks", () => {
  assert.match(css, /backdrop-filter:blur\(var\(--glass-blur\)\) saturate\(160%\) brightness\(var\(--dim,1\)\)/);
  assert.match(css, /-webkit-backdrop-filter:blur\(var\(--glass-blur\)\) saturate\(160%\) brightness\(var\(--dim,1\)\)/);
  assert.match(css, /@media\(prefers-color-scheme:light\)/);
  assert.match(css, /@supports not \(backdrop-filter:blur\(1px\)\)/);
  assert.match(css, /@media\(prefers-reduced-transparency:reduce\)/);
  assert.match(css, /@media\(prefers-reduced-motion:reduce\)/);
  assert.match(css, /\.card,\.now-playing\{[^}]*backdrop-filter:none/);
  assert.doesNotMatch(css, /radial-gradient\([^)]*\)[^;]*var\(--bg\)/);
  assert.doesNotMatch(css, /#wallpaper/); assert.doesNotMatch(html, /wallpaper/);
  assert.doesNotMatch(css, /box-shadow:[^;}]*rgba\((10,132,255|100,210,255)[^;}]*\d+px[^;}]*-\d+px/);
  assert.match(css, /--bg:#0b0b0f/); assert.match(css, /--bg:#f2f2f7/);
  assert.match(css, /\.song-choices,[^{]*\{background:var\(--panel\)/);
});
test("glass foregrounds meet AA on white, black and saturated covers in all preferences", () => {
 const rgb=hex=>hex.match(/[0-9a-f]{2}/gi).map(n=>parseInt(n,16)/255);
 const mix=(fg,bg,a)=>fg.map((n,i)=>n*a+bg[i]*(1-a));
 const lum=rgb=>rgb.map(c=>c<=.04045?c/12.92:((c+.055)/1.055)**2.4).reduce((n,c,i)=>n+c*[.2126,.7152,.0722][i],0);
 const ratio=(a,b)=>(Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);
 for(const light of [false,true])for(const pref of ["clear","standard","opaque"])for(const cover of ["ffffff","000000","ff0088","00ffff"]){
  // Worst case is the content scrolling under a floating layer: bright/dark/saturated cover thumbnail.
  const dim=light?1:(pref==="clear"?.4:.45), under=rgb(cover).map(n=>n*dim);
  const tint=rgb(light?"ffffff":"1e1e24"), a=pref==="clear"?(light?[.72,.84]:[.30,.44]):(light?[.72,.84]:[.40,.56]);
  const solid=rgb(light?"fbfbfd":"232327");
  const layers=[rgb(light?"ffffff":"1c1c1e"),rgb(light?"f2f2f7":"0b0b0f"),
   ...(pref==="opaque"?[solid]:a.map(alpha=>mix(tint,under,alpha)))];
  for(const bg of layers)for(const fg of light?["142137","34445c","06416f"]:["f8fafc","c2ccdd","a5ddff"])
   assert.ok(ratio(rgb(fg),bg)>=4.5,JSON.stringify({light,pref,cover,fg,ratio:ratio(rgb(fg),bg)}));
 }
 assert.match(html,/id="glass-appearance"/); assert.match(css,/prefers-contrast:more/);
});
test("explicit server survives the login redirect and is consumed after selection", () => {
  const vm=require("node:vm");
  const source=fs.readFileSync(path.join(__dirname,"../musicbot/web/dashboard.js"),"utf8");
  const snippet=source.slice(source.indexOf("function rememberGuild"),source.indexOf("async function connect"));
  const stored=new Map(), window={location:{href:"https://music.example.com/?guild=2"},
    sessionStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)}};
  const c=vm.createContext({window,URL,entryGuild:"",manualGuild:"",data:{guilds:[{id:"1"},{id:"2"}],recommended_guild_id:"1"}});
  vm.runInContext(snippet,c);vm.runInContext("captureEntryGuild()",c);
  assert.equal(stored.size,1);
  window.location.href="https://music.example.com/";c.entryGuild="";
  vm.runInContext("captureEntryGuild()",c);
  assert.equal(vm.runInContext("initialGuild(data)",c),"2");
  vm.runInContext('rememberGuild("2")',c);assert.equal(stored.size,0);
  c.manualGuild="1";assert.equal(vm.runInContext("initialGuild(data)",c),"1");
});
