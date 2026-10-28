import { ref, type Ref } from 'vue'
import { dashboard, type Track } from '../store'
import { request } from '../api'
import { command, notice } from './useDashboard'
import { t } from './useLocale'
import { safeURL } from './useTrack'

// Share the lock across popular tracks and both recently played lists.
const adding = ref<string | null>(null)
const resolutionState = ref<'queued' | 'resolving'>('queued')
let actionEpoch = 0

export function useAddToQueue(error: Ref<string> = ref('')) {
  async function add(track: Pick<Track, 'url'>): Promise<void> {
    const guild = dashboard.guildId
    if (!guild || !dashboard.authenticated || !dashboard.connected || dashboard.busy || adding.value !== null || !safeURL(track.url)) return
    const epoch = ++actionEpoch
    const sessionEpoch = dashboard.epoch
    const current = () => epoch === actionEpoch && sessionEpoch === dashboard.epoch && guild === dashboard.guildId
    adding.value = track.url
    resolutionState.value = 'queued'
    error.value = ''
    try {
      const result = await request<{ results?: Array<{ kind: string; allowed: boolean; preview_id?: string; url: string; reason?: string }> }>(
        '/api/guilds/' + encodeURIComponent(guild) + '/resolve',
        {
          method: 'POST',
          body: { query: track.url, action: 'play' },
          onResolutionState: state => { if (current()) resolutionState.value = state },
        },
      )
      if (!current() || !dashboard.authenticated || !dashboard.connected) return
      const candidate = result.results?.find(row => row.kind === 'track' && row.allowed && row.preview_id && safeURL(row.url))
      if (!candidate?.preview_id) throw new Error(result.results?.[0]?.reason || t('m0613'))
      if (dashboard.busy) throw new Error(t('m0614'))
      await command('play', { query: candidate.url, preview_id: candidate.preview_id })
    } catch (cause) {
      if (current()) {
        error.value = cause instanceof Error && cause.message ? cause.message : t('m0221')
        notice(error.value, true)
      }
    } finally {
      if (epoch === actionEpoch) adding.value = null
    }
  }
  return { adding, resolutionState, add }
}
