import { useEffect, useMemo, useRef } from 'react'
import { useStore } from '../../state/store'
import { EmptyState } from '../common/EmptyState'

interface Cited {
  start: number
  end: number
  count: number
}

/**
 * How the market resolves, and the phrases the terminal searches the web with for it. Sentences that a
 * tick or a move points at are highlighted in place, stronger the more items cite them.
 */
export function RulesPanel({ marketId, rules, queries }: { marketId: string; rules: string; queries: string[] | null }) {
  const ticks = useStore((s) => s.ticks[marketId])
  const moves = useStore((s) => s.moves[marketId])
  const focus = useStore((s) => s.focusRule)
  const focused = useRef<HTMLElement | null>(null)

  const cited = useMemo(() => {
    const spans = new Map<string, Cited>()
    const cite = (r: { start: number; end: number } | null | undefined) => {
      // positions are only good for the rules text they were chosen from
      if (!r || r.start < 0 || r.end > rules.length || r.end <= r.start) return
      const key = `${r.start}-${r.end}`
      const c = spans.get(key) ?? { start: r.start, end: r.end, count: 0 }
      c.count += 1
      spans.set(key, c)
    }
    for (const t of ticks ?? []) cite(t.rule)
    for (const m of moves ?? []) if (!m.cause?.rule) cite(m.rule) // its cause's rule is counted on the tick
    // sentences never overlap; if two spans ever did, the earlier one wins
    const out: Cited[] = []
    for (const c of [...spans.values()].sort((a, b) => a.start - b.start)) {
      if (!out.length || c.start >= out[out.length - 1].end) out.push(c)
    }
    return out
  }, [ticks, moves, rules])

  useEffect(() => {
    const el = focused.current
    if (!focus || !el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.remove('tape-focus')
    void el.offsetWidth // restart the animation
    el.classList.add('tape-focus')
  }, [focus])

  if (!rules && !queries?.length) return <EmptyState title="No rules given" />

  const parts: React.ReactNode[] = []
  let at = 0
  for (const c of cited) {
    if (c.start > at) parts.push(rules.slice(at, c.start))
    const isFocus = focus?.start === c.start && focus.end === c.end
    parts.push(
      <mark
        key={c.start}
        ref={isFocus ? focused : undefined}
        title={`${c.count} ${c.count === 1 ? 'item points' : 'items point'} at this sentence`}
        className={`rounded-sm px-0.5 text-text ${c.count >= 3 ? 'bg-accent/35' : c.count === 2 ? 'bg-accent/25' : 'bg-accent/15'}`}
      >
        {rules.slice(c.start, c.end)}
      </mark>,
    )
    at = c.end
  }
  if (at < rules.length) parts.push(rules.slice(at))

  return (
    <div className="flex flex-col gap-3 p-3">
      {rules && <p className="whitespace-pre-line text-xs leading-relaxed text-muted">{parts}</p>}
      {cited.length > 0 && <p className="text-[10px] text-faint">Highlighted: the sentences that made an item on the tape matter.</p>}
      {queries && queries.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-faint">What it searches the web for</span>
          <div className="flex flex-wrap gap-1.5">
            {queries.map((q) => (
              <span key={q} className="rounded border border-line bg-bg px-2 py-0.5 text-xs text-text">
                {q}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
