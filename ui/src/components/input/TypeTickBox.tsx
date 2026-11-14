import { useState, type FormEvent } from 'react'
import { sendTick } from '../../lib/actions'

/** Type a sentence instead of saying it: same scoring, labelled TYPED. Always there as the mic's fallback. */
export function TypeTickBox({ marketId }: { marketId: string }) {
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const sentence = text.trim()
    if (!sentence) return
    setText('') // the pending row on the tape shows it is being scored
    setError(null)
    const err = await sendTick(marketId, sentence, 'typed')
    if (err) {
      setError(err)
      setText((now) => now || sentence) // the sentence stays, ready to send again
    }
  }

  return (
    <form onSubmit={submit} className="flex min-w-0 flex-col gap-1">
      <div className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="…or type what you would say"
          className="h-9 min-w-0 flex-1 rounded border border-line bg-bg px-3 text-sm text-text placeholder:text-faint transition-colors focus:border-accent focus:outline-none"
        />
        <button
          type="submit"
          disabled={!text.trim()}
          className="press h-9 shrink-0 rounded border border-line px-3 text-xs font-semibold uppercase tracking-wider text-muted hover:border-accent hover:text-text disabled:opacity-40"
        >
          Score it
        </button>
      </div>
      {error && <p className="text-xs text-down">{error}</p>}
    </form>
  )
}
