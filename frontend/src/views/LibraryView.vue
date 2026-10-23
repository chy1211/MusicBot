<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { dashboard } from '../store'
import { t } from '../composables/useLocale'
import { useLibrary } from '../composables/useLibrary'
import PlaylistCover from '../components/PlaylistCover.vue'
import TrackArt from '../components/TrackArt.vue'
import { trackThumbnail } from '../composables/useTrack'

const route = useRoute()
const router = useRouter()
const library = useLibrary()
const visible = computed(() => route.path === '/library')
const detailHeading = ref<HTMLElement | null>(null)
const saveSelect = ref<HTMLSelectElement | null>(null)
const saveDialog = ref<HTMLDialogElement | null>(null)
const active = library.activePlaylist
const sourceLabel = computed(() => active.value?.source_type === 'spotify' ? 'Spotify' : active.value?.source_url ? 'YouTube' : '')

function playlistMeta(item: { id: string; tracks: unknown[]; source_url?: string; source_type?: string }): string {
  const source = item.source_type === 'spotify' ? 'Spotify' : item.source_url ? 'YouTube' : item.id === 'favorites' ? t('m0192') : t('m0193')
  return item.tracks.length + ' ' + t('m0033').trim() + (source ? ' · ' + source : '')
}

function submitSave(): void {
  const id = saveSelect.value?.value
  if (id) void library.savePending(id)
}
function chooseList(id: string): void {
  void router.push({ path: '/library', query: { ...route.query, playlist: id } })
}
function backToLists(): void {
  if (router.options.history.state.back === '/library') router.back()
  else {
    const { playlist: _playlist, ...query } = route.query
    void router.replace({ path: '/library', query })
  }
}
function toggleAllSelected(): void {
  const songs = active.value?.tracks ?? []
  library.selected.value = library.selected.value.length === songs.length ? [] : songs.map((_, index) => index)
}
function closeDialog(): void {
  library.closeSave()
  saveDialog.value?.close()
}

watch(() => [route.path, route.query.playlist] as const, async ([path, id]) => {
  if (path === '/library' && typeof id === 'string') library.setActive(id)
  else library.detailOpen.value = false
  await nextTick()
  if (path !== '/library') return
  if (library.detailOpen.value) detailHeading.value?.focus({ preventScroll: true })
  else document.querySelector<HTMLButtonElement>('#library-playlists [aria-current=true]')?.focus({ preventScroll: true })
}, { immediate: true })

onMounted(() => { if (dashboard.authenticated) void library.load() })
watch(library.saveDialogOpen, async open => {
  await nextTick()
  if (open && saveDialog.value && !saveDialog.value.open) saveDialog.value.showModal()
  if (!open && saveDialog.value?.open) saveDialog.value.close()
  if (open) saveSelect.value?.focus({ preventScroll: true })
})
</script>

