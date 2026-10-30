<script setup lang="ts">
import HeaderSearch from './HeaderSearch.vue'
import {dashboard} from '../store'
import {t} from '../composables/useLocale'
import {logout,run,notice} from '../composables/useDashboard'
import {safeURL} from '../composables/useTrack'
</script>
<template><header class="page-heading"><h1>{{ t('m0224') }}</h1><HeaderSearch/><div id="user-profile" class="user-profile" :hidden="dashboard.authMode!=='discord'"><img id="user-avatar" v-if="safeURL(dashboard.me?.avatar)" :src="safeURL(dashboard.me?.avatar)" alt="" referrerpolicy="no-referrer"><span id="user-name">{{ dashboard.me?.name }}</span><details class="account-actions"><summary>{{ t('m0242') }}</summary><div><button id="logout" type="button" class="subtle" :disabled="dashboard.busy" @click="logout()">{{ t('m0243') }}</button><button id="logout-all" type="button" class="subtle" :disabled="dashboard.busy" @click="logout(true)">{{ t('m0244') }}</button></div></details></div></header><p id="notice" class="notice" :class="{visible:!!dashboard.toast,error:dashboard.toastError}" role="status" aria-live="polite" aria-atomic="true"><span>{{ dashboard.toast }}</span><button v-if="dashboard.undoToken" id="undo" type="button" :disabled="dashboard.busy" @click="run('queue/undo',{undo_token:dashboard.undoToken})">{{ t('m0122') }}</button><button id="notice-dismiss" class="notice-dismiss" type="button" :aria-label="t('m0118')" @click="notice('')">×</button></p></template>
