"use strict";
const {test}=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const ts=require("typescript"),vue=require("vue"),{parse,compileScript}=require("@vue/compiler-sfc"),load=require("./dashboard_ts_fixture.cjs");
function track(){return load("frontend/src/composables/useTrack.ts",{'./useLocale':{t:k=>k,locale:{value:"en"},timeZone:{value:"UTC"}}});}
function cover(tracks){
 const descriptor=parse(fs.readFileSync("frontend/src/components/PlaylistCover.vue","utf8")).descriptor;
 const compiled=compileScript(descriptor,{id:"r41-cover"});
 const js=ts.transpileModule(compiled.content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const exports={};vm.runInNewContext(js,{exports,require:name=>name==='vue'?vue:track()});
 return exports.default.setup({tracks,size:56,label:"Test"},{expose(){}});
}
test("current Vue covers sanitize thumbnails and deduplicate legacy YouTube sources",()=>{
 const c=cover([{thumbnail:"https://img.example.test/a.jpg"},{url:"https://youtu.be/abcdefghijk"},{thumbnail:"https://img.example.test/c.jpg"},{url:"https://youtube.com/watch?v=abcdefghijk"},{thumbnail:"https://img.example.test/e.jpg"}]);
 assert.deepEqual(Array.from(c.sources.value),["https://img.example.test/a.jpg","https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg","https://img.example.test/c.jpg","https://img.example.test/e.jpg"]);
 assert.equal(cover([{thumbnail:"https://img.example.test/a.jpg"}]).layoutClass.value,"cover-count-1");
 assert.equal(cover([{thumbnail:"https://img.example.test/a.jpg"},{thumbnail:"https://img.example.test/b.jpg"}]).layoutClass.value,"cover-count-2");
});
test("current Vue covers cap at four and use an empty layout without images",()=>{
 const c=cover(Array.from({length:6},(_,i)=>({thumbnail:"https://img.example.test/"+i+".jpg"})));
 assert.equal(c.sources.value.length,4);
 assert.equal(cover([{url:"https://example.test/no-image"}]).layoutClass.value,"cover-count-0");
});
test("current Vue cover rejects unsafe schemes and credential-bearing URLs",()=>{
 const c=cover([{thumbnail:"javascript:alert(1)",url:"https://example.test/a"},{thumbnail:"https://user:pass@img.example.test/a.jpg"},{thumbnail:"data:image/png;base64,AAAA"},{url:"https://user:pass@youtube.com/watch?v=abcdefghijk"}]);
 assert.deepEqual(Array.from(c.sources.value),[]);
 for(const value of ["javascript:alert(1)","https://u:p@example.test/a","data:image/png;base64,AAAA","https://example.test/a\n"])
  assert.equal(track().safeURL(value),"");
});
test("failed Vue cover images disappear and all failures restore the empty layout",()=>{
 const c=cover([{thumbnail:"https://img.example.test/a.jpg"},{thumbnail:"https://img.example.test/b.jpg"}]);
 c.imageFailed(c.sources.value[0]);assert.equal(c.visibleSources.value.length,1);assert.equal(c.layoutClass.value,"cover-count-1");
 c.imageFailed(c.sources.value[1]);assert.equal(c.visibleSources.value.length,0);assert.equal(c.layoutClass.value,"cover-count-0");
});
