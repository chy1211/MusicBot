import {defineConfig, type Plugin} from 'vite'
import vue from '@vitejs/plugin-vue'
import {VitePWA} from 'vite-plugin-pwa'
import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
const web = resolve(__dirname,'../musicbot/web')
// Preserve the battle-tested gesture/auth/SSE state machines in one lexical
// scope during the framework migration. This is bundled code, never eval.
function dashboardController(): Plugin {
 return {name:'dashboard-controller',resolveId(id){if(id==='virtual:dashboard-controller')return '\0dashboard-controller'},
 load(id){if(id!=='\0dashboard-controller')return
 const names=['i18n','dashboard','playlist-covers','library','popular','admin','permissions','pwa']
 const source=names.map(name=>readFileSync(resolve(web,name+'.js'),'utf8')).join('\n').replace('initialize().finally(', 'const initialized = initialize().finally(')
 return 'let singleton; export function mountController(){if(singleton)return singleton;\n'+source+'\nconst controller = {navigate:libraryView,getState:()=>state,notice,translate:t,ready:initialized}; window.musicbotDashboard=controller; window.localProgress=localProgress; singleton=controller; return controller;\n}'
 }}
}
export default defineConfig({plugins:[vue(),dashboardController(),VitePWA({strategies:'injectManifest',srcDir:'src',filename:'sw.ts',injectRegister:false,registerType:'autoUpdate',
 injectManifest:{globIgnores:['**/index.html'],globPatterns:['**/*.{js,css,html,png,svg,json,webmanifest}'],maximumFileSizeToCacheInBytes:2*1024*1024},
 manifest:{id:'/',name:'Music dashboard',short_name:'Music dashboard',lang:'en',start_url:'/',scope:'/',display:'standalone',theme_color:'#1c211f',background_color:'#f6f3ee',icons:[{src:'/favicon.svg',sizes:'any',type:'image/svg+xml'},{src:'/icon-192.png',sizes:'192x192',type:'image/png'},{src:'/icon-512.png',sizes:'512x512',type:'image/png'}]}})],
 build:{outDir:resolve(web,'dist'),emptyOutDir:true},server:{proxy:{'/api':'http://localhost:8080','/auth':'http://localhost:8080','/ui-config':'http://localhost:8080'}}})
