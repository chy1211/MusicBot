import {computed, onBeforeUnmount, ref, watch} from 'vue'
import {dashboard, type Snapshot, type Track} from '../store'
import {t, locale} from './useLocale'

type SessionState = 'off' | 'starting' | 'active' | 'awaiting-gesture' | 'interrupted' | 'unsupported'
const AUDIO_URL = '/assets/r4-silent.wav'
const PREFERENCE_KEY = 'musicbot-dynamic-island'
let manualResumeOnly = false
const ART_HOSTS = new Set([
  'i.ytimg.com', 'img.youtube.com', 'cdn.discordapp.com',
  'media.discordapp.net', 'i.scdn.co', 'mosaic.scdn.co',
])
const MEDIA_ACTIONS = [
  'play', 'pause', 'stop', 'nexttrack', 'previoustrack',
  'seekforward', 'seekbackward', 'seekto',
] as const satisfies readonly MediaSessionAction[]

// Keep Dashboard SSE alive in the background while the silent audio session is active.
export const islandBackgroundSync = ref(false)

function automaticEnabled(): boolean {
  try { return localStorage.getItem(PREFERENCE_KEY) !== 'off' }
  catch { return true }
}

function savePreference(enabled: boolean): void {
  try { localStorage.setItem(PREFERENCE_KEY, enabled ? 'on' : 'off') }
  catch { /* Storage may be unavailable in private browsing. */ }
}

function safeArtwork(source?: string): string | undefined {
  if (!source) return
  try {
    const url = new URL(source)
    if (url.protocol === 'https:' && ART_HOSTS.has(url.hostname)) return url.href
  } catch {
    return
  }
}

function trackSignature(guildId: string, track: Track | null, status: string): string {
  return [guildId, track?.track_token || track?.url || '',
    track?.title || '', status].join('|')
}

