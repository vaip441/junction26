import { useEffect, useState } from 'react'

/**
 * A button for something that cannot be undone. Two clicks, so a stray one on stage does nothing: the
 * label, then the question, which goes back to the label if it is not answered within a few seconds.
 */
export function ConfirmButton({ label, question, title, onConfirm }: { label: string; question: string; title: string; onConfirm: () => void }) {
  const [armed, setArmed] = useState(false)
  useEffect(() => {
    if (!armed) return
    const timer = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(timer)
  }, [armed])
  return (
    <button
      onClick={() => {
        if (!armed) return setArmed(true)
        setArmed(false)
        onConfirm()
      }}
      title={title}
      className={`press rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wider ${
        armed ? 'border-down/60 text-down' : 'border-line text-faint hover:text-text'
      }`}
    >
      {armed ? question : label}
    </button>
  )
}
