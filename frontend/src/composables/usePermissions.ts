import { computed, ref, watch } from 'vue'
import type { ComputedRef } from 'vue'
import { APIError, request } from '../api'
import { dashboard } from '../store'
import { t } from './useLocale'
export interface PermissionGroup { name:string; values:Record<string,unknown>; editable:string[] }
export interface PermissionData { groups:PermissionGroup[]; limits:Record<string,number>; activity:Array<{detail:string}> }
export interface PermissionChange { group:string; field:string; old_value:unknown; value:unknown }
export function usePermissions(canManage:ComputedRef<boolean>,onUnauthorized:()=>void){
 const data=ref<PermissionData|null>(null), loading=ref(false), error=ref(''), pending=ref<PermissionChange|null>(null), saving=ref(false)
 let epoch=0
 const guild=computed(()=>dashboard.snapshot?.guild_id||'')
 const current=(token:number,id:string)=>token===epoch&&guild.value===id&&canManage.value&&dashboard.authenticated
 async function load(){const id=guild.value,token=++epoch;if(!id||id!==dashboard.guildId||!canManage.value||!dashboard.authenticated){data.value=null;return}loading.value=true;error.value='';try{const v=await request<PermissionData>('/api/guilds/'+encodeURIComponent(id)+'/admin/permissions');if(current(token,id))data.value=v}catch(e){if(token===epoch){data.value=null;if(e instanceof APIError&&e.status===401)onUnauthorized();error.value=e instanceof APIError&&e.status===401?t('admin.error.unauthorized'):e instanceof Error?e.message:t('admin.error.generic')}}finally{if(token===epoch)loading.value=false}}
 function propose(change:PermissionChange){if(!canManage.value)return;error.value='';if(change.field==='AllowPlaylists')pending.value=change;else {const limit=data.value?.limits[change.field];const n=Number(change.value);if(!Number.isSafeInteger(n)||n<0||n>(limit??0)){error.value=t('admin.permissions.invalid');return}if(n!==Number(change.old_value))pending.value={...change,value:n}}}
 async function confirm(){const change=pending.value,id=guild.value,token=epoch;if(!change||!id||!current(token,id))return;saving.value=true;error.value='';try{const {group,field,old_value,value}=change;const result=await request<PermissionData>('/api/guilds/'+encodeURIComponent(id)+'/admin/permissions',{method:'PATCH',body:{group,field,old_value,value}});if(current(token,id)){data.value=result;pending.value=null}}catch(e){if(token===epoch){if(e instanceof APIError&&e.status===401)onUnauthorized();error.value=e instanceof APIError&&e.status===401?t('admin.error.unauthorized'):e instanceof Error?e.message:t('admin.error.generic')}}finally{if(token===epoch)saving.value=false}}
 function cancel(){pending.value=null}
 watch([guild,canManage,()=>dashboard.authenticated],()=>{epoch++;data.value=null;pending.value=null;error.value='';if(canManage.value&&dashboard.authenticated)void load()},{immediate:true})
 return {data,loading,error,pending,saving,load,propose,confirm,cancel}
}
