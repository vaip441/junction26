import { useState, type FormEvent } from 'react'
import { askFor } from '../../lib/actions'
import { useStore } from '../../state/store'

export const ASK_INPUT_ID = 'ask-input'

/**
 * One box for a Kalshi/Polymarket link or a question in plain words. `/` focuses it. What happens next is
 * shown on the centre of the screen (AskStage), not here.
 */
export function AskBar() {
  const [text, setText] = useState('')
  const ask = useStore((s) => s.ask)
  const working = Boolean(ask && !ask.marketId && !ask.error)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const query = text.trim()
    if (!query || working) return
    // leave the field while it works (it is disabled, and a disabled field with focus swallows every key),
    // so P, R and the number keys work again as soon as the question is sent
    const input = document.getElementById(ASK_INPUT_ID)
    input?.blur()
    if (await askFor(query)) setText('')
    else input?.focus() // it failed: back in the field, ready to fix the question
  }

  return (
    <form onSubmit={submit} className="relative min-w-0 flex-1">
      <input
        id={ASK_INPUT_ID}
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={working}
        placeholder="Paste a link or ask anything: “will Jensen step down this year?”   ( / )"
        className="h-8 w-full rounded border border-line bg-bg px-3 text-sm text-text placeholder:text-faint transition-colors focus:border-accent focus:outline-none disabled:opacity-60"
      />
    </form>
  )
}
