import { computed, ref, watch } from 'vue'
import { dashboard } from '../store'
import { request } from '../api'
import { command, notice } from './useDashboard'
import { t } from './useLocale'
import { safeURL } from './useTrack'
import type { LibraryTrack } from './useLibrary'

interface PopularTrack extends LibraryTrack { count: number }
interface PopularPayload { tracks?: PopularTrack[] }
type Period = '7' | '30' | 'all'
const validPeriods: readonly Period[] = ['7', '30', 'all']
const period = ref<Period>('7')
const tracks = ref<PopularTrack[]>([])
const loading = ref(false)
const error = ref('')
const empty = ref(false)
const adding = ref<string | null>(null)
const resolutionState = ref<'queued'|'resolving'>('queued')
let requestEpoch = 0
let actionEpoch = 0

function errorMessage(value: unknown): string { return value instanceof Error && value.message ? value.message : t('m0221') }
function safeUrl(value: unknown): string { return safeURL(value) }
async function load(): Promise<void> {
  const epoch = ++requestEpoch
  const guild = dashboard.guildId
  const sessionEpoch = dashboard.epoch
  if (!guild || !dashboard.authenticated || !dashboard.connected) {
    tracks.value = []
    empty.value = false
    error.value = ''
    loading.value = false
    return
  }
  tracks.value = []
  loading.value = true
  empty.value = false
  error.value = ''
  try {
    const result = await request<PopularPayload>('/api/guilds/' + encodeURIComponent(guild) + '/popular?period=' + encodeURIComponent(period.value))
    if (epoch !== requestEpoch || sessionEpoch !== dashboard.epoch || guild !== dashboard.guildId) return
    tracks.value = (result.tracks ?? []).slice(0, 20)
    empty.value = tracks.value.length === 0
  } catch (cause) {
    if (epoch === requestEpoch && sessionEpoch === dashboard.epoch && guild === dashboard.guildId) {
      tracks.value = []
      error.value = errorMessage(cause)
    }
  } finally { if (epoch === requestEpoch && sessionEpoch === dashboard.epoch) loading.value = false }
}
async function add(track: PopularTrack): Promise<void> {
  const guild = dashboard.guildId
  if (!guild || !dashboard.authenticated || !dashboard.connected || dashboard.busy || adding.value || !safeUrl(track.url)) return
  const epoch = ++actionEpoch
  const sessionEpoch = dashboard.epoch
  adding.value = track.url
  resolutionState.value = 'queued'
  error.value = ''
  try {
    const result = await request<{ results?: Array<{ kind: string; allowed: boolean; preview_id?: string; url: string; reason?: string }> }>(
      '/api/guilds/' + encodeURIComponent(guild) + '/resolve',
      { method: 'POST', body: { query: track.url, action: 'play' }, onResolutionState: state => { if (epoch === actionEpoch) resolutionState.value = state } },
    )
    if (epoch !== actionEpoch || sessionEpoch !== dashboard.epoch || guild !== dashboard.guildId || !dashboard.connected) return
    const candidate = result.results?.find(row => row.kind === 'track' && row.allowed && row.preview_id && safeUrl(row.url))
    if (!candidate?.preview_id) throw new Error(result.results?.[0]?.reason || t('m0613'))
    if (dashboard.busy) throw new Error(t('m0614'))
    await command('play', { query: candidate.url, preview_id: candidate.preview_id })
  } catch (cause) {
    if (epoch === actionEpoch && sessionEpoch === dashboard.epoch && guild === dashboard.guildId) { error.value = errorMessage(cause); notice(error.value, true) }
  } finally { if (epoch === actionEpoch) adding.value = null }
}
function setPeriod(value: string): void {
  if ((validPeriods as readonly string[]).includes(value) && period.value !== value) {
    period.value = value as Period
    void load()
  }
}
watch(() => [dashboard.guildId, dashboard.authenticated, dashboard.connected], () => { void load() })
const hasGuild = computed(() => Boolean(dashboard.guildId && dashboard.authenticated && dashboard.connected))
export function usePopular() { return { period, tracks, loading, error, empty, adding, resolutionState, hasGuild, load, add, setPeriod, safeUrl } }


