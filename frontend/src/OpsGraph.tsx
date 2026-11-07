import { useEffect, useMemo, useRef, useState } from 'react'
import type { Ops, OpsService } from './types'

const W = 1000
const H = 620

// The fleet as glass bubbles inside glass bubbles. A host is the big bubble; inside it, a bubble per group of
// services that live together (a compose project, a Kubernetes namespace); inside that, one glossy orb per service.
// Everything is on screen at once, and clicking a bubble zooms into it. Calls are what the agents know about who
// calls whom (compose depends_on, Service names a workload mentions): arrows with a flow running along them.

type Tone = 'good' | 'warn' | 'bad' | 'muted'
const COLOR: Record<Tone, string> = { good: '#34d399', warn: '#fbbf24', bad: '#f43f5e', muted: '#8b8aa8' }
// the glass is tinted, not painted: healthy glass stays clear so the orbs inside carry the colour
const GLASS: Record<Tone, string> = { good: '#a5f3fc', warn: '#fbbf24', bad: '#f43f5e', muted: '#a1a1c2' }
const LABEL: Record<Tone, string> = { bad: 'down', warn: 'warning or flapping', good: 'healthy', muted: 'silent or accepted' }

function tone(s: OpsService): Tone {
  if (s.dark || s.accepted) return 'muted'
  if (!s.ready) return s.flapping ? 'warn' : 'bad'
  return s.incident ? 'warn' : 'good'
}

const RANK: Record<Tone, number> = { bad: 3, warn: 2, good: 1, muted: 0 }
const worst = (tones: Tone[]): Tone => tones.reduce<Tone>((w, t) => (RANK[t] > RANK[w] ? t : w), 'muted')
const groupOf = (service: string) => (service.includes('/') ? service.split('/')[0] : service)
const shortName = (service: string) => (service.includes('/') ? service.split('/').slice(1).join('/') : service)
const key = (s: OpsService) => `${s.host}:${s.service}`

type Kind = 'fleet' | 'host' | 'group' | 'service'
interface Bubble {
  id: string
  kind: Kind
  name: string
  host: string
  x: number
  y: number
  r: number
  tone: Tone
  children: Bubble[]
  parent: Bubble | null
  service?: OpsService
  count: number
  down: number
  warn: number
}

// Greedy circle packing: biggest first, each next circle at the free spot nearest the centre. Plenty for a few
// dozen circles a level, and no layout library to carry.
function pack(radii: number[], gap: number, aspect = 1): { at: { x: number; y: number }[]; r: number } {
  const order = radii.map((_, i) => i).sort((a, b) => radii[b] - radii[a])
  const at: { x: number; y: number }[] = new Array(radii.length)
  const placed: { x: number; y: number; r: number }[] = []
  for (const i of order) {
    const r = radii[i]
    let best: { x: number; y: number } | null = placed.length ? null : { x: 0, y: 0 }
    let bestD = Infinity
    for (const p of placed) {
      const d = p.r + r + gap
      for (let k = 0; k < 48; k++) {
        const a = (k / 48) * 2 * Math.PI
        const x = p.x + d * Math.cos(a)
        const y = p.y + d * Math.sin(a)
        if (placed.every((q) => Math.hypot(q.x - x, q.y - y) >= q.r + r + gap - 1e-6)) {
          const dist = Math.hypot(x, y * aspect) // aspect > 1 spreads the pile sideways, for a landscape canvas
          if (dist < bestD) {
            bestD = dist
            best = { x, y }
          }
        }
      }
    }
    if (!best) best = { x: Math.max(...placed.map((q) => q.x + q.r)) + r + gap, y: 0 }
    at[i] = best
    placed.push({ ...best, r })
  }
  const minX = Math.min(...at.map((c, i) => c.x - radii[i]))
  const maxX = Math.max(...at.map((c, i) => c.x + radii[i]))
  const minY = Math.min(...at.map((c, i) => c.y - radii[i]))
  const maxY = Math.max(...at.map((c, i) => c.y + radii[i]))
  const cx = (minX + maxX) / 2
  const cy = (minY + maxY) / 2
  for (const c of at) {
    c.x -= cx
    c.y -= cy
  }
  return { at, r: Math.max(...at.map((c, i) => Math.hypot(c.x, c.y) + radii[i])) }
}

