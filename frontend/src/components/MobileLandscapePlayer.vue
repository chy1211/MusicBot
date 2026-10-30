<script setup lang="ts">
import {computed,ref,onMounted,onBeforeUnmount} from 'vue'
import {t} from '../composables/useLocale'
import {dashboard,usable} from '../store'
import {run} from '../composables/useDashboard'
import {safeURL,duration} from '../composables/useTrack'
import {player,progress,seekable,beginSeek,previewSeek,commitSeek} from '../composables/usePlayback'
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
   <div class="landscape-track"><h2>{{song?.title}}</h2><p>{{song?.requester?.name||''}}</p></div>
   <div class="landscape-buttons">
    <button type="button" :disabled="!usable||state?.capabilities?.skip!==true" :aria-label="t('m0332')" @click="run('skip')">⏭</button>
    <button class="primary" type="button" :disabled="!usable||!song||!['playing','paused'].includes(state?.status||'')||state?.capabilities?.[state.status==='playing'?'pause':'resume']!==true" :aria-label="t('m0331')" @click="run(state?.status==='playing'?'pause':'resume')">{{state?.status==='playing'?'Ⅱ':'▶'}}</button>
   </div>
   <div class="landscape-progress"><input type="range" min="0" :max="song?.duration||1" step="1" :value="player.preview??progress" :disabled="!seekable" :aria-label="t('player.position')" @pointerdown="beginSeek('pointer',$event)" @input="previewSeek" @change="seekChange"><div><span>{{duration(player.preview??progress)}}</span><span>{{duration(song?.duration)}}</span></div></div>
   <p class="landscape-hint">{{t('player.rotateHint')}}</p>
  </div>
 </section></template>
