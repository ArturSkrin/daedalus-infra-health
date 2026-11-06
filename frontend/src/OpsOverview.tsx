import type { Ops, OpsService, View } from './types'

// The first tab of /ops, drawn the way the Triage TUI draws a tenant: a score ring with the day around it,
// four coloured goal cards, what is about to break, signals over the day, and the fleet as a map of squares.
// Every number comes from the same view model and ops snapshot the rest of the tracker reads.

const RING = { users: '#22d3ee', forecast: '#e879f9', trust: '#a78bfa', day: '#fbbf24' } as const
const CARD: Record<string, string> = {
  users: 'from-[#0e7490]/70 to-[#155e75]/40',
  forecast: 'from-[#a21caf]/60 to-[#86198f]/30',
  trust: 'from-[#6d28d9]/60 to-[#5b21b6]/30',
  day: 'from-[#b45309]/60 to-[#92400e]/30',
}
const LEVEL: Record<string, string> = { good: '#7ee787', warn: '#f0b429', bad: '#ff6b6b', muted: '#8b87a6' }

function Frame({ title, right, children, className = '' }: { title: string; right?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`relative rounded-md border border-[#2f2a52] bg-[#0f0d1c]/90 px-3 pb-3 pt-4 ${className}`}>
      <span className="absolute -top-2.5 left-3 bg-[#09080f] px-1.5 text-[#e879f9]">{title}</span>
      {right && <span className="absolute -top-2.5 right-3 bg-[#09080f] px-1.5 text-[#8b87a6]">{right}</span>}
      {children}
    </section>
  )
}

// colour of a slice of the day by its error share: the thresholds of "Users now" (0.5 % degraded, 5 % broken)
const errorColor = (share: number) => (share >= 5 ? '#ef4444' : share >= 0.5 ? '#fb923c' : share > 0 ? '#facc15' : '#22d3ee')

