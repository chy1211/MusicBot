"use strict";
const {test}=require("node:test"), assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const source=fs.readFileSync("musicbot/web/dashboard.js","utf8");
const c=vm.createContext({});
vm.runInContext(source.slice(source.indexOf("function segmentGeometry"),source.indexOf("/* Progressive visual helpers")),c);
test("segmented pill stays in padded container: three/four tabs, compact and rotated",()=>{
 for(const n of [3,4])for(const width of [349,364,700])for(const height of [46,54]){
  const group={clientWidth:width,clientHeight:height};
  const style={paddingLeft:"4px",paddingRight:"4px",paddingTop:"4px",paddingBottom:"4px"};
  for(let i=0;i<n;i++){
   const active={offsetLeft:4+i*(width-8)/n,offsetTop:4,offsetWidth:Math.round((width-8)/n),offsetHeight:height-8};
   c.group=group;c.active=active;c.style=style;
   const g=vm.runInContext("segmentGeometry(group,active,style)",c);
   assert.ok(g.x>=4&&g.y>=4&&g.x+g.w<=width-4&&g.y+g.h<=height-4);
   assert.ok(Math.abs(g.x-active.offsetLeft)<1);
  }
 }
});
test("bad transient offsets cannot escape either padded edge",()=>{
 c.group={clientWidth:349,clientHeight:46};c.style={paddingLeft:"6",paddingRight:"8",paddingTop:"4",paddingBottom:"4"};
 for(const x of [-20,999]){c.active={offsetLeft:x,offsetTop:-5,offsetWidth:110,offsetHeight:60};
 const g=vm.runInContext("segmentGeometry(group,active,style)",c);
 assert.ok(g.x>=6&&g.x+g.w<=341&&g.y>=4&&g.y+g.h<=42);}
});
test("all five player buttons share a fixed shape; first paint does not animate",()=>{
 const html=fs.readFileSync("musicbot/web/index.html","utf8"),css=fs.readFileSync("musicbot/web/dashboard.css","utf8");
 for(const id of ["favorite","toggle","skip","repeat","lyrics-toggle"])
  assert.match(html,new RegExp('<button id="'+id+'"[^>]*class="[^"]*player-control'));
 assert.match(css,/#playback-bar \.player-control\{[^}]*height:40px;[^}]*border-radius:20px/);
 assert.match(css,/\.page-tabs,\.queue-filters\{overflow:hidden\}/);
 assert.match(source,/document\.fonts\?\.ready\.then\(align\)/);
 assert.match(source,/orientationchange/);
});