function build(services: OpsService[]): Bubble {
  const leaf = (s: OpsService): Bubble => ({
    id: `s:${key(s)}`,
    kind: 'service',
    name: shortName(s.service),
    host: s.host,
    x: 0,
    y: 0,
    r: s.tier === 1 ? 1.3 : 1,
    tone: tone(s),
    children: [],
    parent: null,
    service: s,
    count: 1,
    down: tone(s) === 'bad' ? 1 : 0,
    warn: tone(s) === 'warn' ? 1 : 0,
  })
  const wrap = (kind: Kind, id: string, name: string, host: string, children: Bubble[], gap: number, pad: number, aspect = 1): Bubble => {
    const { at, r } = pack(
      children.map((c) => c.r),
      gap,
      aspect,
    )
    children.forEach((c, i) => {
      c.x = at[i].x
      c.y = at[i].y
    })
    const b: Bubble = {
      id,
      kind,
      name,
      host,
      x: 0,
      y: 0,
      r: r + pad,
      tone: worst(children.map((c) => c.tone)),
      children,
      parent: null,
      count: children.reduce((n, c) => n + c.count, 0),
      down: children.reduce((n, c) => n + c.down, 0),
      warn: children.reduce((n, c) => n + c.warn, 0),
    }
    for (const c of children) c.parent = b
    return b
  }
  const hosts = [...new Set(services.map((s) => s.host))].sort()
  const root = wrap(
    'fleet',
    'fleet',
    'fleet',
    '',
    hosts.map((h) => {
      const mine = services.filter((s) => s.host === h)
      const kids = [...new Set(mine.map((s) => groupOf(s.service)))].map((g) => {
        const members = mine.filter((s) => groupOf(s.service) === g)
        // a group of one is just that service: a bubble around a single orb says nothing
        return members.length === 1 ? leaf(members[0]) : wrap('group', `g:${h}:${g}`, g, h, members.map(leaf), 0.9, 1.2)
      })
      return wrap('host', `h:${h}`, h, h, kids, 1.1, 2)
    }),
    3.4,
    1,
    1.7,
  )
  const place = (b: Bubble, ox: number, oy: number) => {
    b.x += ox
    b.y += oy
    for (const c of b.children) place(c, b.x, b.y)
  }
  place(root, 0, 0)
  return root
}

function walk(b: Bubble, out: Bubble[] = []): Bubble[] {
  out.push(b)
  for (const c of b.children) walk(c, out)
  return out
}

const within = (b: Bubble | undefined | null, ancestor: Bubble): boolean => {
  for (let p = b; p; p = p.parent) if (p === ancestor) return true
  return false
}

// What the camera frames: the bubble in focus, or for the whole fleet the box around the hosts (the fleet's own
// circle would leave the sides of a landscape canvas empty). r is layout units per pixel.
function frame(b: Bubble): { x: number; y: number; r: number } {
  const parts = b.kind === 'fleet' ? b.children : [b]
  const minX = Math.min(...parts.map((c) => c.x - c.r))
  const maxX = Math.max(...parts.map((c) => c.x + c.r))
  const minY = Math.min(...parts.map((c) => c.y - c.r))
  const maxY = Math.max(...parts.map((c) => c.y + c.r))
  return { x: (minX + maxX) / 2, y: (minY + maxY) / 2, r: Math.max((maxX - minX) / (W - 60), (maxY - minY) / (H - 90)) }
}

