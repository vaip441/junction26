import { pts } from '../../lib/format'
import { MIN_MOVE, WINDOW_SECONDS, type Lifecycle } from '../../lib/lifecycle'
import type { Verdict } from '../../lib/types'

function minutes(seconds: number): string {
  // "min", not "m": the badge is uppercase and "5M" reads as five million on a trading screen
  return `${Math.max(1, Math.round(seconds / 60))} min`
}

const RULE = `Judged like the weekend record: the price ${WINDOW_SECONDS / 60} min after the tick against the price when it arrived; under ${MIN_MOVE} pt counts as no move.`

/**
 * What the price did after this call. Colour still means verdict only: states where the price
 * went our way take the verdict colour, the rest stay grey and carry an icon.
 */
export function LifecycleBadge({ life, verdict }: { life: Lifecycle; verdict: Verdict }) {
  const tone = verdict === 'up' ? 'text-up' : 'text-down'
  const left = minutes(life.remaining)
  const moved = pts(life.change)

  let text: string
  let cls: string
  let title = RULE
  switch (life.state) {
    case 'edge':
      text = `◆ Not priced in · ${left} left`
      cls = `${tone} edge-glow border-current`
      title = `Strong call and the price has not moved yet. ${RULE}`
      break
    case 'watching':
      text = `Watching · ${left} left`
      cls = 'text-muted border-line'
      break
    case 'following':
      text = `↗ Following ${moved}`
      cls = `${tone} border-current/50`
      break
    case 'against':
      text = `↘ Against ${moved}`
      cls = 'text-muted border-line'
      break
    case 'priced_in':
      text = `✓ Priced in ${moved}${life.leadSeconds != null ? ` · ${minutes(life.leadSeconds)} early` : ''}`
      cls = `${tone} border-current/50`
      break
    case 'faded':
      text = `✗ Faded ${moved}`
      cls = 'text-muted border-line'
      break
    case 'flat':
      text = 'No move'
      cls = 'text-faint border-line'
      break
  }

  return (
    <span
      title={title}
      className={`num inline-flex items-center rounded border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider ${cls}`}
    >
      {text}
    </span>
  )
}
