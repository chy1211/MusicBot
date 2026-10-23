export const pages = ['play','library','popular','admin'] as const
export type Page = typeof pages[number]
export function isPage(value: string): value is Page {return (pages as readonly string[]).includes(value)}
