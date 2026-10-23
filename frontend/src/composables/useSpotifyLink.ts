import {ref, watch, onBeforeUnmount} from 'vue'
import {request} from '../api'
import {dashboard, currentTrackKey} from '../store'
import {safeURL} from './useTrack'

export function useSpotifyLink() {
  const url = ref(''), loading = ref(false)
  let sequence = 0
  watch([currentTrackKey, () => dashboard.epoch], async () => {
    const requestSequence = ++sequence, key = currentTrackKey.value, epoch = dashboard.epoch
    const guild = dashboard.guildId, track = dashboard.snapshot?.current, token = track?.track_token
    url.value = ''; loading.value = false
    if (!track || !guild || !dashboard.authenticated || !dashboard.connected) return
    const fallback = 'https://open.spotify.com/search/' + encodeURIComponent(track.title)
    const current = () => requestSequence === sequence && epoch === dashboard.epoch && key === currentTrackKey.value && guild === dashboard.guildId
    loading.value = true
    try {
      const value = await request<{url?: string; track_token?: string}>(`/api/guilds/${encodeURIComponent(guild)}/spotify`)
      if (!current() || value.track_token && token && value.track_token !== token) return
      const candidate = safeURL(value.url)
      url.value = candidate && new URL(candidate).hostname === 'open.spotify.com' && new URL(candidate).protocol === 'https:' ? candidate : fallback
    } catch {
      if (current()) url.value = fallback
    } finally {
      if (current()) loading.value = false
    }
  }, {immediate: true})
  onBeforeUnmount(() => { sequence++ })
  return {url, loading}
}
