import { useStore } from '../../state/store'
import { ConnectionDot } from './ConnectionDot'

function Key({ k, label, on, onClick }: { k: string; label: string; on?: boolean; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1 text-xs ${on ? 'text-text' : 'text-muted'} hover:text-text`}
      title={`${label} (${k})`}
    >
      <kbd className="num rounded border border-line px-1 text-[10px] text-faint">{k}</kbd>
      {label}
    </button>
  )
}

export function TopBar() {
  const muted = useStore((s) => s.muted)
  const presentation = useStore((s) => s.presentation)
  const toggleMute = useStore((s) => s.toggleMute)
  const togglePresentation = useStore((s) => s.togglePresentation)
  return (
    <header className="flex h-12 shrink-0 items-center gap-4 border-b border-line bg-panel px-4">
      <span className="num text-sm font-bold tracking-widest text-text">TERMINAL</span>
      {/* AskBar arrives in build step 5: a link or plain words -> a tracked market */}
      {!presentation && (
        <input
          disabled
          placeholder="Paste a Kalshi or Polymarket link, or ask a question…"
          className="h-8 min-w-0 flex-1 rounded border border-line bg-bg px-3 text-sm text-text placeholder:text-faint disabled:opacity-60"
        />
      )}
      <div className={`flex items-center gap-4 ${presentation ? 'ml-auto' : ''}`}>
        <Key k="M" label={muted ? 'muted' : 'voice on'} on={!muted} onClick={toggleMute} />
        <Key k="P" label="present" on={presentation} onClick={() => togglePresentation()} />
        <ConnectionDot />
      </div>
    </header>
  )
}
