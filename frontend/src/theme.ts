import type { Level, Verdict } from './types'

// One palette for every ring, pill and glow, so a colour always means the
// same decision. "muted" is the colour of "we do not know", never of "fine".
export const LEVEL: Record<Level, { color: string; glow: string }> = {
  good: { color: '#4ade80', glow: '#4ade8055' },
  warn: { color: '#fbbf24', glow: '#fbbf2455' },
  bad: { color: '#ef4444', glow: '#ef444466' },
  muted: { color: '#7c8296', glow: '#7c829633' },
}

export const VERDICT_GLYPH: Record<Verdict, string> = {
  all_clear: '✓',
  schedule: '◖',
  act_now: '◆',
  blind: '?',
}

export const VERDICT_WORD: Record<Verdict, string> = {
  all_clear: 'ALL CLEAR',
  schedule: 'SCHEDULE',
  act_now: 'ACT NOW',
  blind: 'BLIND',
}
