import { useNow } from '../../hooks/useNow'
import { pct } from '../../lib/format'
import type { Investigation, InvestigationStep } from '../../lib/types'
import { useStore } from '../../state/store'
import { SourceIcon } from '../common/SourceIcon'

function minutes(seconds: number): string {
  const m = Math.max(1, Math.round(seconds / 60))
  return m >= 90 ? `${Math.round(m / 60)} h` : `${m} min`
}

function host(url: string): string {
  return url.replace(/^https?:\/\//, '').split('/')[0].replace(/^www\./, '')
}

/** Each agent with its newest step and how many it has made, in the order the agents first appeared. */
function byAgent(steps: InvestigationStep[]): { agent: string; step: InvestigationStep; count: number }[] {
  const out = new Map<string, { agent: string; step: InvestigationStep; count: number }>()
  for (const s of steps) {
    const lane = out.get(s.agent)
    if (lane) {
      lane.step = s
      lane.count += 1
    } else out.set(s.agent, { agent: s.agent, step: s, count: 1 })
  }
  return [...out.values()]
}

/** How a step stands: a pulse while it runs, a mark when it is over. Never a colour: colour means the verdict. */
function Mark({ status }: { status: InvestigationStep['status'] }) {
  if (status === 'running') return <span className="mt-[0.35em] inline-block h-1.5 w-1.5 shrink-0 animate-pulse bg-text" aria-label="working" />
  return (
    <span className="w-1.5 shrink-0 text-center text-faint" aria-label={status === 'done' ? 'done' : 'failed'}>
      {status === 'done' ? '✓' : '✗'}
    </span>
  )
}

/** What a step is doing; a link, with the site's logo, when it is reading a page. */
function Doing({ step }: { step: InvestigationStep }) {
  if (!step.url) return <>{step.text}</>
  return (
    <a href={step.url} target="_blank" rel="noreferrer" className="inline-flex min-w-0 items-center gap-1.5 hover:underline" title={step.url}>
      <SourceIcon source={host(step.url)} className="h-3 w-3" />
      <span className="truncate">{step.text}</span>
    </a>
  )
}

/** What an investigation cost and how long it took, in one line of figures. */
function Spent({ inv, seconds }: { inv: Investigation; seconds: number }) {
  return (
    <span className="num flex flex-wrap gap-x-3 text-muted">
      <span>{inv.model}</span>
      <span>
        <span className="font-semibold text-text">{seconds.toFixed(1)}</span> s
      </span>
      <span>
        Context.dev <span className="font-semibold text-text">{inv.requests}</span> {inv.requests === 1 ? 'request' : 'requests'}
        {inv.credits != null && (
          <>
            , <span className="font-semibold text-text">{inv.credits}</span> credits
          </>
        )}
      </span>
    </span>
  )
}

/**
 * A price move being looked into, as it happens: one row per agent, each showing what that agent is doing
 * now and what its last step found. The agents work at the same time, so several rows pulse at once.
 * Shown at the top of "Why did it move?" while it runs; when it ends, its answer is the move under it and
 * the steps stay there, behind a button.
 */
export function LiveInvestigation({ inv }: { inv: Investigation }) {
  const dismiss = useStore((s) => s.dismissInvestigation)
  const now = useNow(100)
  const failed = inv.status === 'failed'
  const seconds = Math.max(0, (inv.ended ?? now) - inv.ts)
  return (
    <section aria-label="Investigation" className="border-b border-line bg-panel-2 px-3 py-2.5">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs">
        <span className="inv">{failed ? 'Investigation stopped' : 'Investigating'}</span>
        <span className={`num text-sm font-bold ${inv.to >= inv.from ? 'text-up' : 'text-down'}`}>
          {pct(inv.from)} → {pct(inv.to)}
        </span>
        <span className="text-muted">{inv.asked ? 'over the last day' : `in ${minutes(inv.ts - inv.since)}`}</span>
        <span className="ml-auto flex items-baseline gap-3">
          <Spent inv={inv} seconds={seconds} />
          {failed && (
            <button onClick={() => dismiss(inv.market_id)} className="text-muted hover:text-text" title="Close" aria-label="Close">
              ✕
            </button>
          )}
        </span>
      </header>
      {failed && <p className="mt-1.5 text-xs text-muted">{inv.error ?? 'It could not be finished.'} The answer below comes from a single search.</p>}
      <ol className="mt-2 flex flex-col gap-1">
        {byAgent(inv.steps).map(({ agent, step, count }) => (
          <li key={agent} className="grid grid-cols-[4.5rem_minmax(0,1fr)_minmax(0,1fr)] items-baseline gap-x-3 text-xs">
            <span className={`truncate font-semibold ${step.status === 'running' ? 'text-text' : 'text-muted'}`} title={`${count} ${count === 1 ? 'step' : 'steps'} so far`}>
              {agent}
            </span>
            {/* keyed by the step, so a new one fades in over the last */}
            <span key={step.id} className="soft-in flex min-w-0 items-baseline gap-2 text-muted">
              <Mark status={step.status} />
              <span className="min-w-0 truncate" title={step.text}>
                <Doing step={step} />
              </span>
            </span>
            <span key={`${step.id}-found`} className="soft-in min-w-0 truncate text-text" title={step.found ?? undefined}>
              {step.found ?? ''}
            </span>
          </li>
        ))}
        {inv.steps.length === 0 && <li className="text-xs text-muted">Starting…</li>}
      </ol>
    </section>
  )
}

/** Every step of a finished investigation, in the order they started, with when each began. */
export function InvestigationLog({ inv }: { inv: Investigation }) {
  return (
    <ol className="mt-1 flex flex-col gap-0.5 border-l-2 border-line pl-2">
      {inv.steps.map((s) => (
        <li key={s.id} className="grid grid-cols-[3rem_3.5rem_minmax(0,1fr)] items-baseline gap-x-2 text-[11px] leading-snug">
          <span className="num text-right text-faint">+{(s.started - inv.ts).toFixed(1)} s</span>
          <span className="truncate font-semibold text-muted">{s.agent}</span>
          <span className="min-w-0 text-muted">
            <Doing step={s} />
            {s.status === 'failed' && <span className="text-faint"> (did not finish)</span>}
            {s.found && <span className="text-text">: {s.found}</span>}
          </span>
        </li>
      ))}
    </ol>
  )
}

/** One line that says how a move was worked out, for the row of that move. */
export function InvestigationLine({ inv }: { inv: Investigation }) {
  const agents = new Set(inv.steps.map((s) => s.agent)).size
  const seconds = Math.max(0, (inv.ended ?? inv.ts) - inv.ts)
  return (
    <>
      Worked out by {agents} {agents === 1 ? 'agent' : 'agents'} in {seconds.toFixed(1)} s, {inv.requests} Context.dev{' '}
      {inv.requests === 1 ? 'request' : 'requests'}
    </>
  )
}