<template>
  <section id="library-panel" class="card library-page" :class="{ 'detail-open': library.detailOpen.value }" :hidden="!visible" aria-labelledby="library-heading">
    <header class="section-top library-page-heading">
      <div><p class="eyebrow">{{ t('m0232') }}</p><h2 id="library-heading">{{ t('m0232') }}</h2></div>
      <button id="library-refresh" type="button" class="subtle" :disabled="library.loading.value || library.busy.value" :aria-busy="library.loading.value" @click="library.load()">
        {{ library.loading.value ? t('m0217') : t('m0269') }}
      </button>
    </header>

    <div v-if="library.loading.value && !library.payload.value" class="library-loading" role="status" aria-live="polite">
      <span class="sr-only">{{ t('m0217') }}</span><div v-for="n in 3" :key="n" class="library-skeleton" aria-hidden="true"></div>
    </div>
    <div v-else-if="!dashboard.authenticated" class="library-empty-state" role="status"><span class="empty-glyph" aria-hidden="true">♫</span><h3>{{ t('m0216') }}</h3></div>
    <div v-else class="library-workspace" :class="{ 'detail-open': library.detailOpen.value }">
      <aside class="library-sidebar" :aria-label="t('m0275')">
        <form id="library-create" class="library-create-form" @submit.prevent="library.createPlaylist">
          <label for="library-new-name">{{ t('m0277') }}</label>
          <div class="library-create-row"><input id="library-new-name" v-model="library.createName.value" maxlength="60" required :placeholder="t('m0276')"><button id="library-create-button" type="submit" class="primary" :disabled="library.busy.value || !library.createName.value.trim()" :aria-busy="library.busy.value">{{ t('m0278') }}</button></div>
        </form>
        <button id="library-import-hint" class="subtle library-import-hint" type="button" @click="library.goToPlay">{{ t('m0202') }}</button>
        <p v-if="library.loadError.value" class="library-error" role="alert">{{ library.loadError.value }}</p>
        <ul id="library-playlists" class="library-playlists" :aria-busy="library.loading.value">
          <li v-for="item in library.playlists.value" :key="item.id">
            <button type="button" class="library-choice" :aria-current="item.id === library.activeId.value ? 'true' : undefined" @click="chooseList(item.id)">
              <PlaylistCover :tracks="item.tracks" :size="52" :label="library.playlistLabel(item)" />
              <span class="library-choice-title">{{ library.playlistLabel(item) }}</span>
              <small>{{ playlistMeta(item) }}</small>
            </button>
          </li>
        </ul>
        <p v-if="!library.loading.value && !library.playlists.value.length" class="hint library-no-lists">{{ t('m0192') }}</p>
      </aside>

      <section id="library-detail" class="library-detail" aria-labelledby="library-detail-heading">
        <button id="library-back" type="button" class="subtle library-back" @click="backToLists">← <span>{{ t('m0279') }}</span></button>
        <template v-if="active">
          <div class="library-detail-title-row">
            <PlaylistCover :tracks="active.tracks" :size="72" :label="library.playlistLabel(active)" class="playlist-cover-hero" />
            <div class="library-detail-title"><p class="eyebrow">{{ t('m0232') }}</p><h3 id="library-detail-heading" ref="detailHeading" tabindex="-1">{{ library.playlistLabel(active) }}</h3><p id="library-meta" class="hint">{{ active.tracks.length }} {{ t('m0033') }}<template v-if="sourceLabel"> · {{ sourceLabel }}</template></p></div>
          </div>
          <p v-if="active.source_url" id="library-source" class="library-source">{{ t('m0204') }}</p>
          <div class="library-toolbar">
            <button id="library-play-all" class="primary" type="button" :disabled="!active.tracks.length || !dashboard.connected || dashboard.busy || library.busy.value" :aria-busy="library.busy.value" @click="library.playAll">{{ t('m0280') }}</button>
            <button id="library-enqueue-all" type="button" :disabled="!active.tracks.length || !dashboard.connected || dashboard.busy || library.busy.value" @click="library.enqueueAll">{{ t('m0283') }}</button>
            <button id="library-play-selected" type="button" :disabled="!library.canPlaySelected.value || !dashboard.connected || dashboard.busy" @click="library.playSelected">{{ t('m0281') }}<template v-if="library.selected.value.length"> · {{ library.selected.value.length }}</template></button>
            <details id="library-actions" class="library-actions"><summary :aria-label="t('m0282')">•••</summary>
              <div class="library-menu">
                <label for="library-name">{{ t('m0284') }}</label><div class="library-rename-row"><input id="library-name" v-model="library.renameName.value" maxlength="60" :disabled="active.id === 'favorites'"><button id="library-rename" type="button" :disabled="active.id === 'favorites' || library.busy.value || !library.renameName.value.trim()" @click="library.renamePlaylist">{{ t('m0285') }}</button></div>
                <button id="library-sync" v-if="active.source_url" type="button" :disabled="library.busy.value" @click="library.syncPlaylist">{{ t('m0203') }}</button>
                <button id="library-delete" type="button" class="danger" :hidden="active.id === 'favorites'" :disabled="library.busy.value" @click="library.deletePlaylist">{{ t('m0286') }}</button>
              </div>
            </details>
          </div>
          <p v-if="library.loadError.value" class="library-error" role="alert">{{ library.loadError.value }}</p>
          <div v-if="active.tracks.length" class="library-track-tools"><span class="hint">{{ active.tracks.length }} {{ t('m0033').trim() }}</span><button type="button" class="subtle" @click="toggleAllSelected">{{ library.selected.value.length === active.tracks.length ? t('m0261') : t('m0281') }}</button></div>
          <p v-if="!active.tracks.length" id="library-empty" class="library-empty-state" role="status"><span class="empty-glyph" aria-hidden="true">♫</span>{{ t('m0287') }}</p>
          <ol id="library-list" class="library-list">
            <li v-for="(song, index) in active.tracks" :key="song.url + index" class="library-track">
              <input type="checkbox" :checked="library.selected.value.includes(index)" :aria-label="t('m0095') + song.title" @change="library.toggleTrack(index, ($event.target as HTMLInputElement).checked)">
              <TrackArt class="library-track-cover" :track="{ thumbnail: trackThumbnail(song) }" />
              <div class="song"><p><a v-if="library.safeUrl(song.url)" :href="library.safeUrl(song.url)" target="_blank" rel="noopener noreferrer">{{ song.title }}</a><span v-else>{{ song.title }}</span></p><small>{{ library.formatDuration(song.duration) }}</small></div>
              <button type="button" class="subtle library-remove" :aria-label="t('m0194') + song.title" :disabled="library.busy.value" @click="library.removeTrack(index)">{{ t('m0004') }}</button>
            </li>
          </ol>
        </template>
        <div v-else class="library-empty-state"><span class="empty-glyph" aria-hidden="true">♫</span><h3>{{ t('m0232') }}</h3><p>{{ t('m0287') }}</p></div>
      </section>
    </div>
  </section>

    <dialog id="library-save-dialog" ref="saveDialog" class="library-save-dialog" @cancel.prevent="closeDialog" @click.self="closeDialog">
      <form @submit.prevent="submitSave">
        <p class="eyebrow">{{ t('m0299') }}</p><h2>{{ t('m0300') }}</h2>
        <label for="playlist-picker">{{ t('m0300') }}</label>
        <select id="playlist-picker" ref="saveSelect" :disabled="library.busy.value">
          <option v-for="item in library.saveChoices.value" :key="item.id" :value="item.id">{{ library.playlistLabel(item) }}</option>
        </select>
        <div class="selection-tools"><button id="library-save-confirm" class="primary" type="submit" :disabled="library.busy.value || !library.saveChoices.value.length" :aria-busy="library.busy.value">{{ t('m0301') }}</button><button id="library-save-cancel" type="button" class="subtle" @click="closeDialog">{{ t('m0302') }}</button></div>
      </form>
    </dialog>
