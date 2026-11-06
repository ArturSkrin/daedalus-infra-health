import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { addAck, liftAck, loadLive, loadLogs, loadOps, loadScenario } from './api'
import { OpsOverview } from './OpsOverview'
import type { Logs, Ops as OpsData, OpsIncident, OpsService, View } from './types'

// The admin screen: the fleet as panels, for the person who runs it. Same data as the overview, without the
// wording on top: every service with its numbers, what is open, what was accepted, the log lines behind it.
// ?scenario=<id> shows a demo scenario, to look at the screen without agents.

const REFRESH_MS = 20_000
const TABS = ['overview', 'services', 'incidents', 'agents', 'logs'] as const
type Tab = (typeof TABS)[number]
type Tone = 'good' | 'warn' | 'bad' | 'muted'

const C = {
  accent: 'text-[#c792ea]',
  cyan: 'text-[#7fdbff]',
  good: 'text-[#7ee787]',
  warn: 'text-[#f0b429]',
  bad: 'text-[#ff6b6b]',
  dim: 'text-[#6e6a86]',
  text: 'text-[#d8d4ea]',
}
const TONE: Record<Tone, string> = { good: C.good, warn: C.warn, bad: C.bad, muted: C.dim }
const DOT: Record<Tone, string> = { good: 'bg-[#7ee787]', warn: 'bg-[#f0b429]', bad: 'bg-[#ff6b6b]', muted: 'bg-[#6e6a86]' }

const scenarioParam = new URLSearchParams(window.location.search).get('scenario') ?? undefined

const pct = (v?: number | null) => (v === null || v === undefined ? '—' : `${v < 10 ? v.toFixed(1) : Math.round(v)}%`)
const clock = (iso?: string | null) => (iso ? iso.slice(5, 16).replace('T', ' ') : '—')

function ago(iso?: string | null): string {
  if (!iso) return '—'
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000)
  return s < 90 ? `${Math.round(s)}s` : s < 5400 ? `${Math.round(s / 60)}m` : s < 172800 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d`
}

function serviceTone(s: OpsService): Tone {
  if (s.dark || s.accepted) return 'muted'
  if (!s.ready) return s.flapping ? 'warn' : 'bad'
  return s.incident ? 'warn' : 'good'
}

function stateWord(s: OpsService): string {
  if (s.dark) return 'silent'
  if (s.accepted) return 'accepted'
  if (!s.ready) return s.flapping ? 'flapping' : 'down'
  return s.incident ? 'warning' : 'healthy'
}

// ----------------------------------------------------------------- building blocks ---

function Dot({ tone }: { tone: Tone }) {
  return <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${DOT[tone]}`} />
}

function Panel({ title, count, tag, hint, children, className = '' }: {
  title: string
  count?: number | string
  tag?: string
  hint?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`flex min-h-0 flex-col rounded-sm border border-[#2a2840] bg-[#0e0d18] ${className}`}>
      <header className="flex items-center justify-between gap-3 bg-[#1b1930] px-2.5 py-1">
        <span className="truncate">
          <span className="text-[#e6defc]">{title}</span>
          {count !== undefined && <span className={C.dim}>({count})</span>}
          {tag && <span className={`ml-1.5 ${C.cyan}`}>[{tag}]</span>}
        </span>
        {hint && <span className={`shrink-0 ${C.accent} opacity-75`}>{hint}</span>}
      </header>
      <div className="scrollbar-thin min-h-0 flex-1 overflow-auto">{children}</div>
    </section>
  )
}

function Bar({ value, tone }: { value?: number | null; tone: Tone }) {
  const width = value === null || value === undefined ? 0 : Math.min(100, Math.max(2, value))
  return (
    <span className="inline-block h-1.5 w-20 rounded-sm bg-white/5 align-middle">
      <span className={`block h-full rounded-sm ${DOT[tone]}`} style={{ width: `${width}%` }} />
    </span>
  )
}

const th = `px-2 py-1 text-left font-normal ${C.dim}`
const td = 'px-2 py-[3px] align-top'

// ----------------------------------------------------------------------- services ---

const FILTERS = ['all', 'healthy', 'down', 'flapping', 'accepted', 'silent'] as const
type Filter = (typeof FILTERS)[number]

