<script setup lang="ts">
import {computed,ref,onMounted,onBeforeUnmount} from 'vue'
import {t} from '../composables/useLocale'
import {dashboard,usable} from '../store'
import {run} from '../composables/useDashboard'
import {safeURL,duration} from '../composables/useTrack'
import {player,progress,seekable,beginSeek,previewSeek,commitSeek} from '../composables/usePlayback'
import {useLibrary} from '../composables/useLibrary'
const library=useLibrary()
const song=computed(()=>dashboard.snapshot?.current)
const state=computed(()=>dashboard.snapshot)
const exit=ref(false)
function orientation(){if(window.innerHeight>=window.innerWidth)exit.value=false}
onMounted(()=>window.addEventListener('resize',orientation))
onBeforeUnmount(()=>window.removeEventListener('resize',orientation))
function seekChange(){void commitSeek()}
</script>
<template><section class="mobile-landscape" :hidden="exit||!song" :aria-label="t('player.landscape')">
  <div class="landscape-art"><img v-if="safeURL(song?.thumbnail)" :src="safeURL(song?.thumbnail)" alt="" referrerpolicy="no-referrer"><span v-else>♫</span></div>
  <div class="landscape-controls">
   <div class="landscape-top"><button class="subtle" type="button" :aria-label="t('player.return')" @click="exit=true">‹ {{t('player.returnShort')}}</button><span>{{t('m0223')}}</span></div>
   <div class="landscape-track"><h2>{{song?.title}}</h2><p class="landscape-requester"><img v-if="safeURL(song?.requester?.avatar)" :src="safeURL(song?.requester?.avatar)" alt="" loading="lazy" referrerpolicy="no-referrer"><span v-else class="landscape-requester-fallback" aria-hidden="true"><svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-6 16-6 16 0"/></svg></span><span>{{song?.requester?.name||t('m0045')}}</span></p></div>
   <div class="landscape-buttons">
    <button class="landscape-favorite" type="button" :disabled="!usable||!safeURL(song?.url)||library.busy.value" :aria-label="t(library.isFavorite()?'m0200':'m0201')" :aria-pressed="library.isFavorite()" @click="library.toggleFavorite()"><svg viewBox="0 0 24 24" class="landscape-icon" aria-hidden="true"><path d="M20.8 8.1c0 4.2-8.8 10.1-8.8 10.1S3.2 12.3 3.2 8.1A4.9 4.9 0 0 1 12 5.1a4.9 4.9 0 0 1 8.8 3Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg></button>
    <button class="landscape-toggle primary" type="button" :disabled="!usable||!song||!['playing','paused'].includes(state?.status||'')||state?.capabilities?.[state.status==='playing'?'pause':'resume']!==true" :aria-label="t('m0331')" @click="run(state?.status==='playing'?'pause':'resume')"><svg v-if="state?.status==='playing'" class="landscape-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="4.5" width="4.5" height="15" rx="1.1" fill="currentColor"/><rect x="13.5" y="4.5" width="4.5" height="15" rx="1.1" fill="currentColor"/></svg><svg v-else class="landscape-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5a1 1 0 0 1 1.5-.86l11 7.5a1 1 0 0 1 0 1.72l-11 7.5A1 1 0 0 1 7 19.5z" fill="currentColor"/></svg></button>
    <button class="landscape-skip" type="button" :disabled="!usable||state?.capabilities?.skip!==true" :aria-label="t('m0332')" @click="run('skip')"><svg class="landscape-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5a1 1 0 0 1 1.5-.86l9 6.5a1 1 0 0 1 0 1.72l-9 6.5A1 1 0 0 1 4 18.5z" fill="currentColor"/><rect x="17" y="4.5" width="3" height="15" rx="1" fill="currentColor"/></svg></button>
   </div>
   <div class="landscape-progress"><input type="range" min="0" :max="song?.duration||1" step="1" :value="player.preview??progress" :disabled="!seekable" :aria-label="t('player.position')" @pointerdown="beginSeek('pointer',$event)" @input="previewSeek" @change="seekChange"><div><span>{{duration(player.preview??progress)}}</span><span>{{duration(song?.duration)}}</span></div></div>
   <p class="landscape-hint">{{t('player.rotateHint')}}</p>
  </div>
 </section></template>
