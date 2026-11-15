<script setup lang="ts">
import {ref} from 'vue'
import {dashboard} from '../store'
import {t} from '../composables/useLocale'

const retry = ref(new URLSearchParams(window.location.search).get('login') === 'retry')
const pending = ref(false)
const failed = ref(false)

async function login() {
  if (pending.value) return
  pending.value = true
  retry.value = failed.value = false
  try {
    // Store the first-party cookie before navigating to Discord.
    const response = await fetch('/auth/login', {method: 'POST', credentials: 'same-origin'})
    if (response.status === 405) {
      window.location.assign('/auth/login')
      return
    }
    if (!response.ok) throw new Error('login preparation failed')
    const {authorize_url} = await response.json()
    const destination = new URL(authorize_url)
    if (destination.origin !== 'https://discord.com' || destination.pathname !== '/oauth2/authorize') {
      throw new Error('unexpected login destination')
    }
    window.location.assign(destination.href)
  } catch {
    failed.value = true
    pending.value = false
  }
}
</script>
<template>
  <section id="login-screen" class="login-screen" :hidden="dashboard.authenticated" aria-labelledby="login-heading">
    <div class="login-card">
      <span class="login-icon" aria-hidden="true">♫</span>
      <h1 id="login-heading">{{ t('m0224') }}</h1>
      <p>{{ t('m0225') }}</p>
      <p id="login-status" class="hint" :class="{error: retry || failed || dashboard.loginError}" role="status" aria-live="polite">
        {{ retry ? t('auth.retry') : failed ? t('auth.startError') : dashboard.loginStatus || t('m0226') }}
      </p>
      <a id="discord-login" class="primary login-button" :hidden="dashboard.authMode!=='discord'" :aria-disabled="pending" href="/auth/login" @click.prevent="login">{{ t('m0227') }}</a>
    </div>
  </section>
</template>
