<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { dashboard } from '../store'
import { t } from '../composables/useLocale'
import { usePopular } from '../composables/usePopular'
import { useLibrary } from '../composables/useLibrary'

const route = useRoute()
const popular = usePopular()
const library = useLibrary()
const visible = computed(() => route.path === '/popular')
const refreshVisible=()=>{if(visible.value&&dashboard.connected&&dashboard.authenticated)void popular.load()}
onMounted(refreshVisible)
onBeforeUnmount(()=>popular.cancelLoad())
watch(()=>[dashboard.guildId,dashboard.connected,dashboard.authenticated,dashboard.epoch],refreshVisible)
const statusText = computed(() => {
  if (popular.loading.value) return t('m0217')
  if (popular.error.value) return popular.error.value
  if (!popular.hasGuild.value) return t('m0216')
  if (popular.empty.value) return t('m0219')
  return t('m0218')
})
</script>

<template>
  <section id="popular-panel" class="card popular-page" :hidden="!visible" aria-labelledby="popular-heading">
    <header class="section-top popular-heading">
      <div><h2 id="popular-heading">{{ t('m0233') }}</h2></div>
      <button id="popular-refresh" type="button" class="subtle" :disabled="popular.loading.value || !popular.hasGuild.value" :aria-busy="popular.loading.value" @click="popular.load()">{{ t('m0269') }}</button>
    </header>
    <div class="popular-toolbar"><label for="popular-period">{{ t('m0271') }}</label><select id="popular-period" :value="popular.period.value" @change="popular.setPeriod(($event.target as HTMLSelectElement).value)"><option value="7">{{ t('m0272') }}</option><option value="30">{{ t('m0273') }}</option><option value="all">{{ t('m0274') }}</option></select></div>
    <p id="popular-status" class="hint popular-status" :class="{ 'popular-error': popular.error.value }" role="status" aria-live="polite" :aria-busy="popular.loading.value">{{ statusText }}</p>
    <ol id="popular-list" class="history-list popular-list" :aria-busy="popular.loading.value">
      <li v-if="popular.loading.value" v-for="n in 5" :key="n" class="popular-skeleton" aria-hidden="true"></li>
      <li v-for="(song, index) in popular.tracks.value" :key="song.url" class="popular-row">
        <span class="popular-rank" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</span>
        <div class="history-info"><p><a v-if="popular.safeUrl(song.url)" :href="popular.safeUrl(song.url)" target="_blank" rel="noopener noreferrer">{{ song.title }}</a><span v-else>{{ song.title }}</span></p><small>{{ song.count }} {{ t('m0220').replace(/\s*·\s*$/, '') }}<template v-if="song.duration"> · {{ library.formatDuration(song.duration) }}</template></small></div>
        <div class="history-actions">
          <button type="button" class="primary popular-add" :disabled="popular.adding.value !== null || dashboard.busy || !song.url" :aria-label="t('m0132') + song.title" :title="t('m0612')" :aria-busy="popular.adding.value === song.url" @click="popular.add(song)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg></button>
          <button type="button" class="subtle save-to-library" :disabled="!song.url" :aria-label="t('m0198') + ' ' + song.title" :title="t('m0198')" @click="library.openSave(song)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z" /></svg></button>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.popular-page[hidden]{display:none!important}.popular-heading{align-items:flex-end;margin-bottom:1rem}.popular-heading h2{margin:.15rem 0 0}.eyebrow{margin:0;color:var(--muted);font-size:.72rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase}.popular-toolbar{display:flex;align-items:center;gap:.7rem;margin:.8rem 0 1rem}.popular-toolbar label{font-size:.82rem;font-weight:650;color:var(--muted)}.popular-toolbar select{min-width:180px}.popular-status{min-height:1.5rem}.popular-error{color:var(--danger,var(--error))}.popular-list{display:grid;gap:.45rem;padding:0;list-style:none}.popular-row{display:grid;grid-template-columns:52px minmax(0,1fr) auto;align-items:center;gap:1rem;padding:.85rem;border:1px solid var(--line);border-radius:18px;background:color-mix(in srgb,var(--surface) 72%,transparent);transition:transform .16s ease,border-color .16s ease,background .16s ease}.popular-row:hover{transform:translateY(-1px);border-color:color-mix(in srgb,var(--green) 45%,var(--line))}.popular-rank{display:grid;place-items:center;width:42px;height:42px;border-radius:14px;background:var(--surface-2);font-variant-numeric:tabular-nums;font-weight:750;color:var(--green)}.history-info{min-width:0}.history-info p{margin:0;overflow-wrap:anywhere;font-weight:650}.history-info small{color:var(--muted)}.history-actions{display:flex;align-items:center;gap:.5rem}.popular-add,.save-to-library{min-height:44px}.popular-skeleton{height:74px;border-radius:18px;background:linear-gradient(100deg,var(--surface-2),var(--surface),var(--surface-2));background-size:200% 100%;animation:popular-shimmer 1.4s ease-in-out infinite}.popular-page :deep(button:focus-visible),.popular-page :deep(select:focus-visible){outline:3px solid var(--green);outline-offset:3px}@keyframes popular-shimmer{to{background-position-x:-200%}}@media(max-width:650px){.popular-row{grid-template-columns:42px minmax(0,1fr);gap:.7rem;padding:.7rem}.popular-rank{width:38px;height:38px}.history-actions{grid-column:2;justify-content:flex-start;flex-wrap:wrap}.popular-add,.save-to-library{flex:1 1 auto}.popular-toolbar{align-items:flex-start;flex-direction:column}.popular-toolbar select{width:100%}}@media(prefers-reduced-motion:reduce){.popular-row,.popular-skeleton{animation:none;transition:none}}
</style>



