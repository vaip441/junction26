import type { Move } from './types'

/** A cause the model puts at 40% or more is "likely"; below that, with a dozen items splitting the vote, "possible". */
const LIKELY = 0.4

/** The backend's word for how sure the cause is, and its figure where the figure is worth showing. */
export function causeLabel(move: Move): { label: string; percent: number | null } {
  const sure = (move.confidence ?? 0) >= LIKELY
  return { label: sure ? 'Likely cause' : 'Possible cause', percent: sure && move.confidence != null ? Math.round(move.confidence * 100) : null }
}
