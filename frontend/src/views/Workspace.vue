<script setup lang="ts">
import {onMounted,onBeforeUnmount,watch,nextTick} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {dashboard} from '../store'
import {t} from '../composables/useLocale'
import Sidebar from '../components/Sidebar.vue'
import PageHeader from '../components/PageHeader.vue'
import PlayView from './PlayView.vue'
import PopularView from './PopularView.vue'
import LibraryView from './LibraryView.vue'
import AdminView from './AdminView.vue'
import Dialogs from '../components/Dialogs.vue'
import LyricsPanel from '../components/LyricsPanel.vue'
import PlaybackBar from '../components/PlaybackBar.vue'
const route=useRoute(),router=useRouter()
function navigate(event:Event){const page=(event as CustomEvent<string>).detail;if(['play','library','popular','admin'].includes(page))void router.push('/'+page)}
watch(()=>route.path,async()=>{await nextTick();window.scrollTo({top:0,behavior:'instant'});document.querySelector<HTMLElement>('main h2')?.focus({preventScroll:true})})
onMounted(()=>window.addEventListener('musicbot:navigate',navigate));onBeforeUnmount(()=>window.removeEventListener('musicbot:navigate',navigate))
</script>
<template><div id="dashboard" :hidden="!dashboard.authenticated"><a class="skip-link" href="#main-content">{{ t('m0231') }}</a><Sidebar/><main id="main-content" tabindex="-1"><PageHeader/><PlayView :hidden="!['/','/play'].includes(route.path)"/><PopularView/><LibraryView/><div :hidden="route.path!=='/admin'"><AdminView/></div><footer id="identity-note">{{ t(dashboard.authMode==='discord'?'m0046':'m0047') }}</footer></main><Dialogs/><LyricsPanel/><PlaybackBar/></div></template>
