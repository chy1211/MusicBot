import {ref} from 'vue'
import english from '../../public/i18n/en.json'
import chinese from '../../public/i18n/zh-TW.json'
export const locale=ref<'en'|'zh-TW'>('en'),timeZone=ref('UTC')
export function supportedLanguage(value:string){const tag=value.toLowerCase().replaceAll('_','-');return tag.startsWith('en')?'en':tag.startsWith('zh')?'zh-TW':null}
export function chooseLanguage(saved:string|null,languages:readonly string[],fallback:string){if(saved==='en'||saved==='zh-TW')return saved;return languages.map(supportedLanguage).find(Boolean)||(fallback==='zh-TW'?'zh-TW':'en')}
export function t(key:string,params:Record<string,unknown>={}){const catalog:Record<string,string>=locale.value==='zh-TW'?chinese:english;return (catalog[key]||(english as Record<string,string>)[key]||key).replace(/\{(p\d+)\}/g,(match,name:string)=>String(params[name]??match))}
export const translate=t
export async function initLocale(){let config:{time_zone?:string;default_language?:string}={};try{const response=await fetch('/ui-config',{cache:'no-store'});if(response.ok)config=await response.json()}catch{}
 timeZone.value=config.time_zone||'UTC';let saved=null;try{saved=localStorage.getItem('musicbot-language')}catch{}locale.value=chooseLanguage(saved,navigator.languages||[navigator.language],config.default_language||'en') as 'en'|'zh-TW';document.documentElement.lang=locale.value}
export function setLocale(value:string){if(value!=='en'&&value!=='zh-TW')return;try{localStorage.setItem('musicbot-language',value)}catch{}locale.value=value;document.documentElement.lang=value;window.location.reload()}
