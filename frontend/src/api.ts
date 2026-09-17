import type { ScenarioListItem, View } from './types'

// With the backend running, the app talks to /api. On static hosting (GitHub
// Pages) there is no backend, so it falls back to view models exported at
// build time by backend/export_views.py into public/views/.
const STATIC = `${import.meta.env.BASE_URL}views/`

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`${url}: ${response.status}`)
  if (!(response.headers.get('content-type') ?? '').includes('json')) throw new Error(`${url}: not JSON`)
  return response.json() as Promise<T>
}

async function apiOrStatic<T>(apiPath: string, staticFile: string): Promise<T> {
  try {
    return await getJson<T>(`${import.meta.env.BASE_URL}api/${apiPath}`)
  } catch {
    return getJson<T>(STATIC + staticFile)
  }
}

export const loadScenarios = () => apiOrStatic<ScenarioListItem[]>('scenarios', 'index.json')

export const loadScenario = (id: string) => apiOrStatic<View>(`scenarios/${encodeURIComponent(id)}`, `${id}.json`)

export async function liveAvailable(): Promise<boolean> {
  try {
    return (await getJson<{ live: boolean }>(`${import.meta.env.BASE_URL}api/health`)).live
  } catch {
    return false
  }
}

export const loadLive = () => getJson<View>(`${import.meta.env.BASE_URL}api/live`)
