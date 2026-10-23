import {dashboard,expireSession} from './store'
import {t,locale} from './composables/useLocale'
export interface APIOptions {method?:string;body?:unknown;signal?:AbortSignal}
export class APIError extends Error {constructor(message:string,public status:number,public body:Record<string,unknown>={}){super(message)}}
export async function request<T>(path:string,options:APIOptions={}):Promise<T>{
 const headers:Record<string,string>={'X-MusicBot-Dashboard':'1','X-Dashboard-Language':locale.value}
 if(dashboard.authMode==='owner'&&dashboard.secret)headers.Authorization='Bearer '+dashboard.secret
 if(options.body!==undefined)headers['Content-Type']='application/json'
 const abort=new AbortController(),forward=()=>abort.abort();options.signal?.addEventListener('abort',forward,{once:true});if(options.signal?.aborted)abort.abort()
 const timer=setTimeout(()=>abort.abort(),path.endsWith('/resolve')?25000:options.body&&(/\/library\/.*\/play$/.test(path)||'selected_items' in Object(options.body))?150000:30000)
 try{const response=await fetch('/'+path.replace(/^\//,''),{method:options.method||'GET',headers,credentials:'same-origin',cache:'no-store',signal:abort.signal,body:options.body===undefined?undefined:JSON.stringify(options.body)})
 const body=await response.json().catch(()=>({})) as Record<string,unknown>
 if(!response.ok){if(response.status===401&&dashboard.authMode==='discord')expireSession(String(body.error||t('m0055')));throw new APIError(String(body.error||t('m0056')),response.status,body)}return body as T
 }catch(error){if(error instanceof DOMException&&error.name==='AbortError')throw new APIError(t('m0054'),0);throw error}
 finally{clearTimeout(timer);options.signal?.removeEventListener('abort',forward)}
}
