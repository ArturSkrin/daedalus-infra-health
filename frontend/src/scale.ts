// The scale of a bar chart: a little above a normal busy slot, not the single biggest one. One nightly burst (a backup,
// a restart storm) can be 20x every other slot and would flatten the rest of the day into identical stubs; the bars
// above this line are drawn clipped, with a white cap, and keep their exact number on hover.
export function scaleTop(values: number[]): number {
  const sorted = values.filter((v) => v > 0).sort((a, b) => a - b)
  if (!sorted.length) return 0
  const p90 = sorted[Math.floor(0.9 * (sorted.length - 1))]
  return Math.min(sorted[sorted.length - 1], p90 * 1.5)
}
