"use strict";
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),read=p=>fs.readFileSync(path.join(root,p),'utf8');
test('header search waits for an explicit form submit',()=>{
 const code=read('frontend/src/components/HeaderSearch.vue');
 assert.match(code,/@submit\.prevent="search"/);
 assert.match(code,/await resolveQuery\(\)/);
 assert.match(code,/@input="change"/);
 assert.match(code,/await confirmPreview\(song\)/);
 assert.doesNotMatch(code,/watch\(keyword[^)]*resolveQuery/);
});
test('exactly the first queue item is the next-track card',()=>{
 const code=read('frontend/src/components/NextTrack.vue'),css=read('frontend/src/round12.css');
 assert.match(code,/snapshot\?\.queue\?\.\[0\]/);
 assert.match(css,/#play-view #queue>li\[data-position="1"\]\{display:none\}/);
 assert.match(css,/grid-template-columns:minmax\(0,1fr\) minmax\(0,1fr\)/);
});
test('transport handlers remain in original playback component',()=>{
 const code=read('frontend/src/components/PlaybackBar.vue');
 if(code.includes('<template>')){assert.match(code,/id="toggle"/);assert.match(code,/id="skip"/);assert.match(code,/id="repeat"/);}
 assert.match(code,/syncIcon\(\)/);
});
