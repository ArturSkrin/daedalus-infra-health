import type { LogStats, Ops, OpsService, View } from './types'

// The first tab of /ops, in the tracker's own liquid glass. The ring is a clock face of the last 12 hours, one
// tick per 5 minutes, each at its own place on the dial: how much the fleet wrote to its logs, and how much of
// that read like an error. Everything on it opens something: a service, its logs, or the drill-in behind a vital.

const RING = { users: '#22d3ee', forecast: '#e879f9', trust: '#a78bfa', day: '#fbbf24' } as const
const LEVEL: Record<string, string> = { good: '#4ade80', warn: '#fbbf24', bad: '#ef4444', muted: '#7c8296' }

export function Glass({ title, right, children, className = '', onTitle }: {
  title: string
  right?: React.ReactNode
  children: React.ReactNode
  className?: string
  onTitle?: () => void
}) {
  return (
    <section className={`glass rounded-3xl p-4 ${className}`}>
      <header className="mb-3 flex items-baseline justify-between gap-3">
        <button type="button" onClick={onTitle} disabled={!onTitle} className="text-sm font-semibold uppercase tracking-wide text-white/60 enabled:hover:text-white">
          {title}
          {onTitle && <span className="ml-1 text-white/30">→</span>}
        </button>
        {right && <span className="text-xs text-white/35">{right}</span>}
      </header>
      {children}
    </section>
  )
}

// a slice of the logs by the share of it that reads like an error; the same 0.5 % and 5 % lines as "Users now"
const errorColor = (share: number) => (share >= 5 ? '#ef4444' : share >= 0.5 ? '#fb923c' : share > 0 ? '#facc15' : '#22d3ee')

