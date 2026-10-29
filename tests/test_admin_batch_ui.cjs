/* Run inside MusicBot: node --test tests/test_admin_batch_ui.cjs */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname,'..');
const read = p=>fs.readFileSync(path.join(root,p),'utf8');
test('admin owner sections are grouped and diagnostics collapsed',()=>{
 const src=read('frontend/src/views/AdminView.vue');
 for(const id of ['admin-playback-group','admin-apl-group','admin-permissions-group','admin-maintenance-group'])assert.match(src,new RegExp('id="'+id+'"'));
 assert.match(src,/<details id="admin-maintenance-group" class="admin-group">/);
 assert.match(src,/admin-health-summary/);
});
test('save controls require loaded and dirty state',()=>{
 const src=read('frontend/src/views/AdminView.vue');
 for(const flag of ['!notifyDirty','!lyricsDirty','!emptyDirty','!voteDirty'])assert.ok(src.includes(flag),flag);
 const logic=read('frontend/src/composables/useAdmin.ts');
 assert.match(logic,/Promise\.allSettled/);
 assert.match(logic,/lyricsLoaded\.value=false/);
 assert.match(logic,/voteSkipLoaded\.value=false/);
});
test('no public metadata extraction required to render playlist',()=>{
 const code=read('musicbot/web_dashboard_admin.py');
 assert.match(code,/self\.recent_history/);
 assert.match(code,/"known": bool\(valid_title\)/);
 assert.match(code,/"thumbnail":\s*\(?public_url/);
});
test('translations have matching keys',()=>{
 const zh=JSON.parse(read('frontend/public/i18n/zh-TW.json'));
 const en=JSON.parse(read('frontend/public/i18n/en.json'));
 for(const key of Object.keys(zh).filter(k=>k.startsWith('admin.batch.'))){assert.equal(typeof en[key],'string',key)}
});
