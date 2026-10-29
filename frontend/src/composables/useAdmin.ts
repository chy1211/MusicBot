import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { APIError, request } from '../api'
import { dashboard } from '../store'
import { t } from './useLocale'
import { notice } from './useDashboard'
import { toggleLyrics } from './useLyrics'

export type EmptyQueueMode = 'autoplaylist' | 'radio' | 'off'
export interface Channel { id: string; name: string }
export interface NotifySettings { channels: Channel[]; channel_id: string | null; unavailable: boolean }
export interface EmptyQueueSettings { empty_queue: EmptyQueueMode; radio_min_seconds: number; radio_max_seconds: number; seed_count: number; seed_titles: string[]; radio_suspended_seconds: number }
export interface AplTrack { index: number; title: string; url: string; thumbnail?: string; known?: boolean; duration?: number }
export interface AplPage { total: number; matched: number; page: number; page_size: number; revision: number; tracks: AplTrack[] }
export interface Maintenance { audio?: {state:string;buffered_ms:number;capacity_ms:number;underrun_frames:number;read_error?:string;worker_done?:boolean}; cookie?: {status?: string; warning?: boolean; earliest_expiry?: string; remaining_days?: number; updated_at?: string; cookies?: Array<{name:string; expires_at?:string; remaining_days:number}>}; versions?: Record<string,string>; started_at?: string; last_stop?: {time?:string; classification?:string} | null; dashboard_version?:string; build_info?: {commit?:string;time?:string;branch?:string}; viewers?:number; host_status?: {status?:string; written_at?:string; ytdlp_update?: Record<string,string>; cookie_sync?: {result?:string;last_run?:string;next_run?:string}} }

