import { computed, ref, watch } from 'vue'
import { dashboard } from '../store'
import { request } from '../api'
import { notice } from './useDashboard'
import { t } from './useLocale'

export interface LibraryTrack { title: string; url: string; duration?: number | null; thumbnail?: string; preview_id?: string; save_revision?: string }
export interface Playlist { id: string; name: string; tracks: LibraryTrack[]; source_url?: string; source_type?: 'spotify' | 'youtube' }
interface LibraryPayload { revision: string; playlists: Playlist[]; owner?: boolean; sources?: { spotify: boolean; youtube: boolean }; message?: string }
interface SyncPreview { preview_id: string; revision: string; diff: { added: number; removed: number }; warning: string }

const payload = ref<LibraryPayload | null>(null)
const loading = ref(false)
const loadError = ref('')
const busy = ref(false)
const activeId = ref('favorites')
const detailOpen = ref(false)
const selected = ref<number[]>([])
const pendingSave = ref<LibraryTrack | null>(null)
const saveDialogOpen = ref(false)
const createName = ref('')
const renameName = ref('')
const playlists = computed(() => payload.value?.playlists ?? [])
const activePlaylist = computed(() => playlists.value.find(item => item.id === activeId.value) ?? playlists.value[0] ?? null)
const saveChoices = computed(() => playlists.value)
const canPlaySelected = computed(() => selected.value.length > 0 && !busy.value)
let loadEpoch = 0
let mutationEpoch = 0

