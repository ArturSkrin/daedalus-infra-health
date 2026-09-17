import { VERDICT_WORD } from '../theme'
import type { ScenarioListItem, View } from '../types'

interface HeaderProps {
  view: View | null
  scenarios: ScenarioListItem[]
  selected: string
  liveAvailable: boolean
  onSelect: (id: string) => void
}

export const LIVE = '__live__'

// Where the data came from and how fresh it is. Never hidden: a tracker that
// cannot say how old its picture is cannot be trusted with "all clear".
export function Header({ view, scenarios, selected, liveAvailable, onSelect }: HeaderProps) {
  const source = view?.source
  const healthy = source?.connected ?? false

  return (
    <header className="mx-auto mb-3 flex max-w-6xl flex-col gap-2 sm:mb-5 sm:flex-row sm:items-center sm:justify-between sm:gap-3 lg:mb-7">
      <div>
        <h1 className="text-base font-bold tracking-tight sm:text-lg lg:text-xl">Infra Health Tracker</h1>
        <p className="hidden text-xs text-white/40 sm:block">The agent already decided. This is what it decided, and why you can believe it.</p>
      </div>

      <div className="flex flex-wrap items-center gap-2 sm:justify-end">
        {source && (
          <span className="flex items-center gap-1.5 rounded-full border border-white/10 px-3 py-1 text-[11px] text-white/55">
            <span className={`h-1.5 w-1.5 rounded-full ${healthy ? 'animate-pulse bg-good' : 'bg-bad'}`} />
            <span className={source.mode === 'demo' ? 'font-semibold text-warn' : 'font-semibold text-good'}>{source.label}</span>
            <span className="text-white/25">·</span>
            {source.tenant}
            <span className="text-white/25">·</span>
            {healthy ? `data ${source.age} old` : `no data for ${source.age}`}
          </span>
        )}

        <label className="flex items-center gap-1.5 rounded-full border border-white/10 py-1 pl-3 pr-1 text-[11px] text-white/40">
          Scenario
          <select
            value={selected}
            onChange={(e) => onSelect(e.target.value)}
            className="max-w-[15rem] truncate rounded-full bg-panel-2 px-2 py-0.5 text-[11px] text-white/85 outline-none sm:max-w-none"
          >
            {liveAvailable && <option value={LIVE}>Live data</option>}
            {scenarios.map((s, i) => (
              <option key={s.id} value={s.id}>
                S{String(i + 1).padStart(2, '0')} · {s.title} · {VERDICT_WORD[s.expected]}
              </option>
            ))}
          </select>
        </label>
      </div>
    </header>
  )
}
