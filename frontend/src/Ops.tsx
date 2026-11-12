import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { addAck, liftAck, loadLive, loadLogs, loadLogStats, loadOps, loadScenario, loadStream } from './api'
import { Ambient } from './components/Ambient'
import { OpsGraph } from './OpsGraph'
import { Glass, OpsOverview } from './OpsOverview'
import type { Logs, LogStats, Ops as OpsData, OpsIncident, OpsService, View } from './types'

// The admin screen: the fleet for the person who runs it, in the same glass as the overview screen. Everything
// is a way in, like k9s: click or Enter goes one level deeper, Esc comes back, / filters, j/k move.
// ?scenario=<id> shows a demo scenario, to look at the screen without agents.

const REFRESH_MS = 20_000
const TABS = ['overview', 'graph', 'services', 'incidents', 'agents', 'logs'] as const
type Tab = (typeof TABS)[number]
type Tone = 'good' | 'warn' | 'bad' | 'muted'
type LogSource = { label: string; load: () => Promise<Logs> }

const TONE: Record<Tone, string> = { good: 'text-good', warn: 'text-warn', bad: 'text-bad', muted: 'text-white/40' }
const DOT: Record<Tone, string> = { good: 'bg-good', warn: 'bg-warn', bad: 'bg-bad', muted: 'bg-white/30' }

const scenarioParam = new URLSearchParams(window.location.search).get('scenario') ?? undefined

const pct = (v?: number | null) => (v === null || v === undefined ? '—' : `${v < 10 ? v.toFixed(1) : Math.round(v)}%`)
const rps = (v?: number | null) => (v === null || v === undefined ? '—' : v >= 10 ? `${Math.round(v)}` : v >= 0.1 ? v.toFixed(1) : v > 0 ? '<0.1' : '0')
const clock = (iso?: string | null) => (iso ? iso.slice(5, 16).replace('T', ' ') : '—')
const keyOf = (s: { host: string; service: string }) => `${s.host}:${s.service}`

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

const serviceLogs = (s: OpsService): LogSource => ({ label: keyOf(s), load: () => loadLogs(keyOf(s)) })

// ----------------------------------------------------------------- building blocks ---