export function useDynamicIsland() {
  const supported = typeof window !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    'mediaSession' in navigator &&
    'MediaMetadata' in window && typeof MediaMetadata === 'function'
  const isIOS = supported && (/iPhone|iPad|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1))
  const state = ref<SessionState>(supported ? 'off' : 'unsupported')
  const error = ref('')
  const autoplayBlocked = ref(false)
  const showStartNotice = computed(() => autoplayBlocked.value &&
    dashboard.authenticated && dashboard.connected && !!dashboard.guildId &&
    dashboard.snapshot?.status === 'playing' && !!dashboard.snapshot.current)
  const isActive = computed(() => state.value === 'active')
  const canStart = computed(() => supported && dashboard.authenticated &&
    dashboard.connected && !!dashboard.guildId &&
    !!dashboard.snapshot && (state.value === 'off' || state.value === 'awaiting-gesture' || state.value === 'interrupted'))
  let audio: HTMLAudioElement | null = null
  let stopping = false
  let lastSignature = ''
  let generation = 0
  let ownsMediaSession = false
  const registeredActions: MediaSessionAction[] = []

  function clearMediaHandlers(): void {
    if (!supported) return
    for (const action of registeredActions) {
      try {
        navigator.mediaSession.setActionHandler(action, null)
      } catch {
        // Safari may not support the action on this iOS version.
      }
    }
    registeredActions.length = 0
  }

  function registerMediaHandlers(): void {
    if (!supported) return
    clearMediaHandlers()
    // iOS commonly maps the native +/-10s buttons to seekforward/backward.
    // All system controls are read-only and MUST NOT control Discord.
    // In particular, a system "play" action never resumes after Spotify.
    for (const action of MEDIA_ACTIONS) {
      try {
        navigator.mediaSession.setActionHandler(action, () => {})
        registeredActions.push(action)
      } catch {
        // Unsupported iOS action; never substitute a Discord command.
      }
    }
  }

  function releaseMediaSession(): void {
    if (!ownsMediaSession) return
    ownsMediaSession = false
    clearMediaHandlers()
    navigator.mediaSession.playbackState = 'none'
    navigator.mediaSession.metadata = null
  }

  function interrupt(message: string): void {
    if (state.value === 'off' || state.value === 'unsupported') return
    state.value = 'interrupted'
    manualResumeOnly = true
    islandBackgroundSync.value = false
    lastSignature = ''
    error.value = message
    releaseMediaSession()
  }

  function ensureAudio(): HTMLAudioElement {
    if (audio) return audio
    const element = new Audio(AUDIO_URL)
    element.loop = true
    element.volume = 0
    element.preload = 'auto'
    element.addEventListener('pause', () => {
      if (!stopping && state.value === 'active') {
        interrupt(t('island.error.interrupted'))
      }
    })
    element.addEventListener('error', () => {
      if (!stopping && state.value !== 'off' && state.value !== 'unsupported') {
        interrupt(t('island.error.audio'))
      }
    })
    audio = element
    return element
  }

  function progress(snapshot: Snapshot): number {
    const duration = Number(snapshot.current?.duration)
    const base = Math.max(0, Number(snapshot.progress) || 0)
    const elapsed = snapshot.status === 'playing'
      ? Math.max(0, (Date.now() - dashboard.stateAt) / 1000) : 0
    const value = base + elapsed
    return Number.isFinite(duration) && duration > 0
      ? Math.min(value, duration) : value
  }

  function updateMetadata(force = false): void {
    if (!supported || state.value !== 'active') return
    const snapshot = dashboard.snapshot
    if (!dashboard.authenticated || !dashboard.guildId) {
      stop(false)
      return
    }
    if (!snapshot) {
      // A guild switch may clear the snapshot before the next SSE event.
      navigator.mediaSession.metadata = null
      navigator.mediaSession.playbackState = 'paused'
      lastSignature = ''
      return
    }
    const track = snapshot.current
    const signature = trackSignature(dashboard.guildId, track, snapshot.status)
    if (signature !== lastSignature || force) {
      const artwork = safeArtwork(track?.thumbnail)
      navigator.mediaSession.metadata = new MediaMetadata({
        title: track?.title || t('island.empty'),
        artist: track ? t('island.artist') : 'MusicBot',
        album: 'MusicBot',
        ...(artwork ? {artwork: [{src: artwork}]} : {}),
      })
      lastSignature = signature
    }
    navigator.mediaSession.playbackState =
      dashboard.connected && snapshot.status === 'playing' ? 'playing' : 'paused'
    const duration = Number(track?.duration)
    if (Number.isFinite(duration) && duration > 0 &&
        typeof navigator.mediaSession.setPositionState === 'function') {
      try {
        navigator.mediaSession.setPositionState({
          duration,
          position: progress(snapshot),
          playbackRate: 1,
        })
      } catch {
        // Some iOS builds reject updates when the media app is switching.
      }
    }
  }

  function shouldPauseLatePlay(): boolean {
    return state.value === 'off' || state.value === 'awaiting-gesture' || state.value === 'interrupted'
  }

  async function start(automatic = false): Promise<void> {
    if (!canStart.value) return
    if (!automatic) savePreference(true)
    const attempt = ++generation
    const element = ensureAudio()
    state.value = 'starting'
    error.value = ''
    try {
      await element.play()
      if (generation !== attempt) {
        // A late play() resolution after Stop may make audio audible to the
        // media system again. Only pause if no newer session is starting or
        // active; otherwise leave the newer user action in control.
        if (shouldPauseLatePlay()) element.pause()
        return
      }
      if (element.paused) {
        interrupt(t('island.error.competing'))
        return
      }
      autoplayBlocked.value = false
      manualResumeOnly = false
      ownsMediaSession = true
      registerMediaHandlers()
      state.value = 'active'
      islandBackgroundSync.value = true
      lastSignature = ''
      updateMetadata(true)
    } catch (failure) {
      if (generation !== attempt) return
      if (automatic && failure instanceof DOMException && failure.name === 'NotAllowedError') {
        state.value = 'awaiting-gesture'
        autoplayBlocked.value = true
        manualResumeOnly = true
        return
      }
      interrupt(t('island.error.start'))
    }
  }

  function stop(disable = true): void {
    if (disable) savePreference(false)
    autoplayBlocked.value = false
    generation++
    stopping = true
    islandBackgroundSync.value = false
    releaseMediaSession()
    audio?.pause()
    lastSignature = ''
    state.value = supported ? 'off' : 'unsupported'
    error.value = ''
    stopping = false
  }

  function maybeAutoStart(): void {
    if (isIOS && !manualResumeOnly && automaticEnabled() && !document.hidden &&
        dashboard.snapshot?.status === 'playing' && !!dashboard.snapshot.current && state.value === 'off') {
      void start(true)
    }
  }

  watch(() => [
    dashboard.snapshot, dashboard.guildId, dashboard.authenticated,
    dashboard.connected, dashboard.epoch,
  ] as const, () => {
    if (!dashboard.authenticated || !dashboard.guildId) {
      if (state.value !== 'off' && state.value !== 'unsupported') stop(false)
      return
    }
    maybeAutoStart()
    updateMetadata()
  }, {immediate: true})

  watch(locale, () => updateMetadata(true))

  const onVisible = () => {
    if (document.hidden) return
    maybeAutoStart()
    if (state.value !== 'active') return
    if (audio?.paused) {
      interrupt(t('island.error.visible'))
    } else {
      updateMetadata(true)
    }
  }
  document.addEventListener('visibilitychange', onVisible)
  onBeforeUnmount(() => {
    document.removeEventListener('visibilitychange', onVisible)
    stop(false)
    audio?.removeAttribute('src')
    audio?.load()
    audio = null
  })
  return {supported, state, error, isActive, canStart, showStartNotice, start, stop}
}
