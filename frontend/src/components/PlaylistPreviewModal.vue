<script setup lang="ts">
import {computed,onMounted, onBeforeUnmount, ref, watch} from 'vue'
import {headerRequests as requests, confirmHeaderPreview as confirmPreview, selectPreview, type Preview} from '../composables/useRequests'
import {dashboard, usable} from '../store'
import {t} from '../composables/useLocale'
import {duration, safeURL} from '../composables/useTrack'
import TrackArt from './TrackArt.vue'
import {useLibrary} from '../composables/useLibrary'
const props = defineProps<{song: Preview}>()
const emit = defineEmits<{(event: 'close'): void; (event: 'done'): void; (event: 'imported'): void}>()
const dialog = ref<HTMLDialogElement|null>(null)
const submitting = ref(false)
const importing = ref(false)
const library = useLibrary()
const importMode = ref<'existing'|'new'>('existing')
const targetId = ref('favorites')
const newName = ref('')
const importError = ref('')
const eligibleTargets = computed(() => library.playlists.value.filter(item => !item.source_url))
const activeSong = ref(props.song)
watch(()=>props.song, song=>activeSong.value=song)

onMounted(() => {
  dialog.value?.showModal()
  if (props.song.kind === 'playlist' && props.song.save_revision) {
    newName.value = props.song.title.slice(0,60)
    void library.load(true)
  }
})
onBeforeUnmount(() => {if(dialog.value?.open)dialog.value.close()})
async function importSelection(){
 if(importing.value || submitting.value || !activeSong.value.selected.length || !activeSong.value.save_revision) return
 if(importMode.value==='new' && !newName.value.trim()) return
 if(importMode.value==='existing' && !eligibleTargets.value.some(item=>item.id===targetId.value)) return
 // A changed library revision invalidates the one-time preview token. Re-search first.
 if(library.payload.value?.revision !== activeSong.value.save_revision){importError.value=t('r23.stale');return}
 importing.value=true
 importError.value=''
 try {
  const ok=await library.savePreview(activeSong.value,activeSong.value.selected,newName.value.trim(),importMode.value==='existing'?targetId.value:'')
  if(ok)emit('imported')
  else importError.value=library.loadError.value || t('r23.importFailed')
 }finally{importing.value=false}
}
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
  <div v-if="activeSong.kind==='playlist' && activeSong.save_revision" class="header-playlist-import">
   <strong>{{t('r23.import')}}</strong>
   <div class="import-mode" role="group" :aria-label="t('r23.destination')">
    <label><input v-model="importMode" type="radio" value="existing" :disabled="importing">{{t('r23.existing')}}</label>
    <label><input v-model="importMode" type="radio" value="new" :disabled="importing">{{t('r23.new')}}</label>
   </div>
   <template v-if="importMode==='existing'">
    <label for="r23-target">{{t('r23.destination')}}</label>
    <select id="r23-target" v-model="targetId" :disabled="importing || library.loading.value">
     <option v-for="item in eligibleTargets" :key="item.id" :value="item.id">{{library.playlistLabel(item)}}</option>
    </select>
   </template>
   <template v-else>
    <label for="r23-name">{{t('r23.name')}}</label>
    <input id="r23-name" v-model="newName" maxlength="60" :disabled="importing" autocomplete="off">
   </template>
   <p v-if="importError" class="reason" role="alert">{{importError}}</p>
   <button type="button" class="primary import-submit" :disabled="!usable || importing || submitting || library.loading.value || library.busy.value || !activeSong.selected.length || !activeSong.allowed || (importMode==='new'?!newName.trim():!eligibleTargets.some(item=>item.id===targetId))" :aria-busy="importing" @click="importSelection">{{importing?t('m0121'):t('r23.import')}}</button>
  </div>
  <footer class="playlist-modal-footer">
   <button type="button" class="subtle" @click="emit('close')">{{t('m0253')}}</button>
   <button type="button" class="primary" :disabled="!usable||!activeSong.allowed||!activeSong.selected.length||submitting||importing||activeSong.pending||dashboard.busy" :aria-busy="submitting" @click="addSelected">{{t('m0088')}}{{activeSong.selected.length}}{{t('m0089')}}</button>
  </footer>
 </dialog>
</template>
