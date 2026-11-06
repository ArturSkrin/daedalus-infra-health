import { useMemo, useState } from 'react'
import type { Ops, OpsService } from './types'

// The fleet as spheres. Each host is a hub; around it, one sphere per group of services that live together (a
// compose project, a Kubernetes namespace). Edges are what the agents know about who calls whom: compose
// depends_on, and Service names a workload mentions. Clicking a sphere opens it: its services on a ring, the
// calls between them, and the calls that leave the group.

type Tone = 'good' | 'warn' | 'bad' | 'muted'
const COLOR: Record<Tone, string> = { good: '#22c55e', warn: '#f59e0b', bad: '#ef4444', muted: '#6b6790' }
const HOST_COLOR = ['#22d3ee', '#e879f9', '#a78bfa', '#fbbf24', '#34d399', '#f472b6', '#60a5fa']

function tone(s: OpsService): Tone {
  if (s.dark || s.accepted) return 'muted'
  if (!s.ready) return s.flapping ? 'warn' : 'bad'
  return s.incident ? 'warn' : 'good'
}

const RANK: Record<Tone, number> = { bad: 3, warn: 2, good: 1, muted: 0 }
const worst = (tones: Tone[]): Tone => tones.reduce<Tone>((w, t) => (RANK[t] > RANK[w] ? t : w), 'muted')

const groupOf = (service: string) => (service.includes('/') ? service.split('/')[0] : service)
const key = (s: OpsService) => `${s.host}:${s.service}`

interface Group {
  id: string
  host: string
  name: string
  members: OpsService[]
  tone: Tone
  x: number
  y: number
  r: number
}

function Sphere({ x, y, r, color, glow, label, sub, onClick, active }: {
  x: number
  y: number
  r: number
  color: string
  glow?: boolean
  label: string
  sub?: string
  onClick?: () => void
  active?: boolean
}) {
  const id = `g${color.slice(1)}`
  return (
    <g onClick={onClick} className={onClick ? 'cursor-pointer' : ''}>
      <defs>
        <radialGradient id={id} cx="35%" cy="30%" r="75%">
          <stop offset="0%" stopColor="#ffffff" stopOpacity={0.55} />
          <stop offset="35%" stopColor={color} stopOpacity={0.95} />
          <stop offset="100%" stopColor={color} stopOpacity={0.35} />
        </radialGradient>
      </defs>
      {glow && <circle cx={x} cy={y} r={r + 6} fill={color} opacity={0.18} />}
      <circle cx={x} cy={y} r={r} fill={`url(#${id})`} stroke={active ? '#ffffff' : color} strokeWidth={active ? 2 : 1} strokeOpacity={0.8} />
      <text x={x} y={y + r + 13} textAnchor="middle" fill="#d8d4ea" fontSize="11">
        {label}
      </text>
      {sub && (
        <text x={x} y={y + r + 25} textAnchor="middle" fill="#6e6a86" fontSize="9">
          {sub}
        </text>
      )}
    </g>
  )
}

function curve(x1: number, y1: number, x2: number, y2: number, cx: number, cy: number, pull = 0.35): string {
  // a quadratic curve bent toward the centre, the way the Triage graph draws its calls
  const mx = (x1 + x2) / 2
  const my = (y1 + y2) / 2
  return `M ${x1} ${y1} Q ${mx + (cx - mx) * pull} ${my + (cy - my) * pull} ${x2} ${y2}`
}

