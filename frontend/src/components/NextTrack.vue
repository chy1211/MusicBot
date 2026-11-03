<script setup lang="ts">
import {t} from '../composables/useLocale'
import {computed} from 'vue'
import {dashboard,usable} from '../store'
import {run} from '../composables/useDashboard'
import {safeURL, duration} from '../composables/useTrack'
const next = computed(()=>dashboard.snapshot?.queue?.[0] || null)
const artist = computed(()=>next.value?.title.match(/^(.{1,70}?)\s+[-–—]\s+\S/)?.[1]?.trim() || '')
</script>
<template>
 <section class="card next-track-card" :aria-label="t('player.next')">
  <h2>{{t('player.next')}} <small>({{t('player.nextHint')}})</small></h2>
  <div v-if="next" class="next-track-entry">
   <div class="next-track-row">
    <img v-if="safeURL(next.thumbnail)" :src="safeURL(next.thumbnail)" alt="" loading="lazy" referrerpolicy="no-referrer">
    <span v-else class="next-track-fallback" aria-hidden="true">♫</span>
    <div class="next-track-text">
     <strong>{{next.title}}</strong>
     <small v-if="artist" class="next-track-artist">{{artist}}</small>
    </div>
   </div>
   <div class="next-track-footer">
    <small class="queue-requester next-track-requester">
     <span>{{t('m0062')}}</span>
     <img v-if="safeURL(next.requester?.avatar)" :src="safeURL(next.requester?.avatar)" alt="" loading="lazy" referrerpolicy="no-referrer">
     <span>{{next.requester?.name||t('m0045')}}</span>
    </small>
    <div class="next-track-actions">
     <time v-if="next.duration">{{duration(next.duration)}}</time>
     <button type="button" :disabled="!usable||(dashboard.snapshot?.queue.length||0)<2" :aria-label="t('m0069')+' '+next.title" @click="run('queue/move',{from:next.position,to:2,revision:dashboard.snapshot?.revision})">↓</button>
     <button class="next-track-remove" type="button" :disabled="!usable||dashboard.snapshot?.status==='disconnected'" :aria-label="t('m0004')+' '+next.title" @click="run('queue/'+next.position,{revision:dashboard.snapshot?.revision},'DELETE')">×</button>
    </div>
   </div>
  </div>
  <p v-else class="hint">{{t('player.nextEmpty')}}</p>
 </section>
</template>

<style scoped>
.next-track-entry{
 border:1px solid var(--line);
 border-radius:16px;
 padding:14px;
 background:var(--raised);
 min-width:0;
}
.next-track-row{
 display:grid;
 grid-template-columns:88px minmax(0,1fr);
 align-items:center;
 gap:14px;
 min-width:0;
}
.next-track-row>img,.next-track-row>.next-track-fallback{
 width:88px;
 height:88px;
 object-fit:cover;
 border-radius:12px;
}
.next-track-text{
 display:grid;
 gap:5px;
 min-width:0;
}
.next-track-text strong{
 display:block;
 white-space:normal;
 overflow:visible;
 overflow-wrap:anywhere;
 word-break:normal;
 line-height:1.4;
}
.next-track-artist{
 display:block;
 font-size:13px;
 line-height:1.45;
 overflow-wrap:anywhere;
}
.next-track-footer{
 display:flex;
 align-items:center;
 justify-content:space-between;
 gap:12px;
 min-width:0;
 margin-top:12px;
 padding-top:12px;
 border-top:1px solid var(--line);
}
.next-track-requester{
 flex:1 1 auto;
 min-width:0;
 overflow:hidden;
}
.next-track-actions{
 display:flex;
 align-items:center;
 gap:8px;
 flex:0 0 auto;
}
.next-track-actions time{
 color:var(--muted);
 white-space:nowrap;
 font-size:13px;
 font-variant-numeric:tabular-nums;
}
.next-track-actions button{
 display:inline-flex;
 justify-content:center;
 align-items:center;
 width:44px;
 height:44px;
 min-width:44px;
 min-height:44px;
 padding:0;
 border-radius:12px;
 font-size:22px;
 line-height:1;
}
@media(max-width:760px){
 .next-track-row{grid-template-columns:70px minmax(0,1fr);gap:12px}
 .next-track-row>img,.next-track-row>.next-track-fallback{width:70px;height:70px}
 .next-track-entry{padding:12px}
}
@media(max-width:350px){
 .next-track-footer{flex-wrap:wrap}
 .next-track-requester{flex-basis:100%}
 .next-track-actions{margin-left:auto}
}
</style>
