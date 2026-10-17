"use strict";
const {test}=require("node:test"),assert=require("node:assert/strict"),vm=require("node:vm"),fs=require("node:fs");
const source=fs.readFileSync("musicbot/web/i18n.js","utf8"),en=require("../musicbot/web/i18n/en.json"),zh=require("../musicbot/web/i18n/zh-TW.json");
function runtime(){const c=vm.createContext({dashboardTestCatalog:zh});vm.runInContext(source,c);return c;}
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
 ]){
  Object.assign(c,{saved,languages,fallback});assert.equal(vm.runInContext("chooseLanguage(saved,languages,fallback)",c),want);
 }
});
test("translations substitute parameters once and fall back to English",()=>{
 const c=runtime();vm.runInContext('dashboardCatalog={};dashboardEnglish='+JSON.stringify(en),c);
 assert.equal(vm.runInContext('t("m0399",{p0:"{p1}",p1:0,p2:10})',c),"{p1} must be an integer between 0 and 10.");
});
test("frontend contains no hardcoded CJK UI strings or missing translation keys",()=>{
 for(const name of fs.readdirSync("musicbot/web").filter(n=>/\.(js|html|webmanifest)$/.test(n))){
  const text=fs.readFileSync("musicbot/web/"+name,"utf8");assert.doesNotMatch(text,/[\u3400-\u9fff]/,name);
  for(const m of text.matchAll(/\bt\("([^"]+)"/g))assert.ok(en[m[1]],name+":"+m[1]);
 }
});
