import { motion } from 'framer-motion'

interface RingProps {
  percent: number // 0-100 fill amount
  size: number
  strokeWidth: number
  color: string
  glow: string
  // "round" reads better at the large main ring; at icon scale (~48px) a
  // round cap can visually swallow a near-full ring's remaining sliver,
  // making a real value (e.g. 98%) look like a plain closed circle.
  strokeLinecap?: 'round' | 'butt'
  // Apple Watch-style bright dot at the current progress head. At icon
  // scale, this is what actually tells the viewer "there's a start/end
  // here" when the gap itself is only a few degrees wide.
  showEndCap?: boolean
  // Floors how small the unfilled gap can render, purely for legibility
  // at icon scale — a real 98.4% would leave a ~6° sliver that's
  // basically invisible at 48px. The large main ring doesn't need this
  // (omit the prop there); it's big enough to read accurately as-is.
  minGapDegrees?: number
}

export function Ring({
  percent,
  size,
  strokeWidth,
  color,
  glow,
  strokeLinecap = 'round',
  showEndCap = false,
  minGapDegrees = 0,
}: RingProps) {
  const center = size / 2
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const clampedRaw = Math.min(100, Math.max(0, percent))
  const minGapPercent = (minGapDegrees / 360) * 100
  const clamped = minGapDegrees > 0 ? Math.min(clampedRaw, 100 - minGapPercent) : clampedRaw
  const offset = circumference * (1 - clamped / 100)

  // Progress starts at 12 o'clock and sweeps clockwise (matching the ring's
  // own -rotate-90 transform below) — see Ring.tsx history for the derivation.
  const angle = (clamped / 100) * 2 * Math.PI
  const capX = center + radius * Math.cos(angle)
  const capY = center + radius * Math.sin(angle)
  // A genuinely separate circle, not just a thicker stroke segment — sized
  // to visibly poke out past both edges of the ring band.
  const capRadius = strokeWidth * 1.6
  const capVisible = showEndCap && clamped > 0 && clamped < 100

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90 overflow-visible">
      {/* Track is a dim version of the ring's own color, not a fixed gray,
          so it reads as "this ring, unfilled" against any card background. */}
      <circle cx={center} cy={center} r={radius} stroke={color} strokeOpacity={0.16} strokeWidth={strokeWidth} fill="none" />
      <motion.circle
        cx={center}
        cy={center}
        r={radius}
        stroke={color}
        strokeWidth={strokeWidth}
        fill="none"
        strokeLinecap={strokeLinecap}
        strokeDasharray={circumference}
        initial={false}
        animate={{ strokeDashoffset: offset }}
        transition={{ duration: 1.1, ease: 'easeInOut' }}
        style={{ filter: `drop-shadow(0 0 8px ${glow})` }}
      />
      {showEndCap && (
        <motion.circle
          r={capRadius}
          fill={color}
          initial={false}
          animate={{ cx: capX, cy: capY, opacity: capVisible ? 1 : 0 }}
          transition={{ duration: 1.1, ease: 'easeInOut' }}
          // Noticeably brighter than the arc's own dim glow — this dot is
          // "the current position," not part of the ambient ring glow.
          style={{ filter: `drop-shadow(0 0 3px ${color}) drop-shadow(0 0 9px ${color})` }}
        />
      )}
    </svg>
  )
}
