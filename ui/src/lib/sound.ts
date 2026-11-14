// Short synthesized cues for big moves: no audio files, no dependency.

let ctx: AudioContext | null = null

function audio(): AudioContext | null {
  try {
    ctx ??= new AudioContext()
    if (ctx.state === 'suspended') void ctx.resume()
    return ctx
  } catch {
    return null
  }
}

/** Browsers only allow audio after a user gesture: call this from the first click or key press. */
export function unlockAudio(): void {
  audio()
}

/** A rising (up) or falling (down) glide; a stronger move glides further. */
export function playMove(direction: 1 | -1, strength: number): void {
  const a = audio()
  if (!a) return
  const s = Math.min(1, Math.abs(strength))
  const t0 = a.currentTime
  const from = direction > 0 ? 440 : 520
  const ratio = 1.25 + 0.6 * s
  const to = direction > 0 ? from * ratio : from / ratio

  for (const [type, gainPeak, detune] of [['triangle', 0.14, 0], ['sine', 0.08, 7]] as const) {
    const osc = a.createOscillator()
    const gain = a.createGain()
    osc.type = type
    osc.detune.value = detune
    osc.frequency.setValueAtTime(from, t0)
    osc.frequency.exponentialRampToValueAtTime(to, t0 + 0.28)
    gain.gain.setValueAtTime(0.0001, t0)
    gain.gain.exponentialRampToValueAtTime(gainPeak, t0 + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.45)
    osc.connect(gain).connect(a.destination)
    osc.start(t0)
    osc.stop(t0 + 0.5)
  }
}
