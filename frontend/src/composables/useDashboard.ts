import {onMounted, onBeforeUnmount} from 'vue'
import {useRouter} from 'vue-router'
import {mountController} from 'virtual:dashboard-controller'
import {updateState, type DashboardState} from '../store'
import {installTranslator} from './useLocale'
import {isPage} from '../navigation'
export function useDashboard() {
 const router = useRouter()
 const changed = (event: Event) => updateState((event as CustomEvent<DashboardState>).detail)
 const navigate = (event: Event) => {const page = (event as CustomEvent<string>).detail; if(isPage(page) && router.currentRoute.value.path !== '/'+page)void router.push('/'+page)}
 let removeRoute: (()=>void) | undefined
 onMounted(()=>{
  window.addEventListener('musicbot:state',changed);window.addEventListener('musicbot:navigate',navigate)
  const controller = mountController()
  installTranslator(controller.translate)
  const showRoute = () => {const page=router.currentRoute.value.path.slice(1) || 'play'; if(isPage(page)){
   const button=document.getElementById('nav-'+page) as HTMLButtonElement | null
   if(button && !button.hidden && button.getAttribute('aria-pressed')!=='true')button.click()
  }}
  void controller.ready.then(()=>{showRoute();removeRoute=router.afterEach(showRoute)})
  const seed=document.getElementById('demo-query-value') as HTMLInputElement | null
  const query=document.getElementById('query') as HTMLInputElement | null
  if(seed && query)query.value=seed.value
 })
 onBeforeUnmount(()=>{removeRoute?.();window.removeEventListener('musicbot:state',changed);window.removeEventListener('musicbot:navigate',navigate)})
}
