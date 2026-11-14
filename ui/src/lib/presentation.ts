import type { MarketSummary } from './types'

const params = typeof window === 'undefined' ? new URLSearchParams() : new URLSearchParams(window.location.search)

/**
 * Presentation mode (`?presentation=1`): the screen as shown from a projector. Larger type, a wider tape,
 * and it opens on a market with something on it, never on the empty made-up one. Nothing plays or listens
 * by itself: a replay waits for its button, the microphone for its key.
 */
export const presentation = ['1', 'true', 'on'].includes((params.get('presentation') ?? '').toLowerCase())

/** `?market=<id>`: the market to open on, in or out of presentation mode. */
export const wantedMarket = params.get('market')

const busiest = (list: MarketSummary[]) => [...list].sort((a, b) => b.ticks_today - a.ticks_today)[0]

/**
 * Which market the screen opens on. Normally the first in the list. With `?market=` that one, if it is
 * tracked. In presentation mode: a real market with ticks on its tape when there is one, else a replay
 * (the offline demo has only those), and the made-up market only when it is all there is. It stays in the
 * list for the closing interaction.
 */
export function openingMarket(list: MarketSummary[]): string | null {
  if (wantedMarket && list.some((m) => m.id === wantedMarket)) return wantedMarket
  if (!presentation) return list[0]?.id ?? null
  const real = list.filter((m) => !m.made_up && !m.replay)
  const replays = list.filter((m) => m.replay)
  const pick =
    busiest(real.filter((m) => m.ticks_today > 0 && m.price != null)) ??
    busiest(replays.filter((m) => m.ticks_today > 0)) ??
    real[0] ??
    replays[0] ??
    list[0]
  return pick?.id ?? null
}
