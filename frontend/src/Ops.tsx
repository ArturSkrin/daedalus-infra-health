import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { addAck, liftAck, loadLogs, loadOps } from './api'
import type { Logs, Ops as OpsData, OpsIncident, OpsService } from './types'

// The admin screen: the fleet as rows, for the person who runs it. No verdict, no rings: what the agents report,
// what is open, what was accepted, and the log lines behind it. 1-4 switch tabs, / filters, Esc clears.

const REFRESH_MS = 20_000
const TABS = ['services', 'incidents', 'agents', 'logs'] as const
type Tab = (typeof TABS)[number]

const pct = (v?: number | null) => (v === null || v === undefined ? '—' : `${v < 10 ? v.toFixed(1) : Math.round(v)}%`)
const when = (iso?: string | null) => (iso ? iso.slice(5, 16).replace('T', ' ') : '—')

function ago(iso?: string | null): string {
  if (!iso) return '—'
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000)
  return s < 90 ? `${Math.round(s)}s` : s < 5400 ? `${Math.round(s / 60)}m` : s < 172800 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d`
}

function Dot({ tone }: { tone: 'good' | 'warn' | 'bad' | 'muted' }) {
  const color = { good: 'bg-good', warn: 'bg-warn', bad: 'bg-bad', muted: 'bg-muted' }[tone]
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />
}

function serviceTone(s: OpsService): 'good' | 'warn' | 'bad' | 'muted' {
  if (s.dark) return 'muted'
  if (s.accepted) return 'muted'
  if (!s.ready) return s.flapping ? 'warn' : 'bad'
  return s.incident ? 'warn' : 'good'
}

const th = 'px-2 py-1.5 text-left text-[11px] font-medium uppercase tracking-wide text-white/40'
const td = 'px-2 py-1 align-top'

function Services({ rows, onLogs }: { rows: OpsService[]; onLogs: (service: string) => void }) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="border-b border-border">
          {['', 'host', 'service', 'tier', 'cpu', 'mem', 'io', 'mem/limit', 'oom', 'incident', 'flags'].map((h) => (
            <th key={h} className={th}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((s) => (
          <tr
            key={`${s.host}:${s.service}`}
            onClick={() => onLogs(`${s.host}:${s.service}`)}
            className="cursor-pointer border-b border-border/50 hover:bg-white/5"
            title="open its logs"
          >
            <td className={td}>
              <Dot tone={serviceTone(s)} />
            </td>
            <td className={`${td} text-white/50`}>{s.host}</td>
            <td className={`${td} text-white/90`}>{s.service}</td>
            <td className={`${td} text-white/50`}>{s.tier ?? '—'}</td>
            <td className={td}>{pct(s.cpuStallPct)}</td>
            <td className={td}>{pct(s.memStallPct)}</td>
            <td className={td}>{pct(s.ioStallPct)}</td>
            <td className={td}>{pct(s.memOfLimitPct)}</td>
            <td className={td}>{s.oomKills ? <span className="text-bad">{s.oomKills}</span> : '0'}</td>
            <td className={`${td} max-w-md text-white/60`}>{s.dark ? 'silent' : s.incident ?? ''}</td>
            <td className={`${td} whitespace-nowrap`}>
              {s.flapping && <span className="mr-1 rounded bg-warn/15 px-1 text-warn">flapping</span>}
              {s.accepted && <span className="rounded bg-white/10 px-1 text-white/60" title={s.accepted}>accepted</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function AckForm({ service, onDone }: { service: string; onDone: () => void }) {
  const [kind, setKind] = useState<'expected' | 'noise'>('expected')
  const [days, setDays] = useState(7)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const submit = () =>
    addAck({ service, kind, days, reason })
      .then(onDone)
      .catch((e: Error) => setError(e.message))
  return (
    <div className="flex flex-wrap items-center gap-2 bg-white/5 px-2 py-2">
      <select value={kind} onChange={(e) => setKind(e.target.value as 'expected' | 'noise')} className="bg-panel-2 px-1 py-0.5">
        <option value="expected">expected</option>
        <option value="noise">noise</option>
      </select>
      <input
        type="number"
        min={1}
        max={30}
        value={days}
        onChange={(e) => setDays(Number(e.target.value))}
        className="w-14 bg-panel-2 px-1 py-0.5"
      />
      <span className="text-white/40">days</span>
      <input
        autoFocus
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && reason.trim() && submit()}
        placeholder="why: fixing it on Saturday"
        className="min-w-64 flex-1 bg-panel-2 px-1 py-0.5"
      />
      <button type="button" disabled={!reason.trim()} onClick={submit} className="rounded bg-good/20 px-2 py-0.5 text-good disabled:opacity-40">
        accept
      </button>
      {error && <span className="text-bad">{error}</span>}
    </div>
  )
}

function Incidents({ rows, onChanged }: { rows: OpsIncident[]; onChanged: () => void }) {
  const [acking, setAcking] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const lift = (service: string) =>
    liftAck(service)
      .then(onChanged)
      .catch((e: Error) => setError(e.message))
  return (
    <>
      {error && <p className="px-2 py-1 text-bad">{error}</p>}
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border">
            {['', 'status', 'sev', 'service', 'title', 'since', 'for', 'back', 'closed / accepted', ''].map((h, i) => (
              <th key={i} className={th}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((i) => {
            const service = `${i.host}:${i.service}`
            const tone = i.status === 'open' ? (i.severity === 'critical' ? 'bad' : 'warn') : 'muted'
            return [
              <tr key={i.id} className="border-b border-border/50">
                <td className={td}>
                  <Dot tone={tone} />
                </td>
                <td className={td}>{i.status}</td>
                <td className={td}>{i.severity}</td>
                <td className={`${td} whitespace-nowrap text-white/90`}>{service}</td>
                <td className={`${td} max-w-md text-white/60`}>{i.title}</td>
                <td className={`${td} whitespace-nowrap text-white/50`}>{when(i.firstSeen)}</td>
                <td className={td}>{i.status === 'resolved' ? '—' : ago(i.firstSeen)}</td>
                <td className={td}>{i.reopens || ''}</td>
                <td className={`${td} text-white/50`}>
                  {i.status === 'resolved' ? `${when(i.resolvedAt)} by ${i.resolvedBy ?? '—'}` : i.accepted ?? ''}
                </td>
                <td className={`${td} whitespace-nowrap`}>
                  {i.status === 'open' && (
                    <button type="button" onClick={() => setAcking(acking === i.id ? null : i.id)} className="rounded bg-white/10 px-2 text-white/70">
                      ack
                    </button>
                  )}
                  {i.status === 'accepted' && (
                    <button type="button" onClick={() => lift(service)} className="rounded bg-warn/15 px-2 text-warn">
                      lift
                    </button>
                  )}
                </td>
              </tr>,
              acking === i.id && (
                <tr key={`${i.id}-ack`}>
                  <td colSpan={10}>
                    <AckForm
                      service={service}
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
    </>
  )
}

function Agents({ data }: { data: OpsData }) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="border-b border-border">
          {['', 'agent', 'kind', 'last cycle', 'services', 'silent', 'problem'].map((h) => (
            <th key={h} className={th}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.agents.map((a) => (
          <tr key={a.host} className="border-b border-border/50">
            <td className={td}>
              <Dot tone={a.connected ? 'good' : 'bad'} />
            </td>
            <td className={`${td} text-white/90`}>{a.host}</td>
            <td className={`${td} text-white/50`}>{a.cluster ?? '—'}</td>
            <td className={td}>{a.lastMessage ? `${ago(a.lastMessage)} ago` : '—'}</td>
            <td className={td}>{a.services}</td>
            <td className={td}>{a.dark || ''}</td>
            <td className={`${td} text-bad`}>{a.error ?? ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function LogView({ services, service, onPick }: { services: string[]; service: string | null; onPick: (s: string) => void }) {
  // the answer remembers which service it is for: while it is for another one, a request is on its way
  const [answer, setAnswer] = useState<{ service: string; logs?: Logs; error?: string; at: number } | null>(null)
  const [asked, setAsked] = useState(0)
  useEffect(() => {
    if (!service) return
    let cancelled = false
    loadLogs(service)
      .then((logs) => !cancelled && setAnswer({ service, logs, at: Date.now() }))
      .catch((e: Error) => !cancelled && setAnswer({ service, error: e.message, at: Date.now() }))
    return () => {
      cancelled = true
    }
  }, [service, asked])
  const busy = !!service && (answer?.service !== service || answer.at < asked)
  const load = () => setAsked(Date.now())
  const logs = answer?.service === service ? answer.logs : null
  const error = answer?.service === service ? answer.error : null
  return (
    <div className="text-xs">
      <div className="flex flex-wrap items-center gap-2 px-2 py-2">
        <select value={service ?? ''} onChange={(e) => onPick(e.target.value)} className="min-w-72 bg-panel-2 px-1 py-0.5">
          <option value="" disabled>
            pick a service
          </option>
          {services.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <button type="button" onClick={load} disabled={!service || busy} className="rounded bg-white/10 px-2 py-0.5 disabled:opacity-40">
          {busy ? 'loading…' : 'refresh'}
        </button>
        {logs && <span className="text-white/35">{logs.selector} · last 6 h · newest first</span>}
      </div>
      {error && <p className="px-2 text-bad">{error}</p>}
      {logs && logs.lines.length === 0 && <p className="px-2 text-white/40">No lines in the last 6 hours.</p>}
      <pre className="scrollbar-thin max-h-[70vh] overflow-auto whitespace-pre-wrap break-all px-2 leading-relaxed">
        {logs?.lines.map((l, n) => (
          <div key={n}>
            <span className="text-white/30">{when(l.at)} </span>
            <span className={/error|fatal|fail|panic|exception/i.test(l.line) ? 'text-bad' : 'text-white/75'}>{l.line}</span>
          </div>
        ))}
      </pre>
    </div>
  )
}

export default function Ops() {
  const [data, setData] = useState<OpsData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('services')
  const [filter, setFilter] = useState('')
  const [logService, setLogService] = useState<string | null>(null)
  const [loadedAt, setLoadedAt] = useState<number | null>(null)
  const filterRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(
    () =>
      loadOps()
        .then((d) => {
          setData(d)
          setError(null)
          setLoadedAt(Date.now())
        })
        .catch((e: Error) => setError(e.message)),
    [],
  )

  useEffect(() => {
    document.title = 'Daedalus ops'
    refresh()
    const timer = window.setInterval(refresh, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [refresh])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement
      if (e.key === 'Escape') {
        setFilter('')
        filterRef.current?.blur()
      } else if (!typing && e.key === '/') {
        e.preventDefault()
        filterRef.current?.focus()
      } else if (!typing && ['1', '2', '3', '4'].includes(e.key)) {
        setTab(TABS[Number(e.key) - 1])
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const match = useCallback((...fields: (string | null | undefined)[]) => {
    const needle = filter.trim().toLowerCase()
    return !needle || fields.some((f) => f?.toLowerCase().includes(needle))
  }, [filter])

  const services = useMemo(() => (data?.services ?? []).filter((s) => match(s.host, s.service, s.incident)), [data, match])
  const incidents = useMemo(() => (data?.incidents ?? []).filter((i) => match(i.host, i.service, i.title)), [data, match])
  const serviceNames = useMemo(() => (data?.services ?? []).map((s) => `${s.host}:${s.service}`).sort(), [data])

  const openLogs = (service: string) => {
    setLogService(service)
    setTab('logs')
  }

  const counts: Record<Tab, string> = {
    services: data ? `${data.services.filter((s) => !s.ready && !s.accepted).length} down / ${data.services.length}` : '',
    incidents: data ? `${data.incidents.filter((i) => i.status === 'open').length} open` : '',
    agents: data ? `${data.agents.filter((a) => !a.connected).length} silent / ${data.agents.length}` : '',
    logs: '',
  }

  return (
    <div className="min-h-screen bg-bg font-mono text-white/80">
      <header className="flex flex-wrap items-center gap-3 border-b border-border px-3 py-2 text-xs">
        <span className="font-semibold text-white">daedalus ops</span>
        <nav className="flex gap-1">
          {TABS.map((t, n) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`rounded px-2 py-0.5 ${tab === t ? 'bg-white/15 text-white' : 'text-white/50 hover:text-white/80'}`}
            >
              <span className="text-white/30">{n + 1}</span> {t}
              {counts[t] && <span className="ml-1 text-white/35">{counts[t]}</span>}
            </button>
          ))}
        </nav>
        <input
          ref={filterRef}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="/ filter"
          className="w-48 bg-panel-2 px-2 py-0.5"
        />
        <span className="ml-auto text-white/35">{loadedAt ? `updated ${ago(new Date(loadedAt).toISOString())} ago` : 'loading…'}</span>
        <a href="./" className="text-white/50 hover:text-white">
          overview →
        </a>
      </header>
      {error && <p className="px-3 py-2 text-xs text-bad">Could not load: {error}</p>}
      <main className="overflow-x-auto px-1 py-1">
        {data && tab === 'services' && <Services rows={services} onLogs={openLogs} />}
        {data && tab === 'incidents' && <Incidents rows={incidents} onChanged={refresh} />}
        {data && tab === 'agents' && <Agents data={data} />}
        {tab === 'logs' && <LogView services={serviceNames} service={logService} onPick={setLogService} />}
      </main>
    </div>
  )
}
