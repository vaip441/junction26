import { pts } from '../../lib/format'
import { MIN_MOVE, WINDOW_SECONDS, type Lifecycle } from '../../lib/lifecycle'
import type { Verdict } from '../../lib/types'

function minutes(seconds: number): string {
  return `${Math.max(1, Math.round(seconds / 60))} min`
}

const RULE = `Judged like the weekend record: the price ${WINDOW_SECONDS / 60} min after the tick against the price when it arrived; under ${MIN_MOVE} pt counts as no move.`

/**
 * What the price did after this call, as a line of text. Colour still means verdict only: states where the
 * price went our way take the verdict colour, the rest stay grey and carry an icon. The one state that is a
 * block, reversed out in the verdict colour, is the call the price has not caught up with yet.
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
      text = `Not priced in, ${left} left`
      cls = `inv ${verdict === 'up' ? 'inv-up' : 'inv-down'}`
      title = `Strong call and the price has not moved yet. ${RULE}`
      break
    case 'watching':
      text = `Watching, ${left} left`
      cls = 'text-muted'
      break
    case 'following':
      text = `↗ Following ${moved}`
      cls = `${tone} font-semibold`
      break
    case 'against':
      text = `↘ Against ${moved}`
      cls = 'text-muted'
      break
    case 'priced_in':
      text = `✓ Priced in ${moved}${life.leadSeconds != null ? `, ${minutes(life.leadSeconds)} early` : ''}`
      cls = `${tone} font-semibold`
      break
    case 'faded':
      text = `✗ Faded ${moved}`
      cls = 'text-muted'
      break
    case 'flat':
      text = 'No move'
      cls = 'text-faint'
      break
  }

  return (
    <span title={title} className={`num whitespace-nowrap text-xs ${cls}`}>
      {text}
    </span>
  )
}
