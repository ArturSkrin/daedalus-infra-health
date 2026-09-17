import { useState } from 'react'
import type { Indicator, QueueItem } from '../types'

const SEVERITY_COLOR: Record<QueueItem['severity'], string> = {
  critical: '#ef4444',
  warning: '#fbbf24',
  info: '#60a5fa',
}

function QueueRow({ item }: { item: QueueItem }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="rounded-xl border border-white/5 bg-panel-2/60">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full items-start gap-3 px-3 py-2.5 text-left">
        <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: SEVERITY_COLOR[item.severity] }} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-sm font-medium text-white/90">{item.service}</span>
            <span className="shrink-0 text-[11px] text-white/35">open {item.openFor}</span>
          </div>
          <p className="text-xs text-white/55">{item.title}</p>
          <p className="mt-0.5 text-[11px] text-white/35">{item.impact}</p>
        </div>
      </button>
      {open && (
        <div className="border-t border-white/5 px-3 py-3 text-xs leading-relaxed text-white/60">
          {item.rca && (
            <p>
              <span className="font-semibold text-white/80">Agent's diagnosis. </span>
              {item.rca}
            </p>
          )}
          {item.plan.length > 0 && (
            <ol className="mt-2 list-decimal space-y-0.5 pl-4">
              {item.plan.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          )}
        </div>
      )}
    </li>
  )
}

// The queue holds only what needs a human. When it is empty the panel says
// what the agent handled instead, so a quiet day still tells a story.
export function QueuePanel({ queue, day, blind }: { queue: QueueItem[]; day?: Indicator; blind: boolean }) {
  const handled = day?.drill?.handled ?? []
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/60 p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-white/60">Needs a human</h2>
        <span className="text-xs text-white/30">{blind ? 'unknown' : queue.length === 0 ? 'nothing' : `${queue.length} open`}</span>
      </div>

      {queue.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {queue.map((item) => (
            <QueueRow key={item.id} item={item} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-white/45">
          {blind ? 'Unknown. An empty queue means nothing while the fleet is not visible.' : 'Nothing is waiting for you.'}
        </p>
      )}

      {handled.length > 0 && (
        <div className="mt-4 border-t border-white/5 pt-3">
          <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-white/35">Handled by the agent today</h3>
          <ul className="flex flex-col gap-1">
            {handled.map((h) => (
              <li key={h.at + h.service} className="flex items-baseline gap-2 text-xs text-white/50">
                <span className="shrink-0 font-mono text-[11px] text-white/30">{h.at}</span>
                <span className="truncate">
                  <span className="text-white/70">{h.service}</span> · {h.title}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
