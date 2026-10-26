import { onBeforeUnmount, onMounted, ref } from 'vue'

const palettes = ['mint', 'amber', 'ocean', 'rose'] as const
type Palette = typeof palettes[number]
const backgrounds: Record<Palette, Record<'light' | 'dark', string>> = {
  mint: { light: '#f3f5f7', dark: '#1e2226' },
  amber: { light: '#f5f5f5', dark: '#1b1b1b' },
  ocean: { light: '#f2f5fa', dark: '#141b26' },
  rose: { light: '#faf4f6', dark: '#1f1a1d' }
}
type Theme = 'light' | 'dark'
export function useTheme() {
  const media = window.matchMedia('(prefers-color-scheme: light)')
  let preference: Theme | null = null
  try {
    const saved = localStorage.getItem('musicbot-theme')
    if (saved === 'light' || saved === 'dark') preference = saved
  } catch {}
  const mode = ref<Theme>(preference || (media.matches ? 'light' : 'dark'))
  const palette = ref<Palette>('mint')
  try {
    const saved = localStorage.getItem('musicbot-palette')
    if (palettes.includes(saved as Palette)) palette.value = saved as Palette
  } catch {}
  function setPalette(value: string): void {
    palette.value = palettes.includes(value as Palette) ? value as Palette : 'mint'
    try { localStorage.setItem('musicbot-palette', palette.value) } catch {}
    apply()
  }
  function apply(): void {
    mode.value = preference || (media.matches ? 'light' : 'dark')
    document.documentElement.dataset.theme = mode.value
    document.documentElement.dataset.palette = palette.value
    document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute('content', backgrounds[palette.value][mode.value])
  }
  function toggle(): void {
    preference = mode.value === 'light' ? 'dark' : 'light'
    try { localStorage.setItem('musicbot-theme', preference) } catch {}
    apply()
  }
  onMounted(() => { apply(); media.addEventListener('change', apply) })
  onBeforeUnmount(() => media.removeEventListener('change', apply))
  return { mode, toggle, palette, palettes, setPalette }
}
