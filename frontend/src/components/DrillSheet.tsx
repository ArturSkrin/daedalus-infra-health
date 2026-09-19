import { AnimatePresence, motion } from 'framer-motion'
import type { ReactNode } from 'react'
import { Sparkline } from './Sparkline'
import { LEVEL, VERDICT_WORD } from '../theme'
import type { Drill, DrillTarget, Fact, View } from '../types'

function Facts({ facts }: { facts: Fact[] }) {
  return (
    <dl className="grid grid-cols-2 gap-2">
      {facts.map((f) => (
        <div key={f.label} className="rounded-xl border border-white/5 bg-panel-2/60 px-3 py-2">
          <dt className="text-[10px] font-semibold uppercase tracking-wide text-white/35">{f.label}</dt>
          <dd className="text-sm font-semibold text-white/90">{f.value}</dd>
          {f.hint && <dd className="text-[11px] text-white/35">{f.hint}</dd>}
        </div>
      ))}
    </dl>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-white/40">{title}</h4>
      {children}
    </div>
  )
}

function DrillBody({ drill, color }: { drill: Drill; color: string }) {
  return (
    <>
      {drill.facts.length > 0 && <Facts facts={drill.facts} />}

      {drill.steps && (
        <Section title="Steps of the pattern">
          <ol className="flex flex-col gap-1">
            {drill.steps.map((step) => (
              <li key={step.text} className={`flex items-start gap-2 text-xs ${step.done ? 'text-white/80' : 'text-white/35'}`}>
                <span className="mt-0.5 w-3 shrink-0 text-center" style={{ color: step.done ? color : undefined }}>
                  {step.done ? '●' : '○'}
                </span>
                {step.text}
              </li>
            ))}
          </ol>
        </Section>
      )}

      {drill.note && <p className="rounded-xl border border-white/5 bg-panel-2/60 px-3 py-2 text-xs text-white/55">{drill.note}</p>}

      {drill.pressure && (
        <Section title="Resource pressure">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-white/70">
              <thead className="text-[10px] uppercase tracking-wide text-white/35">
                <tr>
                  <th className="py-1 pr-3 font-semibold">Service</th>
                  <th className="py-1 pr-3 font-semibold">Mem stall</th>
                  <th className="py-1 pr-3 font-semibold">Mem vs request</th>
                  <th className="py-1 pr-3 font-semibold">CPU stall</th>
                  <th className="py-1 font-semibold">OOM kills</th>
                </tr>
              </thead>
              <tbody>
                {drill.pressure.map((row) => (
                  <tr key={row.service} className="border-t border-white/5">
                    <td className="py-1.5 pr-3 font-medium text-white/90">{row.service}</td>
                    <td className="py-1.5 pr-3 tabular-nums">{row.memStallPct ?? '—'}%</td>
                    <td className="py-1.5 pr-3 tabular-nums">{row.memOfRequestPct ?? '—'}%</td>
                    <td className="py-1.5 pr-3 tabular-nums">{row.cpuStallPct ?? '—'}%</td>
                    <td className="py-1.5 tabular-nums">{row.oomKills}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {drill.services && (
        <Section title="Services by error rate">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-white/70">
              <thead className="text-[10px] uppercase tracking-wide text-white/35">
                <tr>
                  <th className="py-1 pr-3 font-semibold">Service</th>
                  <th className="py-1 pr-3 font-semibold">Errors</th>
                  <th className="py-1 pr-3 font-semibold">Traffic</th>
                  <th className="py-1 pr-3 font-semibold">Slowest 1%</th>
                  <th className="py-1 font-semibold">Hits next</th>
                </tr>
              </thead>
              <tbody>
                {drill.services.map((row) => (
                  <tr key={row.service} className="border-t border-white/5">
                    <td className="py-1.5 pr-3">
                      <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle" style={{ backgroundColor: LEVEL[row.flag].color }} />
                      <span className="font-medium text-white/90">{row.service}</span>
                      {row.tier === 1 && <span className="ml-1.5 text-[10px] text-white/30">user path</span>}
                      {!row.ready && <span className="ml-1.5 text-[10px] text-bad">not ready</span>}
                    </td>
                    <td className="py-1.5 pr-3 tabular-nums">{row.errPct}%</td>
                    <td className="py-1.5 pr-3 tabular-nums">{row.reqPerSec}/s</td>
                    <td className="py-1.5 pr-3 tabular-nums">{row.p99Ms ?? '—'} ms</td>
                    <td className="py-1.5 text-white/45">{row.hitsNext.join(', ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {drill.dark && drill.dark.length > 0 && (
        <Section title="Silent services">
          <ul className="flex flex-col gap-1 text-xs text-white/70">
            {drill.dark.map((d) => (
              <li key={d.name} className="flex justify-between rounded-lg border border-white/5 bg-panel-2/60 px-3 py-1.5">
                <span className="font-medium text-white/90">{d.name}</span>
                <span className="text-white/45">no events for {d.silentFor}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {drill.sparkline && drill.sparkline.length > 1 && (
        <Section title="Share of failing requests, last 24 h">
          <Sparkline data={drill.sparkline} color={color} />
          <div className="mt-1 flex justify-between text-[10px] text-white/30">
            <span>24 h ago</span>
            <span>last 2 h are compared with the rest</span>
            <span>now</span>
          </div>
        </Section>
      )}

      {drill.signals && drill.signals.length > 0 && (
        <Section title="Where the agent's signals came from">
          <div className="flex flex-wrap gap-1.5">
            {drill.signals.map((s) => (
              <span key={s.label} className="rounded-full border border-white/10 px-2.5 py-1 text-[11px] text-white/55">
                {s.label} <span className="tabular-nums text-white/85">{s.count.toLocaleString('en-US')}</span>
              </span>
            ))}
          </div>
          <p className="mt-1.5 text-[11px] text-white/35">A count here is attribution, not alarm. Only impact on requests moves the verdict.</p>
        </Section>
      )}
    </>
  )
}

function VerdictBody({ view }: { view: View }) {
  const { decision, validation, scenario } = view
  return (
    <>
      <Section title="Rules, first match wins">
        <ol className="flex flex-col gap-1">
          {decision.rules.map((rule, i) => (
            <li
              key={rule.id}
              className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-1.5 text-xs ${
                rule.fired ? 'border-white/25 bg-white/5 text-white' : 'border-white/5 text-white/40'
              }`}
            >
              <span>
                <span className="mr-2 tabular-nums text-white/30">{i + 1}</span>
                {rule.text}
              </span>
              <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide">{rule.leadsTo}</span>
            </li>
          ))}
        </ol>
      </Section>

      {scenario && validation && (
        <Section title="Demo scenario check">
          <div className="rounded-xl border border-white/5 bg-panel-2/60 px-3 py-2 text-xs text-white/60">
            <p className="text-white/80">{scenario.story}</p>
            <p className="mt-1.5">
              Expected <span className="font-semibold text-white/85">{VERDICT_WORD[validation.expected.verdict]}</span>, computed{' '}
              <span className="font-semibold text-white/85">{VERDICT_WORD[validation.computed.verdict]}</span>{' '}
              <span className={validation.passed ? 'text-good' : 'text-bad'}>{validation.passed ? '· match' : '· mismatch'}</span>
            </p>
          </div>
        </Section>
      )}
    </>
  )
}

export function DrillSheet({ view, target, onClose }: { view: View; target: DrillTarget | null; onClose: () => void }) {
  const indicator = target && target !== 'verdict' ? view.indicators.find((i) => i.id === target) : undefined
  const tone = indicator ? LEVEL[indicator.level] : LEVEL[view.decision.level]

  return (
    // initial={false}: a sheet opened by ?drill= on load is visible at once, not after an animation
    <AnimatePresence initial={false}>
      {target && (
        <motion.div
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 backdrop-blur-sm lg:items-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            className="scrollbar-thin flex max-h-[88vh] w-full max-w-xl flex-col gap-4 overflow-y-auto rounded-t-3xl border border-white/10 bg-panel p-5 lg:rounded-3xl"
            initial={{ y: 40, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 40, opacity: 0 }}
            transition={{ duration: 0.25 }}
            onClick={(e) => e.stopPropagation()}
          >
            <header className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wide text-white/40">{indicator ? indicator.title : 'Fleet state'}</div>
                <div className="text-2xl font-extrabold" style={{ color: tone.color }}>
                  {indicator ? indicator.label : view.decision.word}
                </div>
                <p className="mt-0.5 text-sm text-white/70">{indicator ? indicator.caption : view.decision.reason}</p>
              </div>
              <button type="button" onClick={onClose} aria-label="Close" className="rounded-full border border-white/10 px-2.5 py-1 text-xs text-white/50 hover:text-white">
                Close
              </button>
            </header>

            {indicator ? (
              indicator.drill ? (
                <DrillBody drill={indicator.drill} color={tone.color} />
              ) : (
                <p className="text-sm text-white/50">Greyed out: without a connected cluster agent there is nothing trustworthy to show here.</p>
              )
            ) : (
              <VerdictBody view={view} />
            )}

            {indicator && (
              <Section title="How this indicator decides">
                <p className="text-xs leading-relaxed text-white/50">{indicator.how}</p>
              </Section>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
