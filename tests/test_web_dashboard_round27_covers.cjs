"use strict";
const {test}=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.style={};this.attributes={};this.classes=new Set();}
 append(...items){this.children.push(...items);}
 setAttribute(n,v){this.attributes[n]=String(v);}
 getAttribute(n){return this.attributes[n]||null;}
 classList={toggle:(n,on)=>on?this.classes.add(n):this.classes.delete(n)};
 set src(v){this.attributes.src=v;} get src(){return this.attributes.src;}
}
function load(){
 const safeURL=value=>{try{if(/[\u0000-\u001f]/.test(String(value)))return "";const u=new URL(value);return /^https?:$/.test(u.protocol)&&!u.username&&!u.password?value:"";}catch{return "";}};
 const songIdentity=value=>{const raw=safeURL(value);if(!raw)return "";const u=new URL(raw),h=u.hostname.toLowerCase(),p=u.pathname.split("/").filter(Boolean),yt=h==="youtube.com"||h.endsWith(".youtube.com")||h==="youtube-nocookie.com";const id=h==="youtu.be"?p[0]:yt?(u.pathname==="/watch"?u.searchParams.get("v"):["shorts","embed","live","v"].includes(p[0])?p[1]:""):"";return id&&/^[A-Za-z0-9_-]{11}$/.test(id)?"youtube:"+id:"";};
 const c={document:{createElement:t=>new Element(t)},URL,safeURL,songIdentity};
 vm.runInContext(fs.readFileSync(path.join(__dirname,"../musicbot/web/playlist-covers.js"),"utf8"),vm.createContext(c));return c;
}
test("safe thumbnails and legacy YouTube URLs fill unique collage slots",()=>{
 const h=load(),old={url:"https://youtube.com/watch?v=abcdefghijk"};
 assert.deepEqual(Array.from(h.playlistCoverSources([{thumbnail:"https://img.example.test/a.jpg"},{url:"https://youtu.be/abcdefghijk"},{thumbnail:"https://img.example.test/c.jpg"},old,{thumbnail:"https://img.example.test/e.jpg"}])),["https://img.example.test/a.jpg","https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg","https://img.example.test/c.jpg","https://img.example.test/e.jpg"]);
 assert.equal(h.playlistCoverThumbnail(old),"https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg");
 assert.equal(h.playlistCoverElement([{thumbnail:"https://img.example.test/a.jpg"}]).getAttribute("data-count"),"1");
 assert.equal(h.playlistCoverElement([{thumbnail:"https://img.example.test/a.jpg"},{thumbnail:"https://img.example.test/b.jpg"}]).getAttribute("data-count"),"2");
});
test("sources cap at four and no-image playlists show designed vinyl",()=>{
 const h=load(),many=Array.from({length:6},(_,i)=>({thumbnail:"https://img.example.test/"+i+".jpg"}));
 assert.equal(h.playlistCoverSources(many).length,4);
 const none=h.playlistCoverElement([{url:"https://example.test/no-image"}]);
 assert.equal(none.getAttribute("data-count"),"0");assert.ok(none.classes.has("is-empty"));assert.match(none.style.background,/radial-gradient/);
});
test("unsafe schemes and credential-bearing image or song URLs are rejected",()=>{
 const h=load();
 assert.deepEqual(Array.from(h.playlistCoverSources([
 {thumbnail:"javascript:alert(1)",url:"https://example.test/a"},
 {thumbnail:"https://user:pass@img.example.test/a.jpg",url:"https://example.test/b"},
 {thumbnail:"data:image/png;base64,AAAA",url:"https://example.test/c"},
 {thumbnail:"",url:"https://user:pass@youtube.com/watch?v=abcdefghijk"}
 ])),[]);
 assert.equal(h.playlistCoverThumbnail({thumbnail:"javascript:alert(1)",url:"https://example.test/x"}),"");
});
test("failed images hide broken icons and reveal vinyl when every collage image fails",()=>{
 const h=load(),cover=h.playlistCoverElement([{thumbnail:"https://img.example.test/a.jpg"},{thumbnail:"https://img.example.test/b.jpg"}]),images=cover.children;
 assert.equal(images.length,2);images[0].onerror();assert.equal(images[0].hidden,true);assert.equal(images[0].style.display,"none");assert.equal(cover.classes.has("is-empty"),false);
 images[1].onerror();assert.equal(cover.classes.has("is-empty"),true);
});

test("playlist and favorite saves share the sanitized thumbnail field",()=>{
 const helper=load(),library=fs.readFileSync(path.join(__dirname,"../musicbot/web/library.js"),"utf8");
 const declaration=library.match(/function libraryTrack\(song\) \{[\s\S]*?\n\}/);
 assert.ok(declaration);
 const context=vm.createContext({safeURL:value=>{try{const u=new URL(value);return /^https?:$/.test(u.protocol)&&!u.username&&!u.password?value:"";}catch{return "";}},
   playlistCoverThumbnail:helper.playlistCoverThumbnail,songIdentity:()=>""});
 vm.runInContext(declaration[0],context);
 const saved=vm.runInContext('libraryTrack({title:"A",url:"https://example.test/a",duration:9,thumbnail:"https://img.example.test/a.jpg"})',context);
 assert.equal(saved.thumbnail,"https://img.example.test/a.jpg");
 assert.match(library,/const track = libraryTrack\(song\)/);
 assert.match(library,/: \{track:libraryTrack\(song\)\}/);
});
