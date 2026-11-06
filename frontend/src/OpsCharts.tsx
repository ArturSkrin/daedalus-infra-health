import { useState } from 'react'
import type { LogStats } from './types'

// Two charts, one measure each (never two scales on one chart): log lines of the fleet, and the lines of them that
// read like an error. Numbers on the axis, exact values on hover, totals above.

type Activity = NonNullable<LogStats['activity']>

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

function Chart({ activity, values, color, kind, unit }: {
  activity: Activity
  values: number[]
  color: string
  kind: 'area' | 'bars'
  unit: string
}) {
  const [hover, setHover] = useState<number | null>(null)
  const n = values.length
  const top = niceMax(Math.max(...values, 0))
  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom
  const x = (i: number) => PAD.left + (n > 1 ? (i / (n - 1)) * plotW : plotW / 2)
  const y = (v: number) => PAD.top + plotH - (v / top) * plotH
  const line = values.map((v, i) => `${i ? 'L' : 'M'} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ')
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
        {kind === 'area' ? (
          <>
            <path d={`${line} L ${x(n - 1)} ${y(0)} L ${x(0)} ${y(0)} Z`} fill={color} opacity={0.15} />
            <path d={line} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
          </>
        ) : (
          values.map((v, i) =>
            v > 0 ? <rect key={i} x={x(i) - barW / 2} y={y(v)} width={barW} height={y(0) - y(v)} rx={1} fill={color} opacity={hover === i ? 1 : 0.8} /> : null,
          )
        )}
        {hover !== null && (
          <>
            <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={y(0)} stroke="rgba(255,255,255,0.4)" strokeDasharray="3 3" />
            <circle cx={x(hover)} cy={y(values[hover])} r={4} fill={color} stroke="#12121b" strokeWidth={2} />
          </>
        )}
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
  const a = stats.activity
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
        <Tile label="lines, last hour" value={lastLines.toLocaleString()} sub={`${dayLines.toLocaleString()} in 24 h`} />
        <Tile label="errors, last hour" value={lastErrors.toLocaleString()} sub={`${dayErrors.toLocaleString()} in 24 h`} />
        <Tile label="error share, hour" value={share(lastErrors, lastLines)} sub={`${share(dayErrors, dayLines)} over 24 h`} />
        <Tile label="busiest 10 min" value={Math.max(...a.lines, 0).toLocaleString()} sub="lines" />
      </div>
      <div>
        <div className="mb-1 text-xs text-white/55">log lines per {a.stepS / 60} min</div>
        <Chart activity={a} values={a.lines} color="#22d3ee" kind="area" unit="lines" />
      </div>
      <div>
        <div className="mb-1 text-xs text-white/55">error lines per {a.stepS / 60} min</div>
        <Chart activity={a} values={a.errors} color="#ef4444" kind="bars" unit="error lines" />
      </div>
      {stats.reason && <p className="text-[11px] text-white/35">{stats.reason}</p>}
    </div>
  )
}
