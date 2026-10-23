import {shallowRef} from 'vue'
const translator=shallowRef<(key:string)=>string>(key=>key)
export function installTranslator(value:(key:string)=>string){translator.value=value}
export function translate(key:string){return translator.value(key)}
