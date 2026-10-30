'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const read=p=>fs.readFileSync(path.join(root,p),'utf8');
const css=()=>read('frontend/src/styles/mobile-refinements.css');

test('mobile-only listening layout keeps existing stage, sound wave and controls separate',()=>{
  const c=css();
  const view=read('frontend/src/components/NowPlaying.vue');
  assert.match(c,/@media \(max-width:760px\) and \(orientation:portrait\)/);
  assert.match(c,/grid-template-columns:clamp\(94px,29vw,112px\) minmax\(0,1fr\)/);
  assert.match(c,/\.stage-wave\s*\{[^}]*display:flex !important/);
  assert.match(c,/#stage-title\s*\{[^}]*grid-column:2;grid-row:2/);
  assert.match(view,/class="stage-wave"/);
  assert.doesNotMatch(c,/\#playback-bar\s*\{/);
});

test('listener name remains accessible in DOM but only avatars visible on mobile',()=>{
  const c=css(), view=read('frontend/src/components/NowPlaying.vue');
  assert.match(c,/\.listeners-list \.listener:has\(img\) > span\s*\{[^}]*clip:rect/);
  assert.match(view,/\{\{person.name\}\}/);
});

test('header controls are in flow, and history buttons cannot wrap',()=>{
  const c=css();
  assert.match(c,/\.language-preference\s*\{[^}]*position:relative !important/);
  assert.match(c,/\.history-actions\s*\{[^}]*grid-column:3;grid-row:1/);
  assert.match(c,/flex-wrap:nowrap/);
  assert.match(c,/\.queue\s*\{margin-bottom:18px/);
});

test('popular actions keep event handlers and aria labels using inline vector icons',()=>{
  const view=read('frontend/src/views/PopularView.vue');
  assert.match(view,/@click="popular\.add\(song\)"/);
  assert.match(view,/@click="library\.openSave\(song\)"/);
  assert.match(view,/:aria-label="t\('m0132'\) \+ song.title"/);
  assert.match(view,/<svg viewBox="0 0 24 24" aria-hidden="true">/);
});

test('queue button uses the original notice pulse without introducing new keyframes',()=>{
  const action=read('frontend/src/composables/useAddToQueue.ts');
  const c=css();
  assert.match(action,/notice\(t\('m0121'\)\)/);
  assert.match(c,/animation:notice-blink 1.2s/);
  assert.doesNotMatch(c,/@keyframes/);
  assert.match(c,/@media\(prefers-reduced-motion:reduce\)/);
});