function Fleet({ data, onOpen }: { data: Ops; onOpen: (g: Group) => void }) {
  const W = 1000
  const H = 640
  const cx = W / 2
  const cy = H / 2
  const { groups, hubs, links } = useMemo(() => {
    const hosts = [...new Set(data.services.map((s) => s.host))]
    const hubs = hosts.map((host, i) => {
      const angle = (i / Math.max(1, hosts.length)) * 2 * Math.PI - Math.PI / 2
      const spread = hosts.length > 1 ? 210 : 0
      return { host, x: cx + spread * Math.cos(angle) * 1.25, y: cy + spread * Math.sin(angle), color: HOST_COLOR[i % HOST_COLOR.length] }
    })
    const groups: Group[] = []
    for (const hub of hubs) {
      const mine = data.services.filter((s) => s.host === hub.host)
      const names = [...new Set(mine.map((s) => groupOf(s.service)))]
      // one host gets the whole canvas; with several, each keeps a small orbit of its own
      const orbit = hubs.length === 1 ? 240 : Math.min(110, 30 + names.length * 9)
      names.forEach((name, j) => {
        const members = mine.filter((s) => groupOf(s.service) === name)
        const angle = (j / names.length) * 2 * Math.PI
        groups.push({
          id: `${hub.host}:${name}`,
          host: hub.host,
          name,
          members,
          tone: worst(members.map(tone)),
          x: hub.x + orbit * (hubs.length === 1 ? 1.5 : 1) * Math.cos(angle),
          y: hub.y + orbit * Math.sin(angle),
          r: 7 + Math.min(16, Math.sqrt(members.length) * 4.5),
        })
      })
    }
    const byService = new Map<string, Group>()
    for (const g of groups) for (const m of g.members) byService.set(key(m), g)
    const links = new Map<string, [Group, Group]>()
    for (const g of groups)
      for (const m of g.members)
        for (const callee of m.calls) {
          const target = byService.get(`${m.host}:${callee}`)
          if (target && target !== g) links.set(`${g.id}>${target.id}`, [g, target])
        }
    return { groups, hubs, links: [...links.values()] }
  }, [data, cx, cy])

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full">
      {hubs.map((hub) => (
        <g key={hub.host}>
          {groups
            .filter((g) => g.host === hub.host)
            .map((g) => (
              <line key={g.id} x1={hub.x} y1={hub.y} x2={g.x} y2={g.y} stroke={hub.color} strokeOpacity={0.18} />
            ))}
          <circle cx={hub.x} cy={hub.y} r={5} fill={hub.color} />
          <text x={hub.x} y={hub.y - 10} textAnchor="middle" fill={hub.color} fontSize="12" fontWeight="600">
            {hub.host}
          </text>
        </g>
      ))}
      {links.map(([a, b]) => (
        <path key={`${a.id}>${b.id}`} d={curve(a.x, a.y, b.x, b.y, cx, cy, 0.2)} fill="none" stroke="#c792ea" strokeOpacity={0.55} strokeWidth={1.4} />
      ))}
      {groups.map((g) => (
        <Sphere
          key={g.id}
          x={g.x}
          y={g.y}
          r={g.r}
          color={COLOR[g.tone]}
          glow={g.tone === 'bad'}
          label={g.name}
          sub={`${g.members.length}`}
          onClick={() => onOpen(g)}
        />
      ))}
    </svg>
  )
}

function Inside({ data, group, picked, onPick }: { data: Ops; group: Group; picked: string | null; onPick: (k: string) => void }) {
  const W = 1000
  const H = 640
  const cx = W / 2
  const cy = H / 2 + 10
  const members = group.members
  const radius = Math.min(250, 90 + members.length * 14)
  const place = new Map(
    members.map((m, i) => {
      const angle = (i / members.length) * 2 * Math.PI - Math.PI / 2
      return [key(m), { x: cx + radius * 1.35 * Math.cos(angle), y: cy + radius * Math.sin(angle) }]
    }),
  )
  // calls leaving the group: drawn to small satellites outside the ring
  const outside = new Map<string, { x: number; y: number; s: OpsService | undefined }>()
  const allByKey = new Map(data.services.map((s) => [key(s), s]))
  for (const m of members)
    for (const callee of m.calls) {
      const k = `${m.host}:${callee}`
      if (!place.has(k) && !outside.has(k)) {
        const n = outside.size
        outside.set(k, { x: 60 + (n % 2) * 880, y: 70 + Math.floor(n / 2) * 60, s: allByKey.get(k) })
      }
    }
  const edges = members.flatMap((m) => m.calls.map((callee) => [key(m), `${m.host}:${callee}`] as const))
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#c792ea" />
        </marker>
      </defs>
      <text x={cx} y={30} textAnchor="middle" fill="#e879f9" fontSize="15">
        {group.host} / {group.name}
      </text>
      {edges.map(([from, to]) => {
        const a = place.get(from)
        const b = place.get(to) ?? outside.get(to)
        if (!a || !b) return null
        const hot = picked === from || picked === to
        return (
          <path
            key={`${from}>${to}`}
            d={curve(a.x, a.y, b.x, b.y, cx, cy, 0.3)}
            fill="none"
            stroke="#c792ea"
            strokeOpacity={hot ? 0.95 : 0.45}
            strokeWidth={hot ? 2.2 : 1.3}
            markerEnd="url(#arrow)"
          />
        )
      })}
      {[...outside.entries()].map(([k, o]) => (
        <Sphere key={k} x={o.x} y={o.y} r={8} color={o.s ? COLOR[tone(o.s)] : '#6b6790'} label={k.split(':').slice(1).join(':')} sub="outside the group" />
      ))}
      {members.map((m) => {
        const p = place.get(key(m))!
        const t = tone(m)
        return (
          <Sphere
            key={key(m)}
            x={p.x}
            y={p.y}
            r={m.tier === 1 ? 20 : 15}
            color={COLOR[t]}
            glow={t === 'bad'}
            active={picked === key(m)}
            label={m.service.includes('/') ? m.service.split('/').slice(1).join('/') : m.service}
            sub={m.tier === 1 ? 'user path' : undefined}
            onClick={() => onPick(key(m))}
          />
        )
      })}
    </svg>
  )
}

