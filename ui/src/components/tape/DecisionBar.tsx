/**
 * The model's three probabilities as one bar: up (green), no effect (grey), down (red). On a fresh tick it
 * fills first and the verdict appears after, so it reads as the decision being made.
 */
export function DecisionBar({ up, none, down, fresh }: { up: number; none: number; down: number; fresh: boolean }) {
  const total = up + none + down || 1
  const pc = (v: number) => `${(v / total) * 100}%`
  return (
    <div
      className={`flex h-[3px] w-full overflow-hidden bg-line ${fresh ? 'bar-grow' : ''}`}
      title={`Up ${Math.round(up * 100)}%, no effect ${Math.round(none * 100)}%, down ${Math.round(down * 100)}%`}
    >
      <span className="h-full bg-up" style={{ width: pc(up) }} />
      <span className="h-full bg-none/50" style={{ width: pc(none) }} />
      <span className="h-full bg-down" style={{ width: pc(down) }} />
    </div>
  )
}
