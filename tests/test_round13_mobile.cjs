"use strict";
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),read=p=>fs.readFileSync(path.join(root,p),'utf8');
test('landscape player is conditional and has an escape route',()=>{
 const code=read('frontend/src/components/MobileLandscapePlayer.vue');
 assert.match(code,/class="mobile-landscape"/);assert.match(code,/@click="exit=true"/);
 assert.match(code,/@click="run\(state\?\.status/);
});
test('phone media breakpoints preserve safe areas',()=>{
 const css=read('frontend/src/styles/mobile-player.css');
 assert.match(css,/@media\(max-width:760px\) and \(orientation:portrait\)/);
 assert.match(css,/@media\(orientation:landscape\)/);
 assert.match(css,/--safe-bottom/);
 assert.match(css,/\.mobile-landscape:not\(\[hidden\]\)/);
});
