'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const read = (rel) => fs.readFileSync(path.join(root, rel), 'utf8');

test('route views load on demand, global controls remain mounted', () => {
  const view = read('frontend/src/views/Workspace.vue');
  for (const name of ['PlayView','LibraryView','PopularView','AdminView']) {
    assert.match(view, new RegExp(`defineAsyncComponent\\(\\(\\)=>import\\('./${name}\\.vue'\\)\\)`));
    assert.match(view, new RegExp(`<${name} v-if=`));
  }
  assert.match(view, /<PlaybackBar\/>/);
  assert.match(view, /<LyricsPanel\/>/);
  assert.match(view, /library\.saveDialogOpen\.value/);
});

test('admin is not eagerly mounted; existing maintenance monitor is unchanged', () => {
  const view = read('frontend/src/views/Workspace.vue');
  assert.doesNotMatch(view, /<div :hidden="route\.path!==['"]\/admin/);
  const admin = read('frontend/src/views/AdminView.vue');
  assert.match(admin, /route\.path !== '\/admin'/);
});

test('resolution polling uses a fresh abort controller per attempt', () => {
  const api = read('frontend/src/api.ts');
  assert.match(api, /const controller=new AbortController\(\)/);
  assert.match(api, /signal:controller\.signal/);
  assert.match(api, /if\(!finished\)statusTimer=setTimeout\(poll,200\)/);
  assert.doesNotMatch(api, /statusAbort/);
});

test('clock avoids hidden or inactive high-frequency timers and cleans up listener', () => {
  const src = read('frontend/src/composables/usePlayback.ts');
  assert.match(src, /!document\.hidden&&dashboard\.connected&&dashboard\.snapshot\?\.status==='playing'/);
  assert.match(src, /removeEventListener\('visibilitychange',updateClock\)/);
});

test('popular data is fetched on entry, not by a permanent eager watch', () => {
  const state = read('frontend/src/composables/usePopular.ts');
  const view = read('frontend/src/views/PopularView.vue');
  assert.doesNotMatch(state, /=> \{ void load\(\) \}\)/);
  assert.match(view, /onMounted\(refreshVisible\)/);
  assert.match(view, /dashboard\.connected&&dashboard\.authenticated/);
  assert.match(state, /!Array\.isArray\(result\.tracks\)/);
});

test('library has one clear enqueue-all action and save dialog survives lazy mount', () => {
  const view = read('frontend/src/views/LibraryView.vue');
  assert.doesNotMatch(view, /id="library-play-all"/);
  assert.match(view, /id="library-enqueue-all" class="primary"/);
  assert.match(view, /watch\(library\.saveDialogOpen,[\s\S]*?\}, \{ immediate: true \}\)/);
});

test('header and legacy search have isolated results and request lifecycles', () => {
  const source = read('frontend/src/composables/useRequests.ts');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }, reportDiagnostics: true });
  assert.equal((compiled.diagnostics || []).filter(d => d.category === ts.DiagnosticCategory.Error).length, 0);
  const watchers = [];
  const dashboard = { epoch: 1, snapshot: { queue: [], current: null } };
  const modules = {
    vue: { reactive: value => value, watch: (getter, cb) => {watchers.push({getter,cb});return () => {};} },
    '../api': {request: async () => ({results:[]}), APIError: class APIError extends Error {}},
    '../store': { dashboard, usable: {value:true} },
    './useDashboard': { command: async () => true, notice: () => {} },
    './useTrack': { songIdentity: () => '' },
    './useLocale': { t: value => value },
  };
  const exports = {};
  vm.runInNewContext(compiled.outputText, { exports, require: id => {if (!modules[id]) throw Error('Unexpected '+id);return modules[id];} });
  assert.notStrictEqual(exports.requests, exports.headerRequests);
  exports.requests.query = 'legacy';
  exports.headerRequests.query = 'top';
  exports.headerRequests.results.push({title:'Top result'});
  exports.clearPreview();
  assert.equal(exports.headerRequests.results.length,1);
  assert.equal(exports.headerRequests.query,'top');
  exports.requests.results.push({title:'Legacy result'});
  exports.clearHeaderPreview();
  assert.equal(exports.requests.results.length,1);
  dashboard.epoch++;
  watchers.forEach(item => item.cb());
  assert.equal(exports.requests.results.length,0);
  assert.equal(exports.headerRequests.results.length,0);
});

test('playlist modal uses the same isolated header search context', () => {
  assert.match(read('frontend/src/components/HeaderSearch.vue'), /headerRequests as requests/);
  assert.match(read('frontend/src/components/PlaylistPreviewModal.vue'), /confirmHeaderPreview as confirmPreview/);
});
