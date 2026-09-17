// View model served by backend/presentation.py. The frontend renders it and
// decides nothing: every threshold lives in backend/engine.py.

export type Level = 'good' | 'warn' | 'bad' | 'muted'
export type Verdict = 'all_clear' | 'schedule' | 'act_now' | 'blind'
export type IndicatorId = 'users' | 'forecast' | 'trust' | 'day'
export type DrillTarget = IndicatorId | 'verdict'

export interface Fact {
  label: string
  value: string
  hint?: string
}

export interface ServiceRow {
  service: string
  tier: number | null
  errPct: number
  reqPerSec: number
  p99Ms: number | null
  ready: boolean
  fresh: boolean
  hitsNext: string[]
  flag: Level
}

export interface PressureRow {
  service: string
  memStallPct: number | null
  cpuStallPct: number | null
  ioStallPct: number | null
  memOfRequestPct: number | null
  oomKills: number
}

export interface Drill {
  facts: Fact[]
  services?: ServiceRow[]
  steps?: { text: string; done: boolean }[]
  note?: string
  pressure?: PressureRow[]
  dark?: { name: string; silentFor: string }[]
  sparkline?: number[]
  recentFrom?: number
  signals?: { label: string; count: number }[]
  handled?: { service: string; title: string; at: string; rca?: string }[]
}

export interface Indicator {
  id: IndicatorId
  title: string
  question: string
  horizon: string
  state: string
  label: string
  level: Level
  ring: number
  caption: string
  decides: boolean
  drill?: Drill
}

export interface QueueItem {
  id: string
  service: string
  severity: 'critical' | 'warning' | 'info'
  title: string
  openFor: string
  impact: string
  rca?: string
  plan: string[]
  related: string[]
}

export interface Rule {
  id: string
  text: string
  leadsTo: string
  fired: boolean
}

export interface View {
  source: {
    mode: 'demo' | 'live'
    label: string
    tenant: string
    cluster: string | null
    connected: boolean
    age: string
    now: string
  }
  decision: {
    verdict: Verdict
    word: string
    action: string
    level: Level
    trigger: string
    reason: string
    dimmed: boolean
    rules: Rule[]
  }
  indicators: Indicator[]
  queue: QueueItem[]
  scenario?: { id: string; title: string; story: string }
  validation?: {
    passed: boolean
    expected: { verdict: Verdict; states: Record<string, string>; reason?: string }
    computed: { verdict: Verdict; states: Record<string, string> }
  }
}

export interface ScenarioListItem {
  id: string
  title: string
  expected: Verdict
  actual: Verdict
  passed: boolean
}
