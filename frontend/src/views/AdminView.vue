<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import PermissionsEditor from '../components/PermissionsEditor.vue'
import { useAdmin } from '../composables/useAdmin'
import { usePermissions } from '../composables/usePermissions'
import { t } from '../composables/useLocale'
import { safeURL } from '../composables/useTrack'
import { SW_VERSION } from '../version'
import { controllerVersion } from '../composables/usePwa'
const a=useAdmin(), p=usePermissions(a.canManage, () => { a.owner.value=false })
const route = useRoute()
// The admin screen remains mounted while another dashboard route is shown.
// Poll only for the visible, authorized guild, and never overlap requests.
let healthTimer: ReturnType<typeof setInterval> | undefined
function refreshHealth() {
 if (route.path !== '/admin' || document.hidden || !a.canManage.value || a.maintenanceLoading.value) return
 void a.loadMaintenance().catch(() => {})
}
onMounted(() => { healthTimer = setInterval(refreshHealth, 10000); document.addEventListener('visibilitychange', refreshHealth) })
onBeforeUnmount(() => { if (healthTimer) clearInterval(healthTimer); document.removeEventListener('visibilitychange', refreshHealth) })
watch(() => route.path, path => { if (path === '/admin') refreshHealth() })
const notifyChannel=ref(''), emptyMode=ref<'autoplaylist'|'radio'|'off'>('autoplaylist'), radioMin=ref(0), radioMax=ref(0)
const query=ref('')
const permissionDialog=ref<HTMLDialogElement|null>(null)
const adminErrorRef=ref<HTMLDivElement|null>(null),permissionErrorRef=ref<HTMLParagraphElement|null>(null)
watch(()=>a.error.value,async error=>{if(error){await nextTick();adminErrorRef.value?.focus()}})
watch(()=>p.error.value,async error=>{if(error){await nextTick();permissionErrorRef.value?.focus()}})
watch(()=>p.pending.value,async pending=>{await nextTick();const dialog=permissionDialog.value;if(!dialog)return;if(pending&&!dialog.open)dialog.showModal();else if(!pending&&dialog.open)dialog.close()})
const lyricsDraft=ref('true'), voteDraft=ref(true)
const audioStateLabel=computed(()=>{
 const labels:Record<string,string>={playing:t('admin.batch.audio.playing'),paused:t('admin.batch.audio.paused'),preparing:t('admin.batch.audio.preparing'),stopped:t('admin.batch.audio.stopped'),disconnected:t('admin.batch.audio.disconnected')}
 return labels[a.maintenance.value?.audio?.state||'']||t('admin.batch.audio.unknown')
})
const notifyDirty=computed(()=>!!a.notify.value&&notifyChannel.value!==(a.notify.value.channel_id||''))
const lyricsDirty=computed(()=>a.lyricsLoaded.value&&lyricsDraft.value!==String(a.lyricsEnabled.value))
const emptyDirty=computed(()=>!!a.emptyQueue.value&&(emptyMode.value!==a.emptyQueue.value.empty_queue||radioMin.value!==a.emptyQueue.value.radio_min_seconds||radioMax.value!==a.emptyQueue.value.radio_max_seconds))
const voteDirty=computed(()=>a.voteSkipLoaded.value&&voteDraft.value!==a.voteSkip.value)
watch(()=>[a.voteSkip.value,a.voteSkipLoaded.value] as const,([value,loaded])=>{voteDraft.value=loaded?value:true},{immediate:true})
watch(()=>a.notify.value,()=>{notifyChannel.value=a.notify.value?.channel_id||''},{immediate:true})
watch(()=>a.emptyQueue.value,()=>{const v=a.emptyQueue.value;if(v){emptyMode.value=v.empty_queue;radioMin.value=v.radio_min_seconds;radioMax.value=v.radio_max_seconds}},{immediate:true})
watch(()=>[a.lyricsEnabled.value,a.lyricsLoaded.value] as const,([value,loaded])=>{lyricsDraft.value=loaded?String(value):'true'},{immediate:true})
function permissionLabel(field:string){const keys:Record<string,string>={AllowPlaylists:'admin.permissions.allowPlaylists',MaxSongLength:'admin.permissions.maxSongLength',MaxSongs:'admin.permissions.maxSongs',MaxPlaylistLength:'admin.permissions.maxPlaylistLength',MaxSearchItems:'admin.permissions.maxSearchItems',InstaSkip:'admin.permissions.instaSkip',SkipLooped:'admin.permissions.skipLooped',Remove:'admin.permissions.remove',SkipWhenAbsent:'admin.permissions.skipWhenAbsent',BypassKaraokeMode:'admin.permissions.bypassKaraoke',SummonNoVoice:'admin.permissions.summonNoVoice',Extractors:'admin.permissions.extractors',CommandWhitelist:'admin.permissions.commandWhitelist',CommandBlacklist:'admin.permissions.commandBlacklist',GrantToRoles:'admin.permissions.grantRoles',UserList:'admin.permissions.userList'};return t(keys[field]||'admin.permissions.other',{p0:field})}
function display(value:unknown){return typeof value==='boolean'?t(value?'admin.value.enabled':'admin.value.disabled'):Array.isArray(value)?value.join(', '):String(value)}
const details=computed(()=>{
 const m=a.maintenance.value;if(!m)return [] as Array<{label:string;value:string;warning?:boolean}>
 const rows:Array<{label:string;value:string;warning?:boolean}>=[{label:t('admin.maintenance.cookie'),value:m.cookie?.status==='unused'?t('admin.maintenance.unused'):m.cookie?.status==='ok'?t('admin.maintenance.ok'):t('admin.maintenance.unavailable'),warning:m.cookie?.warning}]
 if(m.cookie?.earliest_expiry)rows.push({label:t('admin.maintenance.cookieExpiry'),value:`${date(m.cookie.earliest_expiry)} · ${m.cookie.remaining_days??0} ${t('admin.days')}`,warning:(m.cookie.remaining_days??99)<=7})
 if(m.cookie?.updated_at)rows.push({label:t('admin.maintenance.cookieUpdated'),value:date(m.cookie.updated_at)})
 for(const c of m.cookie?.cookies||[])rows.push({label:c.name,value:`${date(c.expires_at)} · ${c.remaining_days} ${t('admin.days')}`,warning:c.remaining_days<=7})
 for(const [key,label] of [['yt-dlp','admin.maintenance.ytdlp'],['yt-dlp-ejs','admin.maintenance.ytdlpEjs']] as const)rows.push({label:t(label),value:m.versions?.[key]||t('admin.value.unknown')})
 if(m.started_at)rows.push({label:t('admin.maintenance.started'),value:date(m.started_at)})
 if(m.last_stop)rows.push({label:t('admin.maintenance.lastStop'),value:`${date(m.last_stop.time)} · ${m.last_stop.classification||''}`})
 rows.push({label:t('admin.maintenance.buildCommit'),value:m.build_info?.commit||'unknown'})
 rows.push({label:t('admin.maintenance.buildTime'),value:m.build_info?.time||'unknown'})
 rows.push({label:t('admin.maintenance.buildBranch'),value:m.build_info?.branch||'unknown'})
 rows.push({label:t('admin.maintenance.frontendVersion'),value:SW_VERSION})
 rows.push({label:t('admin.maintenance.controllerVersion'),value:controllerVersion.value})
 rows.push({label:t('admin.maintenance.viewers'),value:String(m.viewers??0)})
 if(m.host_status?.status==='unavailable')rows.push({label:t('admin.maintenance.host'),value:t('admin.maintenance.unavailable'),warning:true})
 else if(m.host_status?.written_at){rows.push({label:t('admin.maintenance.hostUpdated'),value:date(m.host_status.written_at)});const update=m.host_status.ytdlp_update;if(update?.updated)rows.push({label:t('admin.maintenance.hostYtdlpUpdate'),value:date(update.updated)+' · '+(update.channel||t('admin.value.unknown'))});for(const name of ['yt-dlp','yt-dlp-ejs','bgutil-plugin'])if(update?.[name])rows.push({label:t('admin.maintenance.hostYtdlpVersion',{p0:name}),value:update[name]});const sync=m.host_status.cookie_sync;if(sync)rows.push({label:t('admin.maintenance.hostCookieSync'),value:(t(({success:'admin.maintenance.sync.success',failure:'admin.maintenance.sync.failure',running:'admin.maintenance.sync.running'} as Record<string,string>)[sync.result||'']||'admin.maintenance.sync.unknown'))+' · '+date(sync.last_run)+' · '+date(sync.next_run)})}
 return rows
})
function date(value?:string){if(!value)return t('admin.value.unknown');const d=new Date(value);return Number.isFinite(d.getTime())?d.toLocaleString(undefined,{hour12:false}):t('admin.value.unknown')}
function syncForm(){const v=a.emptyQueue.value;if(v){emptyMode.value=v.empty_queue;radioMin.value=v.radio_min_seconds;radioMax.value=v.radio_max_seconds}}
function syncNotify(){notifyChannel.value=a.notify.value?.channel_id||''}
function search(){a.aplPage.value=1;a.aplQuery.value=query.value;void a.loadApl().catch(()=>{})}
function movePage(delta:number){a.page(delta)}
function saveQueue(){void a.saveEmptyQueue({empty_queue:emptyMode.value,radio_min_seconds:Number(radioMin.value),radio_max_seconds:Number(radioMax.value)})}
function saveNotify(){void a.saveNotify(notifyChannel.value)}
function saveLyricsButton(){void a.saveLyrics(lyricsDraft.value==='true')}
function toggleVote(event:Event){voteDraft.value=(event.currentTarget as HTMLInputElement).checked}
function saveVoteButton(){void a.saveVoteSkip(voteDraft.value)}
</script>
<template>
<section id="admin-panel" class="card" aria-labelledby="admin-heading">
<header class="section-top"><h2 id="admin-heading">{{ t('admin.heading') }}</h2><button id="maintenance-refresh" type="button" :disabled="a.maintenanceLoading.value" @click="a.loadMaintenance().catch(()=>{})">{{ t('admin.refresh') }}</button></header>
<p v-if="a.loading.value" role="status" aria-live="polite">{{ t('admin.loading') }}</p>
<div v-if="a.error.value" ref="adminErrorRef" class="maintenance-warning" role="alert" tabindex="-1">{{ a.error.value }} <button type="button" @click="a.loadAll()">{{ t('admin.retry') }}</button></div>
<template v-if="a.canManage.value">
<div class="admin-health-summary" role="status" aria-live="off"><strong>{{ t('admin.batch.overview') }}</strong><span>{{ t('admin.batch.audio') }}: {{ audioStateLabel }}</span><span v-if="a.maintenance.value?.audio?.capacity_ms">{{ t('admin.batch.underruns') }}: {{ a.maintenance.value?.audio?.underrun_frames??0 }}</span><span v-if="a.maintenance.value?.audio?.capacity_ms">{{ t('admin.batch.buffer') }}: {{ a.maintenance.value?.audio?.buffered_ms??0 }} ms</span><span v-if="a.maintenanceUpdatedAt.value" id="admin-health-updated">{{ t('admin.batch.lastUpdated') }}：{{ new Date(a.maintenanceUpdatedAt.value).toLocaleTimeString(undefined,{hour12:false}) }}</span></div>
<details id="admin-maintenance-group" class="admin-group"><summary>{{ t('admin.maintenance.heading') }}</summary>
<section aria-labelledby="maintenance-heading"><h3 id="maintenance-heading">{{ t('admin.maintenance.heading') }}</h3><p id="maintenance-status" role="status" aria-live="polite">{{ a.maintenanceLoading.value?t('admin.loading'):'' }}</p><dl id="maintenance-details" class="maintenance-details"><template v-if="details.length"><template v-for="row in details" :key="row.label"><dt>{{ row.label }}</dt><dd :class="{'maintenance-warning':row.warning}">{{ row.value }}</dd></template></template><dd v-else class="hint">{{ t('admin.empty') }}</dd></dl></section></details>
<details id="admin-playback-group" class="admin-group" open><summary>{{ t('admin.batch.playback') }}</summary>
<p v-if="!a.notify.value&&a.notifyStatus.value" id="admin-notify-load-error" role="status">{{ a.notifyStatus.value }}</p>
<form id="admin-notify-form" :hidden="!a.notify.value" class="selection-tools" aria-describedby="admin-notify-help" @submit.prevent="saveNotify"><label for="admin-notify-channel">{{ t('admin.notify.label') }}</label><select id="admin-notify-channel" v-model="notifyChannel" aria-describedby="admin-notify-warning"><option value="">{{ t('admin.notify.default') }}</option><option v-for="channel in a.notify.value?.channels||[]" :key="channel.id" :value="channel.id">#{{ channel.name }}</option><option v-if="a.notify.value?.channel_id&&!a.notify.value.channels.some(c=>c.id===a.notify.value?.channel_id)" :value="a.notify.value.channel_id" disabled>{{ t('admin.notify.unavailable') }}</option></select><button id="admin-notify-save" type="submit" :disabled="!a.notify.value||a.loading.value||!notifyDirty||a.saving.value">{{ t('admin.notify.save') }}</button><p id="admin-notify-help" class="hint">{{ t('admin.notify.help') }}</p><p v-if="a.notify.value?.unavailable" id="admin-notify-warning" class="maintenance-warning" role="status">{{ t('admin.notify.warning') }}</p><p id="admin-notify-status" role="status" aria-live="polite">{{ a.notifyStatus.value }}</p></form>
<form id="admin-lyrics-form" class="selection-tools" @submit.prevent="saveLyricsButton"><label for="admin-lyrics-enabled">{{ t('admin.lyrics.label') }}</label><select id="admin-lyrics-enabled" v-model="lyricsDraft"><option value="true">{{ t('admin.lyrics.allow') }}</option><option value="false">{{ t('admin.lyrics.disable') }}</option></select><button id="admin-lyrics-save" type="submit" :disabled="a.loading.value||!lyricsDirty||a.saving.value">{{ t('admin.save') }}</button><p id="admin-lyrics-status" class="hint" role="status" aria-live="polite">{{ a.lyricsStatus.value }}</p></form>
<form id="empty-queue-form" class="selection-tools" @submit.prevent="saveQueue"><label for="empty-queue-mode">{{ t('admin.emptyQueue.label') }}</label><select id="empty-queue-mode" v-model="emptyMode"><option value="autoplaylist">{{ t('admin.emptyQueue.autoplaylist') }}</option><option value="radio">{{ t('admin.emptyQueue.radio') }}</option><option value="off">{{ t('admin.emptyQueue.stop') }}</option></select><template v-if="emptyMode==='radio'"><label for="radio-min-seconds">{{ t('admin.emptyQueue.radioMin') }}</label><input id="radio-min-seconds" v-model.number="radioMin" type="number" min="0" max="31536000" step="1"><label for="radio-max-seconds">{{ t('admin.emptyQueue.radioMax') }}</label><input id="radio-max-seconds" v-model.number="radioMax" type="number" min="0" max="31536000" step="1"></template><button id="empty-queue-save" type="submit" :disabled="a.loading.value||!emptyDirty||a.saving.value">{{ t('admin.save') }}</button><p id="radio-seeds" class="hint" role="status">{{ a.emptyQueue.value?.seed_count ? t('admin.emptyQueue.seedSummary',{p0:a.emptyQueue.value.seed_titles[0]||'',p1:a.emptyQueue.value.seed_count}) : t('admin.emptyQueue.noSeeds') }}</p><p id="empty-queue-status" role="status" aria-live="polite">{{ a.emptyQueueStatus.value || (a.emptyQueue.value?.radio_suspended_seconds ? t('admin.emptyQueue.suspended',{p0:a.emptyQueue.value.radio_suspended_seconds}):'') }}</p></form></details>
<details id="admin-apl-group" class="admin-group"><summary>{{ t('admin.playlist.heading') }}</summary>
<section aria-labelledby="admin-apl-heading"><h3 id="admin-apl-heading">{{ t('admin.playlist.heading') }}</h3><form id="admin-apl-search" class="input-row" @submit.prevent="search"><label for="admin-apl-query">{{ t('admin.playlist.searchLabel') }}</label><input id="admin-apl-query" v-model="query" type="search" maxlength="100"><button id="admin-apl-search-button" type="submit" :disabled="a.saving.value">{{ t('admin.playlist.search') }}</button></form><p id="admin-apl-count" role="status" aria-live="polite">{{ a.apl.value?t('admin.playlist.count',{p0:a.apl.value.total,p1:a.apl.value.matched,p2:a.apl.value.page}):t('admin.loading') }}</p><ol id="admin-apl-list" class="admin-apl-list"><li v-for="track in a.apl.value?.tracks||[]" :key="track.index"><div class="admin-apl-track"><img v-if="safeURL(track.thumbnail)" class="admin-apl-cover" :src="safeURL(track.thumbnail)" alt="" loading="lazy" referrerpolicy="no-referrer"><span class="admin-apl-copy"><strong v-if="track.known">{{ track.title }}</strong><small>{{ track.url||track.title }}</small></span></div><button type="button" :aria-label="t('admin.playlist.removeLabel',{p0:track.title})" :disabled="a.saving.value" @click="a.removeApl(track)">{{ t('admin.playlist.remove') }}</button></li></ol><p v-if="a.apl.value&&!a.apl.value.tracks.length" class="hint">{{ t('admin.playlist.empty') }}</p><div class="selection-tools"><button id="admin-apl-prev" type="button" :disabled="!a.apl.value||a.aplPage.value<=1" @click="movePage(-1)">{{ t('admin.playlist.previous') }}</button><button id="admin-apl-next" type="button" :disabled="!a.apl.value||a.aplPage.value*a.apl.value.page_size>=a.apl.value.matched" @click="movePage(1)">{{ t('admin.playlist.next') }}</button></div></section></details>
<details id="admin-permissions-group" class="admin-group"><summary>{{ t('admin.permissions.heading') }}</summary>
<section aria-labelledby="vote_skip-heading"><h3 id="vote_skip-heading">{{ t('admin.permissions.heading') }}</h3><form id="admin-vote-skip-form" class="selection-tools" @submit.prevent="saveVoteButton"><label for="admin-vote-skip-enabled">{{ t('admin.voteSkip.label') }}</label><input id="admin-vote-skip-enabled" type="checkbox" role="switch" :checked="voteDraft" :disabled="a.loading.value||!a.voteSkipLoaded.value||a.voteSkipLoading.value" aria-describedby="admin-vote-skip-help" @change="toggleVote"><button id="admin-vote-skip-save" type="submit" :disabled="a.loading.value||!voteDirty||a.saving.value||a.voteSkipLoading.value" >{{ t('admin.voteSkip.save') }}</button><p id="admin-vote-skip-help" class="hint">{{ t('admin.voteSkip.help') }}</p><p id="admin-vote-skip-status" role="status" aria-live="polite">{{ a.voteSkipStatus.value }}</p></form></section>
<PermissionsEditor :data="p.data.value" :loading="p.loading.value" :error="p.error.value" :saving="p.saving.value" @change="p.propose" @retry="p.load" />
</details>
<dialog id="permission-confirm-dialog" ref="permissionDialog" aria-labelledby="permission-confirm-heading" @cancel.prevent="p.cancel"><h2 id="permission-confirm-heading">{{ t('admin.permissions.confirmHeading') }}</h2><p id="permission-confirm-text">{{ p.pending.value ? t('admin.permissions.confirmText',{p0:p.pending.value.group,p1:permissionLabel(p.pending.value.field),p2:display(p.pending.value.old_value),p3:display(p.pending.value.value)}) : '' }}</p><p v-if="p.error.value" ref="permissionErrorRef" role="alert" tabindex="-1">{{ p.error.value }}</p><div class="selection-tools"><button id="permission-confirm" type="button" autofocus :disabled="p.saving.value" @click="p.confirm">{{ t('admin.permissions.confirm') }}</button><button id="permission-cancel" type="button" @click="p.cancel">{{ t('admin.cancel') }}</button></div></dialog>
</template>
<p v-else-if="!a.loading.value" class="hint">{{ t('admin.ownerOnly') }}</p>
</section>
</template>
