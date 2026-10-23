<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {translate} from '../composables/useLocale'
import {dashboardState} from '../store'
const failed = ref(false)
const track = computed(() => dashboardState.value?.current)
const cover = computed(() => {const raw=track.value?.thumbnail?.trim();if(!raw || /[\u0000-\u001f]/.test(raw))return '';try {const u=new URL(raw);return ['http:','https:'].includes(u.protocol) && !u.username && !u.password ? u.href : ''} catch {return ''}})
watch(cover,()=>failed.value=false)
</script>
<template><section v-if="track" class="listening-stage" aria-labelledby="stage-title">
 <div class="stage-art"><img v-if="cover && !failed" :src="cover" alt="" @error="failed=true" /><span v-else aria-hidden="true">&#9835;</span></div>
 <div class="stage-copy"><p class="eyebrow">{{translate("r27.now")}}</p><h2 id="stage-title">{{track.title}}</h2><p class="stage-credit">{{track.requester?.name}}</p><div class="stage-wave" :class="{'is-playing':dashboardState?.status==='playing'}" aria-hidden="true"><i v-for="n in 12" :key="n" :style="{'--n':n}"></i></div></div>
</section></template>
