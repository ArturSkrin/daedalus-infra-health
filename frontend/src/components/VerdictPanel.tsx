import { Ring } from './Ring'
import { LEVEL, VERDICT_GLYPH } from '../theme'
import { useCompact } from '../useCompact'
import type { DrillTarget, View } from '../types'


// The fleet in one word. Rings are the four vitals, outermost first; the word
// under them is the decision the agent already made. No score, no number.
export function VerdictPanel({ view, onOpen }: { view: View; onOpen: (target: DrillTarget) => void }) {
  const { decision, indicators } = view
  const tone = LEVEL[decision.level]
  const urgent = decision.verdict === 'act_now'
  // On a phone all five indicators must fit above the fold, so the rings shrink.
  const compact = useCompact()
  const SIZE = compact ? 150 : 236
  const STROKE = compact ? 9 : 13
  const GAP = compact ? 4 : 5

  return (
    <section className="relative flex flex-col items-center gap-3 overflow-hidden rounded-3xl border border-white/10 bg-panel/60 px-5 py-4 sm:gap-5 sm:px-6 sm:py-7 lg:py-9">
      <div
        className="pointer-events-none absolute inset-0 opacity-70"
        style={{ background: `radial-gradient(circle at 50% 32%, ${tone.glow}, transparent 62%)` }}
      />

      <span className="relative hidden text-[11px] font-semibold uppercase tracking-[0.2em] text-white/40 sm:block">Fleet state</span>

      <div className="relative" style={{ width: SIZE, height: SIZE }}>
        {indicators.map((indicator, i) => {
          const size = SIZE - i * 2 * (STROKE + GAP)
          const color = LEVEL[indicator.level]
          return (
            <button
              key={indicator.id}
              type="button"
              aria-label={`${indicator.title}: ${indicator.label}`}
              onClick={() => onOpen(indicator.id)}
              className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full"
              style={{ width: size, height: size }}
            >
              <Ring percent={indicator.ring * 100} size={size} strokeWidth={STROKE} color={color.color} glow={color.glow} />
            </button>
          )
        })}
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <span className="text-2xl font-black sm:text-4xl" style={{ color: tone.color }} aria-hidden="true">
            {VERDICT_GLYPH[decision.verdict]}
          </span>
        </div>
      </div>

      {/* The word is the product. It never waits for an animation to become readable. */}
      <button
        type="button"
        onClick={() => onOpen('verdict')}
        className={`relative flex flex-col items-center gap-0.5 rounded-2xl border px-6 py-2 sm:gap-1 sm:px-7 sm:py-3 ${urgent ? 'animate-pulse-glow' : ''}`}
        style={{
          opacity: decision.dimmed ? 0.8 : 1,
          borderColor: `${tone.color}55`,
          backgroundColor: tone.glow,
          // @ts-expect-error -- custom property consumed by .animate-pulse-glow
          '--glow-color': urgent ? `${tone.color}b3` : tone.glow,
        }}
      >
        <span className="text-2xl font-black uppercase tracking-wider sm:text-3xl" style={{ color: tone.color }}>
          {decision.word}
        </span>
        <span className="text-xs text-white/55">{decision.action}</span>
      </button>

      <p className="relative max-w-sm text-center text-[13px] leading-snug text-white/80 sm:text-sm">{decision.reason}</p>

      {decision.dimmed && (
        <p className="relative -mt-2 text-center text-[11px] text-white/40">Part of the fleet is not visible, so this is a floor, not a guarantee.</p>
      )}

      <button
        type="button"
        onClick={() => onOpen('verdict')}
        className="relative hidden text-[11px] font-semibold uppercase tracking-wide text-white/35 underline-offset-4 hover:text-white/60 hover:underline sm:block"
      >
        Why this word
      </button>
    </section>
  )
}
