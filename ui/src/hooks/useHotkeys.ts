import { useEffect } from 'react'
import { unlockAudio } from '../lib/sound'
import { useStore } from '../state/store'

/**
 * Stage control from the keyboard: P presentation, M mute, Space mic (made-up markets), 1-9 jump to a
 * market, Esc leaves presentation. Ignored while typing in a field, except Esc, which leaves the field.
 */
export function useHotkeys(): void {
  useEffect(() => {
    const unlock = () => unlockAudio()
    window.addEventListener('pointerdown', unlock, { once: true })

    const onKey = (e: KeyboardEvent) => {
      unlockAudio()
      const target = e.target as HTMLElement | null
      const typing = target?.closest('input, textarea, [contenteditable="true"]')
      if (e.key === 'Escape') {
        if (typing) (target as HTMLElement).blur()
        else useStore.getState().togglePresentation(false)
        return
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return

      const s = useStore.getState()
      if (e.key === 'p' || e.key === 'P') s.togglePresentation()
      else if (e.key === 'm' || e.key === 'M') s.toggleMute()
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
      window.removeEventListener('pointerdown', unlock)
    }
  }, [])
}