function matches(s: OpsService, f: Filter): boolean {
  if (f === 'all') return true
  if (f === 'healthy') return s.ready && !s.dark
  if (f === 'down') return !s.ready && !s.dark && !s.accepted
  if (f === 'flapping') return s.flapping
  if (f === 'accepted') return !!s.accepted
  return !!s.dark
}

function AckForm({ service, severity, onDone }: { service: string; severity?: string; onDone: () => void }) {
  const [kind, setKind] = useState<'expected' | 'noise'>('expected')
  const [days, setDays] = useState(7)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const submit = () =>
    addAck({ service, kind, days, reason, severity: severity as 'info' | 'warning' | 'critical' | undefined })
      .then(onDone)
      .catch((e: Error) => setError(e.message))
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-sm border border-[#2a2840] bg-[#15132a] px-2 py-1.5">
      <select value={kind} onChange={(e) => setKind(e.target.value as 'expected' | 'noise')} className="bg-[#0e0d18] px-1">
        <option value="expected">expected</option>
        <option value="noise">noise</option>
      </select>
      <input type="number" min={1} max={30} value={days} onChange={(e) => setDays(Number(e.target.value))} className="w-12 bg-[#0e0d18] px-1" />
      <span className={C.dim}>days</span>
      <input
        autoFocus
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && reason.trim() && submit()}
        placeholder="why"
        className="min-w-40 flex-1 bg-[#0e0d18] px-1"
      />
      <button type="button" disabled={!reason.trim()} onClick={submit} className={`rounded-sm bg-[#7ee787]/15 px-2 ${C.good} disabled:opacity-40`}>
        accept
      </button>
      {error && <span className={C.bad}>{error}</span>}
    </div>
  )
}

function LogLines({ service, lines = 40, tall = false }: { service: string; lines?: number; tall?: boolean }) {
  const [answer, setAnswer] = useState<{ service: string; logs?: Logs; error?: string; at: number } | null>(null)
  const [asked, setAsked] = useState(0)
  useEffect(() => {
    let cancelled = false
    loadLogs(service)
      .then((logs) => !cancelled && setAnswer({ service, logs, at: Date.now() }))
      .catch((e: Error) => !cancelled && setAnswer({ service, error: e.message, at: Date.now() }))
    return () => {
      cancelled = true
    }
  }, [service, asked])
  const mine = answer?.service === service ? answer : null
  const busy = !mine || mine.at < asked
  return (
    <div>
      <div className={`flex items-center gap-2 ${C.dim}`}>
        <button type="button" onClick={() => setAsked(Date.now())} className="rounded-sm bg-white/5 px-1.5 hover:bg-white/10">
          {busy ? 'loading…' : 'refresh'}
        </button>
        <span className="truncate">{mine?.logs ? `${mine.logs.selector} · last 6 h` : ''}</span>
      </div>
      {mine?.error && <p className={`${C.bad} mt-1`}>{mine.error}</p>}
      {mine?.logs && mine.logs.lines.length === 0 && <p className={`${C.dim} mt-1`}>no lines in the last 6 hours</p>}
      <pre className={`scrollbar-thin mt-1 overflow-auto whitespace-pre-wrap break-all leading-snug ${tall ? 'max-h-[calc(100vh-9rem)]' : 'max-h-80'}`}>
        {mine?.logs?.lines.slice(0, lines).map((l, n) => (
          <div key={n}>
            <span className={C.dim}>{clock(l.at)} </span>
            <span className={/error|fatal|fail|panic|exception|refused|denied/i.test(l.line) ? C.bad : C.text}>{l.line}</span>
          </div>
        ))}
      </pre>
    </div>
  )
}

