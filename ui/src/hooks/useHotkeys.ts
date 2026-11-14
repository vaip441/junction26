import { useEffect } from 'react'
import { ASK_INPUT_ID } from '../components/input/AskBar'
import { useStore } from '../state/store'

/**
 * Stage control from the keyboard: / ask, R record, W why-did-it-move tab, Space mic (made-up markets), 1-9 jump to a
 * market, Esc closes the record or the question. Ignored while typing in a field, except Esc, which leaves the field.
 */
export function useHotkeys(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const typing = target instanceof Element ? target.closest('input, textarea, [contenteditable="true"]') : null
      if (e.key === 'Escape') {
        const s = useStore.getState()
        if (typing) (target as HTMLElement).blur()
        else if (s.recordOpen) s.toggleRecord(false)
        else if (s.ask) s.clearAsk()
        return
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return

      const s = useStore.getState()
      if (e.key === '/') {
        const input = document.getElementById(ASK_INPUT_ID)
        if (input) {
          e.preventDefault()
          input.focus()
        }
      } else if (e.key === 'r' || e.key === 'R') s.toggleRecord()
      else if (e.key === 'w' || e.key === 'W') s.setTab('moves')
      else if (e.key === ' ') {
        const m = s.selectedId ? s.markets[s.selectedId] : undefined
        if (!m?.made_up) return
        e.preventDefault()
        s.setMic(!s.micOn)
      } else if (/^[1-9]$/.test(e.key)) {
        const id = s.order[Number(e.key) - 1]
        if (id) s.select(id)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
    }
  }, [])
}
