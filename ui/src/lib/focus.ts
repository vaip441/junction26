/** Scroll the tape to a tick and flash it. */
export function focusTick(id: number): void {
  const row = document.getElementById(`tick-${id}`)
  if (!row) return
  row.scrollIntoView({ behavior: 'smooth', block: 'center' })
  row.classList.remove('tape-focus')
  void row.offsetWidth // restart the animation
  row.classList.add('tape-focus')
}
