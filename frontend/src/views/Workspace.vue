<script setup lang="ts">
import Sidebar from '../components/Sidebar.vue'
import PageHeader from '../components/PageHeader.vue'
import PlayView from './PlayView.vue'
import PopularView from './PopularView.vue'
import LibraryView from './LibraryView.vue'
import AdminView from './AdminView.vue'
import Dialogs from '../components/Dialogs.vue'
import LyricsPanel from '../components/LyricsPanel.vue'
import PlaybackBar from '../components/PlaybackBar.vue'
</script>
<template><div id="dashboard" hidden><Sidebar/><main><PageHeader/><PlayView/><PopularView/><LibraryView/><Dialogs/><AdminView/><footer id="identity-note" data-i18n="m0047"></footer></main><LyricsPanel/><PlaybackBar/></div></template>
