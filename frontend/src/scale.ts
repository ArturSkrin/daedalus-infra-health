import type { Ops } from './types'

// The scale of a bar chart: a little above a normal busy slot, not the single biggest one. One nightly burst (a backup,
// a restart storm) can be 20x every other slot and would flatten the rest of the day into identical stubs; the bars
// above this line are drawn clipped, with a white cap, and keep their exact number on hover.
export function scaleTop(values: number[]): number {
  const sorted = values.filter((v) => v > 0).sort((a, b) => a - b)
  if (!sorted.length) return 0
  const p90 = sorted[Math.floor(0.9 * (sorted.length - 1))]
  return Math.min(sorted[sorted.length - 1], p90 * 1.5)
}

// Users' traffic of the last 24 h in 10-minute slots, the same shape as the log activity, from the agents' 5-minute
// buckets. null while no agent measures any (no Traefik, or agents older than the ingress reading).
export function trafficActivity(history: Ops['history'], now = Date.now()) {
  const stepS = 600
  const slots = 144
  const start = Math.floor(now / 1000 / stepS) * stepS - (slots - 1) * stepS
  const lines = new Array<number>(slots).fill(0)
  const errors = new Array<number>(slots).fill(0)
  for (const b of history ?? []) {
    const i = Math.floor((Date.parse(b.t) / 1000 - start) / stepS)
    if (i < 0 || i >= slots) continue
    lines[i] += b.traffic ?? 0
    errors[i] += b.trafficErrors ?? 0
  }
  return lines.some((v) => v > 0) ? { stepS, start, lines, errors } : null
}
