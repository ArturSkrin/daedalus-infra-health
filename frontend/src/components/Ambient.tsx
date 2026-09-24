import { LEVEL } from '../theme'
import type { Level } from '../types'

// Three slow pools of colour behind the page. They are what the glass panels refract, and they follow the
// verdict: a quiet fleet sits on green, an outage tints the whole room red before you read a single word.
export function Ambient({ level }: { level: Level | undefined }) {
  const tone = LEVEL[level ?? 'muted']
  return (
    <div className="ambient" aria-hidden="true">
      <i style={{ backgroundColor: tone.color }} />
      <i style={{ backgroundColor: level === 'muted' || !level ? '#3b4160' : '#4f46e5' }} />
      <i style={{ backgroundColor: tone.color }} />
    </div>
  )
}