// The camera eases exponentially toward the frame of the bubble in focus.
function useCamera(target: { x: number; y: number; r: number }) {
  const [cam, setCam] = useState(target)
  const current = useRef(target)
  useEffect(() => {
    const from = current.current
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce || (from.x === target.x && from.y === target.y && from.r === target.r)) {
      current.current = target
      setCam(target)
      return
    }
    const start = performance.now()
    let raf = 0
    const step = (t: number) => {
      const p = Math.min(1, (t - start) / 700)
      const e = p === 1 ? 1 : 1 - 2 ** (-10 * p)
      const next = {
        x: from.x + (target.x - from.x) * e,
        y: from.y + (target.y - from.y) * e,
        r: from.r * (target.r / from.r) ** e, // zoom in log space, so near and far move at the same pace
      }
      current.current = next
      setCam(next)
      if (p < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target.x, target.y, target.r]) // eslint-disable-line react-hooks/exhaustive-deps
  return cam
}

// a name cut to the room under its orb, so neighbours' labels never run into each other
const fit = (name: string, chars: number) => (name.length <= chars ? name : `${name.slice(0, Math.max(3, Math.floor(chars) - 1))}…`)

function Defs() {
  return (
    <defs>
      <style>{`
        .flow { stroke-dasharray: 2 7; animation: flow 1.1s linear infinite; }
        @keyframes flow { to { stroke-dashoffset: -9; } }
        .beat { transform-box: fill-box; transform-origin: center; animation: beat 1.8s cubic-bezier(.2,.7,.3,1) infinite; }
        @keyframes beat { from { transform: scale(1); opacity: .9; } to { transform: scale(1.9); opacity: 0; } }
        .beat-soft { transform-box: fill-box; transform-origin: center; animation: beat-soft 2.4s cubic-bezier(.2,.7,.3,1) infinite; }
        @keyframes beat-soft { from { transform: scale(1); opacity: .7; } to { transform: scale(1.12); opacity: 0; } }
        .bubble { transition: opacity .3s; }
        .tile { fill-opacity: .24; stroke-opacity: .5; stroke-width: 1; transition: fill-opacity .25s ease-out, stroke-opacity .25s ease-out, stroke .25s ease-out; }
        .tile.down { fill-opacity: .5; stroke-opacity: .8; }
        .bubble:hover > .tile, .tile.lit { fill-opacity: .62; stroke: #fff; stroke-opacity: .9; stroke-width: 1.5; }
        .bubble:focus-visible { outline: none; }
        .bubble:focus-visible > .rim { stroke: #fff; stroke-width: 2.5; }
        @media (prefers-reduced-motion: reduce) { .flow, .beat, .beat-soft { animation: none; } }
      `}</style>
      {(Object.keys(GLASS) as Tone[]).map((t) => (
        <g key={t}>
          {/* glass: nearly clear in the middle, denser toward the rim, the way a real bubble catches light */}
          <radialGradient id={`glass-${t}`} cx="50%" cy="42%" r="62%">
            <stop offset="0%" stopColor={GLASS[t]} stopOpacity={0.03} />
            <stop offset="72%" stopColor={GLASS[t]} stopOpacity={0.07} />
            <stop offset="100%" stopColor={GLASS[t]} stopOpacity={t === 'good' ? 0.2 : 0.32} />
          </radialGradient>
          <radialGradient id={`orb-${t}`} cx="36%" cy="30%" r="75%">
            <stop offset="0%" stopColor="#ffffff" stopOpacity={0.95} />
            <stop offset="28%" stopColor={COLOR[t]} />
            <stop offset="100%" stopColor={COLOR[t]} stopOpacity={0.55} />
          </radialGradient>
        </g>
      ))}
      <linearGradient id="rim" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="#fff" stopOpacity={0.7} />
        <stop offset="45%" stopColor="#fff" stopOpacity={0.08} />
        <stop offset="100%" stopColor="#fff" stopOpacity={0.3} />
      </linearGradient>
      <radialGradient id="spec" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stopColor="#fff" stopOpacity={0.55} />
        <stop offset="100%" stopColor="#fff" stopOpacity={0} />
      </radialGradient>
      <filter id="soft" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="6" />
      </filter>
      <marker id="tip" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 9 5 L 0 9 z" fill="#e9d5ff" />
      </marker>
    </defs>
  )
}

function Canvas({ root, focus, picked, onFocus, onPick }: {
  root: Bubble
  focus: Bubble
  picked: string | null
  onFocus: (b: Bubble) => void
  onPick: (b: Bubble) => void
}) {
  const [hover, setHover] = useState<string | null>(null)
  const cam = useCamera(frame(focus))
  const k = 1 / cam.r
  const sx = (x: number) => W / 2 + (x - cam.x) * k
  const sy = (y: number) => H / 2 - 4 + (y - cam.y) * k
  const all = useMemo(() => walk(root), [root])
  const bubbles = all.filter((b) => b.kind === 'host' || b.kind === 'group')
  const orbs = all.filter((b) => b.kind === 'service')
  const byKey = new Map(orbs.map((b) => [key(b.service!), b]))
  const edges = orbs.flatMap((a) =>
    a.service!.calls.flatMap((callee) => {
      const b = byKey.get(`${a.host}:${callee}`)
      return b ? [[a, b] as const] : []
    }),
  )
  const atFleet = focus.kind === 'fleet'
  const lit = (b: Bubble) => b.id === hover || b.id === picked

  const open = (b: Bubble) => (e: React.SyntheticEvent) => {
    e.stopPropagation()
    if (b.kind === 'service') onPick(b)
    else onFocus(b)
  }
  const keys = (b: Bubble) => (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') open(b)(e)
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full select-none" onClick={() => focus.parent && onFocus(focus.parent)}>
      <Defs />
      {/* the bubbles, outermost first so each sits on top of the one that holds it */}
      {bubbles.map((b) => {
        const R = b.r * k
        const x = sx(b.x)
        const y = sy(b.y)
        if (R < 3 || x + R < 0 || x - R > W || y + R < 0 || y - R > H) return null
        const dim = !atFleet && !within(b, focus) && !within(focus, b)
        return (
          <g
            key={b.id}
            className="bubble cursor-pointer"
            opacity={dim ? 0.35 : 1}
            role="button"
            tabIndex={0}
            aria-label={`${b.kind} ${b.name}: ${b.count} services, ${b.down} down`}
            onClick={open(b)}
            onKeyDown={keys(b)}
            onMouseEnter={() => setHover(b.id)}
            onMouseLeave={() => setHover(null)}
          >
            <title>{`${b.name} · ${b.count} services${b.down ? ` · ${b.down} down` : ''}`}</title>
            {b.kind === 'host' && <ellipse cx={x} cy={y + R * 0.97} rx={R * 0.8} ry={Math.max(3, R * 0.09)} fill="#000" opacity={0.4} filter="url(#soft)" />}
            {/* a host stays clear glass with a coloured rim: one service down must not paint a whole server red */}
            <circle cx={x} cy={y} r={R} fill={`url(#glass-${b.kind === 'host' ? 'good' : b.tone})`} />
            <circle
              className="rim"
              cx={x}
              cy={y}
              r={R}
              fill="none"
              stroke={b.tone === 'bad' || b.tone === 'warn' ? COLOR[b.tone] : 'url(#rim)'}
              strokeOpacity={b.tone === 'bad' || b.tone === 'warn' ? 0.75 : 1}
              strokeWidth={hover === b.id ? 2.2 : b.kind === 'host' ? 1.4 : 1}
            />
            {b.tone === 'bad' && <circle className="beat-soft" cx={x} cy={y} r={R} fill="none" stroke={COLOR.bad} strokeWidth={2} pointerEvents="none" />}
          </g>
        )
      })}

      {/* calls: faint at fleet level, arrows with a running flow once you are inside */}
      {edges.map(([a, b]) => {
        const x1 = sx(a.x)
        const y1 = sy(a.y)
        const x2 = sx(b.x)
        const y2 = sy(b.y)
        const len = Math.hypot(x2 - x1, y2 - y1)
        if (len < 4) return null
        const ux = (x2 - x1) / len
        const uy = (y2 - y1) / len
        const ra = a.r * k + 2
        const rb = b.r * k + 4
        const ax = x1 + ux * ra
        const ay = y1 + uy * ra
        const bx = x2 - ux * rb
        const by = y2 - uy * rb
        // bend each call a little to its left, so a call and its answer don't sit on one line
        const mx = (ax + bx) / 2 - uy * len * 0.14
        const my = (ay + by) / 2 + ux * len * 0.14
        const hot = lit(a) || lit(b)
        const inside = within(a, focus) || within(b, focus)
        const opacity = hot ? 1 : atFleet ? 0.28 : inside ? 0.7 : 0.12
        return (
          <path
            key={`${a.id}>${b.id}`}
            d={`M ${ax} ${ay} Q ${mx} ${my} ${bx} ${by}`}
            fill="none"
            stroke={hot ? '#f5d0fe' : '#d8b4fe'}
            strokeOpacity={opacity}
            strokeWidth={hot ? 2.2 : atFleet ? 1 : 1.5}
            strokeLinecap="round"
            className={atFleet && !hot ? undefined : 'flow'}
            markerEnd={atFleet && !hot ? undefined : 'url(#tip)'}
            pointerEvents="none"
          />
        )
      })}

      {orbs.map((b) => {
        const R = b.r * k
        const x = sx(b.x)
        const y = sy(b.y)
        if (x + R < 0 || x - R > W || y + R < 0 || y - R > H) return null
        const t = b.tone
        return (
          <g
            key={b.id}
            className="bubble cursor-pointer"
            opacity={atFleet || within(b, focus) || lit(b) ? 1 : 0.3}
            role="button"
            tabIndex={0}
            aria-label={`${b.service!.service} on ${b.host}: ${LABEL[t]}`}
            onClick={open(b)}
            onKeyDown={keys(b)}
            onMouseEnter={() => setHover(b.id)}
            onMouseLeave={() => setHover(null)}
          >
            <title>{`${b.service!.service} · ${b.host}\n${b.service!.incident ?? LABEL[t]}`}</title>
            {t === 'bad' && <circle className="beat" cx={x} cy={y} r={R} fill="none" stroke={COLOR.bad} strokeWidth={1.5} pointerEvents="none" />}
            {/* a flat, see-through tile: the glass around it carries the depth; hover firms it up and lights its edge */}
            <circle className={`tile rim${t === 'bad' ? ' down' : ''}${lit(b) ? ' lit' : ''}`} cx={x} cy={y} r={R} fill={COLOR[t]} stroke={COLOR[t]} />
            {R >= 20 && (
              <text x={x} y={y + R + 15} textAnchor="middle" fontSize={R >= 32 ? 13 : 11} fill="#f1effa" stroke="#0b0b14" strokeWidth={3} strokeOpacity={0.6} paintOrder="stroke">
                {fit(b.name, (2 * R + 0.9 * k) / (R >= 32 ? 7.2 : 6.2))}
              </text>
            )}
          </g>
        )
      })}

      {/* glare and names go last: they belong to the glass surface, above everything the bubble holds */}
      {bubbles.map((b) => {
        const R = b.r * k
        const x = sx(b.x)
        const y = sy(b.y)
        if (R < 3 || x + R < 0 || x - R > W || y + R < 0 || y - R > H) return null
        const arc = `glass-arc-${b.id}`
        const under = `glass-under-${b.id}`
        // the name follows the upper arc; a long one shrinks to fit, and past a readable size it is cut with …
        const text = b.kind === 'host' ? b.name.toUpperCase() : b.name
        const wanted = Math.min(b.kind === 'host' ? 22 : 18, Math.max(b.kind === 'host' ? 15 : 11, R / 14))
        const perChar = b.kind === 'host' ? 0.74 : 0.62 // glyph width plus letter spacing, in font sizes
        const room = Math.PI * (R - wanted) * 0.78
        const size = Math.max(10, Math.min(wanted, room / (text.length * perChar)))
        const label = fit(text, room / (size * perChar))
        const labelR = R - size
        return (
          <g key={`${b.id}-surface`} pointerEvents="none">
            <ellipse cx={x - R * 0.36} cy={y - R * 0.52} rx={R * 0.38} ry={R * 0.16} transform={`rotate(-28 ${x - R * 0.36} ${y - R * 0.52})`} fill="url(#spec)" opacity={b.kind === 'host' ? 0.45 : 0.6} />
            {R >= 30 && (
              <>
                <path id={arc} d={`M ${x - labelR} ${y} A ${labelR} ${labelR} 0 0 1 ${x + labelR} ${y}`} fill="none" />
                <text fontSize={size} fontWeight={b.kind === 'host' ? 700 : 600} letterSpacing={b.kind === 'host' ? '0.12em' : '0.06em'} fill={b.kind === 'host' ? '#ffffff' : '#e9e6f7'} fillOpacity={0.92}>
                  <textPath href={`#${arc}`} startOffset="50%" textAnchor="middle">
                    {label}
                  </textPath>
                </text>
              </>
            )}
            {b.kind === 'host' && R >= 44 && (
              <>
                {/* the host's status runs along the inside of its lower rim, so neighbours never collide */}
                <path id={under} d={`M ${x - R + 6} ${y} A ${R - 6} ${R - 6} 0 0 0 ${x + R - 6} ${y}`} fill="none" />
                <text fontSize={11} fontWeight={600} letterSpacing="0.04em" fill={b.down ? '#fda4af' : b.warn ? '#fde68a' : '#a7f3d0'} dy={-5}>
                  <textPath href={`#${under}`} startOffset="50%" textAnchor="middle">
                    {b.down ? `${b.down} of ${b.count} down` : b.warn ? `${b.count} services · ${b.warn} warning` : `${b.count} services · all up`}
                  </textPath>
                </text>
              </>
            )}
          </g>
        )
      })}
    </svg>
  )
}

export function OpsGraph({ data, onDetails }: { data: Ops; onDetails: (s: OpsService) => void }) {
  const root = useMemo(() => build(data.services), [data.services])
  const [focusId, setFocusId] = useState('fleet')
  const [picked, setPicked] = useState<string | null>(null)
  const all = useMemo(() => walk(root), [root])
  // the tree is rebuilt on every refresh, so focus is kept by id and found again
  const focus = all.find((b) => b.id === focusId) ?? root
  const pickedBubble = all.find((b) => b.id === picked) ?? null
  const pickedService = pickedBubble?.service ?? null
  const calledBy = pickedService ? data.services.filter((s) => s.host === pickedService.host && s.calls.includes(pickedService.service)) : []
  const edges = data.services.reduce((n, s) => n + s.calls.length, 0)
  const trail: Bubble[] = []
  for (let p: Bubble | null = focus; p; p = p.parent) trail.unshift(p)

  const go = (b: Bubble) => {
    setFocusId(b.id)
    if (!pickedBubble || !within(pickedBubble, b)) setPicked(null)
  }
  const pick = (b: Bubble) => {
    setPicked(b.id)
    if (b.parent && focus.kind === 'fleet') setFocusId(b.parent.id)
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <section className="glass relative min-h-[30rem] overflow-hidden rounded-3xl">
        <header className="absolute left-0 right-0 top-0 z-10 flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
          <nav className="flex min-w-0 items-center gap-1" aria-label="zoom path">
            {trail.map((b, i) => (
              <span key={b.id} className="flex items-center gap-1">
                {i > 0 && <span className="text-white/25">›</span>}
                <button
                  type="button"
                  onClick={() => go(b)}
                  disabled={b === focus}
                  className="truncate rounded-full px-2 py-0.5 text-white/60 transition enabled:hover:bg-white/10 enabled:hover:text-white disabled:text-white"
                >
                  {b.kind === 'fleet' ? `fleet · ${root.count} services` : b.name}
                </button>
              </span>
            ))}
          </nav>
          <span className="shrink-0 text-xs text-white/40">{focus.kind === 'fleet' ? `click a bubble · ${edges} calls known` : 'click empty space to step out'}</span>
        </header>
        <div className="absolute inset-0 pt-8">
          <Canvas root={root} focus={focus} picked={picked} onFocus={go} onPick={pick} />
        </div>
        <div className="absolute bottom-3 left-4 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-white/50">
          {(['bad', 'warn', 'good', 'muted'] as Tone[]).map((t) => (
            <span key={t} className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: COLOR[t] }} />
              {LABEL[t]}
            </span>
          ))}
          <span className="flex items-center gap-1 text-[#e9d5ff]">
            <svg width="22" height="6" aria-hidden>
              <line x1="1" y1="3" x2="21" y2="3" stroke="#d8b4fe" strokeWidth="1.5" strokeDasharray="2 4" />
            </svg>
            calls
          </span>
        </div>
      </section>

      <section className="glass min-h-0 overflow-auto rounded-3xl p-4">
        <header className="mb-2 text-sm font-semibold uppercase tracking-wide text-white/60">{pickedService ? 'service' : focus.kind === 'fleet' ? 'fleet' : focus.kind}</header>
        <div className="space-y-2 text-sm text-white/75">
          {!pickedService && (
            <>
              {focus.kind === 'fleet' && (
                <p>
                  A big bubble is a host, the bubbles inside it are compose projects or namespaces, an orb is one service. Glass takes the colour of the worst
                  service inside it.
                </p>
              )}
              <p className="text-white/45">
                {focus.kind === 'fleet' ? 'Hosts' : 'Inside'} · {focus.count} services{focus.down ? ` · ${focus.down} down` : ''}
              </p>
              {focus.children.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => (c.kind === 'service' ? pick(c) : go(c))}
                  className="flex w-full items-center gap-2 rounded-xl px-2 py-1 text-left transition hover:bg-white/[0.06] hover:text-white"
                >
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: COLOR[c.tone] }} />
                  <span className="truncate">{c.kind === 'service' ? c.service!.service : c.name}</span>
                  <span className="ml-auto shrink-0 tabular-nums text-white/40">{c.kind === 'service' ? (c.service!.calls.length ? `→ ${c.service!.calls.length}` : '') : c.count}</span>
                </button>
              ))}
              {focus.kind === 'fleet' && (
                <p className="pt-2 text-xs text-white/40">
                  Calls come from compose <span className="text-[#e9d5ff]">depends_on</span> and from Kubernetes Service names a workload mentions in its env or args. A URL
                  kept in a Secret is not read, so a missing arrow does not prove there is no call.
                </p>
              )}
            </>
          )}
          {pickedService && (
            <>
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: COLOR[tone(pickedService)] }} />
                <span className="text-base text-white">{pickedService.service}</span>
              </div>
              <p className="text-white/45">
                {pickedService.host} · tier {pickedService.tier ?? '—'}
              </p>
              {pickedService.incident && <p className={pickedService.severity === 'critical' ? 'text-[#fb7185]' : 'text-[#fbbf24]'}>{pickedService.incident}</p>}
              <div>
                <div className="text-white/45">calls</div>
                {pickedService.calls.length ? pickedService.calls.map((c) => <div key={c}>→ {c}</div>) : <div className="text-white/35">nothing known</div>}
              </div>
              <div>
                <div className="text-white/45">called by</div>
                {calledBy.length ? calledBy.map((c) => <div key={c.service}>← {c.service}</div>) : <div className="text-white/35">nothing known</div>}
              </div>
              <div className="flex gap-2 pt-1">
                <button type="button" onClick={() => onDetails(pickedService)} className="rounded-full bg-white/10 px-3 py-1 transition hover:bg-white/20">
                  details, ack and logs →
                </button>
                <button type="button" onClick={() => setPicked(null)} className="rounded-full px-3 py-1 text-white/50 transition hover:bg-white/10 hover:text-white">
                  back
                </button>
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  )
}