export function useAdmin() {
 const guild = computed(() => dashboard.snapshot?.guild_id || '')
 const canManage = computed(() => dashboard.authenticated && guild.value === dashboard.guildId && !!owner.value)
 const owner = ref(false), loading = ref(false), saving = ref(false), error = ref('')
 let saveCount=0
 const beginSave=()=>{saveCount++;saving.value = true}
 const endSave=()=>{saveCount=Math.max(0,saveCount-1);saving.value=saveCount>0}
 const notify = ref<NotifySettings | null>(null), notifyStatus = ref('')
 const lyricsLoaded = ref(false), voteSkipLoaded = ref(false)
 const lyricsEnabled = ref(true), lyricsStatus = ref('')
 const emptyQueue = ref<EmptyQueueSettings | null>(null), emptyQueueStatus = ref('')
 const apl = ref<AplPage | null>(null), aplPage = ref(1), aplQuery = ref('')
 const maintenance = ref<Maintenance | null>(null), maintenanceLoading = ref(false)
 const voteSkip = ref(true), voteSkipLoading = ref(false), voteSkipStatus = ref('')
 let epoch = 0, aplSequence = 0
 const path = (id:string,suffix:string) => `/api/guilds/${encodeURIComponent(id)}/admin/${suffix}`
 const current = (token:number,id:string) => token === epoch && guild.value === id
 const message = (e:unknown) => e instanceof Error ? e.message : t('admin.error.generic')
 function handleError(e:unknown){if(e instanceof APIError&&e.status===401){owner.value=false;notify.value=null;emptyQueue.value=null;apl.value=null;maintenance.value=null;error.value=t('admin.error.unauthorized')}else error.value=message(e)}
 async function loadAll() {
  const id=guild.value, token=++epoch
  if(!id||id!==dashboard.guildId||!dashboard.authenticated){owner.value=false;loading.value=false;notify.value=null;emptyQueue.value=null;apl.value=null;maintenance.value=null;lyricsLoaded.value=false;voteSkipLoaded.value=false;return}
  // Do not expose the previous guild's settings while a new guild loads.
  owner.value=false;notify.value=null;emptyQueue.value=null;apl.value=null;maintenance.value=null
  lyricsLoaded.value=false;voteSkipLoaded.value=false
  aplPage.value=1;aplQuery.value='';maintenanceLoading.value=false;voteSkipLoading.value=false
  notifyStatus.value='';lyricsStatus.value='';emptyQueueStatus.value='';voteSkipStatus.value=''
  loading.value=true;error.value=''
  try {
   const capability=await request<{owner:boolean}>('/api/library')
   if(!current(token,id))return
   owner.value=capability.owner===true
   if(!owner.value){notify.value=null;emptyQueue.value=null;apl.value=null;maintenance.value=null;return}
   // An unavailable endpoint must not block successful independent panels.
   const results=await Promise.allSettled([loadNotify(token,id),loadLyrics(token,id),loadEmptyQueue(token,id),loadApl(token,id),loadMaintenance(token,id),loadVoteSkip(token,id)])
   if(current(token,id)&&results.some(v=>v.status==='rejected'))error.value=t('admin.batch.partialLoad')
  } catch(e) {if(current(token,id)){if(e instanceof APIError&&e.status===401){owner.value=false;notify.value=null;emptyQueue.value=null;apl.value=null;maintenance.value=null;error.value=t('admin.error.unauthorized')}else error.value=message(e)}}
  finally {if(current(token,id))loading.value=false}
 }
 async function loadNotify(token=epoch,id=guild.value){if(!id)return;try{const v=await request<NotifySettings>(path(id,'notification-channel'));if(!Array.isArray(v.channels))throw new Error(t('admin.error.generic'));if(current(token,id)){notify.value=v;notifyStatus.value=''}}catch(e){if(current(token,id)){notify.value=null;notifyStatus.value=message(e)}throw e}}
 async function saveNotify(channelId:string){const id=guild.value,token=epoch;if(!id||!canManage.value||!notify.value||saving.value)return;beginSave();notifyStatus.value='';try{const v=await request<NotifySettings>(path(id,'notification-channel'),{method:'POST',body:{channel_id:channelId||null}});if(!current(token,id))return;notify.value=v;notifyStatus.value=t('admin.notify.saved')}catch(e){if(current(token,id))notifyStatus.value=message(e)}finally{endSave()}}
 async function loadLyrics(token=epoch,id=guild.value){if(!id)return;try{const v=await request<{enabled:boolean}>(path(id,'lyrics'));if(typeof v.enabled!=='boolean')throw new Error(t('admin.error.generic'));if(current(token,id)){lyricsEnabled.value=v.enabled;lyricsLoaded.value=true;lyricsStatus.value=''}}catch(e){if(current(token,id)){lyricsLoaded.value=false;lyricsStatus.value=message(e)}throw e}}
 async function saveLyrics(enabled:boolean){const id=guild.value,token=epoch;if(!id||!canManage.value||!lyricsLoaded.value||saving.value)return;beginSave();lyricsStatus.value='';try{const v=await request<{enabled:boolean}>(path(id,'lyrics'),{method:'POST',body:{enabled}});if(!current(token,id))return;lyricsEnabled.value=v.enabled;if(dashboard.snapshot)dashboard.snapshot.lyrics_available=v.enabled;if(!v.enabled)toggleLyrics(false);lyricsStatus.value=t('admin.lyrics.saved')}catch(e){if(current(token,id))lyricsStatus.value=message(e)}finally{endSave()}}
 async function loadEmptyQueue(token=epoch,id=guild.value){if(!id)return;try{const v=await request<EmptyQueueSettings>(path(id,'empty-queue'));if(!['autoplaylist','radio','off'].includes(v.empty_queue))throw new Error(t('admin.error.generic'));if(current(token,id)){emptyQueue.value=v;emptyQueueStatus.value=''}}catch(e){if(current(token,id)){emptyQueue.value=null;emptyQueueStatus.value=message(e)}throw e}}
 async function saveEmptyQueue(data:Pick<EmptyQueueSettings,'empty_queue'|'radio_min_seconds'|'radio_max_seconds'>){const id=guild.value,token=epoch;if(!id||!canManage.value||!emptyQueue.value||saving.value)return;beginSave();emptyQueueStatus.value='';try{if(![data.radio_min_seconds,data.radio_max_seconds].every(v=>Number.isInteger(v)&&v>=0)||(data.radio_max_seconds>0&&data.radio_min_seconds>data.radio_max_seconds))throw new Error(t('admin.radio.invalid'));const v=await request<EmptyQueueSettings>(path(id,'empty-queue'),{method:'POST',body:data});if(!current(token,id))return;emptyQueue.value=v;emptyQueueStatus.value=t('admin.emptyQueue.saved');notice(emptyQueueStatus.value)}catch(e){if(current(token,id))emptyQueueStatus.value=message(e)}finally{endSave()}}
 async function loadApl(token=epoch,id=guild.value){if(!id)return;const sequence=++aplSequence;const q=new URLSearchParams({page:String(aplPage.value),q:aplQuery.value});try{const v=await request<AplPage>(path(id,`autoplaylist?${q}`));if(!Array.isArray(v.tracks))throw new Error(t('admin.error.generic'));if(current(token,id)&&sequence===aplSequence)apl.value=v}catch(e){if(current(token,id)&&sequence===aplSequence){apl.value=null;handleError(e)}throw e}}
 async function changeApl(data:Record<string,unknown>,method='POST'){const id=guild.value,token=epoch;if(!id||!canManage.value||saving.value)return;beginSave();error.value='';try{if(!apl.value)await loadApl(token,id);if(!current(token,id))return;const revision=apl.value?.revision;await request(path(id,'autoplaylist'),{method,body:{...data,revision}});if(!current(token,id))return;await loadApl(token,id);if(current(token,id))notice(t('admin.playlist.saved'))}catch(e){if(current(token,id))handleError(e)}finally{endSave()}}
 async function removeApl(track:AplTrack){if(!window.confirm(t('admin.playlist.removeConfirm')))return;await changeApl({index:track.index},'DELETE')}
 async function loadMaintenance(token=epoch,id=guild.value){if(!id)return;maintenanceLoading.value=true;try{const v=await request<Maintenance>(path(id,'maintenance'));if(current(token,id))maintenance.value=v}catch(e){if(current(token,id)){maintenance.value=null;handleError(e)}throw e}finally{if(current(token,id))maintenanceLoading.value=false}}
 async function loadVoteSkip(token=epoch,id=guild.value){if(!id)return;voteSkipLoading.value=true;try{const v=await request<{enabled:boolean}>(path(id,'vote-skip'));if(typeof v.enabled!=='boolean')throw new Error(t('admin.error.generic'));if(current(token,id)){voteSkip.value=v.enabled;voteSkipLoaded.value=true;voteSkipStatus.value=''}}catch(e){if(current(token,id)){voteSkipLoaded.value=false;voteSkipStatus.value=message(e)}throw e}finally{if(current(token,id))voteSkipLoading.value=false}}
 async function saveVoteSkip(enabled:boolean){const id=guild.value,token=epoch;if(!id||!canManage.value||!voteSkipLoaded.value||saving.value)return;beginSave();voteSkipStatus.value='';try{const v=await request<{enabled:boolean}>(path(id,'vote-skip'),{method:'POST',body:{enabled}});if(!current(token,id))return;voteSkip.value=v.enabled;voteSkipStatus.value=t('admin.voteSkip.saved')}catch(e){if(current(token,id))voteSkipStatus.value=message(e)}finally{endSave()}}
 function page(delta:number){aplPage.value=Math.max(1,aplPage.value+delta);void loadApl().catch(()=>{})}
 watch([guild,()=>dashboard.authenticated,()=>dashboard.snapshot?.guild_id],()=>void loadAll(),{immediate:true})
 onBeforeUnmount(()=>{epoch++})
 return {owner,canManage,loading,saving,error,notify,notifyStatus,lyricsEnabled,lyricsLoaded,lyricsStatus,emptyQueue,emptyQueueStatus,apl,aplPage,aplQuery,maintenance,maintenanceLoading,voteSkip,voteSkipLoaded,voteSkipLoading,voteSkipStatus,loadAll,loadMaintenance,saveNotify,saveLyrics,saveEmptyQueue,loadApl,page,removeApl,saveVoteSkip}
}
