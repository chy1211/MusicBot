<script setup lang="ts">
import {t} from '../composables/useLocale'
import {computed} from 'vue'
import {dashboard,usable} from '../store'
import {run} from '../composables/useDashboard'
import {safeURL, duration} from '../composables/useTrack'
const next = computed(()=>dashboard.snapshot?.queue?.[0] || null)
</script>
<template><section class="card next-track-card" :aria-label="t('player.next')">
  <h2>{{t('player.next')}} <small>({{t('player.nextHint')}})</small></h2>
  <div v-if="next" class="next-track-row">
   <img v-if="safeURL(next.thumbnail)" :src="safeURL(next.thumbnail)" alt="" loading="lazy" referrerpolicy="no-referrer">
   <span v-else class="next-track-fallback" aria-hidden="true">♫</span>
   <div class="next-track-text"><strong>{{next.title}}</strong><small>{{t('m0062')}}{{next.requester?.name||t('m0045')}}</small></div>
   <time v-if="next.duration">{{duration(next.duration)}}</time>
   <button type="button" :disabled="!usable||(dashboard.snapshot?.queue.length||0)<2" :aria-label="t('m0069')+' '+next.title" @click="run('queue/move',{from:next.position,to:2,revision:dashboard.snapshot?.revision})">↓</button>
   <button class="next-track-remove" type="button" :disabled="!usable||dashboard.snapshot?.status==='disconnected'" :aria-label="t('m0004')+' '+next.title" @click="run('queue/'+next.position,{revision:dashboard.snapshot?.revision},'DELETE')">×</button>
  </div><p v-else class="hint">{{t('player.nextEmpty')}}</p>
 </section></template>
