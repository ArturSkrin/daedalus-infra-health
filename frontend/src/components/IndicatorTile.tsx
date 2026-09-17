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
      className="group flex h-full flex-col gap-1.5 rounded-2xl border bg-panel-2/70 p-3 text-left transition hover:border-white/25 sm:gap-2.5 sm:p-3.5 lg:p-4"
      style={{ borderColor: indicator.decides ? `${tone.color}88` : 'rgba(255,255,255,0.1)' }}
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
