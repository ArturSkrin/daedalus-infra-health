import { useEffect, useRef, useState } from 'react'
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

// A real swipeable, snap-scrolling page carousel on a phone -- the label under "On the wrist" has always said
// "swipe", but the layout only ever wrapped or squeezed. Desktop keeps the original static row (three faces
// fit comfortably side by side there, so paging would just add friction).
function FacesCarousel({ children }: { children: ReactNode[] }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cardRefs = useRef<Array<HTMLDivElement | null>>([])
  const [active, setActive] = useState(0)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
        if (!visible) return
        const index = cardRefs.current.findIndex((el) => el === visible.target)
        if (index !== -1) setActive(index)
      },
      { root: container, threshold: [0.5, 0.75, 1] },
    )

    cardRefs.current.forEach((card) => card && observer.observe(card))
    return () => observer.disconnect()
  }, [children.length])

  return (
    <div>
      <div
        ref={containerRef}
        className="no-scrollbar -mx-5 flex snap-x snap-mandatory gap-5 overflow-x-auto px-5 pb-1 lg:mx-0 lg:flex-wrap lg:justify-around lg:overflow-visible lg:px-0 lg:pb-0"
      >
        {children.map((child, i) => (
          <div
            key={i}
            ref={(el) => {
              cardRefs.current[i] = el
            }}
            className="shrink-0 snap-center lg:shrink"
          >
            {child}
          </div>
        ))}
      </div>

      <div className="mt-3 flex items-center justify-center gap-1.5 lg:hidden">
        {children.map((_, i) => (
          <span key={i} className={`h-1.5 rounded-full transition-all duration-200 ${i === active ? 'w-4 bg-white/60' : 'w-1.5 bg-white/20'}`} />
        ))}
      </div>
    </div>
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
    <section className="glass rounded-3xl p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-white/60">On the wrist</h2>
        <span className="text-xs text-white/30">three faces, swipe</span>
      </div>

      <FacesCarousel>
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
      </FacesCarousel>

      <p className="mt-4 text-center text-[11px] text-white/30">
        Acknowledging from the wrist is offered only for SCHEDULE. ACT NOW needs context, so it sends you to the phone.
      </p>
    </section>
  )
}