function ScoreRing({ view, history }: { view: View; history: Ops['history'] }) {
  const size = 300
  const c = size / 2
  const rings = view.indicators.map((i, n) => ({ id: i.id, value: i.ring, r: 92 - n * 15 }))
  const score = Math.round((100 * view.indicators.reduce((sum, i) => sum + i.ring, 0)) / Math.max(1, view.indicators.length))
  // the day around the score, 96 slices of 15 minutes: bar length is traffic, colour is the share of it that failed
  const slices = 96
  const step = Math.max(1, Math.ceil(history.length / slices))
  const bars = Array.from({ length: Math.ceil(history.length / step) }, (_, i) => {
    const chunk = history.slice(i * step, (i + 1) * step)
    const requests = chunk.reduce((n, b) => n + b.requests, 0)
    const errors = chunk.reduce((n, b) => n + b.errors, 0)
    return { requests, share: requests ? (100 * errors) / requests : 0 }
  })
  const peak = Math.max(...bars.map((b) => b.requests), 0)
  const level = LEVEL[view.decision.level]
  return (
    <div className="flex flex-col items-center">
      <svg viewBox={`0 0 ${size} ${size}`} className="h-72 w-72">
        {Array.from({ length: slices }, (_, t) => {
          const bar = bars[t - (slices - bars.length)]         // the newest slice sits just left of twelve o'clock
          const angle = (t / slices) * 2 * Math.PI - Math.PI / 2
          const r1 = 104
          const r2 = r1 + 3 + (bar && peak > 0 ? (bar.requests / peak) * 38 : 0)
          return (
            <line
              key={t}
              x1={c + r1 * Math.cos(angle)}
              y1={c + r1 * Math.sin(angle)}
              x2={c + r2 * Math.cos(angle)}
              y2={c + r2 * Math.sin(angle)}
              stroke={bar ? errorColor(bar.share) : '#2f2a52'}
              strokeOpacity={bar ? 0.95 : 0.6}
              strokeWidth={3.2}
              strokeLinecap="round"
            >
              {bar && <title>{`${Math.round(bar.requests)} requests, ${bar.share.toFixed(2)}% failed`}</title>}
            </line>
          )
        })}
        <line x1={c} y1={c - 102} x2={c} y2={c - 150} stroke="#f5f3ff" strokeOpacity={0.7} strokeWidth={1.5} />
        {rings.map(({ id, value, r }) => {
          const length = 2 * Math.PI * r
          return (
            <g key={id} transform={`rotate(-90 ${c} ${c})`}>
              <circle cx={c} cy={c} r={r} fill="none" stroke={RING[id]} strokeOpacity={0.15} strokeWidth={10} />
              <circle
                cx={c}
                cy={c}
                r={r}
                fill="none"
                stroke={RING[id]}
                strokeWidth={10}
                strokeLinecap="round"
                strokeDasharray={`${Math.max(0.01, value) * length} ${length}`}
              />
            </g>
          )
        })}
        <text x={c} y={c + 4} textAnchor="middle" fill="#f5f3ff" fontSize="34" fontWeight="700">
          {score}%
        </text>
        <text x={c} y={c + 24} textAnchor="middle" fill="#8b87a6" fontSize="10">
          fleet score
        </text>
      </svg>
      <div className="mt-1 text-lg font-bold tracking-[0.2em]" style={{ color: level }}>
        {view.decision.word}
      </div>
      <p className="mt-1 max-w-sm text-center text-[#b9b4d6]">{view.decision.reason}</p>
      <div className="mt-2 flex gap-3 text-[10px] text-[#6e6a86]">
        <span>around: last 24 h, height = traffic</span>
        {[['#22d3ee', 'no errors'], ['#facc15', '< 0.5%'], ['#fb923c', '< 5%'], ['#ef4444', '≥ 5%']].map(([color, label]) => (
          <span key={label} className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: color }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  )
}

function Goals({ view }: { view: View }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {view.indicators.map((i) => (
        <div key={i.id} className={`rounded-md bg-gradient-to-br ${CARD[i.id]} px-3 py-2.5`}>
          <div className="flex items-center gap-1.5 text-[11px] text-white/80">
            <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: RING[i.id as keyof typeof RING] }} />
            {i.title}
          </div>
          {/* the card keeps its goal colour; the word turns red or amber when that goal is not met */}
          <div className="mt-1 text-2xl font-bold" style={{ color: i.level === 'bad' ? '#fca5a5' : i.level === 'warn' ? '#fde68a' : '#ffffff' }}>
            {i.label}
          </div>
          <div className="mt-0.5 line-clamp-2 min-h-[2.5em] text-[11px] text-white/70">{i.caption}</div>
          <div className="mt-2 h-1 rounded-full bg-black/30">
            <div className="h-full rounded-full" style={{ width: `${Math.round(i.ring * 100)}%`, backgroundColor: RING[i.id as keyof typeof RING] }} />
          </div>
        </div>
      ))}
    </div>
  )
}

function risk(s: OpsService): number {
  if (s.accepted || s.dark) return 0
  if (!s.ready) return s.flapping ? 80 : 100
  const stall = Math.max(s.cpuStallPct ?? 0, s.memStallPct ?? 0, s.ioStallPct ?? 0)
  return Math.max(stall * 5, (s.memOfLimitPct ?? 0) >= 80 ? s.memOfLimitPct ?? 0 : 0, s.incident ? 50 : 0)
}

function AboutToBreak({ data }: { data: Ops }) {
  const ranked = data.services
    .map((s) => ({ s, r: Math.min(100, Math.round(risk(s))) }))
    .filter((x) => x.r >= 20)
    .sort((a, b) => b.r - a.r)
    .slice(0, 6)
  if (ranked.length === 0) return <p className="text-[#7ee787]">✓ nothing is close to breaking</p>
  return (
    <div className="flex flex-wrap gap-3">
      {ranked.map(({ s, r }) => {
        const color = r >= 90 ? '#ef4444' : r >= 60 ? '#f97316' : '#f59e0b'
        const word = !s.ready ? (s.flapping ? 'flap' : 'down') : `${r}%`
        return (
          <div key={`${s.host}:${s.service}`} className="flex w-20 flex-col items-center" title={`${s.host}:${s.service}${s.incident ? ` — ${s.incident}` : ''}`}>
            <div
              className="flex h-16 w-16 items-center justify-center rounded-full text-sm font-bold text-white"
              style={{ background: `radial-gradient(circle at 35% 30%, ${color}, ${color}99 60%, ${color}55)`, boxShadow: `0 0 18px ${color}66` }}
            >
              {word}
            </div>
            <span className="mt-1 w-full truncate text-center text-[10px] text-[#b9b4d6]">{s.service}</span>
            <span className="w-full truncate text-center text-[10px] text-[#7fdbff]">{s.host}</span>
          </div>
        )
      })}
    </div>
  )
}

