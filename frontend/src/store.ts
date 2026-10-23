import { shallowRef, readonly } from 'vue'
export interface Track { title: string; url: string; thumbnail?: string; duration?: number; requester?: {name: string} }
export interface DashboardState { guild_id: string; status: string; current: Track | null; queue: Track[]; progress: number; volume: number }
const state = shallowRef<DashboardState | null>(null)
export const dashboardState = readonly(state)
export function updateState(value: DashboardState | null) { state.value = value }
