import { Ring } from './Ring'
import { LEVEL } from '../theme'
import { useCompact } from '../useCompact'
import type { Indicator } from '../types'

// One vital: a state word and one human sentence. Never a raw value; those
// live one tap deeper, in the drill-in.
export function IndicatorTile({ indicator, onOpen }: { indicator: Indicator; onOpen: () => void }) {
  const tone = LEVEL[indicator.level]
  const compact = useCompact()

  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`${indicator.title}: ${indicator.label} — open for details`}
      className="glass group flex h-full cursor-pointer flex-col gap-1.5 rounded-2xl p-3 text-left transition hover:brightness-110 active:scale-[0.97] sm:gap-2.5 sm:p-3.5 lg:p-4"
      style={indicator.decides ? { borderColor: `${tone.color}99`, boxShadow: `inset 0 1px 0 rgba(255,255,255,0.16), 0 0 0 1px ${tone.color}33, 0 18px 48px -22px ${tone.color}66` } : undefined}
    >
      <div className="flex items-center gap-2.5">
        <div className="shrink-0">
          <Ring percent={indicator.ring * 100} size={compact ? 30 : 40} strokeWidth={compact ? 4 : 5} color={tone.color} glow={tone.glow} showEndCap minGapDegrees={14} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-semibold uppercase leading-tight text-white/50 sm:text-[11px] sm:tracking-wide">{indicator.title}</div>
          <div className="text-lg font-bold leading-tight sm:text-xl" style={{ color: tone.color }}>
            {indicator.label}
          </div>
        </div>
        {/* Always visible, unlike the bottom-row "details" hint (which a driving indicator overrides with
            "drives the verdict") -- this is the one disclosure cue every tile keeps no matter its state. */}
        <svg
          className="shrink-0 text-white/20 transition group-hover:translate-x-0.5 group-hover:text-white/45"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m9 6 6 6-6 6" />
        </svg>
      </div>

      <p className="line-clamp-3 text-xs leading-snug text-white/75 sm:text-[13px]">{indicator.caption}</p>

      <p className="hidden text-[11px] leading-snug text-white/30 lg:block">{indicator.question}</p>

      <div className="mt-auto hidden items-center justify-between gap-2 text-[10px] font-semibold uppercase tracking-wide text-white/30 sm:flex">
        <span>{indicator.horizon}</span>
        {indicator.decides ? <span style={{ color: tone.color }}>drives the verdict</span> : <span className="opacity-0 transition group-hover:opacity-100">details</span>}
      </div>
    </button>
  )
}
