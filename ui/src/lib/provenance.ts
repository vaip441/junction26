import type { Provenance } from './types'

/** The ways of finding an item that are Context.dev's. Nothing else is ever credited to it. */
const CONTEXT_DEV: readonly Provenance[] = ['context_web_search', 'context_news_search', 'context_monitor']

export function viaContextDev(p: Provenance | undefined): boolean {
  return p != null && CONTEXT_DEV.includes(p)
}

/** The way of finding, as a name: for the counts in the Sources tab. */
export const FOUND_BY: Record<Provenance, string> = {
  context_web_search: 'Context.dev web search',
  context_news_search: 'Context.dev news',
  context_monitor: 'Context.dev monitor',
  google_news: 'Google News',
  reddit: 'Reddit feed',
  polymarket_comments: 'Polymarket comments',
  bluesky: 'Bluesky search',
  truth_social: 'Truth Social feed',
  microphone: 'Microphone',
  typed: 'Typed',
  replay: 'Prerecorded replay',
  unknown: 'Not recorded',
}

/**
 * The words beside a tick that say how it was found, apart from who published it. Null where there is
 * nothing to say: a spoken or typed line says so in its tag already, and an older tick's way was not recorded.
 */
export function foundVia(p: Provenance | undefined): string | null {
  if (p == null || p === 'unknown' || p === 'microphone' || p === 'typed') return null
  if (p === 'replay') return 'Prerecorded replay'
  return `Found via ${FOUND_BY[p]}`
}
