<script setup lang="ts">
import { computed, ref } from 'vue'
import type { LibraryTrack } from '../composables/useLibrary'
import { trackThumbnail } from '../composables/useTrack'

const props = withDefaults(defineProps<{ tracks: LibraryTrack[]; size?: number; label?: string }>(), { size: 56, label: '' })
const failed = ref<string[]>([])
function thumbnail(track: LibraryTrack): string { return trackThumbnail(track) }
const sources = computed(() => {
  const seen = new Set<string>()
  const result: string[] = []
  for (const track of props.tracks || []) {
    const source = thumbnail(track)
    if (source && !seen.has(source)) { seen.add(source); result.push(source) }
    if (result.length === 4) break
  }
  return result
})
const visibleSources = computed(() => sources.value.filter(source => !failed.value.includes(source)))
const layoutClass = computed(() => 'cover-count-' + visibleSources.value.length)
function imageFailed(source: string): void { if (!failed.value.includes(source)) failed.value.push(source) }
</script>

<template>
  <span class="playlist-cover" :class="layoutClass" :style="{ width: size + 'px', height: size + 'px' }" role="img" :aria-label="label" :aria-hidden="!label">
    <img v-for="source in visibleSources" :key="source" :src="source" alt="" loading="lazy" referrerpolicy="no-referrer" @error="imageFailed(source)">
    <span class="cover-disc" aria-hidden="true"><span></span></span>
  </span>
</template>

<style scoped>
.playlist-cover{position:relative;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;flex:0 0 auto;overflow:hidden;aspect-ratio:1;border:1px solid color-mix(in srgb,var(--line) 72%,transparent);border-radius:15px;background:radial-gradient(circle at 50% 50%,#f3d98c 0 5%,#26262c 6% 10%,#8c8879 11% 13%,#16181b 14% 100%);box-shadow:0 8px 20px rgba(0,0,0,.15)}.playlist-cover img{z-index:1;width:100%;height:100%;min-width:0;min-height:0;object-fit:cover}.cover-count-1{grid-template-columns:1fr;grid-template-rows:1fr}.cover-count-2{grid-template-rows:1fr}.cover-count-3 img:first-child{grid-row:span 2}.cover-disc{position:absolute;inset:0;display:grid;place-items:center;opacity:0;pointer-events:none;background:radial-gradient(circle,#f4d88b 0 5%,#272830 6% 10%,#797575 11% 13%,#14151b 14% 100%)}.cover-disc span{width:14%;height:14%;border-radius:50%;background:#eee2bc}.playlist-cover:not(:has(img)){display:block}.playlist-cover:not(:has(img)) .cover-disc{opacity:1}
</style>


