<script setup lang="ts">
import {watch,nextTick,ref,onMounted,onBeforeUnmount} from 'vue'
import {dashboard} from '../store'
import {t} from '../composables/useLocale'
import {run} from '../composables/useDashboard'
import {player,seekable,progress,beginSeek,commitSeek} from '../composables/usePlayback'
import {cancelDrag} from '../composables/useQueue'
import {lyrics,toggleLyrics} from '../composables/useLyrics'
const dialog=ref<HTMLDialogElement|null>(null)
watch(()=>dashboard.shortcutsOpen,async open=>{await nextTick();if(open&&!dialog.value?.open)dialog.value?.showModal();else if(!open&&dialog.value?.open)dialog.value.close()})
function keyboard(event:KeyboardEvent){if(event.key==='Escape'){cancelDrag();if(player.choices){player.choices=false;document.getElementById('bar-title')?.focus()}if(lyrics.menu)lyrics.menu=false;return}const target=event.target as HTMLElement;if(event.defaultPrevented||event.repeat||event.isComposing||event.ctrlKey||event.altKey||event.metaKey||target?.closest('input,textarea,select,button,a,summary,[contenteditable=true],[role=menu]')||document.querySelector('dialog[open]')||!dashboard.authenticated)return
if(event.key==='?'){event.preventDefault();dashboard.shortcutsOpen=true}else if(event.key==='/'){event.preventDefault();window.dispatchEvent(new CustomEvent('musicbot:navigate',{detail:'play'}));requestAnimationFrame(()=>document.getElementById('query')?.focus())}else if(event.key===' '){event.preventDefault();document.getElementById('toggle')?.click()}else if(event.key.toLowerCase()==='n'){event.preventDefault();document.getElementById('skip')?.click()}else if(['ArrowLeft','ArrowRight'].includes(event.key)&&seekable.value){event.preventDefault();beginSeek('shortcut');player.preview=Math.max(0,Math.min(dashboard.snapshot?.current?.duration||0,progress.value+(event.key==='ArrowLeft'?-10:10)));void commitSeek()}}
onMounted(()=>document.addEventListener('keydown',keyboard));onBeforeUnmount(()=>document.removeEventListener('keydown',keyboard))
</script>
<template><dialog id="shortcuts-dialog" ref="dialog" aria-labelledby="shortcuts-heading" @cancel="dashboard.shortcutsOpen=false" @close="dashboard.shortcutsOpen=false"><div class="section-top"><h2 id="shortcuts-heading">{{ t('m0288') }}</h2><button id="shortcuts-close" type="button" :aria-label="t('m0289')" @click="dashboard.shortcutsOpen=false">{{ t('m0290') }}</button></div><dl class="shortcut-list"><dt><kbd>{{ t('m0291') }}</kbd></dt><dd>{{ t('m0292') }}</dd><dt><kbd>N</kbd></dt><dd>{{ t('m0293') }}</dd><dt><kbd>← / →</kbd></dt><dd>{{ t('m0294') }}</dd><dt><kbd>/</kbd></dt><dd>{{ t('m0295') }}</dd><dt><kbd>?</kbd></dt><dd>{{ t('m0296') }}</dd><dt><kbd>Esc</kbd></dt><dd>{{ t('m0297') }}</dd></dl><p class="hint">{{ t('m0298') }}</p></dialog></template>
