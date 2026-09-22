import { useEffect, useMemo, useRef, useState } from 'react'
import { liveAvailable as checkLive, loadLive, loadScenario, loadScenarios } from './api'
import { DrillSheet } from './components/DrillSheet'
import { Header, LIVE } from './components/Header'
import { IndicatorTile } from './components/IndicatorTile'
import { GridIcon, MobileTabBar, QueueIcon, WatchIcon } from './components/MobileTabBar'
import { QueuePanel } from './components/QueuePanel'
import { VerdictPanel } from './components/VerdictPanel'
import { WatchFaces } from './components/WatchFaces'
import { LEVEL, VERDICT_GLYPH } from './theme'
import type { DrillTarget, ScenarioListItem, View } from './types'

const DEFAULT_SCENARIO = 's01_calm'
const LIVE_REFRESH_MS = 30_000

// What the URL asks for, or null when it asks for nothing. With no explicit choice the app opens live data
// when the backend has a live source, and the first demo scenario otherwise: someone who wired a real
// application in wants to see it, not a mock, and a judge without a backend still lands on S01.
function requestedSelection(): string | null {
  const params = new URLSearchParams(window.location.search)
  if (params.has('live')) return LIVE
  return params.get('scenario')
}

function App() {
  const [scenarios, setScenarios] = useState<ScenarioListItem[]>([])
  const [selected, setSelected] = useState<string | null>(requestedSelection)
  const [view, setView] = useState<View | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [live, setLive] = useState(false)
  // ?drill=users|forecast|trust|day|verdict opens one level deep on load, for deep links
  const [drill, setDrill] = useState<DrillTarget | null>(
    () => new URLSearchParams(window.location.search).get('drill') as DrillTarget | null,
  )

  useEffect(() => {
    loadScenarios().then(setScenarios).catch((e: Error) => setError(e.message))
    checkLive().then((available) => {
      setLive(available)
      // Also overrides an explicit ?live=1: a stale link/bookmark from when live mode *was* configured
      // must not strand the app on a permanent 503 with no way back to a working screen.
      setSelected((current) => (current === null || (current === LIVE && !available) ? (available ? LIVE : DEFAULT_SCENARIO) : current))
    })
  }, [])

  useEffect(() => {
    if (selected === null) return
    let cancelled = false
    const load = () =>
      (selected === LIVE ? loadLive() : loadScenario(selected))
        .then((v) => {
          if (cancelled) return
          setView(v)
          setError(null)
        })
        .catch((e: Error) => {
          if (cancelled) return
          setError(e.message)
          // A live source that stopped answering must not leave the last good screen up: a stale ALL CLEAR
          // under an error banner is still an ALL CLEAR to someone glancing at it.
          if (selected === LIVE) setView(null)
        })

    load()
    const timer = selected === LIVE ? window.setInterval(load, LIVE_REFRESH_MS) : undefined

    const params = new URLSearchParams(window.location.search)
    params.delete('live')
    params.delete('drill')
    params.delete('scenario')
    params.set(selected === LIVE ? 'live' : 'scenario', selected === LIVE ? '1' : selected)
    window.history.replaceState(null, '', `?${params.toString()}`)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [selected])

  const pick = (id: string) => {
    setDrill(null)
    setSelected(id)
  }

  const verdictRef = useRef<HTMLDivElement>(null)
  const indicatorsRef = useRef<HTMLDivElement>(null)
  const queueRef = useRef<HTMLDivElement>(null)
  const watchRef = useRef<HTMLDivElement>(null)

  // Stable identity across unrelated re-renders (e.g. opening a drill sheet elsewhere on the page): the tab
  // bar's IntersectionObserver only needs to reset when the view itself changes, never just because App did.
  const tabs = useMemo(
    () =>
      view && [
        {
          id: 'verdict',
          label: 'Verdict',
          ref: verdictRef,
          icon: (
            // Fixed to the same 18px box as the other tabs' SVG icons: a text glyph's line-height metrics
            // differ from a fixed-size SVG, and this row is top-aligned, so an unboxed glyph would sit at a
            // different height than its neighbors instead of sharing their baseline.
            <span
              className="flex h-4.5 w-4.5 items-center justify-center text-base font-black leading-none"
              style={{ color: LEVEL[view.decision.level].color }}
              aria-hidden="true"
            >
              {VERDICT_GLYPH[view.decision.verdict]}
            </span>
          ),
        },
        { id: 'indicators', label: 'Vitals', ref: indicatorsRef, icon: <GridIcon /> },
        { id: 'queue', label: 'Queue', ref: queueRef, icon: <QueueIcon /> },
        { id: 'watch', label: 'Watch', ref: watchRef, icon: <WatchIcon /> },
      ],
    [view],
  )

  return (
    <div className="min-h-screen bg-bg px-3 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))] sm:px-4 sm:pb-5 sm:pt-[max(1.25rem,env(safe-area-inset-top))] lg:px-10 lg:py-9">
      <Header view={view} scenarios={scenarios} selected={selected ?? DEFAULT_SCENARIO} liveAvailable={live} onSelect={pick} />

      <main className="mx-auto flex max-w-6xl flex-col gap-3 pb-20 sm:gap-4 sm:pb-0 lg:gap-6">
        {error && (
          <div className="rounded-2xl border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-white/80">
            Could not load the tracker data: {error}
          </div>
        )}

        {view && (
          <>
            <div className="grid grid-cols-1 gap-3 sm:gap-4 lg:grid-cols-[1fr_1fr] lg:gap-6">
              <div ref={verdictRef}>
                <VerdictPanel view={view} onOpen={setDrill} />
              </div>
              <div ref={indicatorsRef} className="grid grid-cols-2 gap-2 sm:gap-3 lg:gap-4">
                {view.indicators.map((indicator) => (
                  <IndicatorTile key={indicator.id} indicator={indicator} onOpen={() => setDrill(indicator.id)} />
                ))}
              </div>
            </div>

            <div ref={queueRef}>
              <QueuePanel queue={view.queue} day={view.indicators.find((i) => i.id === 'day')} blind={view.decision.verdict === 'blind'} />
            </div>
            <div ref={watchRef}>
              <WatchFaces view={view} />
            </div>
            <DrillSheet view={view} target={drill} onClose={() => setDrill(null)} />

            {tabs && <MobileTabBar tabs={tabs} />}
          </>
        )}
      </main>
    </div>
  )
}

export default App
