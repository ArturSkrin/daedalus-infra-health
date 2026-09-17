import type { ReactNode } from 'react'
import { Ring } from './Ring'
import { LEVEL } from '../theme'
import type { View } from '../types'

const FACE = 176

function Face({ label, children }: { label: string; children: ReactNode }) {
  return (
    <figure className="flex flex-col items-center gap-2">
      <div
        className="relative flex items-center justify-center overflow-hidden rounded-full border-[6px] border-[#1b1b26] bg-black shadow-[0_0_0_2px_#2a2a3a]"
        style={{ width: FACE, height: FACE }}
      >
        {children}
      </div>
      <figcaption className="text-[10px] font-semibold uppercase tracking-wide text-white/30">{label}</figcaption>
    </figure>
  )
}

// Three faces on swipe. The wrist shows the same decision as the phone, with
// less: readable at arm's length, in the dark, in one second.
export function WatchFaces({ view }: { view: View }) {
  const { decision, indicators, queue } = view
  const tone = LEVEL[decision.level]
  const forecast = indicators.find((i) => i.id === 'forecast')
  const top = queue[0]
  const ringSize = 100

  return (
    <section className="rounded-3xl border border-white/10 bg-panel/60 p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-white/60">On the wrist</h2>
        <span className="text-xs text-white/30">three faces, swipe</span>
      </div>

      <div className="flex flex-wrap items-start justify-around gap-5">
        <Face label="1 · the glance">
          <div className="relative -translate-y-3" style={{ width: ringSize, height: ringSize }}>
            {indicators.map((indicator, i) => {
              const size = ringSize - i * 2 * 8
              const color = LEVEL[indicator.level]
              return (
                <div key={indicator.id} className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
                  <Ring percent={indicator.ring * 100} size={size} strokeWidth={5} color={color.color} glow={color.glow} />
                </div>
              )
            })}
          </div>
          <span className="absolute bottom-3.5 text-[11px] font-black uppercase tracking-wider" style={{ color: tone.color }}>
            {decision.word}
          </span>
        </Face>

        <Face label="2 · the open thing">
          <div className="flex flex-col items-center gap-1.5 px-6 text-center">
            <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: tone.color }}>
              {top ? top.service : decision.word}
            </span>
            <span className="line-clamp-3 text-[12px] leading-tight text-white/85">{top ? top.title : decision.reason}</span>
            {decision.verdict === 'schedule' && (
              <span className="mt-1 rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-wide" style={{ borderColor: `${tone.color}88`, color: tone.color }}>
                Scheduled ✓
              </span>
            )}
            {decision.verdict === 'act_now' && <span className="mt-1 text-[10px] uppercase tracking-wide text-white/40">open on phone</span>}
          </div>
        </Face>

        <Face label="3 · what's brewing">
          <div className="flex flex-col items-center gap-1 px-6 text-center">
            <span className="text-2xl font-black" style={{ color: forecast ? LEVEL[forecast.level].color : LEVEL.muted.color }}>
              {forecast?.label ?? '—'}
            </span>
            <span className="line-clamp-3 text-[11px] leading-tight text-white/60">{forecast?.caption}</span>
          </div>
        </Face>
      </div>

      <p className="mt-4 text-center text-[11px] text-white/30">
        Acknowledging from the wrist is offered only for SCHEDULE. ACT NOW needs context, so it sends you to the phone.
      </p>
    </section>
  )
}
