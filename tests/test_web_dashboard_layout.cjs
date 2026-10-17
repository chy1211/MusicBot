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