</template>

<style scoped>
.library-page{overflow:visible}.library-page-heading{align-items:flex-end;margin-bottom:1.25rem}.library-page-heading h2{margin:.15rem 0 0}.eyebrow{margin:0;color:var(--muted);font-size:.72rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase}.library-workspace{display:grid;grid-template-columns:minmax(220px,.78fr) minmax(0,1.5fr);gap:clamp(1rem,2vw,2rem)}.library-sidebar{min-width:0}.library-create-form,.library-menu{display:grid;gap:.6rem}.library-create-form label,.library-menu label,.library-save-dialog label{font-size:.8rem;font-weight:650;color:var(--muted)}.library-create-row,.library-rename-row{display:flex;gap:.5rem;min-width:0}.library-create-row input,.library-rename-row input{min-width:0;flex:1}.library-rename-row input{width:0;min-width:60%;flex:1 1 0}.library-rename-row button{width:auto;flex:0 0 auto;white-space:nowrap}.library-import-hint{margin:.65rem 0;width:100%;text-align:left}.library-playlists{display:grid;gap:.55rem;padding:0;margin:.25rem 0;list-style:none}.library-choice{display:grid;grid-template-columns:52px minmax(0,1fr);grid-template-rows:auto auto;align-items:center;gap:.12rem .75rem;width:100%;padding:.65rem;border-radius:16px;text-align:left}.library-choice .playlist-cover{grid-row:span 2;grid-column:1}.library-choice-title{min-width:0;overflow-wrap:anywhere;font-weight:650}.library-choice small{color:var(--muted)}.library-detail{min-width:0;padding:clamp(.9rem,2vw,1.45rem);border:1px solid var(--line);border-radius:24px;background:color-mix(in srgb,var(--surface) 75%,transparent)}.library-back{margin:-.2rem 0 .7rem}.library-detail-title-row{display:flex;align-items:center;gap:1rem;margin-bottom:1rem}.library-detail-title h3{margin:.2rem 0;font-size:clamp(1.2rem,2.7vw,1.8rem);overflow-wrap:anywhere}.library-detail-title .hint{margin:0}.library-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:.55rem;margin:.75rem 0 1rem}.library-actions{position:relative;margin-left:auto}.library-actions>summary{display:grid;place-items:center;width:44px;height:44px;border-radius:14px;cursor:pointer}.library-actions[open] .library-menu{position:absolute;z-index:5;right:0;top:calc(100% + .5rem);width:min(19rem,calc(100vw - 3rem));padding:1rem;border:1px solid var(--line);border-radius:18px;background:var(--opaque);box-shadow:var(--shadow);backdrop-filter:blur(22px)}.library-source,.library-track-tools{display:flex;align-items:center;justify-content:space-between;gap:.7rem}.library-track-tools{padding:.5rem 0;border-bottom:1px solid var(--line)}.library-list{display:grid;gap:.45rem;padding:0;margin:.3rem 0 0;list-style:none}.library-track{display:grid;grid-template-columns:24px 42px minmax(0,1fr) auto;align-items:center;gap:.7rem;padding:.65rem .55rem;border-bottom:1px solid var(--line)}.library-track-cover{width:42px;height:42px;object-fit:cover;border-radius:11px;background:var(--surface-2)}.library-track-cover-empty{display:grid;place-items:center;color:var(--muted)}.library-track .song{min-width:0}.library-track .song p{margin:0;overflow-wrap:anywhere}.library-track .song small{color:var(--muted)}.library-remove{min-height:42px}.library-empty-state{display:grid;justify-items:center;align-content:center;gap:.6rem;min-height:210px;padding:1.5rem;color:var(--muted);text-align:center}.library-empty-state h3,.library-empty-state p{margin:0}.empty-glyph{display:grid;place-items:center;width:54px;height:54px;border-radius:18px;background:var(--surface-2);color:var(--green);font-size:1.5rem}.library-loading{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem;min-height:250px}.library-skeleton{height:210px;border-radius:20px;background:linear-gradient(100deg,var(--surface-2),var(--surface),var(--surface-2));background-size:200% 100%;animation:library-shimmer 1.4s ease-in-out infinite}.library-error{margin:.65rem 0;color:var(--danger,var(--error))}.library-save-dialog{width:min(440px,calc(100vw - 2rem));padding:1.4rem;border:1px solid var(--line);border-radius:24px;background:var(--opaque);color:var(--text);box-shadow:var(--shadow);backdrop-filter:blur(24px)}.library-save-dialog::backdrop{background:rgba(11,13,15,.45);backdrop-filter:blur(4px)}.library-save-dialog form{display:grid;gap:.85rem}.library-save-dialog h2{margin:0}.library-save-dialog select{width:100%}.selection-tools{display:flex;justify-content:flex-end;gap:.6rem}.library-page[hidden]{display:none!important}@keyframes library-shimmer{to{background-position-x:-200%}}@media(max-width:760px){.library-workspace{grid-template-columns:1fr}.library-workspace.detail-open .library-sidebar{display:none}.library-workspace:not(.detail-open) .library-detail{display:none}.library-detail{min-height:300px}.library-loading{grid-template-columns:1fr}.library-skeleton{height:92px}.library-track{grid-template-columns:24px 38px minmax(0,1fr) auto;gap:.5rem}.library-track-cover{width:38px;height:38px}.library-toolbar>*{flex:1 1 auto}.library-actions{margin-left:auto}}@media(prefers-reduced-motion:reduce){.library-skeleton{animation:none}}
</style>




