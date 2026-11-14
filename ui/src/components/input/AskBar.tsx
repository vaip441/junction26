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
    // a cell of the top bar, not a box inside it: the whole cell is the field, and it darkens while typed in
    <form
      onSubmit={submit}
      className="group flex min-w-0 flex-1 items-center gap-3 border-l border-line px-4 transition-colors focus-within:bg-bg focus-within:shadow-[inset_0_-2px_0_var(--color-text)]"
    >
      <label htmlFor={ASK_INPUT_ID} className="shrink-0 text-xs font-semibold text-muted group-focus-within:text-text">
        Ask
      </label>
      <input
        id={ASK_INPUT_ID}
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={working}
        placeholder="will Jensen step down this year? Or paste a Kalshi or Polymarket link"
        className="h-full min-w-0 flex-1 bg-transparent text-sm text-text placeholder:text-faint focus:outline-none disabled:opacity-60"
      />
      <span className="hidden shrink-0 text-xs text-faint group-focus-within:hidden md:inline" aria-hidden="true">
        press /
      </span>
    </form>
  )
}
