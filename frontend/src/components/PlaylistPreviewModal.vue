<script setup lang="ts">
import {onMounted, onBeforeUnmount, ref, watch} from 'vue'
import {requests, confirmPreview, selectPreview, type Preview} from '../composables/useRequests'
import {dashboard, usable} from '../store'
import {t} from '../composables/useLocale'
import {duration, safeURL} from '../composables/useTrack'
import TrackArt from './TrackArt.vue'
const props = defineProps<{song: Preview}>()
const emit = defineEmits<{(event: 'close'): void; (event: 'done'): void}>()
const dialog = ref<HTMLDialogElement|null>(null)
const submitting = ref(false)
const activeSong = ref(props.song)
watch(()=>props.song, song=>activeSong.value=song)

onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => {if(dialog.value?.open)dialog.value.close()})
async function addSelected(){
 if(submitting.value || activeSong.value.pending || !activeSong.value.selected.length)return
 submitting.value=true
 try {
  await confirmPreview(activeSong.value)
  if(!requests.results.length)emit('done')
  else {const fresh=requests.results.find(song=>song.kind==='playlist');if(fresh)activeSong.value=fresh}
 } finally {submitting.value=false}
}
</script>
<template>
 <dialog ref="dialog" class="header-playlist-modal" :aria-label="activeSong.title" @close="emit('close')" @cancel.prevent="emit('close')">
  <header class="playlist-modal-heading"><div><small>{{t('m0081')}}</small><h2>{{activeSong.title}}</h2><p class="hint">{{activeSong.checked_count??activeSong.entries?.length??0}} / {{activeSong.count??activeSong.entries?.length??0}}</p></div>
    <button type="button" class="subtle" :aria-label="t('m0253')" @click="emit('close')">×</button></header>
  <p v-if="activeSong.reason||activeSong.warning" class="hint">{{activeSong.reason||activeSong.warning}}</p>
  <p v-if="dashboard.toastError" role="alert">{{dashboard.toast}}</p>
  <div class="playlist-modal-tools">
   <button type="button" :disabled="!activeSong.allowed||submitting" @click="selectPreview(activeSong,true)">{{t('m0093')}}</button>
   <button type="button" :disabled="submitting" @click="selectPreview(activeSong,false)">{{t('m0094')}}</button>
   <span>{{t('m0087')}}{{activeSong.selected.length}}{{t('m0033')}}</span>
  </div>
  <ol class="playlist-modal-entries">
   <li v-for="item in activeSong.entries||[]" :key="item.item_id">
    <label>
     <input v-model="activeSong.selected" type="checkbox" :value="item.item_id" :disabled="!activeSong.allowed||!item.allowed||submitting"/>
     <TrackArt :track="item"/>
     <span class="playlist-modal-entry-label"><strong>{{item.title}}</strong><small>{{item.duration?duration(item.duration):t('m0085')}}</small><small v-if="item.reason">{{item.reason}}</small></span>
    </label>
   </li>
  </ol>
  <footer class="playlist-modal-footer">
   <button type="button" class="subtle" @click="emit('close')">{{t('m0253')}}</button>
   <button type="button" class="primary" :disabled="!usable||!activeSong.allowed||!activeSong.selected.length||submitting||activeSong.pending||dashboard.busy" :aria-busy="submitting" @click="addSelected">{{t('m0088')}}{{activeSong.selected.length}}{{t('m0089')}}</button>
  </footer>
 </dialog>
</template>
