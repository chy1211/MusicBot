// Structural regression check. Browser snapshots/real Vue build are Codex tasks.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const read = p => fs.readFileSync(path.join(root, p), 'utf8');
test('history buttons keep existing click handlers but use SVG masks', () => {
  const view = read('frontend/src/views/PlayView.vue');
  const css = read('frontend/src/styles/history-actions-icons.css');
  const index = read('frontend/src/styles/index.css');
  assert.match(view, /@click="historyQueue\.add\(song\)"/);
  assert.match(view, /@click="library\.openSave\(song\)"/);
  assert.match(css, /history-add\.svg/);
  assert.match(css, /history-heart\.svg/);
  assert.match(css, /44px/);
  assert.match(index, /history-actions-icons\.css/);
});
test('SVG assets are vector paths', () => {
  for (const name of ['history-add', 'history-heart']) {
    const svg = read(`frontend/public/icons/${name}.svg`);
    assert.match(svg, /<svg\b/);
    assert.match(svg, /<path\b/);
    assert.match(svg, /<\/svg>/);
    assert.doesNotMatch(svg, /<script|onload\s*=/i);
  }
});
test('search remains explicitly submitted and shows source/version', () => {
  const view = read('frontend/src/components/HeaderSearch.vue');
  assert.match(view, /@submit\.prevent="search"/);
  assert.match(view, /song\.source/);
  assert.match(view, /song\.version/);
  assert.doesNotMatch(view, /watch\(keyword,\s*\(.*resolveQuery/);
});