function Detail({ s, data, onChanged, onLogs }: { s: OpsService; data: OpsData; onChanged: () => void; onLogs: () => void }) {
  const name = `${s.host}:${s.service}`
  const history = data.incidents.filter((i) => i.host === s.host && i.service === s.service)
  const open = history.find((i) => i.status === 'open')
  const accepted = data.acks.find((a) => a.service === name)
  const [acking, setAcking] = useState(false)
  const tone = serviceTone(s)
  const stall = (label: string, v?: number | null) => (
    <div className="flex items-center gap-2">
      <span className={`w-20 ${C.dim}`}>{label}</span>
      <Bar value={v} tone={(v ?? 0) >= 10 ? 'bad' : (v ?? 0) >= 5 ? 'warn' : 'good'} />
      <span>{pct(v)}</span>
    </div>
  )
  return (
    <div className="space-y-3 px-3 py-2.5">
      <div>
        <div className="flex items-center gap-2">
          <Dot tone={tone} />
          <span className="text-base text-white">{s.service}</span>
          <span className={TONE[tone]}>{stateWord(s)}</span>
        </div>
        <div className={C.dim}>
          <span className={C.cyan}>{s.host}</span> · {s.cluster ?? '—'} · tier {s.tier ?? '—'}
          {s.tier === 1 && ' (user path)'}
        </div>
      </div>

      <div className="space-y-0.5">
        {stall('cpu stall', s.cpuStallPct)}
        {stall('mem stall', s.memStallPct)}
        {stall('io stall', s.ioStallPct)}
        <div className="flex items-center gap-2">
          <span className={`w-20 ${C.dim}`}>mem/limit</span>
          <Bar value={s.memOfLimitPct} tone={(s.memOfLimitPct ?? 0) >= 90 ? 'bad' : 'good'} />
          <span>{pct(s.memOfLimitPct)}</span>
          <span className={`ml-3 ${C.dim}`}>oom</span>
          <span className={s.oomKills ? C.bad : ''}>{s.oomKills ?? 0}</span>
        </div>
      </div>

      {(s.incident || accepted) && (
        <div className="rounded-sm border border-[#2a2840] px-2 py-1.5">
          {s.incident && <p className={s.severity === 'critical' ? C.bad : C.warn}>{s.incident}</p>}
          {open && (
            <p className={C.dim}>
              open {ago(open.firstSeen)} · since {clock(open.firstSeen)}
              {open.reopens > 0 && ` · back ${open.reopens}× in 6 h`}
            </p>
          )}
          {accepted && (
            <p className={C.text}>
              <span className={C.dim}>accepted as {accepted.kind} until {accepted.until.slice(0, 10)}: </span>
              {accepted.reason}
            </p>
          )}
          <div className="mt-1.5 flex gap-1.5">
            {open && !acking && (
              <button type="button" onClick={() => setAcking(true)} className="rounded-sm bg-white/10 px-2">
                <span className={C.accent}>a</span> ack
              </button>
            )}
            {accepted && (
              <button type="button" onClick={() => liftAck(name).then(onChanged)} className={`rounded-sm bg-[#f0b429]/15 px-2 ${C.warn}`}>
                lift
              </button>
            )}
          </div>
          {acking && (
            <div className="mt-1.5">
              <AckForm
                service={name}
                severity={open?.severity}
                onDone={() => {
                  setAcking(false)
                  onChanged()
                }}
              />
            </div>
          )}
        </div>
      )}

      {history.length > 0 && (
        <div>
          <div className={C.dim}>last day</div>
          {history.map((i) => (
            <div key={i.id} className={C.text}>
              <span className={C.dim}>{clock(i.firstSeen)} </span>
              {i.status}
              {i.resolvedAt && <span className={C.dim}> → {clock(i.resolvedAt)} by {i.resolvedBy}</span>}
            </div>
          ))}
        </div>
      )}

      <div>
        <div className={`mb-1 flex justify-between ${C.dim}`}>
          <span>logs</span>
          <button type="button" onClick={onLogs} className="hover:text-white">
            <span className={C.accent}>l</span> full screen →
          </button>
        </div>
        <LogLines service={name} lines={30} />
      </div>
    </div>
  )
}

