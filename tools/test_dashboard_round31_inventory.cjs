#!/usr/bin/env node
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const testsDir = path.join(root, "tests");
const out = path.join(root, "frontend", "TEST-MIGRATION.md");
const excluded = new Set(["test_web_dashboard_pwa.cjs", "test_web_dashboard_round27_offline.cjs", "test_web_dashboard_round27_registration.cjs"]);
const inputs = fs.readdirSync(testsDir).filter(n => n.endsWith(".cjs") && n !== "dashboard_i18n_fixture.cjs").sort();
const cases = [];
function mapping(title, file) {
  if (excluded.has(file)) return "Retain in the existing worker/offline/registration suite; no legacy assertion removed.";
  const t = title.toLowerCase();
  if (/logout|session|auth|discord|owner|secret|401|403|login/.test(t)) return "Drive the rendered login/session flow; inspect #discord-login, #dashboard, profile/connection controls and verify API requests or cleared DOM.";
  if (/guild|server/.test(t)) return "Select #guild in the rendered app; assert displayed guild/state, scoped request payloads, and stale-response result.";
  if (/queue|drag|reorder|shuffle|position|estimate|filter/.test(t)) return "Operate #queue and its rendered rows/actions; assert row order/count, disabled/empty states, notices, and resulting API mutations.";
  if (/seek|progress|track token/.test(t)) return "Operate the rendered seek range by pointer/touch/keyboard; inspect value/progress and the scoped seek request.";
  if (/volume|playback|player|repeat|skip|control/.test(t)) return "Use rendered playback controls; assert accessible state/value and the matching guild-scoped request.";
  if (/preview|lookup|resolve|recommend|duplicate|spotify|history replay|playnext/.test(t)) return "Fill #query, operate #enqueue and #preview-panel; assert visible result/denial/busy state and only the explicitly confirmed command request.";
  if (/lyric|offset|timing|alignment/.test(t)) return "Open #lyrics-panel and #lyrics-timing-menu; assert rendered lyric/highlight/offset state and timing or retry requests.";
  if (/popular/.test(t)) return "Open #nav-popular/#popular-panel; assert ranked rows, count/duration, period empty/error states, and one-click resolved enqueue.";
  if (/playlist|library|favorite|collection/.test(t)) return "Open #nav-library/#library-panel; operate rendered playlist rows/cover/save controls; assert cover images, selection, revision payload and toast.";
  if (/permission|admin|notification|vote skip|maintenance|management/.test(t)) return "Open #nav-admin/#admin-panel; operate rendered setting controls and confirmation dialogs; assert capability gating and API payload.";
  if (/sse|reconnect|poll|rate limit|backoff|timeout/.test(t)) return "Observe rendered state transitions while fixture endpoints/stream change or fail; assert recovered/cleared UI and no stale content.";
  if (/language|translation|catalog|label|busy/.test(t)) return "Switch the rendered language selector; assert visible labels, placeholders, accessible names and parameterized messages.";
  if (/glass|theme|layout|brand|phone|pill|touch|aria|accessible|toast|css/.test(t)) return "Assert computed styles and browser geometry/accessibility on the built DOM at mobile/desktop and light/dark settings.";
  if (/shortcut|keyboard/.test(t)) return "Send real keyboard input to the rendered page; assert focus, dialog/command effects, and ignored editable/modifier cases.";
  return "Exercise the corresponding rendered control and assert visible DOM state plus its externally observable API effect; refine selector from the original assertion below.";
}
function callEnd(src, start) {
  let depth = 0, quote = null, escape = false;
  for (let i = start; i < src.length; i++) {
    const c = src[i];
    if (quote) { if (escape) escape = false; else if (c === "\\") escape = true; else if (c === quote) quote = null; continue; }
    if (c === "\"" || c === "'" || c === "`") { quote = c; continue; }
    if (c === "(") depth++;
    else if (c === ")") { depth--; if (depth === 0) return i + 1; }
  }
  return src.length;
}
for (const file of inputs) {
  const source = fs.readFileSync(path.join(testsDir, file), "utf8");
  const starts = [...source.matchAll(/^\s*test\s*\(/gm)].map(m => m.index + m[0].indexOf("test"));
  for (let ix = 0; ix < starts.length; ix++) {
    const start = starts[ix], end = starts[ix + 1] ?? source.length;
    const titleStart = source.indexOf("(", start) + 1;
    const titleEnd = callEnd(source, source.indexOf("(", start));
    const head = source.slice(titleStart, titleEnd);
    const title = (head.match(/^\s*([\"'`])([\s\S]*?)\1/) || [null, null, "(dynamic test title)"])[2].replace(/\s+/g, " ");
    const body = source.slice(start, end);
    const assertionMatches = [...body.matchAll(/\bassert\.[A-Za-z_$][\w$]*/g)];
    const lineAssertions = [];
    for (const m of assertionMatches) {
      const absolute = start + m.index;
      const line = source.slice(source.lastIndexOf("\n", absolute - 1) + 1, source.indexOf("\n", absolute) < 0 ? source.length : source.indexOf("\n", absolute)).trim();
      lineAssertions.push({line: source.slice(0, absolute).split("\n").length, expression: line.replace(/\|/g, "\\|").replace(/`/g, "\\`")});
    }
    cases.push({file, title, assertions: assertionMatches.length, mapped: !excluded.has(file), target: mapping(title, file), lineAssertions});
  }
}
const mappedCases = cases.filter(x => x.mapped);
const mappedAssertions = mappedCases.reduce((n, x) => n + x.assertions, 0);
let md = `# Vue 測試移植 inventory 與 mapping\n\n`;
md += `此檔由 \`node tools/test_dashboard_round31_inventory.cjs\` 從現有 CJS 案例產生。原基線記錄為 **211 tests / 856 textual asserts**；目前工作樹解析到 **${cases.length} test cases / ${cases.reduce((n,x)=>n+x.assertions,0)} assert calls**，其中移植範圍 **${mappedCases.length} / ${mappedAssertions}**。數字差異保留為待核對項，不以刪除或重複測試補數。PWA、offline、registration 三組按任務先保留。\n\n`;
md += `驗收規則：映射後測試必須載入 Vite 建置輸出，使用 Playwright 對 rendered DOM 做互動，並在 API fixture 觀察結果；不得讀取／執行原 public JS，也不得用搜尋 TS 原始碼替代行為。重構無法在瀏覽器呈現的底層時序意圖，須以可觀察 UI/API 結果保留因果驗證。\n\n`;
md += `## 各組數量\n\n| 舊測試檔 | 案例 | assert calls | 狀態 |\n|---|---:|---:|---|\n`;
for (const f of inputs) { const cs=cases.filter(c=>c.file===f); md += `| \`${f}\` | ${cs.length} | ${cs.reduce((n,c)=>n+c.assertions,0)} | ${excluded.has(f)?"保留原套件":"逐項映射，逐步換成瀏覽器互動"} |\n`; }
md += `\n## 逐案映射\n`;
for (const c of cases) {
  md += `\n### \`${c.file}:${c.lineAssertions[0]?.line || 1}\` — ${c.title}\n\n`;
  md += `- 舊意圖：${c.assertions} 個 assert calls；${c.mapped?"納入 Vue browser migration":"既有真實 PWA/offline suite 暫保留"}\n`;
  md += `- 新驗證：${c.target}\n`;
  if (c.lineAssertions.length) {
    md += `- 舊斷言逐行索引：\n`;
    for (const a of c.lineAssertions) md += `  - L${a.line}: \`${a.expression}\`\n`;
  }
}
md += `\n## 執行矩陣\n\n`;
md += `browser runner 將以 Node 啟動 credential-free \`tools/dashboard_demo.py\` fixture server，提供固定 guild、song、playlist、permission 與錯誤情境；Playwright 載入 build 後的頁面，逐項檢查 DOM 和 API request。視窗至少含 390px mobile、393px standalone safe-area、1440px desktop，並跑 light/dark。現有輪次 screenshot runner 的 demo API 可沿用；新測試不載入 legacy controller。\n`;
fs.writeFileSync(out, md, "utf8");
process.stdout.write(JSON.stringify({output: out, files: inputs.length, cases: cases.length, mappedCases: mappedCases.length, asserts: cases.reduce((n,x)=>n+x.assertions,0), mappedAsserts: mappedAssertions, excluded: [...excluded]}, null, 2)+"\n");
