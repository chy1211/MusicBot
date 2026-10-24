import {dashboard,expireSession} from './store'
import {t,locale} from './composables/useLocale'
export type ResolutionState = 'queued'|'resolving'
export interface APIOptions {method?:string;body?:unknown;signal?:AbortSignal;onResolutionState?:(state:ResolutionState)=>void}
export class APIError extends Error {constructor(message:string,public status:number,public body:Record<string,unknown>={}){super(message)}}
export async function request<T>(path:string,options:APIOptions={}):Promise<T>{
 const headers:Record<string,string>={'X-MusicBot-Dashboard':'1','X-Dashboard-Language':locale.value}
 if(dashboard.authMode==='owner'&&dashboard.secret)headers.Authorization='Bearer '+dashboard.secret
 if(options.body!==undefined)headers['Content-Type']='application/json'
 const abort=new AbortController(),forward=()=>abort.abort();options.signal?.addEventListener('abort',forward,{once:true});if(options.signal?.aborted)abort.abort()
 const resolution=options.method==='POST'&&/^\/api\/guilds\/[^/]+\/(resolve|play|playnext|library\/.*\/(play|preview))$/.test(path)
 const batch=options.body&&(/\/library\/.*\/play$/.test(path)||'selected_items' in Object(options.body))
 // A compatibility add can renew/preview then enqueue. Each admission can wait
 // 15s, in addition to provider time and worker reap. Batch keeps its old budget
 // plus room for queued tracks. The HTTP result is independent of status polling.
 const timer=setTimeout(()=>abort.abort(),resolution?(batch?180000:85000):30000)
 const statusAbort=new AbortController();let statusTimer:ReturnType<typeof setTimeout>|undefined,finished=false
 if(resolution&&options.onResolutionState){
  const id=Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');headers['X-MusicBot-Request-ID']=id
  const statusPath=path.replace(/(\/api\/guilds\/[^/]+)\/.*/, '$1/resolution-status')+'?request_id='+id
  options.onResolutionState('queued')
  const poll=async()=>{
   const timeout=setTimeout(()=>statusAbort.abort(),3000)
   try{const response=await fetch(statusPath,{headers,credentials:'same-origin',cache:'no-store',signal:statusAbort.signal});if(response.ok){const value=await response.json();if(!finished&&(value.state==='queued'||value.state==='resolving'))options.onResolutionState?.(value.state)}}catch{/* Status failure must never cancel or delay the original POST. */}
   finally{clearTimeout(timeout);if(!finished&&!statusAbort.signal.aborted)statusTimer=setTimeout(poll,200)}
  };statusTimer=setTimeout(poll,100)
 }
 try{const response=await fetch('/'+path.replace(/^\//,''),{method:options.method||'GET',headers,credentials:'same-origin',cache:'no-store',signal:abort.signal,body:options.body===undefined?undefined:JSON.stringify(options.body)})
 const body=await response.json().catch(()=>({})) as Record<string,unknown>
 if(!response.ok){if(response.status===401&&dashboard.authMode==='discord')expireSession(String(body.error||t('m0055')));throw new APIError(String(body.error||t('m0056')),response.status,body)}return body as T
 }catch(error){if(error instanceof DOMException&&error.name==='AbortError')throw new APIError(t('m0054'),0);throw error}
 finally{finished=true;clearTimeout(statusTimer);statusAbort.abort();clearTimeout(timer);options.signal?.removeEventListener('abort',forward)}
}
