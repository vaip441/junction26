// Spoken call-outs (speechSynthesis), with a "speaking" signal so the microphone can pause and the
// terminal never scores its own voice.

type Listener = (speaking: boolean) => void

const listeners = new Set<Listener>()
let queued = 0

function setQueued(n: number) {
  const was = queued > 0
  queued = Math.max(0, n)
  if (was !== queued > 0) for (const fn of listeners) fn(queued > 0)
}

export const voiceAvailable = typeof window !== 'undefined' && 'speechSynthesis' in window

export function isSpeaking(): boolean {
  return queued > 0
}

export function onSpeakingChange(fn: Listener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

/** Speak `text`. Drops it when two call-outs are already waiting, so a burst of ticks never lags minutes behind. */
export function say(text: string): void {
  if (!voiceAvailable || queued >= 2) return
  const u = new SpeechSynthesisUtterance(text)
  u.rate = 1.05
  const done = () => setQueued(queued - 1)
  u.onend = done
  u.onerror = done
  setQueued(queued + 1)
  window.speechSynthesis.speak(u)
}

export function silence(): void {
  if (!voiceAvailable) return
  window.speechSynthesis.cancel()
  setQueued(0)
}
