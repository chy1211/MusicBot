import {createApp} from 'vue'
import {createRouter, createWebHashHistory} from 'vue-router'
import App from './App.vue'
import Workspace from './views/Workspace.vue'
import {pages} from './navigation'
import './style.css'
import './round12.css'
import './round13.css'
import './round14.css'
import './round15.css'
const router = createRouter({history:createWebHashHistory(),routes:[{path:'/',component:Workspace},...pages.map(page=>({path:'/'+page,component:Workspace}))]})
const app = createApp(App)
app.use(router)
void router.isReady().then(()=>app.mount('#app'))
