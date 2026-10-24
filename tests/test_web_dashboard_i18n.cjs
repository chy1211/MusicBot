"use strict";
const {test}=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path");
const load=require("./dashboard_ts_fixture.cjs");
const en=require("../frontend/public/i18n/en.json"),zh=require("../frontend/public/i18n/zh-TW.json");
function runtime(overrides={}) {return load("frontend/src/composables/useLocale.ts", {vue:{ref:value=>({value})},...overrides});}
test("catalogs have identical, complete keys and placeholder sets",()=>{
 assert.deepEqual(Object.keys(en),Object.keys(zh));
 for(const key of Object.keys(en)){
  assert.ok(en[key].trim()&&zh[key].trim(),key);
  assert.deepEqual([...(en[key].match(/\{p\d+\}/g)||[])].sort(),[...(zh[key].match(/\{p\d+\}/g)||[])].sort(),key);
 }
});
test("language preference: saved selection, browser languages, server default, English",()=>{
 const c=runtime();
 for(const [saved,languages,fallback,want]of[
  ["en",["zh-TW"],"zh-TW","en"],[null,["fr-FR","zh-Hant-TW","en"],"en","zh-TW"],
  ["unknown",["fr"],"zh-TW","zh-TW"],[null,[],"unknown","en"],[null,["en-GB"],"zh-TW","en"]
 ]) assert.equal(c.chooseLanguage(saved,languages,fallback),want);
});
test("translations substitute parameters once and fall back to English",()=>{
 const c=runtime({'../../public/i18n/zh-TW.json':{}});c.locale.value="zh-TW";
 assert.equal(c.t("m0399",{p0:"{p1}",p1:0,p2:10}),"{p1} must be an integer between 0 and 10.");
});
test("frontend contains no hardcoded CJK UI strings or missing translation keys",()=>{
 const root=path.resolve(__dirname,"..","frontend");
 const walk=dir=>fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(path.join(dir,e.name)):[path.join(dir,e.name)]);
 for(const file of [...walk(path.join(root,"src")),...walk(path.join(root,"public")),path.join(root,"index.html")]){
  if(!/\.(js|html|vue|ts|css)$/.test(file)||file.endsWith("env.d.ts"))continue;
  const text=fs.readFileSync(file,"utf8");assert.doesNotMatch(text,/[\u3400-\u9fff]/,file);
  for(const m of text.matchAll(/\bt\(["']([^"']+)["']/g))assert.ok(en[m[1]],file+":"+m[1]);
 }
});
