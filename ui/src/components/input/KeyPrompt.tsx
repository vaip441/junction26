import { useState, type FormEvent } from 'react'
import { setWriteKey } from '../../lib/api'
import { useStore } from '../../state/store'

/** Asks once for the shared write key when the backend refuses a write without it. Stored in this browser. */
export function KeyPrompt() {
  const open = useStore((s) => s.needKey)
  const close = useStore((s) => s.setNeedKey)
  const [key, setKey] = useState('')
  if (!open) return null

  const save = (e: FormEvent) => {
    e.preventDefault()
    if (!key.trim()) return
    setWriteKey(key.trim())
    setKey('')
    close(false)
  }

  return (
    <div
      className="dim-in fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4"
      onClick={() => close(false)}
      onKeyDown={(e) => e.key === 'Escape' && close(false)}
    >
      <form
        role="dialog"
        aria-modal="true"
        aria-label="Terminal key"
        onSubmit={save}
        onClick={(e) => e.stopPropagation()}
        className="pop-in flex w-full max-w-sm flex-col gap-3 rounded-xs border border-line bg-panel p-5"
      >
        <h2 className="text-base font-semibold text-text">Terminal key</h2>
        <p className="text-xs text-muted">
          Adding a market or scoring a sentence needs the team's shared key. It is kept in this browser only.
        </p>
        <input
          autoFocus
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          className="field h-9 px-3 text-sm"
        />
        <div className="flex justify-end gap-2">
          <button type="button" onClick={() => close(false)} className="press btn border-transparent!">
            Cancel
          </button>
          <button
            type="submit"
            disabled={!key.trim()}
            className="press btn btn-solid"
          >
            Save
          </button>
        </div>
      </form>
    </div>
  )
}
