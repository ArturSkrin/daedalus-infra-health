import type { AckIn, Logs, LogStats, Ops, ScenarioListItem, View } from './types'

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) {
    // the backend's own words when it gives any ("logs are not configured…"), the bare status otherwise
    const detail = await response.json().catch(() => null)
    throw new Error(typeof detail?.detail === 'string' ? detail.detail : `${url}: ${response.status}`)
  }
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

export const loadOps = (scenario?: string) => api<Ops>(`ops${scenario ? `?scenario=${encodeURIComponent(scenario)}` : ''}`)

export const loadLogs = (service: string) => api<Logs>(`logs?service=${encodeURIComponent(service)}`)

// a Loki stream by its own labels, as loadLogStats lists the noisy ones
export const loadStream = (host: string, service: string) =>
  api<Logs>(`logs?loki_host=${encodeURIComponent(host)}&loki_service=${encodeURIComponent(service)}`)

export const loadLogStats = (scenario?: string) => api<LogStats>(`logstats${scenario ? `?scenario=${encodeURIComponent(scenario)}` : ''}`)

async function send(method: string, path: string, body?: unknown): Promise<void> {
  const response = await fetch(`${import.meta.env.BASE_URL}api/${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(typeof detail?.detail === 'string' ? detail.detail : `${path}: ${response.status}`)
  }
}

export const addAck = (ack: AckIn) => send('POST', 'acks', ack)

export const liftAck = (service: string) => send('DELETE', `acks/${encodeURIComponent(service)}`)
