"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const vm = require("node:vm");
const script = readFileSync(join(__dirname, "../frontend/index.html"), "utf8").match(/<script>(.*?)<\/script>/s)[1];
const backgrounds = {mint:["#1e2226","#f3f5f7"],amber:["#1b1b1b","#f5f5f5"],ocean:["#141b26","#f2f5fa"],rose:["#1f1a1d","#faf4f6"]};
function boot(saved, systemLight = false, blocked = false) {
  const root = {dataset:{}}, meta = {};
  vm.runInNewContext(script, {
    localStorage:{getItem:key=>{if(blocked)throw Error("blocked");return saved[key]??null;}},
    matchMedia:()=>({matches:systemLight}),
    document:{documentElement:root,querySelector:selector=>{assert.equal(selector,'meta[name="theme-color"]');return meta;}}
  });
  return {palette:root.dataset.palette, theme:root.dataset.theme, color:meta.content};
}
test("R46 palette bootstrap sets every day/night combination before Vue loads", () => {
  for(const [palette, bg] of Object.entries(backgrounds))for(const [index,theme] of ["dark","light"].entries()){
    assert.deepEqual(boot({"musicbot-palette":palette,"musicbot-theme":theme}, theme === "dark"), {palette,theme,color:bg[index]});
  }
});
test("R46 palette bootstrap validates storage and preserves system theme fallback", () => {
  for(const invalid of [null,"","corrupt","__proto__","constructor","AMBER"]){
    assert.deepEqual(boot({"musicbot-palette":invalid,"musicbot-theme":"bad"},true),{palette:"mint",theme:"light",color:"#f3f5f7"});
  }
  for(const light of [true,false]) assert.deepEqual(boot({},light,true),{palette:"mint",theme:light?"light":"dark",color:light?"#f3f5f7":"#1e2226"});
});
