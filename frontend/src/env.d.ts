/// <reference types="vite/client" />
declare module "virtual:dashboard-controller" {
 export function mountController(): {ready: Promise<void>; translate(key:string):string; navigate(page: string): void; getState(): import("./store").DashboardState | null; notice(message: string, error?: boolean): void}
}
