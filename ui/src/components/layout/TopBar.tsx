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
      <div className="flex shrink-0 items-center gap-2 px-4">
        {/* the mark: a price line that jumps where a dot of news lands */}
        <svg aria-hidden="true" viewBox="6 10 36 28" className="h-5 w-auto text-text">
          <path d="M9 31H21V17H39" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="21" cy="31" r="5" fill="var(--color-up)" stroke="var(--color-panel)" strokeWidth="2.5" />
        </svg>
        {/* on a phone the mark stands for the name: the question box needs the width */}
        <span className="wordmark text-[0.95rem] leading-none text-text max-sm:sr-only">Priced In</span>
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
