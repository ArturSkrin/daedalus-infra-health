import { LEVEL } from '../theme'
import type { FleetItem } from '../types'

interface FleetBarProps {
  fleet: FleetItem[]
  tenant: string | null
  onPick: (tenant: string) => void
}

// Every host on one line, worst first: the screen below shows one of them, this shows that the others are fine.
export function FleetBar({ fleet, tenant, onPick }: FleetBarProps) {
  if (fleet.length < 2) return null
  const rank = { bad: 0, warn: 1, muted: 2, good: 3 }
  const ordered = [...fleet].sort((a, b) => rank[a.level] - rank[b.level])
  return (
    <nav className="mx-auto mb-3 flex max-w-6xl flex-wrap gap-2 sm:mb-5" aria-label="Hosts">
      {ordered.map((item) => (
        <button
          key={item.tenant}
          type="button"
          onClick={() => onPick(item.tenant)}
          title={item.reason}
          aria-current={item.tenant === tenant}
          className={`glass-pill flex items-center gap-1.5 px-3 py-1 text-[11px] transition-transform active:scale-[0.97] ${
            item.tenant === tenant ? 'text-white ring-1 ring-white/30' : 'text-white/55'
          }`}
        >
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: LEVEL[item.level].color }} />
          {item.tenant}
          <span className="font-semibold" style={{ color: LEVEL[item.level].color }}>
            {item.word}
          </span>
        </button>
      ))}
    </nav>
  )
}
