import { useEffect } from 'react'
import { useNow } from '../../hooks/useNow'
import type { MarketEvent } from '../../lib/types'
import { useStore } from '../../state/store'

type StepState = 'done' | 'active' | 'todo' | 'failed'

interface Step {
  label: string
  state: StepState
}

const ICON: Record<StepState, string> = { done: '✓', active: '◌', todo: '·', failed: '✗' }
const TONE: Record<StepState, string> = {
  done: 'text-text',
  active: 'text-accent',
  todo: 'text-faint',
  failed: 'text-down',
}

function last(steps: MarketEvent[], status: string): MarketEvent | undefined {
  return [...steps].reverse().find((s) => s.status === status)
}

/**
 * The search, narrated as a checklist so the wait reads as work: searching venues, contracts found,
 * tracking (or a made-up market), finding sources, ready. Closes itself a few seconds after "ready".
 */
export function AskProgress() {
  const ask = useStore((s) => s.ask)
  const title = useStore((s) => (s.ask?.marketId ? s.markets[s.ask.marketId]?.title : undefined))
  const clear = useStore((s) => s.clearAsk)
  const now = useNow(1000)

  const ready = ask ? last(ask.steps, 'ready') : undefined
  useEffect(() => {
    if (!ready) return
    const t = setTimeout(clear, 5000)
    return () => clearTimeout(t)
  }, [ready, clear])

  if (!ask) return null
  const isLink = /^https?:\/\//i.test(ask.query)
  const found = last(ask.steps, 'found contracts')
  const failedEvent = last(ask.steps, 'failed')
  const tracked = ask.marketId != null

  const steps: Step[] = []
  if (isLink) {
    steps.push({ label: 'Reading the link', state: tracked ? 'done' : 'active' })
  } else {
    steps.push({ label: 'Searching Kalshi and Polymarket', state: found || tracked ? 'done' : 'active' })
    steps.push({
      label:
        found?.count == null
          ? 'Matching contracts to the question'
          : found.count === 0
            ? 'No contract asks this'
            : `Found ${found.count} matching contract${found.count === 1 ? '' : 's'}, picking the best`,
      state: tracked ? 'done' : found ? 'active' : 'todo',
    })
  }
  steps.push({
    label: tracked
      ? ask.matched === false
        ? `Made up a market for it: ${title ?? ask.query}`
        : `Tracking: ${title ?? 'the market'}`
      : 'Tracking the market',
    state: tracked ? 'done' : 'todo',
  })
  steps.push({
    label: 'Finding sources: news, posts, filings',
    state: ready ? 'done' : tracked ? 'active' : 'todo',
  })
  steps.push({
    label: ready ? `Ready: ${ready.ticks ?? 'the'} item${ready.ticks === 1 ? '' : 's'} on the tape` : 'Filling the tape',
    state: ready ? 'done' : 'todo',
  })

  if (ask.error || failedEvent) {
    const i = steps.findIndex((s) => s.state === 'active')
    if (i >= 0) steps[i] = { ...steps[i], state: 'failed' }
  }

  const elapsed = Math.max(0, Math.round(now - ask.started))
  return (
    <div className="absolute left-0 right-0 top-full z-20 mt-1 rounded border border-line bg-panel-2 p-3 shadow-xl">
      <div className="mb-2 flex items-center gap-2">
        <p className="min-w-0 flex-1 truncate text-xs text-muted">
          {isLink ? 'Link' : 'Question'}: <span className="text-text">{ask.query}</span>
        </p>
        {!ready && !ask.error && <span className="num text-[11px] text-faint">{elapsed}s</span>}
        <button type="button" onClick={clear} className="text-xs text-muted hover:text-text" title="Close (Esc)">
          ✕
        </button>
      </div>
      <ol className="flex flex-col gap-1">
        {steps.map((s) => (
          <li key={s.label} className={`flex items-baseline gap-2 text-sm ${TONE[s.state]}`}>
            <span className={`num w-3 shrink-0 text-center ${s.state === 'active' ? 'animate-pulse' : ''}`}>{ICON[s.state]}</span>
            <span className="truncate">{s.label}</span>
          </li>
        ))}
      </ol>
      {ask.error && <p className="mt-2 text-xs text-down">{ask.error}</p>}
    </div>
  )
}
