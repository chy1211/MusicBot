<script setup lang="ts">
import {locale,setLocale,t} from '../composables/useLocale'
</script>
<template><div class="language-preference"><label for="dashboard-language">{{ t('language') }}</label><select id="dashboard-language" :value="locale" :aria-label="t('language')" @change="setLocale(($event.target as HTMLSelectElement).value)"><option value="en">{{ t('language.en') }}</option><option value="zh-TW">{{ t('language.zh-TW') }}</option></select></div></template>
