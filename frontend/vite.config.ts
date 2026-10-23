import {defineConfig} from 'vite'
import vue from '@vitejs/plugin-vue'
import {VitePWA} from 'vite-plugin-pwa'
import {resolve} from 'node:path'
export default defineConfig({plugins:[vue(),VitePWA({strategies:'injectManifest',srcDir:'src',filename:'sw.ts',injectRegister:false,registerType:'autoUpdate',injectManifest:{globIgnores:['**/index.html'],globPatterns:['**/*.{js,css,html,png,svg,json,webmanifest}'],maximumFileSizeToCacheInBytes:2*1024*1024},manifest:{id:'/',name:'Music dashboard',short_name:'Music dashboard',lang:'en',start_url:'/',scope:'/',display:'standalone',theme_color:'#1c211f',background_color:'#f6f3ee',icons:[{src:'/favicon.svg',sizes:'any',type:'image/svg+xml'},{src:'/icon-192.png',sizes:'192x192',type:'image/png'},{src:'/icon-512.png',sizes:'512x512',type:'image/png'}]}})],build:{outDir:resolve(__dirname,'../musicbot/web/dist'),emptyOutDir:true},server:{proxy:{'/api':'http://localhost:8080','/auth':'http://localhost:8080','/ui-config':'http://localhost:8080'}}})
