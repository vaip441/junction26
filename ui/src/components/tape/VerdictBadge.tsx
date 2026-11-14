import type { Verdict } from '../../lib/types'

const LOOK: Record<Verdict, { label: string; arrow: string; tone: string }> = {
  up: { label: 'Up', arrow: '▲', tone: 'text-up' },
  down: { label: 'Down', arrow: '▼', tone: 'text-down' },
  none: { label: 'No effect', arrow: '•', tone: 'text-none' },
}

/** Verdict and its confidence. `strength` (-1..1) sets how strong the colour is. */
export function VerdictBadge({ verdict, confidence, strength }: { verdict: Verdict; confidence: number; strength: number }) {
  const look = LOOK[verdict]
  const opacity = verdict === 'none' ? 1 : 0.55 + 0.45 * Math.min(1, Math.abs(strength))
  return (
    <span className={`num inline-flex shrink-0 items-baseline gap-1 whitespace-nowrap text-[0.8125rem] font-bold ${look.tone}`} style={{ opacity }}>
      <span className="text-[0.7em]">{look.arrow}</span>
      <span>{look.label}</span>
      <span className="font-medium">{Math.round(confidence * 100)}%</span>
    </span>
  )
}
