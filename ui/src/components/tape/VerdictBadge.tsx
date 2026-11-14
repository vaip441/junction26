import type { Verdict } from '../../lib/types'

const LOOK: Record<Verdict, { label: string; arrow: string; tone: string }> = {
  up: { label: 'UP', arrow: '▲', tone: 'text-up' },
  down: { label: 'DOWN', arrow: '▼', tone: 'text-down' },
  none: { label: 'NO EFFECT', arrow: '•', tone: 'text-none' },
}

/** Verdict and its confidence. `strength` (-1..1) sets how strongly the colour glows. */
export function VerdictBadge({ verdict, confidence, strength }: { verdict: Verdict; confidence: number; strength: number }) {
  const look = LOOK[verdict]
  const opacity = verdict === 'none' ? 1 : 0.55 + 0.45 * Math.min(1, Math.abs(strength))
  return (
    <span className={`num inline-flex items-baseline gap-1 text-xs font-bold ${look.tone}`} style={{ opacity }}>
      <span>{look.arrow}</span>
      <span>{look.label}</span>
      <span className="font-normal">{Math.round(confidence * 100)}%</span>
    </span>
  )
}
