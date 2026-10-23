import {reactive, computed} from 'vue'
export interface Person {id?:string;name:string;avatar?:string}
export interface Track {title:string;url:string;thumbnail?:string;duration?:number;requester?:Person;position?:number;mine?:boolean;seekable?:boolean;track_token?:string;played_at?:number}
export interface Snapshot {guild_id?:string;status:string;current:Track|null;queue:Track[];progress:number;volume:number|null;repeat:string;revision:string;capabilities?:Record<string,boolean>;lyrics_available?:boolean;listeners?:{connected:boolean;channel?:string;members:Person[]};activity?:{activity:{actor:string;detail:string;time:number;source:string;result:string}[]}}
export interface Me extends Person {can_manage?:boolean;capabilities?:Record<string,boolean>}
export interface Guild {id:string;name:string}
export const dashboard=reactive({snapshot:null as Snapshot|null,guildId:'',guilds:[] as Guild[],me:null as Me|null,authMode:'' as ''|'owner'|'discord',authenticated:false,secret:'',connected:false,loading:false,busy:false,epoch:0,stateSequence:0,stateAt:0,lastPoll:0,streaming:false,connection:'offline',loginStatus:'',loginError:false,history:[] as Track[],historyLoading:false,historyError:'',toast:'',toastError:false,undoToken:'',updateAvailable:false,shortcutsOpen:false})
export const dashboardState=computed(()=>dashboard.snapshot)
export const usable=computed(()=>dashboard.authenticated&&dashboard.connected&&!dashboard.busy&&!!dashboard.guildId)
export const currentTrackKey=computed(()=>dashboard.snapshot?.current?JSON.stringify([dashboard.guildId,dashboard.snapshot.current.url,dashboard.snapshot.current.title,dashboard.snapshot.current.duration,dashboard.snapshot.current.track_token]):'')
export function expireSession(message=''){dashboard.epoch++;dashboard.stateSequence++;dashboard.authenticated=false;dashboard.connected=false;dashboard.guilds=[];dashboard.guildId='';dashboard.snapshot=null;dashboard.me=null;dashboard.secret='';dashboard.history=[];dashboard.historyLoading=false;dashboard.historyError='';dashboard.loading=false;dashboard.toast='';dashboard.undoToken='';dashboard.loginStatus=message;dashboard.busy=false}