function Clock({ view, stats, healthy, total }: { view: View; stats: LogStats | null; healthy: number; total: number }) {
  const size = 320
  const c = size / 2
  const activity = stats?.activity
  const lines = activity?.lines ?? []
  const peak = Math.max(...lines, 0)
  // a 12-hour dial: the angle of a point is its own wall-clock time, so 12 is at the top and 6 at the bottom
  const angleOf = (unix: number) => {
    const d = new Date(unix * 1000)
    return (((d.getHours() % 12) * 60 + d.getMinutes()) / 720) * 2 * Math.PI - Math.PI / 2
  }
  const now = Date.parse(view.source.now) / 1000        // the moment the backend judged, so the hand matches the data
  const hand = angleOf(now)
  const rings = view.indicators.map((i, n) => ({ id: i.id, value: i.ring, r: 88 - n * 14 }))
  return (
    <div className="flex flex-col items-center">
      <svg viewBox={`0 0 ${size} ${size}`} className="h-80 w-80">
        {Array.from({ length: 12 }, (_, h) => {
          const a = (h / 12) * 2 * Math.PI - Math.PI / 2
          return (
            <text key={h} x={c + 150 * Math.cos(a)} y={c + 150 * Math.sin(a) + 4} textAnchor="middle" fontSize="11" fill="rgba(255,255,255,0.35)">
              {h === 0 ? 12 : h}
            </text>
          )
        })}
        {lines.map((count, i) => {
          const at = (activity?.start ?? 0) + i * (activity?.stepS ?? 300)
          const a = angleOf(at)
          const share = count ? (100 * (activity?.errors[i] ?? 0)) / count : 0
          const r1 = 100
          const r2 = r1 + 2 + (peak ? (count / peak) * 36 : 0)
          return (
            <line
              key={at}
              x1={c + r1 * Math.cos(a)}
              y1={c + r1 * Math.sin(a)}
              x2={c + r2 * Math.cos(a)}
              y2={c + r2 * Math.sin(a)}
              stroke={errorColor(share)}
              strokeWidth={2.4}
              strokeLinecap="round"
              opacity={0.35 + 0.65 * (1 - (now - at) / 43200)}
            >
              <title>{`${new Date(at * 1000).toTimeString().slice(0, 5)}: ${Math.round(count)} log lines, ${share.toFixed(1)}% errors`}</title>
            </line>
          )
        })}
        {!lines.length &&
          Array.from({ length: 144 }, (_, i) => {
            const a = (i / 144) * 2 * Math.PI
            return <line key={i} x1={c + 100 * Math.cos(a)} y1={c + 100 * Math.sin(a)} x2={c + 104 * Math.cos(a)} y2={c + 104 * Math.sin(a)} stroke="rgba(255,255,255,0.12)" strokeWidth={2} />
          })}
        <line x1={c + 60 * Math.cos(hand)} y1={c + 60 * Math.sin(hand)} x2={c + 142 * Math.cos(hand)} y2={c + 142 * Math.sin(hand)} stroke="#fff" strokeOpacity={0.8} strokeWidth={1.5} />
        {rings.map(({ id, value, r }) => {
          const length = 2 * Math.PI * r
          return (
            <g key={id} transform={`rotate(-90 ${c} ${c})`}>
              <circle cx={c} cy={c} r={r} fill="none" stroke={RING[id]} strokeOpacity={0.14} strokeWidth={9} />
              <circle cx={c} cy={c} r={r} fill="none" stroke={RING[id]} strokeWidth={9} strokeLinecap="round" strokeDasharray={`${Math.max(0.01, value) * length} ${length}`} />
            </g>
          )
        })}
        <text x={c} y={c - 2} textAnchor="middle" fill="#fff" fontSize="30" fontWeight="700">
          {healthy}/{total}
        </text>
        <text x={c} y={c + 18} textAnchor="middle" fill="rgba(255,255,255,0.45)" fontSize="10">
          services healthy
        </text>
      </svg>
      <div className="text-2xl font-black tracking-[0.18em]" style={{ color: LEVEL[view.decision.level], textShadow: `0 0 24px ${LEVEL[view.decision.level]}66` }}>
        {view.decision.word}
      </div>
      <p className="mt-1 max-w-md text-center text-sm text-white/65">{view.decision.reason}</p>
      <div className="mt-3 flex flex-wrap justify-center gap-x-3 gap-y-1 text-[11px] text-white/40">
        <span>dial: log lines, last 12 h</span>
        {[['#22d3ee', 'no errors'], ['#facc15', '< 0.5%'], ['#fb923c', '< 5%'], ['#ef4444', '≥ 5%']].map(([color, label]) => (
          <span key={label} className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
            {label}
          </span>
        ))}
        {stats && !stats.available && <span className="text-warn">{stats.reason}</span>}
      </div>
    </div>
  )
}

