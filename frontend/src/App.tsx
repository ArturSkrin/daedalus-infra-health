import { useEffect, useState } from 'react'
import { liveAvailable as checkLive, loadLive, loadScenario, loadScenarios } from './api'
import { DrillSheet } from './components/DrillSheet'
import { Header, LIVE } from './components/Header'
import { IndicatorTile } from './components/IndicatorTile'
import { QueuePanel } from './components/QueuePanel'
import { VerdictPanel } from './components/VerdictPanel'
import { WatchFaces } from './components/WatchFaces'
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
      setSelected((current) => current ?? (available ? LIVE : DEFAULT_SCENARIO))
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

  return (
    <div className="min-h-screen bg-bg px-3 py-3 sm:px-4 sm:py-5 lg:px-10 lg:py-9">
      <Header view={view} scenarios={scenarios} selected={selected ?? DEFAULT_SCENARIO} liveAvailable={live} onSelect={pick} />

      <main className="mx-auto flex max-w-6xl flex-col gap-3 sm:gap-4 lg:gap-6">
        {error && (
          <div className="rounded-2xl border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-white/80">
            Could not load the tracker data: {error}
          </div>
        )}

        {view && (
          <>
            <div className="grid grid-cols-1 gap-3 sm:gap-4 lg:grid-cols-[1fr_1fr] lg:gap-6">
              <VerdictPanel view={view} onOpen={setDrill} />
              <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:gap-4">
                {view.indicators.map((indicator) => (
                  <IndicatorTile key={indicator.id} indicator={indicator} onOpen={() => setDrill(indicator.id)} />
                ))}
              </div>
            </div>

            <QueuePanel queue={view.queue} day={view.indicators.find((i) => i.id === 'day')} blind={view.decision.verdict === 'blind'} />
            <WatchFaces view={view} />
            <DrillSheet view={view} target={drill} onClose={() => setDrill(null)} />
          </>
        )}
      </main>
    </div>
  )
}

export default App
