<script setup lang="ts">
import {ref, watch} from 'vue'
import {useRouter} from 'vue-router'
import {requests, resolveQuery, confirmPreview, clearPreview, type Preview} from '../composables/useRequests'
import {dashboard, usable} from '../store'
import {t} from '../composables/useLocale'
import {duration, safeURL} from '../composables/useTrack'
const router=useRouter()
const open=ref(false)
const input=ref<HTMLInputElement|null>(null)
const keyword=ref('')
let submitted=''
watch(()=>dashboard.epoch,()=>{open.value=false;keyword.value='';submitted=''})
function change(){open.value=false;clearPreview()}
async function search(){
 if(!keyword.value.trim()||!usable.value||requests.loading)return
 requests.query=keyword.value.trim();submitted=requests.query
 await resolveQuery()
 if(requests.query===submitted && requests.results.length)open.value=true
}
async function add(song:Preview){
 if(song.kind==='playlist'){
  open.value=false;await router.push('/play')
  document.getElementById('preview-panel')?.scrollIntoView({block:'start'})
  return
 }
 await confirmPreview(song)
 if(!requests.results.length){open.value=false;keyword.value='';submitted=''}
}
function key(event:KeyboardEvent){
 if(event.key==='Escape'){open.value=false;return}
 if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){
  event.preventDefault();input.value?.focus()
 }
}
function outside(event:PointerEvent){
 if(!(event.target as HTMLElement)?.closest('.header-search'))open.value=false
}
import {onMounted,onBeforeUnmount} from 'vue'
onMounted(()=>{document.addEventListener('keydown',key);document.addEventListener('pointerdown',outside)})
onBeforeUnmount(()=>{document.removeEventListener('keydown',key);document.removeEventListener('pointerdown',outside)})
</script>
<template><div class="header-search">
  <form class="header-search-form" role="search" @submit.prevent="search">
   <label class="sr-only" for="header-query">{{t('m0246')}}</label>
   <input id="header-query" ref="input" v-model="keyword" type="search" maxlength="2000" :placeholder="t('m0247')" @input="change" autocomplete="off">
   <button class="primary" type="submit" :disabled="!usable||!keyword.trim()||requests.loading" :aria-busy="requests.loading">{{t(requests.loading?'resolve.resolving':'m0248')}}</button>
  </form>
  <div v-if="open&&requests.results.length" class="header-search-popover" role="region" :aria-label="t('m0252')">
   <div class="header-search-title"><strong>{{t('m0252')}}</strong><button type="button" class="subtle" :aria-label="t('m0253')" @click="open=false">×</button></div>
   <ul><li v-for="song in requests.results" :key="song.preview_id" class="header-result">
    <img v-if="safeURL(song.thumbnail)" :src="safeURL(song.thumbnail)" alt="" loading="lazy" referrerpolicy="no-referrer">
    <div class="header-result-copy"><strong>{{song.title}}</strong><small v-if="song.artist">{{song.artist}}</small><small>{{song.duration?duration(song.duration):t('m0085')}}</small><small v-if="song.reason">{{song.reason}}</small></div>
    <button type="button" :disabled="!usable||!song.allowed||song.pending||dashboard.busy" :aria-label="t('m0612')+' '+song.title" @click="add(song)">{{song.kind==='playlist'?'⋯':'＋'}}</button>
   </li></ul>
  </div>
  <p v-if="requests.error" class="reason" role="alert">{{requests.error}}</p>
 </div></template>