function Vitals({ view }: { view: View }) {
  return (
    <div className="grid grid-cols-2 gap-2.5">
      {view.indicators.map((i) => (
        <a
          key={i.id}
          href={`./?live=1&drill=${i.id}`}
          className="group rounded-2xl border border-white/10 p-3 transition hover:border-white/30 active:scale-[0.98]"
          style={{ background: `linear-gradient(135deg, ${RING[i.id as keyof typeof RING]}33, ${RING[i.id as keyof typeof RING]}0d)` }}
          title="open the drill-in behind this vital"
        >
          <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-white/55">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: RING[i.id as keyof typeof RING] }} />
            {i.title}
          </div>
          <div className="mt-1 text-2xl font-bold" style={{ color: i.level === 'good' ? '#fff' : LEVEL[i.level] }}>
            {i.label}
          </div>
          <div className="mt-0.5 line-clamp-2 min-h-[2.4em] text-xs text-white/60">{i.caption}</div>
          <div className="mt-2 h-1 rounded-full bg-white/10">
            <div className="h-full rounded-full" style={{ width: `${Math.round(i.ring * 100)}%`, backgroundColor: RING[i.id as keyof typeof RING] }} />
          </div>
        </a>
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

function AboutToBreak({ data, onPick }: { data: Ops; onPick: (s: OpsService) => void }) {
  const ranked = data.services
    .map((s) => ({ s, r: Math.min(100, Math.round(risk(s))) }))
    .filter((x) => x.r >= 20)
    .sort((a, b) => b.r - a.r)
    .slice(0, 6)
  if (ranked.length === 0) return <p className="text-sm text-good">✓ nothing is close to breaking</p>
  return (
    <div className="flex flex-wrap gap-3">
      {ranked.map(({ s, r }) => {
        const color = r >= 90 ? '#ef4444' : r >= 60 ? '#f97316' : '#f59e0b'
        return (
          <button key={`${s.host}:${s.service}`} type="button" onClick={() => onPick(s)} className="flex w-20 flex-col items-center transition active:scale-95" title={s.incident ?? ''}>
            <span
              className="flex h-16 w-16 items-center justify-center rounded-full text-sm font-bold text-white"
              style={{ background: `radial-gradient(circle at 35% 30%, #ffffff88, ${color} 45%, ${color}66)`, boxShadow: `0 0 22px ${color}77` }}
            >
              {!s.ready ? (s.flapping ? 'flap' : 'down') : `${r}%`}
            </span>
            <span className="mt-1 w-full truncate text-center text-[11px] text-white/75">{s.service}</span>
            <span className="w-full truncate text-center text-[10px] text-white/40">{s.host}</span>
          </button>
        )
      })}
    </div>
  )
}

function Noisy({ stats, onStream }: { stats: LogStats | null; onStream: (host: string, service: string) => void }) {
  if (!stats) return <p className="text-sm text-white/40">loading…</p>
  if (!stats.available) return <p className="text-sm text-white/40">{stats.reason}</p>
  if (!stats.noisiest.length) return <p className="text-sm text-good">✓ no error lines in the last hour</p>
  const top = Math.max(...stats.noisiest.map((n) => n.errors))
  return (
    <div className="space-y-1.5">
      {stats.noisiest.map((n) => (
        <button key={`${n.host}:${n.service}`} type="button" onClick={() => onStream(n.host, n.service)} className="group block w-full text-left">
          <div className="flex justify-between gap-2 text-sm">
            <span className="truncate text-white/80 group-hover:text-white">
              <span className="text-white/40">{n.host} · </span>
              {n.service}
            </span>
            <span className="shrink-0 tabular-nums text-bad">{Math.round(n.errors)}</span>
          </div>
          <div className="mt-0.5 h-1 rounded-full bg-white/5">
            <div className="h-full rounded-full bg-bad/70" style={{ width: `${(100 * n.errors) / top}%` }} />
          </div>
        </button>
      ))}
    </div>
  )
}

function FleetMap({ data, onPick }: { data: Ops; onPick: (s: OpsService) => void }) {
  const color = (s: OpsService) =>
    s.dark || s.accepted ? '#4b5068' : !s.ready ? (s.flapping ? '#f59e0b' : '#ef4444') : s.incident ? '#f59e0b' : '#22c55e'
  return (
    <div className="flex flex-wrap gap-2">
      {data.agents.map((a) => {
        const services = data.services.filter((s) => s.host === a.host)
        const down = services.filter((s) => !s.ready && !s.dark && !s.accepted).length
        return (
          <div key={a.host} className="min-w-36 flex-1 rounded-2xl border border-white/10 bg-white/[0.03] p-2.5" style={{ flexGrow: Math.max(1, services.length) }}>
            <div className="mb-1.5 flex justify-between gap-2 text-xs">
              <span className="truncate text-white/75">{a.host}</span>
              <span className={!a.connected || down ? 'text-bad' : 'text-good'}>{!a.connected ? 'silent' : down ? `${down} down` : `${services.length} ok`}</span>
            </div>
            <div className="flex flex-wrap gap-1">
              {services.map((s) => (
                <button
                  key={s.service}
                  type="button"
                  title={`${s.service} — ${s.incident ?? (s.ready ? 'healthy' : 'down')}`}
                  onClick={() => onPick(s)}
                  className="h-3.5 w-3.5 rounded-[4px] transition hover:scale-125"
                  style={{ backgroundColor: color(s), boxShadow: `0 0 6px ${color(s)}66` }}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ago(iso?: string | null): string {
  if (!iso) return '—'
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000)
  return s < 90 ? `${Math.round(s)}s` : s < 5400 ? `${Math.round(s / 60)}m` : s < 172800 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d`
}

export function OpsOverview({ data, view, stats, onPick, onGraph, onStream, onIncidents }: {
  data: Ops
  view: View | null
  stats: LogStats | null
  onPick: (s: OpsService) => void
  onGraph: () => void
  onStream: (host: string, service: string) => void
  onIncidents: () => void
}) {
  const open = data.incidents.filter((i) => i.status === 'open')
  const counted = data.services.filter((s) => !s.dark)
  const healthy = counted.filter((s) => s.ready && !s.incident).length
  const byKey = new Map(data.services.map((s) => [`${s.host}:${s.service}`, s]))
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
      <Glass title="fleet" right={view ? `data ${view.source.age} old` : undefined} className="xl:col-span-5 xl:row-span-2">
        {view ? <Clock view={view} stats={stats} healthy={healthy} total={counted.length} /> : <p className="text-white/40">loading…</p>}
      </Glass>

      <Glass title="vitals" right={view ? `${view.indicators.filter((i) => i.level === 'good').length} of 4 fine · click for the why` : undefined} className="xl:col-span-4">
        {view && <Vitals view={view} />}
      </Glass>

      <Glass title={open.length ? `${open.length} open` : 'nothing open'} right={`${data.acks.length} accepted`} onTitle={onIncidents} className="xl:col-span-3">
        {open.length === 0 && <p className="text-sm text-good">✓ nothing needs you now.</p>}
        <div className="space-y-2">
          {open.map((i) => (
            <button
              key={i.id}
              type="button"
              onClick={() => {
                const s = byKey.get(`${i.host}:${i.service}`)
                if (s) onPick(s)
              }}
              className={`block w-full rounded-xl border-l-2 bg-white/[0.03] px-2.5 py-1.5 text-left transition hover:bg-white/[0.07] ${i.severity === 'critical' ? 'border-bad' : 'border-warn'}`}
            >
              <div className="flex justify-between gap-2 text-sm">
                <span className="truncate text-white">{i.service}</span>
                <span className="shrink-0 text-xs text-white/40">{ago(i.firstSeen)}</span>
              </div>
              <div className="line-clamp-2 text-xs text-white/55">{i.title}</div>
              <div className="text-[10px] text-white/35">
                {i.host}
                {i.reopens > 0 && ` · back ${i.reopens}×`}
              </div>
            </button>
          ))}
          {data.acks.map((a) => (
            <div key={a.service} className="rounded-xl bg-white/[0.02] px-2.5 py-1.5 text-xs text-white/45">
              <span className="text-white/65">{a.service}</span> · accepted until {a.until.slice(0, 10)}
              <div className="text-[11px]">{a.reason}</div>
            </div>
          ))}
        </div>
      </Glass>

      <Glass title="what is about to break" right="click one" className="xl:col-span-4">
        <AboutToBreak data={data} onPick={onPick} />
      </Glass>

      <Glass title="errors in logs" right="last hour · click for the lines" className="xl:col-span-3">
        <Noisy stats={stats} onStream={onStream} />
      </Glass>

      <Glass title="fleet map" right={`${data.services.length} services`} onTitle={onGraph} className="xl:col-span-12">
        <FleetMap data={data} onPick={onPick} />
      </Glass>
    </div>
  )
}
