import type { Move } from './types'

/** An item the model puts at 40% or more is the "likely" explanation; below that, with a dozen items splitting
 *  the vote, a "possible" one. Never "the cause": the model picks the best match among the items found, and a
 *  price can move for reasons nobody posted. */
const LIKELY = 0.4

/** The backend's word for how sure the cause is, and its figure where the figure is worth showing. */
export function causeLabel(move: Move): { label: string; percent: number | null } {
  const sure = (move.confidence ?? 0) >= LIKELY
  return { label: sure ? 'Likely explanation' : 'Possible explanation', percent: sure && move.confidence != null ? Math.round(move.confidence * 100) : null }
}