function errorText(error: unknown): string { return error instanceof Error && error.message ? error.message : t('m0190') }
function safeMediaUrl(value: unknown): string {
  if (typeof value !== 'string' || /[\u0000-\u001f]/.test(value)) return ''
  try { const url = new URL(value); return /^https?:$/.test(url.protocol) && !url.username && !url.password ? value : '' }
  catch { return '' }
}
function playlistLabel(item: Playlist): string { return item.id === 'favorites' ? t('m0192') : item.name }
function songIdentity(value: string): string {
  const raw = safeMediaUrl(value)
  if (!raw) return ''
  const url = new URL(raw), host = url.hostname.toLowerCase(), parts = url.pathname.split('/').filter(Boolean)
  const youtube = host === 'youtube.com' || host.endsWith('.youtube.com') || host === 'youtube-nocookie.com' || host.endsWith('.youtube-nocookie.com')
  const id = host === 'youtu.be' || host === 'www.youtu.be' ? parts[0] : youtube ? (url.pathname === '/watch' ? url.searchParams.get('v') : ['shorts','embed','live','v'].includes(parts[0]) ? parts[1] : '') : ''
  if (id && /^[A-Za-z0-9_-]{11}$/.test(id)) return 'youtube:' + id
  url.hash = ''
  url.pathname = url.pathname.endsWith('/') && url.pathname !== '/' ? url.pathname.slice(0, -1) : url.pathname
  for (const key of Array.from(url.searchParams.keys())) if (/^utm_/i.test(key) || /^(si|feature|fbclid|gclid)$/i.test(key)) url.searchParams.delete(key)
  url.searchParams.sort()
  return url.href
}
function current(epoch: number, guild: string): boolean { return epoch === mutationEpoch && guild === dashboard.guildId && dashboard.authenticated }
function setActive(id: string): void {
  activeId.value = id
  detailOpen.value = true
  selected.value = []
  if (activePlaylist.value) renameName.value = playlistLabel(activePlaylist.value)
}
async function load(silent = false): Promise<boolean> {
  const epoch = ++loadEpoch
  if (!dashboard.authenticated) { reset(); return false }
  if (!silent) loading.value = true
  loadError.value = ''
  try {
    const value = await request<LibraryPayload>('/api/library')
    if (epoch !== loadEpoch || !dashboard.authenticated) return false
    payload.value = value
    if (!value.playlists.some(item => item.id === activeId.value)) activeId.value = 'favorites'
    renameName.value = activePlaylist.value ? playlistLabel(activePlaylist.value) : ''
    return true
  } catch (error) {
    if (epoch === loadEpoch) loadError.value = errorText(error)
    return false
  } finally { if (epoch === loadEpoch) loading.value = false }
}
async function mutate(id: string, body: Record<string, unknown>, method = 'PATCH', suffix = ''): Promise<boolean> {
  if (!payload.value || busy.value) return false
  const epoch = ++mutationEpoch
  const guild = dashboard.guildId
  busy.value = true
  loadError.value = ''
  try {
    const result = await request<LibraryPayload>('/api/library/' + encodeURIComponent(id) + suffix, {
      method, body: { ...body, revision: payload.value.revision },
    })
    if (!current(epoch, guild)) return false
    payload.value = result
    selected.value = []
    if (!result.playlists.some(item => item.id === activeId.value)) { activeId.value = 'favorites'; detailOpen.value = false }
    renameName.value = activePlaylist.value ? playlistLabel(activePlaylist.value) : ''
    notice(result.message || t('m0195'))
    return true
  } catch (error) {
    if (current(epoch, guild)) loadError.value = errorText(error)
    return false
  } finally { if (epoch === mutationEpoch) busy.value = false }
}
async function createPlaylist(): Promise<void> {
  const name = createName.value.trim()
  if (!name || busy.value) return
  const epoch = ++mutationEpoch
  const guild = dashboard.guildId
  busy.value = true
  loadError.value = ''
  try {
    const result = await request<LibraryPayload>('/api/library', { method: 'POST', body: { name } })
    if (!current(epoch, guild)) return
    payload.value = result
    createName.value = ''
    const newest = result.playlists[result.playlists.length - 1]
    if (newest) setActive(newest.id)
    detailOpen.value = true
    notice(result.message || t('m0195'))
  } catch (error) { if (current(epoch, guild)) loadError.value = errorText(error) }
  finally { if (epoch === mutationEpoch) busy.value = false }
}
async function play(items?: number[]): Promise<void> {
  const list = activePlaylist.value
  const guild = dashboard.guildId
  if (!list || !payload.value || !guild || !dashboard.connected || dashboard.busy || busy.value || !list.tracks.length || (items && !items.length)) return
  const epoch = ++mutationEpoch
  busy.value = true
  loadError.value = ''
  try {
    const body: { revision: string; selected_items?: string[] } = { revision: payload.value.revision }
    if (items) body.selected_items = items.map(String)
    const result = await request<{ message?: string; skipped?: number }>(
      '/api/guilds/' + encodeURIComponent(guild) + '/library/' + encodeURIComponent(list.id) + '/play',
      { method: 'POST', body },
    )
    if (!current(epoch, guild)) return
    notice(result.message || t('m0195'))
    if ((result.skipped ?? 0) > 0) loadError.value = result.message || t('m0195')
  } catch (error) { if (current(epoch, guild)) loadError.value = errorText(error) }
  finally { if (epoch === mutationEpoch) busy.value = false }
}
async function openSave(track: LibraryTrack): Promise<void> {
  const url = safeMediaUrl(track.url)
  if (!url || !track.title.trim()) { notice(t('m0197')); return }
  if (!await load()) return
  pendingSave.value = {
    title: track.title, url,
    duration: typeof track.duration === 'number' && Number.isFinite(track.duration) ? track.duration : null,
    ...(safeMediaUrl(track.thumbnail) ? { thumbnail: safeMediaUrl(track.thumbnail) } : {}),
  }
  saveDialogOpen.value = true
}
async function savePending(playlistId: string): Promise<void> {
  if (!pendingSave.value || !playlistId) return
  if (await mutate(playlistId, { track: pendingSave.value }, 'POST', '/tracks')) {
    saveDialogOpen.value = false
    pendingSave.value = null
  }
}
function isFavorite(track?: LibraryTrack): boolean {
  const candidate = track ?? dashboard.snapshot?.current
  if (!candidate?.url) return false
  const key = songIdentity(candidate.url)
  return Boolean(key && playlists.value[0]?.tracks.some(item => songIdentity(item.url) === key))
}
async function toggleFavorite(track?: LibraryTrack): Promise<void> {
  const candidate = track ?? dashboard.snapshot?.current
  if (!candidate || busy.value || !await load()) return
  const url = safeMediaUrl(candidate.url)
  if (!url) return
  const key = songIdentity(url)
  const saved = playlists.value[0]?.tracks.some(item => songIdentity(item.url) === key) ?? false
  if (saved) await mutate('favorites', { action: 'remove_url', url })
  else await mutate('favorites', { track: {
    title: candidate.title, url, duration: candidate.duration ?? null,
    ...(safeMediaUrl(candidate.thumbnail) ? { thumbnail: safeMediaUrl(candidate.thumbnail) } : {}),
  } }, 'POST', '/tracks')
}
async function savePreview(track: LibraryTrack, selectedItems: Iterable<string>, name: string): Promise<void> {
  if (!track.preview_id || !track.save_revision || busy.value) return
  const epoch = ++mutationEpoch
  const guild = dashboard.guildId
  busy.value = true
  loadError.value = ''
  try {
    const result = await request<LibraryPayload>('/api/library/import', {
      method: 'POST', body: { preview_id: track.preview_id, revision: track.save_revision, name, selected_items: Array.from(selectedItems) },
    })
    if (!current(epoch, guild)) return
    payload.value = result
    const newest = result.playlists[result.playlists.length - 1]
    if (newest) setActive(newest.id)
    detailOpen.value = true
    window.dispatchEvent(new CustomEvent('musicbot:navigate', { detail: 'library' }))
    notice(result.message || t('m0195'))
  } catch (error) { if (current(epoch, guild)) loadError.value = errorText(error) }
  finally { if (epoch === mutationEpoch) busy.value = false }
}
async function syncPlaylist(): Promise<void> {
  const list = activePlaylist.value
  const guild = dashboard.guildId
  if (!list || !payload.value || !guild || busy.value) return
  const epoch = ++mutationEpoch
  busy.value = true
  loadError.value = ''
  try {
    const preview = await request<SyncPreview>(
      '/api/guilds/' + encodeURIComponent(guild) + '/library/' + encodeURIComponent(list.id) + '/sync/preview',
      { method: 'POST', body: { revision: payload.value.revision } },
    )
    if (!current(epoch, guild) || activePlaylist.value?.id !== list.id) return
    const prompt = t('m0206') + preview.diff.added + t('m0207') + preview.diff.removed + t('m0208') + preview.warning + t('m0209')
    if (!window.confirm(prompt)) return
    const result = await request<LibraryPayload>('/api/library/' + encodeURIComponent(list.id) + '/sync', {
      method: 'POST', body: { preview_id: preview.preview_id, revision: preview.revision },
    })
    if (!current(epoch, guild)) return
    payload.value = result
    notice(result.message || t('m0195'))
  } catch (error) { if (current(epoch, guild)) loadError.value = errorText(error) }
  finally { if (epoch === mutationEpoch) busy.value = false }
}
function toggleTrack(index: number, checked: boolean): void {
  const next = new Set(selected.value)
  if (checked) next.add(index)
  else next.delete(index)
  selected.value = Array.from(next).sort((a, b) => a - b)
}
function closeSave(): void { saveDialogOpen.value = false; pendingSave.value = null }
function goToPlay(): void {
  window.dispatchEvent(new CustomEvent('musicbot:navigate', { detail: 'play' }))
  requestAnimationFrame(() => document.getElementById('query')?.focus())
}
function formatDuration(seconds?: number | null): string {
  if (!seconds || !Number.isFinite(seconds)) return t('m0097')
  const total = Math.floor(seconds)
  return Math.floor(total / 60) + ':' + String(total % 60).padStart(2, '0')
}
function reset(): void {
  ++loadEpoch
  ++mutationEpoch
  payload.value = null
  loading.value = false
  busy.value = false
  loadError.value = ''
  activeId.value = 'favorites'
  detailOpen.value = false
  selected.value = []
  closeSave()
}
watch(() => dashboard.authenticated, value => { if (value) void load(); else reset() })

export function useLibrary() {
  return {
    payload, playlists, activePlaylist, loading, loadError, busy, activeId, detailOpen, selected,
    pendingSave, saveDialogOpen, saveChoices, createName, renameName, canPlaySelected,
    load, setActive, createPlaylist,
    renamePlaylist: () => activePlaylist.value && mutate(activePlaylist.value.id, { name: renameName.value }),
    deletePlaylist: () => {
      const list = activePlaylist.value
      if (!list || list.id === 'favorites' || !window.confirm(t('m0199'))) return Promise.resolve(false)
      return mutate(list.id, {}, 'DELETE')
    },
    removeTrack: (index: number) => activePlaylist.value && mutate(activePlaylist.value.id, { action: 'remove', index }),
    playAll: () => play(), enqueueAll: () => play(), playSelected: () => play(selected.value),
    toggleTrack, openSave, closeSave, savePending, toggleFavorite, isFavorite, safeUrl: safeMediaUrl, savePreview, syncPlaylist, goToPlay, formatDuration, playlistLabel,
  }
}