function buckets(times: (string | null | undefined)[], hours = 24): number[] {
  const out = Array<number>(hours).fill(0)
  const now = Date.now()
  for (const t of times) {
    if (!t) continue
    const age = (now - Date.parse(t)) / 3_600_000
    if (age >= 0 && age < hours) out[hours - 1 - Math.floor(age)] += 1
  }
  return out
}

function squeeze(values: number[], width: number): number[] {
  const step = Math.max(1, Math.ceil(values.length / width))
  return Array.from({ length: Math.ceil(values.length / step) }, (_, i) => Math.max(...values.slice(i * step, (i + 1) * step)))
}

function Signals({ data, view }: { data: Ops; view: View | null }) {
  const errors = view?.indicators.find((i) => i.id === 'day')?.drill?.sparkline ?? []
  const rows = [
    { label: 'request errors', color: '#ff6b6b', values: squeeze(errors, 48), total: `${errors.length ? Math.max(...errors).toFixed(2) : 0}% peak` },
    { label: 'incidents opened', color: '#fb923c', values: buckets(data.incidents.map((i) => i.firstSeen)), total: String(data.incidents.length) },
    { label: 'state changes', color: '#a78bfa', values: buckets((view?.journal ?? []).map((e) => e.at)), total: String(view?.journal.length ?? 0) },
    { label: 'resolved by agent', color: '#22d3ee', values: buckets(data.incidents.map((i) => (i.resolvedBy === 'agent' ? i.resolvedAt : null))),
      total: String(data.incidents.filter((i) => i.resolvedBy === 'agent').length) },
  ]
  return (
    <div className="space-y-2">
      {rows.map((row) => {
        const top = Math.max(...row.values, 0)
        return (
          <div key={row.label} className="grid grid-cols-[9rem_6rem_1fr] items-end gap-2">
            <span style={{ color: row.color }}>{row.label}</span>
            <span className="text-right text-[#d8d4ea]">{row.total}</span>
            <div className="flex h-6 items-end gap-[2px]">
              {row.values.map((v, n) => (
                <div
                  key={n}
                  className="flex-1 rounded-t-[1px]"
                  style={{ height: top > 0 && v > 0 ? `${Math.max(12, (v / top) * 100)}%` : '2px', backgroundColor: row.color, opacity: v > 0 ? 0.9 : 0.18 }}
                />
              ))}
            </div>
          </div>
        )
      })}
      <div className="grid grid-cols-[9rem_6rem_1fr] gap-2 text-[10px] text-[#6e6a86]">
        <span />
        <span />
        <span className="flex justify-between">
          <span>24 h ago</span>
          <span>now</span>
        </span>
      </div>
    </div>
  )
}

const SQUARE: Record<string, string> = { good: '#22c55e', warn: '#f59e0b', bad: '#ef4444', muted: '#4b4766' }

function tone(s: OpsService): string {
  if (s.dark || s.accepted) return 'muted'
  if (!s.ready) return s.flapping ? 'warn' : 'bad'
  return s.incident ? 'warn' : 'good'
}

