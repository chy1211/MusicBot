import { computed, ref, watch } from 'vue'
import { dashboard } from '../store'
import { request } from '../api'
import { useAddToQueue } from './useAddToQueue'
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
const { adding, resolutionState, add } = useAddToQueue(error)
let requestEpoch = 0

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
    if (result.tracks !== undefined && !Array.isArray(result.tracks)) throw new Error(t('m0221'))
    tracks.value = (result.tracks ?? []).slice(0, 20)
    empty.value = tracks.value.length === 0
  } catch (cause) {
    if (epoch === requestEpoch && sessionEpoch === dashboard.epoch && guild === dashboard.guildId) {
      tracks.value = []
      error.value = errorMessage(cause)
    }
  } finally { if (epoch === requestEpoch && sessionEpoch === dashboard.epoch) loading.value = false }
}
function setPeriod(value: string): void {
  if ((validPeriods as readonly string[]).includes(value) && period.value !== value) {
    period.value = value as Period
    void load()
  }
}
function cancelLoad() {
  ++requestEpoch; tracks.value = []; empty.value = false; error.value = ''; loading.value = false
}
// Requests start only while PopularView is mounted. Invalidate old responses on a guild/session change.
watch(() => [dashboard.guildId, dashboard.authenticated, dashboard.connected, dashboard.epoch], () => {
  ++requestEpoch; tracks.value = []; empty.value = false; error.value = ''; loading.value = false
}, { flush: 'sync' })
const hasGuild = computed(() => Boolean(dashboard.guildId && dashboard.authenticated && dashboard.connected))
export function usePopular() { return { period, tracks, loading, error, empty, adding, resolutionState, hasGuild, load, cancelLoad, add, setPeriod, safeUrl } }


