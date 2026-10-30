import {createApp} from 'vue'
import {createRouter, createWebHashHistory} from 'vue-router'
import App from './App.vue'
import Workspace from './views/Workspace.vue'
import {pages} from './navigation'
import './styles/index.css'
const router = createRouter({history:createWebHashHistory(),routes:[{path:'/',component:Workspace},...pages.map(page=>({path:'/'+page,component:Workspace}))]})
const app = createApp(App)
app.use(router)
void router.isReady().then(()=>app.mount('#app'))
