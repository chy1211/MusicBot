export interface APIOptions {method?: string; body?: unknown; signal?: AbortSignal}
// Typed transport for Vue-owned features. Identity stays in the server session.
export async function request<T>(path: string, options: APIOptions = {}): Promise<T> {
 const response = await fetch(path, {method: options.method || 'GET', credentials:'same-origin', cache:'no-store', signal:options.signal,
 headers:{'X-MusicBot-Dashboard':'1','X-Dashboard-Language':document.documentElement.lang, ...(options.body === undefined ? {} : {'Content-Type':'application/json'})},
 body: options.body === undefined ? undefined : JSON.stringify(options.body)})
 const data = await response.json()
 if (!response.ok) throw new Error(data.error || String(response.status))
 return data as T
}
