import { useEffect, useRef, useState } from 'react'
import type { ReactNode, RefObject } from 'react'

export interface MobileTab {
  id: string
  label: string
  icon: ReactNode
  ref: RefObject<HTMLDivElement | null>
}

export function GridIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  )
}

export function QueueIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 6h1.5M4 12h1.5M4 18h1.5" />
      <path d="M9 6h11M9 12h11M9 18h11" />
    </svg>
  )
}

export function WatchIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l3 2" />
    </svg>
  )
}

// iOS-style tab bar for a screen that is one long scroll on a phone: each button jumps to a section instead of
// forcing a scroll, and the active tab tracks whichever section is actually on screen. A translucent "material"
// bar, like the ones docked to the bottom of a native app, not a webpage footer.
export function MobileTabBar({ tabs }: { tabs: MobileTab[] }) {
  const [active, setActive] = useState(0)
  // A tap drives a `scrollIntoView({ block: 'start' })` jump, which lands the target at the very top of the
  // viewport — outside the mid-screen band this observer watches. Without this guard, the observer would keep
  // reporting whatever section is still passing through that band mid-animation and fight the tap's own choice.
  const suppressUntil = useRef(0)

  useEffect(() => {
    const targets = tabs.map((t) => t.ref.current).filter((el): el is HTMLDivElement => el !== null)
    if (targets.length === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (Date.now() < suppressUntil.current) return
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
        if (!visible) return
        const index = tabs.findIndex((t) => t.ref.current === visible.target)
        if (index !== -1) setActive(index)
      },
      { rootMargin: '-35% 0px -50% 0px', threshold: [0, 0.25, 0.5, 0.75, 1] },
    )
    targets.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [tabs])

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 border-t border-white/10 bg-panel/75 backdrop-blur-xl sm:hidden"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <div className="mx-auto grid max-w-6xl grid-cols-4 px-1 py-1">
        {tabs.map((tab, i) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => {
              setActive(i)
              suppressUntil.current = Date.now() + 700
              tab.ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
            }}
            className={`flex flex-col items-center gap-0.5 rounded-2xl px-2 py-1.5 transition-transform active:scale-90 ${
              active === i ? 'text-white' : 'text-white/40'
            }`}
          >
            <span className={`transition-opacity ${active === i ? 'opacity-100' : 'opacity-70'}`}>{tab.icon}</span>
            <span className="text-[10px] font-semibold">{tab.label}</span>
          </button>
        ))}
      </div>
    </nav>
  )
}
