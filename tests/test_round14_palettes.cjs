"use strict";
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),read=p=>fs.readFileSync(path.join(root,p),'utf8');
test('new palettes use requested tokens and preserve all old variants',()=>{
 const theme=read('frontend/src/composables/useTheme.ts'),css=read('frontend/src/round14.css');
 for(const p of ['mint','amber','ocean','rose','noir','iris']) assert.ok(theme.includes("'"+p+"'"));
 for(const token of ['#0F0F10','#1A1A1D','#26262B','#E53935','#C62828','#C9A46B','#F8F9FC','#6366F1','#4F46E5','#8B5CF6','#E4E7F0'])assert.ok(css.includes(token),token);
 assert.match(theme,/palette\.value === 'noir' \? 'dark'/);
 assert.match(theme,/palette\.value === 'iris' \? 'light'/);
});
test('two languages contain consistent new labels',()=>{
 const en=read('frontend/public/i18n/en.json');
 const zh=read('frontend/public/i18n/zh-TW.json');
 for(const key of ['palette.noir','palette.iris']){assert.ok(en.includes('\"'+key+'\"'));assert.ok(zh.includes('\"'+key+'\"'));}
});
