<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {translate} from '../composables/useLocale'
import {dashboardState} from '../store'
import {safeURL} from '../composables/useTrack'
const failed = ref(false)
const track = computed(() => dashboardState.value?.current)
const listeners = computed(() => dashboardState.value?.listeners?.members || [])
const expandedListeners = ref(false)
watch(()=>dashboardState.value?.guild_id,()=>expandedListeners.value=false)
const cover = computed(() => {const raw=track.value?.thumbnail?.trim();if(!raw || /[\u0000-\u001f]/.test(raw))return '';try {const u=new URL(raw);return ['http:','https:'].includes(u.protocol) && !u.username && !u.password ? u.href : ''} catch {return ''}})
watch(cover,()=>failed.value=false)
</script>
<template><section v-if="track" class="listening-stage" aria-labelledby="stage-title">
 <div class="stage-art"><img v-if="cover && !failed" :src="cover" alt="" @error="failed=true" /><span v-else aria-hidden="true">&#9835;</span></div>
 <div class="stage-copy"><p class="eyebrow">{{translate(dashboardState?.status==='preparing'?'player.preparingNext':'r27.now')}}</p><h2 id="stage-title">{{track.title}}</h2><div class="stage-request"><span class="hint">{{translate('m0062')}}</span><span class="listener"><img v-if="safeURL(track.requester?.avatar)" :src="safeURL(track.requester?.avatar)" alt="" loading="lazy" referrerpolicy="no-referrer"><span>{{track.requester?.name||translate('m0045')}}</span></span></div><div class="stage-wave" :class="{'is-playing':dashboardState?.status==='playing'}" aria-hidden="true"><i v-for="n in 12" :key="n" :style="{'--n':n}"></i></div><section class="stage-audience" aria-labelledby="listeners-heading"><h3 id="listeners-heading">{{translate('m0267')}}</h3><p id="listeners-status" class="hint" role="status">{{dashboardState?.listeners?.connected?translate('m0176')+' · '+dashboardState.listeners.channel+' · '+listeners.length+translate('m0177'):translate('m0178')}}</p><div id="listeners-list" class="listeners-list"><span v-for="(person,index) in expandedListeners?listeners:listeners.slice(0,8)" :key="person.id||index" class="listener"><img v-if="safeURL(person.avatar)" :src="safeURL(person.avatar)" alt="" loading="lazy" referrerpolicy="no-referrer"><span>{{person.name}}</span></span><button v-if="listeners.length>8" class="subtle" type="button" :aria-expanded="expandedListeners" @click="expandedListeners=!expandedListeners">{{expandedListeners?'−':translate('m0179')+(listeners.length-8)+translate('m0177')}}</button></div></section></div>
</section></template>