function FleetMap({ data, onPick }: { data: Ops; onPick: (s: OpsService) => void }) {
  const hosts = data.agents.map((a) => ({ agent: a, services: data.services.filter((s) => s.host === a.host) }))
  return (
    <div className="flex flex-wrap gap-2">
      {hosts.map(({ agent, services }) => {
        const down = services.filter((s) => tone(s) === 'bad').length
        return (
          <div key={agent.host} className="min-w-40 flex-1 rounded-sm border border-[#2f2a52] bg-[#14112a] p-2" style={{ flexGrow: Math.max(1, services.length) }}>
            <div className="mb-1.5 flex justify-between gap-2 text-[11px]">
              <span className="truncate text-[#7fdbff]">{agent.host}</span>
              <span className={down ? 'text-[#ff6b6b]' : agent.connected ? 'text-[#7ee787]' : 'text-[#ff6b6b]'}>
                {agent.connected ? (down ? `${down} down` : `${services.length} ok`) : 'silent'}
              </span>
            </div>
            <div className="flex flex-wrap gap-[3px]">
              {services.map((s) => (
                <button
                  key={s.service}
                  type="button"
                  title={`${s.service} — ${s.incident ?? (s.ready ? 'healthy' : 'down')}`}
                  onClick={() => onPick(s)}
                  className="h-3.5 w-3.5 rounded-[2px] hover:outline hover:outline-1 hover:outline-white"
                  style={{ backgroundColor: SQUARE[tone(s)] }}
                />
              ))}
              {!agent.connected && <span className="text-[10px] text-[#6e6a86]">{agent.error}</span>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function OpsOverview({ data, view, onPick, onGraph }: {
  data: Ops
  view: View | null
  onPick: (s: OpsService) => void
  onGraph: () => void
}) {
  const open = data.incidents.filter((i) => i.status === 'open')
  return (
    <div className="grid grid-cols-1 gap-4 pt-2 xl:grid-cols-12">
      <Frame title={`${view?.source.tenant ?? 'fleet'} score`} right={view ? `data ${view.source.age} old` : undefined} className="xl:col-span-4">
        {view ? <ScoreRing view={view} history={data.history ?? []} /> : <p className="text-[#6e6a86]">loading…</p>}
      </Frame>

      <div className="flex flex-col gap-4 xl:col-span-4">
        <Frame title="vitals" right={view ? `${view.indicators.filter((i) => i.level === 'good').length} of 4 fine` : undefined}>
          {view && <Goals view={view} />}
        </Frame>
        <Frame title="what is about to break" right="ranked">
          <AboutToBreak data={data} />
        </Frame>
      </div>

      <Frame title={open.length ? `${open.length} open` : 'nothing open'} right={`${data.acks.length} accepted`} className="xl:col-span-4">
        {open.length === 0 && <p className="text-[#7ee787]">✓ nothing needs you now.</p>}
        <div className="space-y-2">
          {open.map((i) => (
            <div key={i.id} className={`border-l-2 pl-2 ${i.severity === 'critical' ? 'border-[#ef4444]' : 'border-[#f59e0b]'}`}>
              <div className="flex justify-between gap-2">
                <span>
                  <span className={i.severity === 'critical' ? 'text-[#ff6b6b]' : 'text-[#f0b429]'}>[{i.severity === 'critical' ? 'CRIT' : 'WARN'}]</span>{' '}
                  <span className="text-white">{i.service}</span>
                </span>
                <span className="shrink-0 text-[#7fdbff]">open {ago(i.firstSeen)}</span>
              </div>
              <div className="text-[#b9b4d6]">{i.title}</div>
              <div className="text-[10px] text-[#6e6a86]">
                {i.host}
                {i.reopens > 0 && ` · back ${i.reopens}× in 6 h`}
              </div>
            </div>
          ))}
          {data.acks.map((a) => (
            <div key={a.service} className="border-l-2 border-[#4b4766] pl-2 text-[#8b87a6]">
              <span className="text-[#b9b4d6]">{a.service}</span> · accepted until {a.until.slice(0, 10)}
              <div className="text-[10px]">{a.reason}</div>
            </div>
          ))}
        </div>
      </Frame>

      <Frame title="signals" right="last 24 h" className="xl:col-span-7">
        <Signals data={data} view={view} />
      </Frame>

      <Frame title="fleet map" right={`${data.services.length} services · click a square`} className="xl:col-span-5">
        <FleetMap data={data} onPick={onPick} />
        <button type="button" onClick={onGraph} className="mt-2 text-[#c792ea] hover:text-white">
          who calls whom: the service graph →
        </button>
      </Frame>
    </div>
  )
}

function ago(iso?: string | null): string {
  if (!iso) return '—'
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000)
  return s < 90 ? `${Math.round(s)}s` : s < 5400 ? `${Math.round(s / 60)}m` : s < 172800 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d`
}
