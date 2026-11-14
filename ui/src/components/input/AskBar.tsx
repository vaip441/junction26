import { useState, type FormEvent } from 'react'
import { askFor } from '../../lib/actions'
import { useStore } from '../../state/store'
import { AskProgress } from './AskProgress'

export const ASK_INPUT_ID = 'ask-input'

/** One box for a Kalshi/Polymarket link or a question in plain words. `/` focuses it. */
export function AskBar() {
  const [text, setText] = useState('')
  const ask = useStore((s) => s.ask)
  const working = Boolean(ask && !ask.marketId && !ask.error)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const query = text.trim()
    if (!query || working) return
    if (await askFor(query)) setText('')
  }

  return (
    <form onSubmit={submit} className="relative min-w-0 flex-1">
      <input
        id={ASK_INPUT_ID}
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={working}
        placeholder="Paste a link or ask anything: “will Jensen step down this year?”   ( / )"
        className="h-8 w-full rounded border border-line bg-bg px-3 text-sm text-text placeholder:text-faint focus:border-accent focus:outline-none disabled:opacity-60"
      />
      {ask && <AskProgress />}
    </form>
  )
}