function Services({ data, rows, selected, onSelect, onChanged, onLogs }: {
  data: OpsData
  rows: OpsService[]
  selected: OpsService | null
  onSelect: (s: OpsService) => void
  onChanged: () => void
  onLogs: () => void
}) {
  const [filter, setFilter] = useState<Filter>('all')
  const shown = rows.filter((s) => matches(s, filter))
  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      <Panel title="services" count={data.services.length} tag="fleet" hint="click a row · j/k move · l logs">
        <div className="flex flex-wrap gap-3 border-b border-[#2a2840] px-2.5 py-1.5">
          {FILTERS.map((f) => {
            const n = data.services.filter((s) => matches(s, f)).length
            const tone: Tone = f === 'healthy' ? 'good' : f === 'down' ? 'bad' : f === 'flapping' ? 'warn' : 'muted'
            return (
              <button key={f} type="button" onClick={() => setFilter(f)} className={`flex items-center gap-1 ${filter === f ? 'text-white underline underline-offset-4' : C.dim}`}>
                {f !== 'all' && <Dot tone={tone} />}
                {f} <span className={filter === f ? 'text-white' : ''}>{n}</span>
              </button>
            )
          })}
        </div>
        <table className="w-full">
          <thead className="sticky top-0 bg-[#0e0d18]">
            <tr>
              {['', 'service', 'host', 'tier', 'cpu', 'mem', 'io', 'mem/lim', 'state'].map((h) => (
                <th key={h} className={th}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((s) => {
              const key = `${s.host}:${s.service}`
              const active = selected && `${selected.host}:${selected.service}` === key
              const tone = serviceTone(s)
              return (
                <tr
                  key={key}
                  onClick={() => onSelect(s)}
                  className={`cursor-pointer border-b border-[#2a2840]/40 ${active ? 'bg-[#c792ea]/15' : 'hover:bg-white/[0.04]'}`}
                >
                  <td className={td}>
                    <Dot tone={tone} />
                  </td>
                  <td className={`${td} text-white/90`}>{s.service}</td>
                  <td className={`${td} ${C.cyan}`}>{s.host}</td>
                  <td className={`${td} ${C.dim}`}>{s.tier ?? '—'}</td>
                  <td className={`${td} ${(s.cpuStallPct ?? 0) >= 5 ? C.warn : ''}`}>{pct(s.cpuStallPct)}</td>
                  <td className={`${td} ${(s.memStallPct ?? 0) >= 5 ? C.warn : ''}`}>{pct(s.memStallPct)}</td>
                  <td className={`${td} ${(s.ioStallPct ?? 0) >= 5 ? C.warn : ''}`}>{pct(s.ioStallPct)}</td>
                  <td className={`${td} ${(s.memOfLimitPct ?? 0) >= 90 ? C.bad : ''}`}>{pct(s.memOfLimitPct)}</td>
                  <td className={`${td} ${TONE[tone]}`}>{stateWord(s)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </Panel>
      <Panel title="detail" tag={selected ? selected.host : undefined}>
        {selected ? (
          <Detail key={`${selected.host}:${selected.service}`} s={selected} data={data} onChanged={onChanged} onLogs={onLogs} />
        ) : (
          <p className={`px-3 py-2 ${C.dim}`}>pick a service on the left</p>
        )}
      </Panel>
    </div>
  )
}

// ---------------------------------------------------------------------- incidents ---

function Incidents({ rows, onChanged }: { rows: OpsIncident[]; onChanged: () => void }) {
  const [acking, setAcking] = useState<string | null>(null)
  const open = rows.filter((i) => i.status === 'open').length
  return (
    <Panel title="incidents" count={rows.length} tag="last 24 h" hint={`${open} open · a ack · lift ends an ack`} className="h-full">
      <table className="w-full">
        <thead className="sticky top-0 bg-[#0e0d18]">
          <tr>
            {['sev', 'status', 'service', 'title', 'since', 'for', 'back', 'closed / accepted', ''].map((h, n) => (
              <th key={n} className={th}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((i) => {
            const service = `${i.host}:${i.service}`
            const sev = i.severity === 'critical' ? C.bad : i.severity === 'warning' ? C.warn : C.cyan
            const status = i.status === 'open' ? C.bad : i.status === 'accepted' ? C.dim : C.good
            return [
              <tr key={i.id} className="border-b border-[#2a2840]/40">
                <td className={`${td} ${i.status === 'open' ? sev : C.dim}`}>{i.severity === 'critical' ? 'CRIT' : i.severity === 'warning' ? 'WARN' : 'INFO'}</td>
                <td className={`${td} ${status}`}>{i.status}</td>
                <td className={`${td} whitespace-nowrap`}>
                  <span className={C.cyan}>{i.host}</span>
                  <span className={C.dim}>:</span>
                  {i.service}
                </td>
                <td className={`${td} ${C.text}`}>{i.title}</td>
                <td className={`${td} whitespace-nowrap ${C.dim}`}>{clock(i.firstSeen)}</td>
                <td className={td}>{i.status === 'resolved' ? '—' : ago(i.firstSeen)}</td>
                <td className={`${td} ${i.reopens >= 5 ? C.warn : ''}`}>{i.reopens || ''}</td>
                <td className={`${td} ${C.dim}`}>{i.status === 'resolved' ? `${clock(i.resolvedAt)} by ${i.resolvedBy ?? '—'}` : i.accepted ?? ''}</td>
                <td className={`${td} whitespace-nowrap`}>
                  {i.status === 'open' && (
                    <button type="button" onClick={() => setAcking(acking === i.id ? null : i.id)} className="rounded-sm bg-white/10 px-2">
                      ack
                    </button>
                  )}
                  {i.status === 'accepted' && (
                    <button type="button" onClick={() => liftAck(service).then(onChanged)} className={`rounded-sm bg-[#f0b429]/15 px-2 ${C.warn}`}>
                      lift
                    </button>
                  )}
                </td>
              </tr>,
              acking === i.id && (
                <tr key={`${i.id}-ack`}>
                  <td colSpan={9} className="px-2 py-1">
                    <AckForm
                      service={service}
                      severity={i.severity}
                      onDone={() => {
                        setAcking(null)
                        onChanged()
                      }}
                    />
                  </td>
                </tr>
              ),
            ]
          })}
        </tbody>
      </table>
    </Panel>
  )
}

// ------------------------------------------------------------------------- agents ---

function Agents({ data }: { data: OpsData }) {
  return (
    <Panel title="agents" count={data.agents.length} hint="one per host and per k3s cluster" className="h-full">
      <table className="w-full">
        <thead className="sticky top-0 bg-[#0e0d18]">
          <tr>
            {['', 'agent', 'kind', 'last cycle', 'services', 'silent', 'problem'].map((h) => (
              <th key={h} className={th}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.agents.map((a) => (
            <tr key={a.host} className="border-b border-[#2a2840]/40">
              <td className={td}>
                <Dot tone={a.connected ? 'good' : 'bad'} />
              </td>
              <td className={`${td} ${C.cyan}`}>{a.host}</td>
              <td className={`${td} ${C.dim}`}>{a.cluster ?? '—'}</td>
              <td className={td}>{a.lastMessage ? `${ago(a.lastMessage)} ago` : '—'}</td>
              <td className={td}>{a.services}</td>
              <td className={`${td} ${a.dark ? C.warn : ''}`}>{a.dark || ''}</td>
              <td className={`${td} ${C.bad}`}>{a.error ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

// --------------------------------------------------------------------------- page ---

export default function Ops() {
  const [data, setData] = useState<OpsData | null>(null)
  const [view, setView] = useState<View | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('overview')
  const [search, setSearch] = useState('')
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [logService, setLogService] = useState<string | null>(null)
  const [loadedAt, setLoadedAt] = useState<number | null>(null)
  const [, setTick] = useState(0)
  const searchRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(() => {
    loadOps(scenarioParam)
      .then((d) => {
        setData(d)
        setError(null)
        setLoadedAt(Date.now())
      })
      .catch((e: Error) => setError(e.message))
    ;(scenarioParam ? loadScenario(scenarioParam) : loadLive()).then(setView).catch(() => setView(null))
  }, [])

  useEffect(() => {
    document.title = 'Daedalus ops'
    refresh()
    const timer = window.setInterval(refresh, REFRESH_MS)
    const ticker = window.setInterval(() => setTick((t) => t + 1), 5000)
    return () => {
      window.clearInterval(timer)
      window.clearInterval(ticker)
    }
  }, [refresh])

  const services = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (data?.services ?? []).filter((s) => !needle || [s.host, s.service, s.incident].some((f) => f?.toLowerCase().includes(needle)))
  }, [data, search])
  const incidents = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (data?.incidents ?? []).filter((i) => !needle || [i.host, i.service, i.title].some((f) => f.toLowerCase().includes(needle)))
  }, [data, search])
  const selected = services.find((s) => `${s.host}:${s.service}` === selectedKey) ?? services[0] ?? null
  const serviceNames = useMemo(() => (data?.services ?? []).map((s) => `${s.host}:${s.service}`).sort(), [data])

  const openLogs = useCallback((service: string | null) => {
    if (service) setLogService(service)
    setTab('logs')
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement
      if (e.key === 'Escape') {
        setSearch('')
        searchRef.current?.blur()
        return
      }
      if (typing) return
      if (e.key === '/') {
        e.preventDefault()
        searchRef.current?.focus()
      } else if (/^[1-5]$/.test(e.key)) {
        setTab(TABS[Number(e.key) - 1])
      } else if (tab === 'services' && (e.key === 'j' || e.key === 'k' || e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
        e.preventDefault()
        const index = services.findIndex((s) => s === selected)
        const next = services[Math.max(0, Math.min(services.length - 1, index + (e.key === 'j' || e.key === 'ArrowDown' ? 1 : -1)))]
        if (next) setSelectedKey(`${next.host}:${next.service}`)
      } else if (tab === 'services' && e.key === 'l' && selected) {
        openLogs(`${selected.host}:${selected.service}`)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [tab, services, selected, openLogs])

  const keys: [string, string][] = [
    ['1', 'overview'],
    ['2', 'services'],
    ['3', 'incidents'],
    ['4', 'agents'],
    ['5', 'logs'],
    ['/', 'filter'],
    ['esc', 'clear'],
  ]
  const open = data?.incidents.filter((i) => i.status === 'open').length ?? 0

  return (
    <div className={`flex h-screen flex-col bg-[#09080f] font-mono text-[12px] ${C.text}`}>
      <header className="flex items-center gap-3 border-b border-[#2a2840] px-3 py-1.5">
        <span className={`font-semibold ${C.accent}`}>◉ daedalus</span>
        <span className={C.dim}>ops</span>
        {scenarioParam ? (
          <span className={`rounded-sm bg-[#f0b429]/15 px-1.5 ${C.warn}`}>demo · {scenarioParam}</span>
        ) : (
          <span className={`flex items-center gap-1 ${C.good}`}>
            <Dot tone={error ? 'bad' : 'good'} /> live
          </span>
        )}
        <span className={C.dim}>
          {data ? `${data.agents.length} agents · ${data.services.length} services · ${open} open` : ''}
        </span>
        <input
          ref={searchRef}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="/ filter"
          className="ml-2 w-56 rounded-sm border border-[#2a2840] bg-[#0e0d18] px-2"
        />
        <span className={`ml-auto ${C.dim}`}>{loadedAt ? `updated ${ago(new Date(loadedAt).toISOString())} ago` : 'loading…'}</span>
        <a href="./" className={`${C.dim} hover:text-white`}>
          overview screen →
        </a>
      </header>

      {error && <p className={`px-3 py-1 ${C.bad}`}>could not load: {error}</p>}

      <main className={`min-h-0 flex-1 p-2 ${tab === 'overview' ? 'scrollbar-thin overflow-auto' : ''}`}>
        {data && tab === 'overview' && (
          <OpsOverview
            data={data}
            view={view}
            onPick={(s) => {
              setSelectedKey(`${s.host}:${s.service}`)
              setTab('services')
            }}
          />
        )}
        {data && tab === 'services' && (
          <Services
            data={data}
            rows={services}
            selected={selected}
            onSelect={(s) => setSelectedKey(`${s.host}:${s.service}`)}
            onChanged={refresh}
            onLogs={() => openLogs(selected ? `${selected.host}:${selected.service}` : null)}
          />
        )}
        {data && tab === 'incidents' && <Incidents rows={incidents} onChanged={refresh} />}
        {data && tab === 'agents' && <Agents data={data} />}
        {tab === 'logs' && (
          <Panel title="logs" tag={logService ?? undefined} hint="newest first · last 6 h" className="h-full">
            <div className="px-2.5 py-2">
              <select
                value={logService ?? ''}
                onChange={(e) => setLogService(e.target.value)}
                className="mb-2 min-w-80 rounded-sm border border-[#2a2840] bg-[#0e0d18] px-1"
              >
                <option value="" disabled>
                  pick a service
                </option>
                {serviceNames.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
              {logService && <LogLines service={logService} lines={500} tall />}
            </div>
          </Panel>
        )}
      </main>

      <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-[#2a2840] px-3 py-1">
        {keys.map(([key, label]) => {
          const active = TABS[Number(key) - 1] === tab
          return (
            <button
              key={key}
              type="button"
              onClick={() => /^[1-5]$/.test(key) && setTab(TABS[Number(key) - 1])}
              className="flex items-center gap-1"
            >
              <span className={`rounded-sm px-1 ${active ? 'bg-[#c792ea] text-[#09080f]' : `bg-[#c792ea]/20 ${C.accent}`}`}>&lt;{key}&gt;</span>
              <span className={active ? 'text-white' : C.dim}>{label}</span>
            </button>
          )
        })}
      </footer>
    </div>
  )
}
