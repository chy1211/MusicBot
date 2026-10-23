import { computed, ref, watch } from 'vue'
import { request } from '../api'
import { dashboard } from '../store'
import { t } from './useLocale'
export interface PermissionGroup { name:string; values:Record<string,unknown>; editable:string[] }
export interface PermissionData { groups:PermissionGroup[]; limits:Record<string,number>; activity:Array<{detail:string}> }
export interface PermissionChange { group:string; field:string; old_value:unknown; value:unknown }
export function usePermissions(){
 const data=ref<PermissionData|null>(null), loading=ref(false), error=ref(''), pending=ref<PermissionChange|null>(null), saving=ref(false)
 let epoch=0
 const guild=computed(()=>dashboard.guildId)
 async function load(){const id=guild.value,token=++epoch;if(!id)return;loading.value=true;error.value='';try{const v=await request<PermissionData>(`/api/guilds/${encodeURIComponent(id)}/admin/permissions`);if(token===epoch&&guild.value===id)data.value=v}catch(e){if(token===epoch)error.value=e instanceof Error?e.message:t('admin.error.generic')}finally{if(token===epoch)loading.value=false}}
 function propose(change:PermissionChange){error.value='';if(change.field==='AllowPlaylists')pending.value=change;else {const limit=data.value?.limits[change.field];const n=Number(change.value);if(!Number.isSafeInteger(n)||n<0||n> (limit??0)){error.value=t('admin.permissions.invalid');return}if(n!==Number(change.old_value))pending.value={...change,value:n}}}
 async function confirm(){const change=pending.value,id=guild.value,token=epoch;if(!change||!id)return;saving.value=true;error.value='';try{const {group,field,old_value,value}=change;data.value=await request<PermissionData>(`/api/guilds/${encodeURIComponent(id)}/admin/permissions`,{method:'PATCH',body:{group,field,old_value,value}});if(token===epoch&&guild.value===id)pending.value=null}catch(e){error.value=e instanceof Error?e.message:t('admin.error.generic')}finally{saving.value=false}}
 watch(guild,()=>{data.value=null;pending.value=null;void load()},{immediate:true})
 return {data,loading,error,pending,saving,load,propose,confirm,cancel:()=>pending.value=null}
}
