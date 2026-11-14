import { loadMarket } from '../hooks/useStream'
import { useStore } from '../state/store'
import { api } from './api'
import { announceTick, forgetTicks } from './bus'
import { tickLifecycle } from './lifecycle'
import type { PricePoint, Tick } from './types'

const FRAME_MS = 100
/** The big price follows every this many frames: changed ten times a second it only flickers. */
const PRICE_EVERY = 5
/** How long a replay takes on screen: longer for a busier tape, so its rows can be read as they land. */
const seconds = (ticks: number) => Math.min(90, Math.max(45, 40 + ticks * 0.5))

let timer: ReturnType<typeof setInterval> | undefined

/**
 * Play a finished market back from its first price: the chart draws, each post lands on the tape when it
 * was posted, and its call is judged as the price goes on. The backend serves the whole replay; the
 * playing is this screen's own, so two screens can watch at different moments.
 */
export async function playReplay(id: string): Promise<void> {
  stopReplay()
  const meta = useStore.getState().markets[id]?.replay
  if (!meta) return
  let ticks: Tick[]
  let prices: PricePoint[]
  try {
    ;[ticks, prices] = await Promise.all([api.ticks(id, 500), api.prices(id)])
  } catch {
    return // backend unreachable: the connection dot already says so
  }
  if (prices.length < 2 || useStore.getState().selectedId !== id) return
  ticks = [...ticks].sort((a, b) => a.ts - b.ts)
  forgetTicks(ticks.map((t) => t.id))
  useStore.getState().startReplay(id, prices[0], meta.start, prices.length)

  const t0 = performance.now()
  const length = seconds(ticks.length) * 1000
  let shownTicks = 0
  let shownPrices = 1
  let frame = 0
  timer = setInterval(() => {
    const k = Math.min(1, (performance.now() - t0) / length)
    const clock = meta.start + (meta.end - meta.start) * k
    while (shownPrices < prices.length && prices[shownPrices].ts <= clock) shownPrices++
    const added: Tick[] = []
    while (shownTicks < ticks.length && ticks[shownTicks].ts <= clock) added.push(ticks[shownTicks++])
    const big = frame++ % PRICE_EVERY === 0 || k === 1 ? prices[shownPrices - 1].price : null
    useStore.getState().replayFrame(clock, prices.slice(0, shownPrices), [...added].reverse(), big)
    added.forEach(announceTick)
    if (k === 1) stopReplay(true)
  }, FRAME_MS)
}

/** Stop where it is and show the whole of it again. `finished`: it reached its end by itself. */
export function stopReplay(finished = false): void {
  clearInterval(timer)
  timer = undefined
  const id = useStore.getState().replay?.id
  if (!id) return
  useStore.getState().endReplay(finished)
  void loadMarket(id)
}

export interface Tally {
  /** Calls whose 15 minutes are over, by what the price did; `open` are still inside theirs. */
  followed: number
  against: number
  flat: number
  open: number
}

/** The scoreboard of a replay as of `now`: every up or down call so far, judged like the tape judges it. */
export function tally(ticks: Tick[] | undefined, prices: PricePoint[] | undefined, now: number): Tally {
  const out: Tally = { followed: 0, against: 0, flat: 0, open: 0 }
  for (const t of ticks ?? []) {
    const life = tickLifecycle(t, prices, false, now)
    if (!life) continue
    if (life.state === 'priced_in') out.followed++
    else if (life.state === 'faded') out.against++
    else if (life.state === 'flat') out.flat++
    else out.open++
  }
  return out
}
