import { useEffect, useState } from 'react'
import type { Timing } from '../../lib/types'
import { useStore } from '../../state/store'

/** A duration in the unit a person would say it in: "2.1 s", "4 min", "3 h". */
function duration(seconds: number): string {
  if (seconds < 10) return `${seconds.toFixed(1)} s`
  if (seconds < 90) return `${Math.round(seconds)} s`
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`
  return `${Math.round(seconds / 3600)} h`
}

function every(seconds: number): string {
  return seconds < 120 ? `${seconds} s` : `${Math.round(seconds / 60)} min`
}

/** This screen's own clock. Not useNow: on a replay that tells the replay's time, and this line is about now. */
function useClock(everyMs: number): number {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), everyMs)
    return () => clearInterval(t)
  }, [everyMs])
  return now
}

function Cell({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <span title={title} className="flex items-center gap-1.5 whitespace-nowrap">
      {children}
    </span>
  )
}

function Measured({ label, t, title }: { label: string; t: Timing; title: string }) {
  if (t.median == null || t.p95 == null) return null // too few ticks to measure: say nothing, not zero
  return (
    <Cell title={`${title} Measured on ${t.n} live ticks of the last 24 hours.`}>
      {label} <span className="num font-semibold text-text">{duration(t.median)}</span> median,{' '}
      <span className="num text-text">{duration(t.p95)}</span> p95 <span className="num text-faint">n={t.n}</span>
    </Cell>
  )
}

/**
 * The line under everything, like a terminal's status line: what kind of data is on screen (live, a replay,
 * a made-up market), whether the stream is connected, when it last brought something for this market, how
 * often the terminal checks, and how fast it has measured itself to be. Every figure is one the backend
 * measured; where there is none yet, the cell is left out. Nothing here moves unless something arrived.
 */
export function StatusLine() {
  const stream = useStore((s) => s.stream)
  const metrics = useStore((s) => s.metrics)
  const market = useStore((s) => (s.selectedId ? s.markets[s.selectedId] : undefined))
  const last = useStore((s) => (s.selectedId ? s.lastLive[s.selectedId] : undefined))
  const now = useClock(1000)

  const connected = stream === 'live'
  const offline = metrics?.mode === 'offline'
  const real = Boolean(market && !market.made_up && !market.replay)

  return (
    <footer className="flex min-h-8 shrink-0 flex-wrap items-center gap-x-5 gap-y-1 border-t border-line bg-panel px-4 py-1.5 text-xs text-muted">
      {market?.replay ? (
        <Cell title="A finished market played back from stored data. Nothing on it was found or scored just now.">
          <span className="tag-replay">REPLAY</span> prerecorded, played from stored data, no new API calls
        </Cell>
      ) : market?.made_up ? (
        <Cell title="An illustrative market: its price is nudged by model-scored input and is not a real market forecast.">
          <span className="rounded-xs bg-madeup/15 px-1.5 font-semibold text-madeup">SYNTHETIC</span> illustrative market, not a real
          forecast
        </Cell>
      ) : real && connected ? (
        <Cell title="A real market, and the stream that carries its prices and ticks is connected.">
          <span className="inv">LIVE</span>
        </Cell>
      ) : real ? (
        <Cell title="A real market, but the stream is not connected: what is on screen may be behind.">
          <span className="rounded-xs border border-line px-1.5 font-semibold text-muted">NOT LIVE</span>
        </Cell>
      ) : null}

      <Cell title="The server-sent-events stream that carries every price and tick to this screen">
        <span className={`h-1.5 w-1.5 rounded-full ${connected ? 'bg-text' : 'border border-muted'}`} />
        {connected ? 'Stream connected' : stream === 'connecting' ? 'Stream connecting…' : 'Stream disconnected, reconnecting…'}
      </Cell>

      {real && connected && last != null && (
        <Cell title="When the stream last carried a price or a tick for this market">
          last update <span className="num text-text">{Math.max(0, Math.round(now - last))} s</span> ago
        </Cell>
      )}

      {real && metrics && !offline && market && (
        <Cell title="How often the terminal asks the venue for the price, and searches the web for this market">
          price checked every <span className="num text-text">{every(metrics.price_check_seconds)}</span>
          {market.poll_seconds > 0 && (
            <>
              , web searched every <span className="num text-text">{every(market.poll_seconds)}</span>
            </>
          )}
        </Cell>
      )}

      {/* measured on live ticks, so shown with a live market only: beside a replay it would read as the replay's */}
      {real && metrics && !offline && (
        <>
          <Measured
            label="found → scored"
            t={metrics.discovery_to_scored}
            title="From the moment an item reached the terminal until it was scored and on the tape."
          />
          <Measured
            label="published → found"
            t={metrics.publication_to_discovery}
            title="From the time the publisher states until the item reached the terminal."
          />
        </>
      )}

      {metrics && (
        <span className="ml-auto whitespace-nowrap text-faint">
          {offline ? 'Offline replay demo: nothing is searched or scored' : 'Live web data by Context.dev'}
        </span>
      )}
    </footer>
  )
}
