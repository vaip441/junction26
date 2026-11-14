import { ConnectionDot } from './ConnectionDot'

export function TopBar() {
  return (
    <header className="flex h-12 shrink-0 items-center gap-4 border-b border-line bg-panel px-4">
      <span className="num text-sm font-bold tracking-widest text-text">TERMINAL</span>
      {/* AskBar arrives in build step 5: a link or plain words -> a tracked market */}
      <input
        disabled
        placeholder="Paste a Kalshi or Polymarket link, or ask a question…"
        className="h-8 min-w-0 flex-1 rounded border border-line bg-bg px-3 text-sm text-text placeholder:text-faint disabled:opacity-60"
      />
      <ConnectionDot />
    </header>
  )
}