export function OpsGraph({ data, onDetails }: { data: Ops; onDetails: (s: OpsService) => void }) {
  const [picked, setPicked] = useState<string | null>(null)
  const [group, setGroup] = useState<Group | null>(null)
  const pickedService = data.services.find((s) => key(s) === picked) ?? null
  const calledBy = pickedService ? data.services.filter((s) => s.host === pickedService.host && s.calls.includes(pickedService.service)) : []
  const edges = data.services.reduce((n, s) => n + s.calls.length, 0)

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <section className="glass relative min-h-[28rem] overflow-hidden rounded-3xl">
        <header className="absolute left-0 right-0 top-0 z-10 flex justify-between px-4 py-2 text-sm">
          <span>
            <span className="text-[#e6defc]">service graph</span>
            <span className="text-[#6e6a86]">({data.services.length})</span>
            {group && <span className="ml-1.5 text-[#7fdbff]">[{group.id}]</span>}
          </span>
          <span className="text-[#c792ea] opacity-75">
            {group ? (
              <button type="button" onClick={() => setGroup(null)} className="hover:text-white">
                ← back to the fleet
              </button>
            ) : (
              `click a sphere · ${edges} calls known`
            )}
          </span>
        </header>
        <div className="absolute inset-0 pt-9">
          {group ? (
            <Inside data={data} group={group} picked={picked} onPick={setPicked} />
          ) : (
            <Fleet
              data={data}
              onOpen={(g) => {
                setGroup(g)
                setPicked(null)
              }}
            />
          )}
        </div>
        <div className="absolute bottom-3 left-4 flex gap-3 text-[11px] text-white/45">
          {(['bad', 'warn', 'good', 'muted'] as Tone[]).map((t) => (
            <span key={t} className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: COLOR[t] }} />
              {{ bad: 'down', warn: 'warning or flapping', good: 'healthy', muted: 'silent or accepted' }[t]}
            </span>
          ))}
          <span className="text-[#c792ea]">— calls</span>
        </div>
      </section>

      <section className="glass min-h-0 overflow-auto rounded-3xl p-4">
        <header className="mb-2 text-sm font-semibold uppercase tracking-wide text-white/60">{pickedService ? 'service' : group ? 'group' : 'how to read it'}</header>
        <div className="space-y-2 text-sm text-white/75">
          {!group && (
            <>
              <p>Each host is a hub, each sphere around it a compose project or a namespace. Size is how many services it has, colour is its worst service.</p>
              <p className="text-[#6e6a86]">
                Calls come from compose <span className="text-[#c792ea]">depends_on</span> and from Kubernetes Service names a workload mentions in its env or
                args. A URL kept in a Secret is not read, so a missing line does not prove there is no call.
              </p>
            </>
          )}
          {group && !pickedService && (
            <>
              <p>
                <span className="text-[#7fdbff]">{group.host}</span> / {group.name}: {group.members.length} services, click one.
              </p>
              {group.members.map((m) => (
                <button key={key(m)} type="button" onClick={() => setPicked(key(m))} className="flex w-full items-center gap-2 text-left hover:text-white">
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: COLOR[tone(m)] }} />
                  <span className="truncate">{m.service}</span>
                  {m.calls.length > 0 && <span className="ml-auto text-[#6e6a86]">→ {m.calls.length}</span>}
                </button>
              ))}
            </>
          )}
          {pickedService && (
            <>
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: COLOR[tone(pickedService)] }} />
                <span className="text-base text-white">{pickedService.service}</span>
              </div>
              <p className="text-[#6e6a86]">
                <span className="text-[#7fdbff]">{pickedService.host}</span> · tier {pickedService.tier ?? '—'}
              </p>
              {pickedService.incident && <p className={pickedService.severity === 'critical' ? 'text-[#ff6b6b]' : 'text-[#f0b429]'}>{pickedService.incident}</p>}
              <div>
                <div className="text-[#6e6a86]">calls</div>
                {pickedService.calls.length ? pickedService.calls.map((c) => <div key={c}>→ {c}</div>) : <div className="text-[#6e6a86]">nothing known</div>}
              </div>
              <div>
                <div className="text-[#6e6a86]">called by</div>
                {calledBy.length ? calledBy.map((c) => <div key={c.service}>← {c.service}</div>) : <div className="text-[#6e6a86]">nothing known</div>}
              </div>
              <button type="button" onClick={() => onDetails(pickedService)} className="rounded-sm bg-white/10 px-2 hover:bg-white/20">
                details, ack and logs →
              </button>
            </>
          )}
        </div>
      </section>
    </div>
  )
}
