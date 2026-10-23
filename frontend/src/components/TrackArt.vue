<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {safeURL} from '../composables/useTrack'
const props=defineProps<{track?:{thumbnail?:string}|null;imageId?:string}>(),failed=ref(false)
const source=computed(()=>safeURL(props.track?.thumbnail));watch(source,()=>failed.value=false)
</script>
<template><div class="art"><span aria-hidden="true">♫</span><img v-if="source&&!failed" :id="imageId" :src="source" alt="" loading="lazy" referrerpolicy="no-referrer" @error="failed=true"></div></template>
