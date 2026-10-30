<script setup lang="ts">
import {nextTick,onBeforeUnmount,onMounted,ref} from 'vue'
import {locale,setLocale,t} from '../composables/useLocale'
import {useTheme} from '../composables/useTheme'
const {mode,toggle,palette,palettes,setPalette}=useTheme()
const paletteLabels={mint:'palette.mint',amber:'palette.amber',ocean:'palette.ocean',rose:'palette.rose',noir:'palette.noir',iris:'palette.iris'}
const paletteColors={mint:'#8fd6c4',amber:'#ffa31a',ocean:'#7aa7ff',rose:'#f29bb8',noir:'#E53935',iris:'#6366F1'}
const paletteToggle=ref<HTMLButtonElement|null>(null)
const palettePanel=ref<HTMLElement|null>(null)
const paletteOpen=ref(false)
function focusSelected(){palettePanel.value?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus()}
async function togglePalette(){
  if(paletteOpen.value){closePalette();return}
  paletteOpen.value=true
  await nextTick()
  focusSelected()
}
function closePalette(){
  if(!paletteOpen.value)return
  paletteOpen.value=false
  paletteToggle.value?.focus()
}
function choosePalette(value:string){setPalette(value);closePalette()}
async function movePalette(event:KeyboardEvent){
  if(event.key!=='ArrowLeft'&&event.key!=='ArrowRight')return
  event.preventDefault()
  const index=palettes.indexOf(palette.value)
  setPalette(palettes[(index+(event.key==='ArrowRight'?1:-1)+palettes.length)%palettes.length]!)
  await nextTick()
  focusSelected()
}
function outsidePalette(event:MouseEvent){
  const target=event.target as Node
  if(!palettePanel.value?.contains(target)&&!paletteToggle.value?.contains(target))closePalette()
}
function escapePalette(event:KeyboardEvent){
  if(paletteOpen.value&&event.key==='Escape'){event.preventDefault();event.stopPropagation();closePalette()}
}
onMounted(()=>{document.addEventListener('click',outsidePalette);document.addEventListener('keydown',escapePalette,true)})
onBeforeUnmount(()=>{document.removeEventListener('click',outsidePalette);document.removeEventListener('keydown',escapePalette,true)})
</script>
<template>
  <div class="language-preference">
    <div class="palette-picker">
    <button id="palette-toggle" ref="paletteToggle" type="button" :aria-label="t('palette')" aria-haspopup="true" :aria-expanded="paletteOpen" aria-controls="palette-panel" @click="togglePalette">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M12 3a9 9 0 1 0 0 18h1.1a2.2 2.2 0 0 0 1.6-3.7 1.4 1.4 0 0 1 1-2.4h1.8A3.5 3.5 0 0 0 21 11.4C21 6.8 17 3 12 3Z"/>
        <circle cx="7.5" cy="10" r=".9"/><circle cx="11" cy="6.9" r=".9"/><circle cx="15.6" cy="7.8" r=".9"/><circle cx="6.9" cy="14.5" r=".9"/>
      </svg>
    </button>
    <div v-if="paletteOpen" id="palette-panel" ref="palettePanel" class="palette-panel" role="radiogroup" :aria-label="t('palette')" @keydown="movePalette">
      <button v-for="item in palettes" :key="item" type="button" class="palette-swatch" :data-palette="item" role="radio" :aria-checked="palette===item" :aria-label="t(paletteLabels[item])" :title="t(paletteLabels[item])" :tabindex="palette===item?0:-1" @click="choosePalette(item)">
        <span aria-hidden="true" :style="{backgroundColor:paletteColors[item]}"/>
      </button>
    </div>
    </div>
    <button id="theme-toggle" type="button" :disabled="palette==='noir'||palette==='iris'" :data-mode="mode" :aria-label="t(mode === 'light' ? 'theme.light' : 'theme.dark')" @click="toggle"><svg class="theme-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg><svg class="theme-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z"/></svg></button>
    <label for="dashboard-language">{{ t('language') }}</label><select id="dashboard-language" :value="locale" :aria-label="t('language')" @change="setLocale(($event.target as HTMLSelectElement).value)"><option value="en">{{ t('language.en') }}</option><option value="zh-TW">{{ t('language.zh-TW') }}</option></select>
  </div>
</template>
