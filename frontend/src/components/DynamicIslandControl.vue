<script setup lang="ts">
import {useDynamicIsland} from '../composables/useDynamicIsland'
import {t} from '../composables/useLocale'

const {supported, state, error, canStart, showStartNotice, start, stop} = useDynamicIsland()
</script>

<template>
  <Teleport v-if="showStartNotice" to="#dashboard-sidebar">
    <button id="island-activate-notice" type="button" :disabled="!canStart" @click="start()">
      {{ t(state === 'starting' ? 'island.status.starting' : 'island.activate') }}
    </button>
  </Teleport>
  <section v-if="supported" class="card dynamic-island" :aria-label="t('island.label')">
    <div class="dynamic-island__heading">
      <strong>{{ t('island.heading') }}</strong>
      <small>{{ t('island.subtitle') }}</small>
    </div>
    <div class="dynamic-island__actions">
      <button v-if="state !== 'active'" type="button"
        :disabled="!canStart" @click="start()">
        {{ state === 'interrupted' ? t('island.resume') : t('island.activate') }}
      </button>
      <button v-else type="button" @click="stop()">{{ t('island.stop') }}</button>
      <span role="status" aria-live="polite">
        {{ state === 'active' ? t('island.status.active') :
           state === 'starting' ? t('island.status.starting') :
          state === 'awaiting-gesture' ? t('island.status.awaitingGesture') :
           state === 'interrupted' ? t('island.status.interrupted') :
           t('island.status.off') }}
      </span>
    </div>
    <p v-if="error" class="dynamic-island__error" role="alert">{{ error }}</p>
    <small>{{ t('island.warning') }}</small>
  </section>
</template>

<style scoped>
.dynamic-island { display: grid; gap: 10px; }
.dynamic-island__heading { display: flex; flex-direction: column; gap: 4px; }
.dynamic-island__actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.dynamic-island__actions button { cursor: pointer; }
.dynamic-island__error { color: var(--danger, #e86b72); }
</style>
