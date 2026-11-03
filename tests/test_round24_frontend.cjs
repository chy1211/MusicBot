'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root=path.resolve(__dirname,'..');
const read = file => fs.readFileSync(path.join(root,file),'utf8');

test('desktop wave: only 12 bars condensed in existing 44px column',()=>{
 const css=read('frontend/src/styles/r24-layout.css');
 const hero=read('frontend/src/components/NowPlaying.vue');
 assert.match(css, /min-width:\s*1001px/);
 assert.match(css, /stage-copy\s*>\s*\.stage-wave\s*>\s*i/);
 assert.match(css, /gap:\s*1px/);
 assert.match(css, /flex:\s*0 0 2px/);
 assert.match(hero, /v-for="n in 12"/);
 const waveCss=css.split('/* The dialog itself')[0];
 assert.doesNotMatch(waveCss, /grid-template-columns|stage-art|stage-request|stage-audience/);
});

test('playlist modal has one scrollable song list and a persistent action footer',()=>{
 const vue=read('frontend/src/components/PlaylistPreviewModal.vue');
 const css=read('frontend/src/styles/r24-layout.css');
 assert.match(vue,/class="playlist-modal-body"/);
 assert.match(vue,/class="playlist-modal-song-panel"/);
 assert.match(vue,/class="playlist-modal-import-panel"/);
 assert.match(vue,/class="playlist-modal-footer"/);
 assert.match(vue,/class="primary import-submit"/);
 assert.match(css,/\.playlist-modal-entries\s*\{[\s\S]*?overflow-y:\s*auto;/);
 assert.match(css,/\.playlist-modal-footer\s*\{[\s\S]*?flex:\s*0 0 auto/);
 assert.match(css,/\.playlist-modal-body\s*\{[\s\S]*?overflow-y:\s*auto/);
 assert.match(vue,/v-model="activeSong.selected"/);
 assert.match(vue,/@click="importSelection"/);
 assert.match(vue,/@click="addSelected"/);
});

test('both history/popular hearts toggle the Favorites playlist, not open save modal',()=>{
 const history=read('frontend/src/views/PlayView.vue');
 const popular=read('frontend/src/views/PopularView.vue');
 for(const content of [history,popular]) {
   assert.match(content,/:aria-pressed="library.isFavorite\(song\)"/);
   assert.match(content,/@click="library.toggleFavorite\(song\)"/);
 }
 assert.match(read('frontend/src/composables/useLibrary.ts'),/find\(list => list.id === 'favorites'\)/);
});

test('180 days is default across frontend, API and bounded popularity store',()=>{
 assert.match(read('frontend/src/composables/usePopular.ts'),/const period = ref<Period>\('180'\)/);
 assert.match(read('frontend/src/views/PopularView.vue'),/<option value="180">/);
 assert.match(read('musicbot/dashboard_backend/state.py'),/request.query.get\("period", "180"\)/);
 assert.match(read('musicbot/web_dashboard_stats.py'),/"180": 179/);
});
