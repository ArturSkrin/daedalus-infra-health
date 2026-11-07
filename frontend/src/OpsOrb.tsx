import { useId } from 'react'

// One service at risk as a soft lit sphere: a matte body lit from the upper left and falling into shade toward the
// lower right, a small soft highlight, a faint rim of bounced light along the bottom, and the colour glowing out
// onto the panel around it. A down service's glow breathes. No text on the sphere: the caption under it speaks.
export function Orb({ color, size = 76, pulse }: { color: string; size?: number; pulse?: boolean }) {
  const id = useId().replace(/:/g, '')
  const c = 60
  const r = 35
  return (
    <svg viewBox="0 0 120 120" width={size} height={size} aria-hidden className="overflow-visible">
      <defs>
        <radialGradient id={`glow${id}`}>
          <stop offset="35%" stopColor={color} stopOpacity={0.5} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </radialGradient>
        <radialGradient id={`light${id}`} cx="34%" cy="28%" r="62%">
          <stop offset="0%" stopColor="#fff" stopOpacity={0.62} />
          <stop offset="55%" stopColor="#fff" stopOpacity={0} />
        </radialGradient>
        <radialGradient id={`shade${id}`} cx="40%" cy="34%" r="72%">
          <stop offset="50%" stopColor="#000" stopOpacity={0} />
          <stop offset="100%" stopColor="#000" stopOpacity={0.5} />
        </radialGradient>
        <linearGradient id={`rim${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="55%" stopColor="#fff" stopOpacity={0} />
          <stop offset="100%" stopColor="#fff" stopOpacity={0.45} />
        </linearGradient>
        <filter id={`blur${id}`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2" />
        </filter>
      </defs>
      <circle className={pulse ? 'orb-breathe' : undefined} cx={c} cy={c} r={r * 1.9} fill={`url(#glow${id})`} opacity={0.85} />
      <ellipse cx={c} cy={c + r + 5} rx={r * 0.7} ry={3.5} fill="#000" opacity={0.4} filter={`url(#blur${id})`} />
      <circle cx={c} cy={c} r={r} fill={color} />
      <circle cx={c} cy={c} r={r} fill={`url(#light${id})`} />
      <circle cx={c} cy={c} r={r} fill={`url(#shade${id})`} />
      <circle cx={c} cy={c} r={r - 0.75} fill="none" stroke={`url(#rim${id})`} strokeWidth={1.5} />
      <ellipse cx={c - 12} cy={c - 16} rx={8} ry={4.5} transform={`rotate(-30 ${c - 12} ${c - 16})`} fill="#fff" opacity={0.75} filter={`url(#blur${id})`} />
    </svg>
  )
}
