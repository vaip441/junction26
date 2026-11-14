import { useStore } from '../../state/store'
import { AskBar } from '../input/AskBar'
import { ConnectionDot } from './ConnectionDot'

function Key({ k, label, on, onClick }: { k: string; label: string; on?: boolean; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`press flex items-center gap-1 text-xs ${on ? 'text-text' : 'text-muted'} hover:text-text`}
      title={`${label} (${k})`}
    >
      <kbd className="num rounded border border-line px-1 text-[10px] text-faint">{k}</kbd>
      {label}
    </button>
  )
}

export function TopBar() {
  const presentation = useStore((s) => s.presentation)
  const togglePresentation = useStore((s) => s.togglePresentation)
  return (
    <header className="flex h-12 shrink-0 items-center gap-4 border-b border-line bg-panel px-4">
      <span className="num shrink-0 text-sm font-bold tracking-widest text-text">
        TERMINAL
      </span>
      {!presentation && <AskBar />}
      <div className={`flex shrink-0 items-center gap-4 ${presentation ? 'ml-auto' : ''}`}>
        {/* keyboard hints: no use on a phone, and the ask box needs the width */}
        <span className="hidden items-center gap-4 md:flex">
          <Key k="P" label="present" on={presentation} onClick={() => togglePresentation()} />
        </span>
        <ConnectionDot />
      </div>
    </header>
  )
}
