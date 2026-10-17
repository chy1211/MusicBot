"use strict";
const {test} = require("node:test"), assert = require("node:assert/strict");
const fs = require("node:fs"), vm = require("node:vm");
const en = require("../musicbot/web/i18n/en.json"), zh = require("../musicbot/web/i18n/zh-TW.json");
class Element {
  constructor() { this.children = []; this.dataset = {}; this.id = ""; this.classList = {toggle() {}}; }
  get childNodes() { return this.children; }
  get textContent() { return this.children.length ? this.children.map(n => n.textContent).join("") : this.text || ""; }
  set textContent(value) { this.children = []; this.text = String(value); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this.text = ""; }
  setAttribute() {}
}
function setup() {
  const root = new Element();
  const document = {documentElement: {}, getElementById() { return null; }, createElement() { return new Element(); },
    querySelectorAll(selector) {
      if (selector !== "[data-i18n]") return [];
      const found = [];
      function visit(node) { if (node.dataset.i18n) found.push(node); node.children.forEach(visit); }
      visit(root); return found;
    }};
  const c = vm.createContext({document, dashboardTestCatalog: en, root});
  vm.runInContext(fs.readFileSync("musicbot/web/i18n.js", "utf8"), c);
  const source = fs.readFileSync("musicbot/web/dashboard.js", "utf8");
  vm.runInContext(source.slice(source.indexOf("// Preserve"), source.indexOf("function safeURL")), c);
  const button = new Element(); root.append(button); c.button = button;
  const language = lang => vm.runInContext("dashboardCatalog=" + JSON.stringify(lang === "en" ? en : zh) + "; applyDashboardLanguage()", c);
  return {c, button, language, run: code => vm.runInContext(code, c)};
}
test("query keeps its exact translation node through busy and language changes", () => {
  const {c,button,language,run} = setup();
  const label = new Element(); label.dataset.i18n = "m0248"; label.textContent = en.m0248;
  button.append(label); button.id = "enqueue";
  language("zh"); assert.equal(button.textContent, zh.m0248);
  run("buttonBusy(button,true)"); assert.equal(button.textContent, zh.m0044);
  language("en"); assert.equal(button.textContent, en.m0044);
  run("buttonBusy(button,false)"); assert.equal(button.children[0], label);
  assert.equal(button.textContent, en.m0248);
  language("zh"); assert.equal(button.textContent, zh.m0248);
});
test("busy before translations arrive restores current language, never saved English", () => {
  const {button,language,run} = setup();
  const label = new Element(); label.dataset.i18n = "m0248"; label.textContent = en.m0248; button.append(label);
  run("buttonBusy(button,true)"); language("zh");
  assert.equal(button.textContent, zh.m0044);
  run("buttonBusy(button,false)"); assert.equal(button.textContent, zh.m0248);
  language("en"); assert.equal(button.textContent, en.m0248);
});
test("dynamic preview, undo and library labels remain translatable and reentrant", () => {
  for (const key of ["m0090","m0104","m0122","m0004","m0198","m0202","m0203","m0101"]) {
    const {button,language,run} = setup();
    run('buttonLabel(button,"'+key+'"); buttonBusy(button,true); buttonBusy(button,true)');
    language("zh"); assert.equal(button.textContent, zh.m0044);
    run("buttonBusy(button,false); buttonBusy(button,false)");
    assert.equal(button.textContent, zh[key]);
    language("en"); assert.equal(button.textContent, en[key]);
  }
});
test("playlist counts and busy text translate; navigation preserves its label", () => {
  const {button,language,run} = setup();
  run('buttonLabel(button,"m0088",3,"m0089"); buttonBusy(button,true,3)');
  language("zh"); assert.equal(button.textContent, zh.m0102+"3"+zh.m0103);
  run("buttonBusy(button,false)"); assert.equal(button.textContent, zh.m0088+"3"+zh.m0089);
  button.id = "nav-library"; const label = button.children[0];
  run("buttonBusy(button,true); buttonBusy(button,false)"); assert.equal(button.children[0], label);
});