function Dot({ tone }: { tone: Tone }) {
  return <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${DOT[tone]}`} />
}

function Bar({ value, tone }: { value?: number | null; tone: Tone }) {
  const width = value === null || value === undefined ? 0 : Math.min(100, Math.max(2, value))
  return (
    <span className="inline-block h-1.5 w-24 rounded-full bg-white/10 align-middle">
      <span className={`block h-full rounded-full ${DOT[tone]}`} style={{ width: `${width}%` }} />
    </span>
  )
}

const th = 'px-2.5 py-1.5 text-left text-[11px] font-medium uppercase tracking-wide text-white/40'
const td = 'px-2.5 py-1.5 align-top'
const rowClass = (active: boolean) => `cursor-pointer border-b border-white/5 transition ${active ? 'bg-white/[0.09]' : 'hover:bg-white/[0.05]'}`

function Scroll({ children }: { children: ReactNode }) {
  return <div className="scrollbar-thin -mx-4 -mb-4 min-h-0 flex-1 overflow-auto px-2 pb-2">{children}</div>
}

// ------------------------------------------------------------------------- forms ---

function AckForm({ service, severity, onDone }: { service: string; severity?: string; onDone: () => void }) {
  const [kind, setKind] = useState<'expected' | 'noise'>('expected')
  const [days, setDays] = useState(7)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const submit = () =>
    addAck({ service, kind, days, reason, severity: severity as 'info' | 'warning' | 'critical' | undefined })
      .then(onDone)
      .catch((e: Error) => setError(e.message))
  const field = 'rounded-lg border border-white/10 bg-black/30 px-2 py-1'
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-white/10 bg-white/[0.04] p-2 text-sm">
      <select value={kind} onChange={(e) => setKind(e.target.value as 'expected' | 'noise')} className={field}>
        <option value="expected">expected</option>
        <option value="noise">noise</option>
      </select>
      <input type="number" min={1} max={30} value={days} onChange={(e) => setDays(Number(e.target.value))} className={`${field} w-16`} />
      <span className="text-white/40">days</span>
      <input
        autoFocus
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        onKeyDown={(e) => {
          e.stopPropagation()
          if (e.key === 'Enter' && reason.trim()) submit()
        }}
        placeholder="why"
        className={`${field} min-w-40 flex-1`}
      />
      <button type="button" disabled={!reason.trim()} onClick={submit} className="rounded-full bg-good/20 px-3 py-1 text-good disabled:opacity-40">
        accept
      </button>
      {error && <span className="text-bad">{error}</span>}
    </div>
  )
}

function LogLines({ source, lines = 40, tall = false }: { source: LogSource; lines?: number; tall?: boolean }) {
  const [answer, setAnswer] = useState<{ label: string; logs?: Logs; error?: string; at: number } | null>(null)
  const [asked, setAsked] = useState(0)
  const { label, load } = source
  useEffect(() => {
    let cancelled = false
    load()
      .then((logs) => !cancelled && setAnswer({ label, logs, at: Date.now() }))
      .catch((e: Error) => !cancelled && setAnswer({ label, error: e.message, at: Date.now() }))
    return () => {
      cancelled = true
    }
    // the source is identified by its label; a new closure for the same label is the same source
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [label, asked])
  const mine = answer?.label === label ? answer : null
  const busy = !mine || mine.at < asked
  return (
    <div className="text-xs">
      <div className="flex items-center gap-2 text-white/40">
        <button type="button" onClick={() => setAsked(Date.now())} className="rounded-full bg-white/10 px-2.5 py-0.5 hover:bg-white/20">
          {busy ? 'loading…' : 'refresh'}
        </button>
        <span className="truncate font-mono">{mine?.logs ? `${mine.logs.selector} · last 6 h · newest first` : ''}</span>
      </div>
      {mine?.error && <p className="mt-1 text-bad">{mine.error}</p>}
      {mine?.logs && mine.logs.lines.length === 0 && <p className="mt-1 text-white/40">no lines in the last 6 hours</p>}
      <pre className={`scrollbar-thin mt-2 overflow-auto whitespace-pre-wrap break-all rounded-xl bg-black/30 p-2 font-mono leading-snug ${tall ? 'max-h-[calc(100vh-14rem)]' : 'max-h-72'}`}>
        {mine?.logs?.lines.slice(0, lines).map((l, n) => (
          <div key={n}>
            <span className="text-white/30">{clock(l.at)} </span>
            <span className={/error|fatal|fail|panic|exception|refused|denied/i.test(l.line) ? 'text-bad' : 'text-white/75'}>{l.line}</span>
          </div>
        ))}
      </pre>
    </div>
  )
}

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

function Detail({ s, data, onChanged, onLogs }: { s: OpsService; data: OpsData; onChanged: () => void; onLogs: () => void }) {
  const name = keyOf(s)
  const history = data.incidents.filter((i) => i.host === s.host && i.service === s.service)
  const open = history.find((i) => i.status === 'open')
  const accepted = data.acks.find((a) => a.service === name)
  const calledBy = data.services.filter((o) => o.host === s.host && o.calls.includes(s.service))
  const [acking, setAcking] = useState(false)
  const tone = serviceTone(s)
  const stall = (label: string, v?: number | null) => (
    <div className="flex items-center gap-3">
      <span className="w-24 text-white/45">{label}</span>
      <Bar value={v} tone={(v ?? 0) >= 10 ? 'bad' : (v ?? 0) >= 5 ? 'warn' : 'good'} />
      <span className="tabular-nums">{pct(v)}</span>
    </div>
  )
  return (
    <div className="space-y-4 text-sm">
      <div>
        <div className="flex items-center gap-2">
          <Dot tone={tone} />
          <span className="text-lg font-semibold text-white">{s.service}</span>
          <span className={TONE[tone]}>{stateWord(s)}</span>
        </div>
        <div className="text-white/45">
          {s.host} · {s.cluster ?? '—'} · tier {s.tier ?? '—'}
          {s.tier === 1 && ' (user path)'}
        </div>
      </div>

      {s.urls.length > 0 && (
        <div className="space-y-1 text-xs">
          <div className="text-white/40">public addresses, from the internet</div>
          {s.urls.map((url) => {
            const site = data.sites.find((x) => x.url === url)
            return (
              <div key={url} className="flex items-center gap-2">
                <Dot tone={!site ? 'muted' : site.ok ? 'good' : 'bad'} />
                <a href={url} target="_blank" rel="noreferrer" className="truncate text-white/80 hover:text-white">
                  {url}
                </a>
                <span className={`ml-auto shrink-0 ${site && !site.ok ? 'text-bad' : 'text-white/40'}`}>{site?.detail ?? 'not checked yet'}</span>
              </div>
            )
          })}
        </div>
      )}

      {s.reqPerSec !== null && s.reqPerSec !== undefined && (
        <div className="grid grid-cols-3 gap-2">
          {[
            ['req/s', rps(s.reqPerSec), 'text-white'],
            ['5xx', pct(s.errPct), (s.errPct ?? 0) >= 5 ? 'text-bad' : (s.errPct ?? 0) >= 0.5 ? 'text-warn' : 'text-white'],
            ['p99', s.p99Ms !== null && s.p99Ms !== undefined ? `${Math.round(s.p99Ms)} ms` : '—', (s.p99Ms ?? 0) >= 1000 ? 'text-warn' : 'text-white'],
          ].map(([label, value, tone]) => (
            <div key={label} className="rounded-2xl border border-white/10 bg-white/[0.03] px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-white/45">{label}</div>
              <div className={`text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
            </div>
          ))}
          <p className="col-span-3 text-[11px] text-white/35">users&apos; traffic through Traefik, last 5 minutes</p>
        </div>
      )}

      <div className="space-y-1">
        {stall('cpu stall', s.cpuStallPct)}
        {stall('mem stall', s.memStallPct)}
        {stall('io stall', s.ioStallPct)}
        <div className="flex items-center gap-3">
          <span className="w-24 text-white/45">mem / limit</span>
          <Bar value={s.memOfLimitPct} tone={(s.memOfLimitPct ?? 0) >= 90 ? 'bad' : 'good'} />
          <span className="tabular-nums">{pct(s.memOfLimitPct)}</span>
          <span className="ml-2 text-white/45">oom</span>
          <span className={s.oomKills ? 'text-bad' : ''}>{s.oomKills ?? 0}</span>
        </div>
      </div>

      {(s.incident || accepted) && (
        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-3">
          {s.incident && <p className={s.severity === 'critical' ? 'text-bad' : 'text-warn'}>{s.incident}</p>}
          {open && (
            <p className="text-xs text-white/45">
              open {ago(open.firstSeen)} · since {clock(open.firstSeen)}
              {open.reopens > 0 && ` · back ${open.reopens}× in 6 h`}
            </p>
          )}
          {accepted && (
            <p className="text-white/70">
              <span className="text-white/40">accepted as {accepted.kind} until {accepted.until.slice(0, 10)}: </span>
              {accepted.reason}
            </p>
          )}
          <div className="mt-2 flex gap-2">
            {open && !acking && (
              <button type="button" onClick={() => setAcking(true)} className="rounded-full bg-white/10 px-3 py-0.5 hover:bg-white/20">
                ack
              </button>
            )}
            {accepted && (
              <button type="button" onClick={() => liftAck(name).then(onChanged)} className="rounded-full bg-warn/15 px-3 py-0.5 text-warn">
                lift
              </button>
            )}
          </div>
          {acking && (
            <div className="mt-2">
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

      {(s.calls.length > 0 || calledBy.length > 0) && (
        <div className="grid grid-cols-2 gap-3 text-xs">
          <div>
            <div className="text-white/40">calls</div>
            {s.calls.map((c) => <div key={c}>→ {c}</div>)}
          </div>
          <div>
            <div className="text-white/40">called by</div>
            {calledBy.map((c) => <div key={c.service}>← {c.service}</div>)}
          </div>
        </div>
      )}

      {history.length > 0 && (
        <div className="text-xs">
          <div className="text-white/40">last day</div>
          {history.map((i) => (
            <div key={i.id} className="text-white/70">
              <span className="text-white/35">{clock(i.firstSeen)} </span>
              {i.status}
              {i.resolvedAt && <span className="text-white/35"> → {clock(i.resolvedAt)} by {i.resolvedBy}</span>}
            </div>
          ))}
        </div>
      )}

      <div>
        <div className="mb-1 flex justify-between text-xs text-white/40">
          <span>logs</span>
          <button type="button" onClick={onLogs} className="hover:text-white">
            full screen · Enter →
          </button>
        </div>
        <LogLines source={serviceLogs(s)} lines={30} />
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
    <div className="grid h-full min-h-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      <Glass title={`services (${data.services.length})`} right="click or j/k · Enter logs" className="flex min-h-0 flex-col">
        <div className="mb-2 flex flex-wrap gap-2">
          {FILTERS.map((f) => {
            const n = data.services.filter((s) => matches(s, f)).length
            const tone: Tone = f === 'healthy' ? 'good' : f === 'down' ? 'bad' : f === 'flapping' ? 'warn' : 'muted'
            return (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs transition ${filter === f ? 'bg-white/15 text-white' : 'bg-white/[0.04] text-white/50 hover:text-white/80'}`}
              >
                {f !== 'all' && <Dot tone={tone} />}
                {f} <span className="tabular-nums">{n}</span>
              </button>
            )
          })}
        </div>
        <Scroll>
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-[#12121b]/90 backdrop-blur">
              <tr>
                {['', 'service', 'host', 'tier', 'req/s', '5xx', 'cpu', 'mem', 'io', 'mem/lim', 'state'].map((h) => (
                  <th key={h} className={th}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((s) => {
                const tone = serviceTone(s)
                return (
                  <tr key={keyOf(s)} onClick={() => onSelect(s)} onDoubleClick={onLogs} className={rowClass(!!selected && keyOf(selected) === keyOf(s))}>
                    <td className={td}>
                      <Dot tone={tone} />
                    </td>
                    <td className={`${td} text-white/90`}>{s.service}</td>
                    <td className={`${td} text-white/50`}>{s.host}</td>
                    <td className={`${td} text-white/40`}>{s.tier ?? '—'}</td>
                    <td className={`${td} tabular-nums text-white/70`}>{rps(s.reqPerSec)}</td>
                    <td className={`${td} tabular-nums ${(s.errPct ?? 0) >= 5 ? 'text-bad' : (s.errPct ?? 0) >= 0.5 ? 'text-warn' : 'text-white/70'}`}>
                      {s.reqPerSec === null || s.reqPerSec === undefined ? '—' : pct(s.errPct)}
                    </td>
                    <td className={`${td} tabular-nums ${(s.cpuStallPct ?? 0) >= 5 ? 'text-warn' : 'text-white/70'}`}>{pct(s.cpuStallPct)}</td>
                    <td className={`${td} tabular-nums ${(s.memStallPct ?? 0) >= 5 ? 'text-warn' : 'text-white/70'}`}>{pct(s.memStallPct)}</td>
                    <td className={`${td} tabular-nums ${(s.ioStallPct ?? 0) >= 5 ? 'text-warn' : 'text-white/70'}`}>{pct(s.ioStallPct)}</td>
                    <td className={`${td} tabular-nums ${(s.memOfLimitPct ?? 0) >= 90 ? 'text-bad' : 'text-white/70'}`}>{pct(s.memOfLimitPct)}</td>
                    <td className={`${td} ${TONE[tone]}`}>{stateWord(s)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </Scroll>
      </Glass>
      <Glass title={selected ? 'service' : 'detail'} right={selected?.host} className="min-h-0 overflow-auto">
        {selected ? (
          <Detail key={keyOf(selected)} s={selected} data={data} onChanged={onChanged} onLogs={onLogs} />
        ) : (
          <p className="text-white/40">pick a service on the left</p>
        )}
      </Glass>
    </div>
  )
}

// ---------------------------------------------------------------------- incidents ---

function Incidents({ rows, cursor, onCursor, onOpen, onChanged }: {
  rows: OpsIncident[]
  cursor: number
  onCursor: (n: number) => void
  onOpen: (i: OpsIncident) => void
  onChanged: () => void
}) {
  const [acking, setAcking] = useState<string | null>(null)
  const open = rows.filter((i) => i.status === 'open').length
  return (
    <Glass title={`incidents (${rows.length})`} right={`${open} open · last 24 h · Enter opens the service`} className="flex h-full min-h-0 flex-col">
      <Scroll>
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-[#12121b]/90 backdrop-blur">
            <tr>
              {['sev', 'status', 'service', 'what', 'since', 'for', 'back', 'closed / accepted', ''].map((h, n) => (
                <th key={n} className={th}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((i, n) => {
              const service = keyOf(i)
              const sev = i.status !== 'open' ? 'text-white/35' : i.severity === 'critical' ? 'text-bad' : 'text-warn'
              return [
                <tr key={i.id} onClick={() => onCursor(n)} onDoubleClick={() => onOpen(i)} className={rowClass(n === cursor)}>
                  <td className={`${td} ${sev}`}>{i.severity === 'critical' ? 'CRIT' : i.severity === 'warning' ? 'WARN' : 'INFO'}</td>
                  <td className={`${td} ${i.status === 'open' ? 'text-bad' : i.status === 'accepted' ? 'text-white/40' : 'text-good'}`}>{i.status}</td>
                  <td className={`${td} whitespace-nowrap`}>
                    <span className="text-white/45">{i.host}:</span>
                    <span className="text-white/90">{i.service}</span>
                  </td>
                  <td className={`${td} text-white/65`}>{i.title}</td>
                  <td className={`${td} whitespace-nowrap text-white/40`}>{clock(i.firstSeen)}</td>
                  <td className={`${td} tabular-nums`}>{i.status === 'resolved' ? '—' : ago(i.firstSeen)}</td>
                  <td className={`${td} tabular-nums ${i.reopens >= 5 ? 'text-warn' : ''}`}>{i.reopens || ''}</td>
                  <td className={`${td} text-white/45`}>{i.status === 'resolved' ? `${clock(i.resolvedAt)} by ${i.resolvedBy ?? '—'}` : i.accepted ?? ''}</td>
                  <td className={`${td} whitespace-nowrap`} onClick={(e) => e.stopPropagation()}>
                    <button type="button" onClick={() => onOpen(i)} className="mr-1 rounded-full bg-white/5 px-2.5 py-0.5 text-xs hover:bg-white/15">
                      open
                    </button>
                    {i.status === 'open' && (
                      <button type="button" onClick={() => setAcking(acking === i.id ? null : i.id)} className="rounded-full bg-white/10 px-2.5 py-0.5 text-xs hover:bg-white/20">
                        ack
                      </button>
                    )}
                    {i.status === 'accepted' && (
                      <button type="button" onClick={() => liftAck(service).then(onChanged)} className="rounded-full bg-warn/15 px-2.5 py-0.5 text-xs text-warn">
                        lift
                      </button>
                    )}
                  </td>
                </tr>,
                acking === i.id && (
                  <tr key={`${i.id}-ack`}>
                    <td colSpan={9} className="px-2 py-1.5">
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
      </Scroll>
    </Glass>
  )
}

// ------------------------------------------------------------------------- agents ---

function Agents({ data, onHost }: { data: OpsData; onHost: (host: string) => void }) {
  return (
    <Glass title={`agents (${data.agents.length})`} right="one per host and per k3s cluster · click shows its services" className="h-full">
      <table className="w-full text-sm">
        <thead>
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
            <tr key={a.host} onClick={() => onHost(a.host)} className={rowClass(false)}>
              <td className={td}>
                <Dot tone={a.connected ? 'good' : 'bad'} />
              </td>
              <td className={`${td} text-white/90`}>{a.host}</td>
              <td className={`${td} text-white/45`}>{a.cluster ?? '—'}</td>
              <td className={`${td} tabular-nums`}>{a.lastMessage ? `${ago(a.lastMessage)} ago` : '—'}</td>
              <td className={`${td} tabular-nums`}>{a.services}</td>
              <td className={`${td} tabular-nums ${a.dark ? 'text-warn' : ''}`}>{a.dark || ''}</td>
              <td className={`${td} text-bad`}>{a.error ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Glass>
  )
}

// --------------------------------------------------------------------------- page ---

export default function Ops() {
  const [data, setData] = useState<OpsData | null>(null)
  const [view, setView] = useState<View | null>(null)
  const [stats, setStats] = useState<LogStats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [trail, setTrail] = useState<Tab[]>(['overview'])
  const [search, setSearch] = useState('')
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [incidentCursor, setIncidentCursor] = useState(0)
  const [logSource, setLogSource] = useState<LogSource | null>(null)
  const [loadedAt, setLoadedAt] = useState<number | null>(null)
  const [, setTick] = useState(0)
  const searchRef = useRef<HTMLInputElement>(null)
  const tab = trail[trail.length - 1]

  // k9s-style: going somewhere pushes, Esc pops back to where you came from
  const go = useCallback((next: Tab) => setTrail((t) => (t[t.length - 1] === next ? t : [...t.slice(-9), next])), [])
  const back = useCallback(() => setTrail((t) => (t.length > 1 ? t.slice(0, -1) : t)), [])

  const refresh = useCallback(() => {
    loadOps(scenarioParam)
      .then((d) => {
        setData(d)
        setError(null)
        setLoadedAt(Date.now())
      })
      .catch((e: Error) => setError(e.message))
    ;(scenarioParam ? loadScenario(scenarioParam) : loadLive()).then(setView).catch(() => setView(null))
    loadLogStats(scenarioParam).then(setStats).catch(() => setStats(null))
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
  const selected = services.find((s) => keyOf(s) === selectedKey) ?? services[0] ?? null
  const byKey = useMemo(() => new Map((data?.services ?? []).map((s) => [keyOf(s), s])), [data])

  const openService = useCallback(
    (s: OpsService) => {
      setSelectedKey(keyOf(s))
      go('services')
    },
    [go],
  )
  const openLogs = useCallback(
    (source: LogSource) => {
      setLogSource(source)
      go('logs')
    },
    [go],
  )
  const openIncident = useCallback(
    (i: OpsIncident) => {
      const s = byKey.get(keyOf(i))
      if (s) openService(s)
    },
    [byKey, openService],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement
      if (e.key === 'Escape') {
        if (search || typing) {
          setSearch('')
          searchRef.current?.blur()
        } else back()
        return
      }
      if (typing) return
      const down = e.key === 'j' || e.key === 'ArrowDown'
      const up = e.key === 'k' || e.key === 'ArrowUp'
      if (e.key === '/') {
        e.preventDefault()
        searchRef.current?.focus()
      } else if (/^[1-6]$/.test(e.key)) {
        go(TABS[Number(e.key) - 1])
      } else if (tab === 'services' && (down || up)) {
        e.preventDefault()
        const index = services.findIndex((s) => s === selected)
        const next = services[Math.max(0, Math.min(services.length - 1, index + (down ? 1 : -1)))]
        if (next) setSelectedKey(keyOf(next))
      } else if (tab === 'services' && (e.key === 'Enter' || e.key === 'l') && selected) {
        openLogs(serviceLogs(selected))
      } else if (tab === 'incidents' && (down || up)) {
        e.preventDefault()
        setIncidentCursor((n) => Math.max(0, Math.min(incidents.length - 1, n + (down ? 1 : -1))))
      } else if (tab === 'incidents' && e.key === 'Enter' && incidents[incidentCursor]) {
        openIncident(incidents[incidentCursor])
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [tab, services, selected, incidents, incidentCursor, search, go, back, openLogs, openIncident])

  const keys: [string, string][] = [
    ['1', 'overview'],
    ['2', 'graph'],
    ['3', 'services'],
    ['4', 'incidents'],
    ['5', 'agents'],
    ['6', 'logs'],
    ['/', 'filter'],
    ['esc', trail.length > 1 ? 'back' : 'clear'],
  ]
  const open = data?.incidents.filter((i) => i.status === 'open').length ?? 0

  return (
    <div className="flex h-screen flex-col text-white/80">
      <Ambient level={view?.decision.level} />
      <header className="flex flex-wrap items-center gap-3 px-5 pb-2 pt-4">
        <span className="text-lg font-bold tracking-tight text-white">Infra Health · ops</span>
        {scenarioParam ? (
          <span className="glass-pill px-3 py-0.5 text-xs text-warn">demo · {scenarioParam}</span>
        ) : (
          <span className="glass-pill flex items-center gap-1.5 px-3 py-0.5 text-xs">
            <Dot tone={error ? 'bad' : 'good'} /> live
          </span>
        )}
        <span className="text-xs text-white/40">{data ? `${data.agents.length} agents · ${data.services.length} services · ${open} open` : ''}</span>
        <input
          ref={searchRef}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="/ filter"
          className="glass-pill ml-2 w-56 px-3 py-1 text-sm outline-none placeholder:text-white/35"
        />
        <span className="ml-auto text-xs text-white/35">{loadedAt ? `updated ${ago(new Date(loadedAt).toISOString())} ago` : 'loading…'}</span>
        <a href="./" className="glass-pill px-3 py-1 text-xs text-white/60 hover:text-white">
          overview screen →
        </a>
      </header>

      <nav className="flex flex-wrap gap-1.5 px-5 pb-3">
        {TABS.map((t, n) => (
          <button
            key={t}
            type="button"
            onClick={() => go(t)}
            className={`rounded-full px-3.5 py-1 text-sm transition ${tab === t ? 'bg-white/20 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.25)]' : 'text-white/50 hover:bg-white/10 hover:text-white/80'}`}
          >
            <span className="mr-1 text-white/30">{n + 1}</span>
            {t}
          </button>
        ))}
      </nav>

      {error && <p className="px-5 pb-2 text-sm text-bad">could not load: {error}</p>}

      <main className={`min-h-0 flex-1 px-5 pb-3 ${tab === 'overview' ? 'scrollbar-thin overflow-auto' : ''}`}>
        {data && tab === 'overview' && (
          <OpsOverview
            data={data}
            view={view}
            stats={stats}
            onPick={openService}
            onGraph={() => go('graph')}
            onIncidents={() => go('incidents')}
            onStream={(host, service) => openLogs({ label: `${host} · ${service}`, load: () => loadStream(host, service) })}
          />
        )}
        {data && tab === 'graph' && <OpsGraph data={data} onDetails={openService} />}
        {data && tab === 'services' && (
          <Services
            data={data}
            rows={services}
            selected={selected}
            onSelect={(s) => setSelectedKey(keyOf(s))}
            onChanged={refresh}
            onLogs={() => selected && openLogs(serviceLogs(selected))}
          />
        )}
        {data && tab === 'incidents' && (
          <Incidents rows={incidents} cursor={incidentCursor} onCursor={setIncidentCursor} onOpen={openIncident} onChanged={refresh} />
        )}
        {data && tab === 'agents' && (
          <Agents
            data={data}
            onHost={(host) => {
              setSearch(host)
              go('services')
            }}
          />
        )}
        {tab === 'logs' && (
          <Glass title={logSource ? `logs · ${logSource.label}` : 'logs'} right="Esc back" className="flex h-full min-h-0 flex-col">
            <select
              value={logSource?.label ?? ''}
              onChange={(e) => {
                const s = byKey.get(e.target.value)
                if (s) setLogSource(serviceLogs(s))
              }}
              className="mb-2 w-full max-w-md rounded-full border border-white/10 bg-black/30 px-3 py-1 text-sm"
            >
              <option value="" disabled>
                pick a service
              </option>
              {[...byKey.keys()].sort().map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
            {logSource && <LogLines source={logSource} lines={500} tall />}
          </Glass>
        )}
      </main>

      <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 pb-3 text-xs">
        {keys.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => (/^[1-6]$/.test(key) ? go(TABS[Number(key) - 1]) : key === 'esc' ? back() : searchRef.current?.focus())}
            className="flex items-center gap-1.5"
          >
            <kbd className={`rounded-md px-1.5 py-0.5 font-mono ${TABS[Number(key) - 1] === tab ? 'bg-white/25 text-white' : 'bg-white/10 text-white/60'}`}>{key}</kbd>
            <span className={TABS[Number(key) - 1] === tab ? 'text-white' : 'text-white/45'}>{label}</span>
          </button>
        ))}
      </footer>
    </div>
  )
}
