import { useStore } from '../state/store'

/**
 * Scroll the tape to a tick and flash it. On a narrow screen the tape may not be on screen yet (it is part
 * of the live view), so the view is opened first and the row is looked for again once it has been drawn.
 */
export function focusTick(id: number): void {
  useStore.getState().setView('live')
  const find = (tries: number) => {
    const row = document.getElementById(`tick-${id}`)
    if (!row) {
      if (tries > 0) setTimeout(() => find(tries - 1), 60)
      return
    }
    row.scrollIntoView({ behavior: 'smooth', block: 'center' })
    row.classList.remove('tape-focus')
    void row.offsetWidth // restart the animation
    row.classList.add('tape-focus')
  }
  find(5)
}
