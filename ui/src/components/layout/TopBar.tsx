import { useStore } from '../../state/store'
import { AskBar } from '../input/AskBar'

/**
 * One bar across the top, cut into cells like the status line of a terminal: the name, the question box,
 * and how many markets are tracked.
 */
export function TopBar() {
  const count = useStore((s) => s.order.length)
  return (
    <header className="flex h-11 shrink-0 items-stretch border-b border-line bg-panel">
      <div className="flex shrink-0 items-center px-4">
        <span className="wordmark text-[0.95rem] leading-none text-text">Terminal</span>
      </div>
      <AskBar />
      {/* no use on a phone, and the question box needs the width */}
      {count > 0 && (
        <span className="hidden shrink-0 items-center border-l border-line px-4 text-xs text-muted lg:flex">
          <span className="num mr-1 text-text">{count}</span> {count === 1 ? 'market' : 'markets'}
        </span>
      )}
    </header>
  )
}
