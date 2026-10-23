import { onBeforeUnmount, onMounted, ref } from 'vue'

type Theme = 'light' | 'dark'
export function useTheme() {
  const media = window.matchMedia('(prefers-color-scheme: light)')
  let preference: Theme | null = null
  try {
    const saved = localStorage.getItem('musicbot-theme')
    if (saved === 'light' || saved === 'dark') preference = saved
  } catch {}
  const mode = ref<Theme>(preference || (media.matches ? 'light' : 'dark'))
  function apply(): void {
    mode.value = preference || (media.matches ? 'light' : 'dark')
    document.documentElement.dataset.theme = mode.value
    document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute('content', mode.value === 'light' ? '#f3f5f7' : '#1e2226')
  }
  function toggle(): void {
    preference = mode.value === 'light' ? 'dark' : 'light'
    try { localStorage.setItem('musicbot-theme', preference) } catch {}
    apply()
  }
  onMounted(() => { apply(); media.addEventListener('change', apply) })
  onBeforeUnmount(() => media.removeEventListener('change', apply))
  return { mode, toggle }
}
