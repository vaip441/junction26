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
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4" onClick={() => close(false)}>
      <form
        onSubmit={save}
        onClick={(e) => e.stopPropagation()}
        className="flex w-full max-w-sm flex-col gap-3 rounded border border-line bg-panel p-5"
      >
        <h2 className="text-sm font-semibold text-text">Terminal key</h2>
        <p className="text-xs text-muted">
          Adding markets and scoring sentences need the team's shared key. It is kept in this browser only.
        </p>
        <input
          autoFocus
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          className="h-9 rounded border border-line bg-bg px-3 text-sm text-text focus:border-accent focus:outline-none"
        />
        <div className="flex justify-end gap-2">
          <button type="button" onClick={() => close(false)} className="px-3 py-1.5 text-xs text-muted hover:text-text">
            Cancel
          </button>
          <button type="submit" className="rounded border border-accent/60 px-3 py-1.5 text-xs font-semibold text-text">
            Save
          </button>
        </div>
      </form>
    </div>
  )
}
