import { useId } from 'react'

// One service as a glossy glass orb, the same material as the orbs on the graph: a white highlight up and to the
// left, the colour deepening toward the far edge, a thin lit rim, a shadow resting under it. A down service pulses.
export function Orb({ color, size = 68, pulse, children }: { color: string; size?: number; pulse?: boolean; children?: React.ReactNode }) {
  const id = useId().replace(/:/g, '')
  const c = 50
  const r = 38
  return (
    <svg viewBox="0 0 100 100" width={size} height={size} aria-hidden className="overflow-visible">
      <defs>
        <radialGradient id={`body${id}`} cx="36%" cy="30%" r="78%">
          <stop offset="0%" stopColor="#ffffff" stopOpacity={0.95} />
          <stop offset="26%" stopColor={color} />
          <stop offset="78%" stopColor={color} stopOpacity={0.78} />
          <stop offset="100%" stopColor="#0b0b14" stopOpacity={0.55} />
        </radialGradient>
        <linearGradient id={`rim${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#fff" stopOpacity={0.75} />
          <stop offset="50%" stopColor="#fff" stopOpacity={0.05} />
          <stop offset="100%" stopColor="#fff" stopOpacity={0.35} />
        </linearGradient>
        <radialGradient id={`spec${id}`}>
          <stop offset="0%" stopColor="#fff" stopOpacity={0.8} />
          <stop offset="100%" stopColor="#fff" stopOpacity={0} />
        </radialGradient>
        <filter id={`soft${id}`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="3" />
        </filter>
      </defs>
      {pulse && <circle className="orb-pulse" cx={c} cy={c} r={r} fill={color} opacity={0.45} />}
      <ellipse cx={c} cy={c + r + 6} rx={r * 0.72} ry={5} fill="#000" opacity={0.5} filter={`url(#soft${id})`} />
      <circle cx={c} cy={c} r={r} fill={`url(#body${id})`} />
      <circle cx={c} cy={c} r={r - 0.6} fill="none" stroke={`url(#rim${id})`} strokeWidth={1.2} />
      <ellipse cx={c - 12} cy={c - 20} rx={14} ry={6.5} transform={`rotate(-28 ${c - 12} ${c - 20})`} fill={`url(#spec${id})`} />
      {children}
    </svg>
  )
}
