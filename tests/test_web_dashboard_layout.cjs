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
