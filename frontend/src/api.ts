import type { ScenarioListItem, View } from './types'

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`${url}: ${response.status}`)
  if (!(response.headers.get('content-type') ?? '').includes('json')) throw new Error(`${url}: not JSON`)
  return response.json() as Promise<T>
}

const api = <T,>(path: string) => getJson<T>(`${import.meta.env.BASE_URL}api/${path}`)

export const loadScenarios = () => api<ScenarioListItem[]>('scenarios')

export const loadScenario = (id: string) => api<View>(`scenarios/${encodeURIComponent(id)}`)

export async function liveAvailable(): Promise<boolean> {
  try {
    return (await api<{ live: boolean }>('health')).live
  } catch {
    return false
  }
}

export const loadLive = (tenant?: string) => api<View>(`live${tenant ? `?tenant=${encodeURIComponent(tenant)}` : ''}`)
