<script setup lang="ts">
import {defineAsyncComponent,onMounted,onBeforeUnmount,watch,nextTick} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {dashboard} from '../store'
import {t} from '../composables/useLocale'
import {useLibrary} from '../composables/useLibrary'
import Sidebar from '../components/Sidebar.vue'
import PageHeader from '../components/PageHeader.vue'
const PlayView=defineAsyncComponent(()=>import('./PlayView.vue'))
import MobileLandscapePlayer from '../components/MobileLandscapePlayer.vue'
const PopularView=defineAsyncComponent(()=>import('./PopularView.vue'))
const LibraryView=defineAsyncComponent(()=>import('./LibraryView.vue'))
const AdminView=defineAsyncComponent(()=>import('./AdminView.vue'))
import Dialogs from '../components/Dialogs.vue'
import LyricsPanel from '../components/LyricsPanel.vue'
import PlaybackBar from '../components/PlaybackBar.vue'
const route=useRoute(),router=useRouter()
const library=useLibrary()
function navigate(event:Event){const page=(event as CustomEvent<string>).detail;if(['play','library','popular','admin'].includes(page))void router.push('/'+page)}
watch(()=>route.path,async()=>{await nextTick();window.scrollTo({top:0,behavior:'instant'});document.querySelector<HTMLElement>('main h2')?.focus({preventScroll:true})})
onMounted(()=>window.addEventListener('musicbot:navigate',navigate));onBeforeUnmount(()=>window.removeEventListener('musicbot:navigate',navigate))
</script>
<template><div id="dashboard" :hidden="!dashboard.authenticated"><a class="skip-link" href="#main-content">{{ t('m0231') }}</a><Sidebar/><main id="main-content" tabindex="-1"><PageHeader/><PlayView v-if="dashboard.authenticated&&['/','/play'].includes(route.path)"/><PopularView v-if="dashboard.authenticated&&route.path==='/popular'"/><LibraryView v-if="dashboard.authenticated&&(route.path==='/library'||library.saveDialogOpen.value)"/><AdminView v-if="dashboard.authenticated&&route.path==='/admin'"/><footer id="identity-note">{{ t(dashboard.authMode==='discord'?'m0046':'m0047') }}</footer></main><Dialogs/><LyricsPanel/><PlaybackBar/><MobileLandscapePlayer/></div></template>
