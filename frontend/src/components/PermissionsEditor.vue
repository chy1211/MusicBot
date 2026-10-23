<script setup lang="ts">
import type { PermissionData, PermissionChange } from '../composables/usePermissions'
import { nextTick, ref, watch } from 'vue'
import { t } from '../composables/useLocale'
const props=defineProps<{data:PermissionData|null;loading:boolean;error:string;saving:boolean}>()
const errorRef=ref<HTMLElement|null>(null)
watch(()=>props.error,async error=>{if(error){await nextTick();errorRef.value?.focus()}})
const emit=defineEmits<{change:[value:PermissionChange];confirm:[];cancel:[];retry:[]}>()
const names:Record<string,string>={AllowPlaylists:'admin.permissions.allowPlaylists',MaxSongLength:'admin.permissions.maxSongLength',MaxSongs:'admin.permissions.maxSongs',MaxPlaylistLength:'admin.permissions.maxPlaylistLength',Permission:'admin.permissions.permission',MaxSearchItems:'admin.permissions.maxSearchItems',InstaSkip:'admin.permissions.instaSkip',SkipLooped:'admin.permissions.skipLooped',Remove:'admin.permissions.remove',SkipWhenAbsent:'admin.permissions.skipWhenAbsent',BypassKaraokeMode:'admin.permissions.bypassKaraoke',SummonNoVoice:'admin.permissions.summonNoVoice',Extractors:'admin.permissions.extractors',CommandWhitelist:'admin.permissions.commandWhitelist',CommandBlacklist:'admin.permissions.commandBlacklist',GrantToRoles:'admin.permissions.grantRoles',UserList:'admin.permissions.userList'}
function label(field:string){return t(names[field]||'admin.permissions.other',{p0:field})}
function display(value:unknown){return typeof value==='boolean'?t(value?'admin.value.enabled':'admin.value.disabled'):Array.isArray(value)?value.join(', ')||t('admin.value.none'):String(value)}
</script>
<template>
<section id="admin-permissions" aria-labelledby="permissions-heading">
<h3 id="permissions-heading">{{ t('admin.permissions.heading') }}</h3>
<p v-if="loading" role="status" aria-live="polite">{{ t('admin.loading') }}</p>
<div v-if="error" ref="errorRef" class="maintenance-warning" role="alert" tabindex="-1">{{ error }} <button type="button" @click="emit('retry')">{{ t('admin.retry') }}</button></div>
<div v-if="data && !data.groups.length" class="hint">{{ t('admin.permissions.empty') }}</div>
<details v-for="group in data?.groups || []" :key="group.name"><summary>{{ group.name }}</summary>
<div v-for="(value,field) in group.values" :key="field" class="permission-row">
<label :for="`permission-${group.name}-${field}`">{{ label(field) }}</label>
<template v-if="group.editable.includes(field)"><select v-if="field==='AllowPlaylists'" :id="`permission-${group.name}-${field}`" :aria-label="label(field)" :value="String(value)" @change="emit('change',{group:group.name,field,old_value:value,value:($event.target as HTMLSelectElement).value==='true'})"><option value="true">{{ t('admin.value.enabled') }}</option><option value="false">{{ t('admin.value.disabled') }}</option></select><input v-else :id="`permission-${group.name}-${field}`" type="number" min="0" step="1" :max="data?.limits[field]" :value="String(value)" :aria-label="label(field)" @change="emit('change',{group:group.name,field,old_value:value,value:($event.target as HTMLInputElement).value})" /></template>
<span v-else>{{ display(value) }}</span></div></details>
<ol v-if="data?.activity.length" class="activity-list"><li v-for="(item,index) in data.activity" :key="index">{{ item.detail }}</li></ol>
</section>
</template>
