import { useState } from 'react'
import { scaleTop } from './scale'
import type { LogStats } from './types'

// Two charts, one measure each (never two scales on one chart): how much, and how much of it failed. For the logs:
// lines, and lines that read like an error. For users' traffic: requests through the ingress, and the 5xx among them.
// Numbers on the axis, exact values on hover, totals above.

export type Activity = NonNullable<LogStats['activity']>

const WORDS = {
  logs: { lines: 'lines', errors: 'errors', unit: 'lines', errorUnit: 'error lines', chart: 'log lines', errorChart: 'error lines' },
  traffic: { lines: 'requests', errors: '5xx', unit: 'requests', errorUnit: '5xx', chart: 'requests', errorChart: '5xx responses' },
}

const W = 640
const H = 150
const PAD = { left: 44, right: 8, top: 8, bottom: 20 }

function niceMax(v: number): number {
  if (v <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(v))
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= v) ?? 10 * p
}

const fmt = (v: number) => (v >= 10_000 ? `${(v / 1000).toFixed(0)}k` : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : `${Math.round(v)}`)
const hhmm = (unix: number) => new Date(unix * 1000).toTimeString().slice(0, 5)

function Chart({ activity, values, color, unit }: {
  activity: Activity
  values: number[]
  color: string
  unit: string
}) {
  const [hover, setHover] = useState<number | null>(null)
  const n = values.length
  const top = niceMax(scaleTop(values))
  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom
  const x = (i: number) => PAD.left + (n > 1 ? (i / (n - 1)) * plotW : plotW / 2)
  const y = (v: number) => PAD.top + plotH - (v / top) * plotH
  const barW = Math.max(1, plotW / n - 1.5)
  const at = (i: number) => activity.start + i * activity.stepS
  const hours = [24, 18, 12, 6, 0]
  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const box = e.currentTarget.getBoundingClientRect()
          const px = ((e.clientX - box.left) / box.width) * W
          setHover(Math.max(0, Math.min(n - 1, Math.round(((px - PAD.left) / plotW) * (n - 1)))))
        }}
      >
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(top * f)} y2={y(top * f)} stroke="rgba(255,255,255,0.08)" />
            <text x={PAD.left - 6} y={y(top * f) + 3} textAnchor="end" fontSize="10" fill="rgba(255,255,255,0.45)">
              {fmt(top * f)}
            </text>
          </g>
        ))}
        {hours.map((h) => {
          const i = n - 1 - Math.round((h * 3600) / activity.stepS)
          if (i < 0) return null
          return (
            <text key={h} x={x(i)} y={H - 5} textAnchor={h === 24 ? 'start' : h === 0 ? 'end' : 'middle'} fontSize="10" fill="rgba(255,255,255,0.4)">
              {h === 0 ? 'now' : `${h} h ago`}
            </text>
          )
        })}
        {values.map((v, i) => {
          if (v <= 0) return null
          const shown = Math.min(v, top)
          return (
            <g key={i} opacity={hover === i ? 1 : 0.8}>
              <rect x={x(i) - barW / 2} y={y(shown)} width={barW} height={y(0) - y(shown)} rx={1} fill={color} />
              {v > top && <rect x={x(i) - barW / 2} y={PAD.top - 3} width={barW} height={3} rx={1} fill="#fff" />}
            </g>
          )
        })}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={y(0)} stroke="rgba(255,255,255,0.4)" strokeDasharray="3 3" />}
      </svg>
      {hover !== null && (
        <div
          className="pointer-events-none absolute top-0 rounded-xl border border-white/15 bg-black/70 px-2.5 py-1.5 text-xs backdrop-blur"
          style={{ left: `${(x(hover) / W) * 100}%`, transform: `translateX(${x(hover) > W * 0.7 ? '-105%' : '8%'})` }}
        >
          <div className="text-white/50">
            {hhmm(at(hover))}–{hhmm(at(hover) + activity.stepS)}
          </div>
          <div className="tabular-nums text-white">
            {Math.round(values[hover]).toLocaleString()} {unit}
          </div>
        </div>
      )}
    </div>
  )
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-white/45">{label}</div>
      <div className="text-xl font-semibold tabular-nums text-white">{value}</div>
      {sub && <div className="text-[11px] text-white/40">{sub}</div>}
    </div>
  )
}

export function LogCharts({ stats }: { stats: LogStats | null }) {
  if (!stats) return <p className="text-sm text-white/40">loading…</p>
  if (!stats.available || !stats.activity) return <p className="text-sm text-white/40">{stats.reason ?? 'no log data'}</p>
  return (
    <>
      <Charts a={stats.activity} kind="logs" />
      {stats.reason && <p className="mt-2 text-[11px] text-white/35">{stats.reason}</p>}
    </>
  )
}

export function TrafficCharts({ activity }: { activity: Activity | null }) {
  if (!activity)
    return (
      <p className="text-sm text-white/40">
        no users&apos; traffic measured yet: it comes from Traefik on the k3s hosts, once their agents run a version that reads it
      </p>
    )
  return <Charts a={activity} kind="traffic" />
}

function Charts({ a, kind }: { a: Activity; kind: keyof typeof WORDS }) {
  const w = WORDS[kind]
  const perHour = Math.round(3600 / a.stepS)
  const sum = (v: number[]) => v.reduce((s, x) => s + x, 0)
  const lastLines = sum(a.lines.slice(-perHour))
  const lastErrors = sum(a.errors.slice(-perHour))
  const dayLines = sum(a.lines)
  const dayErrors = sum(a.errors)
  const share = (e: number, l: number) => (l ? `${((100 * e) / l).toFixed(2)}%` : '—')
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile label={`${w.lines}, last hour`} value={Math.round(lastLines).toLocaleString()} sub={`${Math.round(dayLines).toLocaleString()} in 24 h`} />
        <Tile label={`${w.errors}, last hour`} value={Math.round(lastErrors).toLocaleString()} sub={`${Math.round(dayErrors).toLocaleString()} in 24 h`} />
        <Tile label={`${w.errors} share, hour`} value={share(lastErrors, lastLines)} sub={`${share(dayErrors, dayLines)} over 24 h`} />
        <Tile label="busiest 10 min" value={Math.round(Math.max(...a.lines, 0)).toLocaleString()} sub={`${w.unit}, at ${hhmm(a.start + a.lines.indexOf(Math.max(...a.lines, 0)) * a.stepS)}`} />
      </div>
      <div>
        <div className="mb-1 text-xs text-white/55">{w.chart} per {a.stepS / 60} min · a white cap: taller than the scale, hover for the number</div>
        <Chart activity={a} values={a.lines} color="#22d3ee" unit={w.unit} />
      </div>
      <div>
        <div className="mb-1 text-xs text-white/55">{w.errorChart} per {a.stepS / 60} min</div>
        <Chart activity={a} values={a.errors} color="#ef4444" unit={w.errorUnit} />
      </div>
    </div>
  )
}
