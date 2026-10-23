<script setup lang="ts">
import {dashboard} from '../store'
import {t} from '../composables/useLocale'
</script>
<template><section id="login-screen" class="login-screen" :hidden="dashboard.authenticated" aria-labelledby="login-heading"><div class="login-card"><span class="login-icon" aria-hidden="true">♫</span><h1 id="login-heading">{{ t('m0224') }}</h1><p>{{ t('m0225') }}</p><p id="login-status" class="hint" :class="{error:dashboard.loginError}" role="status" aria-live="polite">{{ dashboard.loginStatus || t('m0226') }}</p><a id="discord-login" class="primary login-button" :hidden="dashboard.authMode!=='discord'" href="/auth/login">{{ t('m0227') }}</a></div></section></template>
