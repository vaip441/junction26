import { useState, type ReactNode } from 'react'
import { useStore, type View } from '../../state/store'

const ICON = { fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' } as const

const VIEWS: { id: View; label: string; icon: ReactNode }[] = [
  {
    id: 'markets',
    label: 'Markets',
    icon: <path {...ICON} d="M4 7h16M4 12h16M4 17h16" />,
  },
  {
    id: 'live',
    label: 'Live',
    // the mark itself: a price line that jumps where a dot of news lands
    icon: (
      <>
        <path {...ICON} d="M3 16h7V8h11" />
        <circle cx="10" cy="16" r="3" fill="var(--color-up)" stroke="var(--color-panel)" strokeWidth="1.5" />
      </>
    ),
  },
  {
    id: 'details',
    label: 'Details',
    icon: (
      <>
        <circle {...ICON} cx="12" cy="12" r="8.5" />
        <path {...ICON} d="M12 11v5.5M12 7.5v.5" />
      </>
    ),
  },
]

/**
 * How a narrow screen is moved around: three views, one on screen at a time, picked from a bar under the
 * thumb. The list of markets; the picked market live (its chart with the tape under it); the details
 * behind it. Each view scrolls as one page, so a finger never lands in a box that scrolls on its own.
 * Tapping the view already on screen takes it back to its top.
 */
export function BottomNav({ onAgain }: { onAgain: () => void }) {
  const view = useStore((s) => s.view)
  const setView = useStore((s) => s.setView)
  const count = useStore((s) => s.order.length)
  // something landed on the tape while another view was on screen: a dot on Live says so
  const newest = useStore((s) => (s.selectedId ? s.ticks[s.selectedId]?.[0]?.id : undefined))
  const [seen, setSeen] = useState(newest)
  if (view === 'live' && seen !== newest) setSeen(newest) // on screen, everything on the tape has been seen
  const unseen = view !== 'live' && newest != null && seen != null && newest !== seen

  return (
    <nav aria-label="Views" className="flex shrink-0 border-t border-line bg-panel pb-[env(safe-area-inset-bottom)]">
      {VIEWS.map((v) => {
        const on = v.id === view
        return (
          <button
            key={v.id}
            onClick={() => (on ? onAgain() : setView(v.id))}
            aria-current={on ? 'page' : undefined}
            className={`relative flex h-13 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold transition-colors ${
              on ? 'text-text shadow-[inset_0_2px_0_var(--color-text)]' : 'text-muted active:text-text'
            }`}
          >
            <span className="relative">
              <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5">
                {v.icon}
              </svg>
              {v.id === 'live' && unseen && (
                <span className="absolute -right-1.5 -top-0.5 h-2 w-2 rounded-full bg-text ring-2 ring-panel" aria-label="new on the tape" />
              )}
            </span>
            <span>
              {v.label}
              {v.id === 'markets' && count > 0 && <span className="num ml-1 font-normal text-faint">{count}</span>}
            </span>
          </button>
        )
      })}
    </nav>
  )
}
