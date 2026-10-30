'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const read = p => fs.readFileSync(path.join(root,p),'utf8');

test('queue controls have a fixed minimum height, even when empty', () => {
  const css=read('frontend/src/styles/playlist-import-controls.css');
  assert.match(css,/#play-view > \.queue \.queue-filters\s*\{[^}]*min-height:\s*52px/s);
  assert.match(css,/\.queue-filters > button\s*\{[^}]*min-height:\s*44px/s);
});
test('desktop uses the original stage-wave, no new animation keyframes', () => {
  const css=read('frontend/src/styles/playlist-import-controls.css');
  assert.match(css,/\.stage-copy > \.stage-wave\s*\{[^}]*display:\s*flex/s);
  assert.doesNotMatch(css,/@keyframes/);
});
test('popular, header selection, playlist modal all use the same pulse', () => {
  const css=read('frontend/src/styles/playlist-import-controls.css');
  assert.match(css,/\.popular-add\[aria-busy="true"\]::before\s*\{[^}]*content:\s*none/s);
  assert.match(css,/\.header-result > button\[aria-busy="true"\]/);
  assert.match(css,/\.playlist-modal-footer \.primary\[aria-busy="true"\]/);
  assert.match(css,/\.import-submit\[aria-busy="true"\]/);
  assert.match(css,/animation:\s*notice-blink/);
});
test('saved heart comes from real library state and uses filled SVG asset', () => {
  const lib=read('frontend/src/composables/useLibrary.ts');
  assert.match(lib,/function isSaved\(/);
  assert.match(lib,/playlists\.value\.some/);
  const css=read('frontend/src/styles/playlist-import-controls.css');
  assert.match(css,/history-heart-filled\.svg/);
  assert.match(css,/save-to-library\[aria-pressed="true"\]/);
});
test('playlist modal has existing and new destinations, loaded library revision', () => {
  const modal=read('frontend/src/components/PlaylistPreviewModal.vue');
  assert.match(modal,/importMode/);
  assert.match(modal,/targetId/);
  assert.match(modal,/newName/);
  assert.match(modal,/activeSong\.value\.save_revision/);
  assert.match(modal,/library\.savePreview\(/);
  assert.match(modal,/emit\('imported'\)/);
});
