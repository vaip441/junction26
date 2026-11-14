import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { transcribe } from '../lib/actions'

/** The microphone and an audio worklet are all it needs: every current browser, not only Chrome. */
export const speechInputAvailable =
  typeof window !== 'undefined' &&
  Boolean(navigator.mediaDevices?.getUserMedia) &&
  typeof AudioWorkletNode !== 'undefined'

export type MicState = 'off' | 'starting' | 'listening' | 'unsupported' | 'denied'

const RATE = 16000 // what the recording is sent at: plenty for speech, 32 kB a second
const CHUNK_MS = 100 // loudness is judged in pieces this long
const FLOOR = 0.012 // a room is never quieter than this (RMS of samples in -1..1)
const OVER_NOISE = 2.5 // speech is this many times louder than the room's hum
const START_CHUNKS = 2 // loud pieces in a row that begin a sentence
const END_CHUNKS = 8 // quiet pieces in a row that end it: 0.8 s
const LEAD_CHUNKS = 3 // pieces kept from just before it began, so the first word is whole
const TAIL_CHUNKS = 3 // of the closing silence, this much is sent
const MIN_VOICED = 3 // fewer loud pieces than this is a cough or a clink, not a sentence
const MAX_CHUNKS = 150 // a sentence is cut at 15 s and the rest starts a new one

// Runs on the audio thread: hands the microphone's samples over in CHUNK_MS pieces.
const TAP = `
class Tap extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(Math.round(sampleRate * ${CHUNK_MS} / 1000)); this.n = 0 }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (!ch) return true
    let i = 0
    while (i < ch.length) {
      const k = Math.min(ch.length - i, this.buf.length - this.n)
      this.buf.set(ch.subarray(i, i + k), this.n)
      this.n += k
      i += k
      if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice()); this.n = 0 }
    }
    return true
  }
}
registerProcessor('tap', Tap)
`

/** Mono samples at any rate -> a 16 kHz, 16-bit WAV file. */
function wav(chunks: Float32Array[], rate: number): Blob {
  const length = chunks.reduce((n, c) => n + c.length, 0)
  const all = new Float32Array(length)
  let at = 0
  for (const c of chunks) {
    all.set(c, at)
    at += c.length
  }
  const step = rate / RATE
  const count = Math.floor(length / step)
  const view = new DataView(new ArrayBuffer(44 + count * 2))
  const text = (o: number, s: string) => [...s].forEach((ch, i) => view.setUint8(o + i, ch.charCodeAt(0)))
  text(0, 'RIFF')
  view.setUint32(4, 36 + count * 2, true)
  text(8, 'WAVEfmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, RATE, true)
  view.setUint32(28, RATE * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  text(36, 'data')
  view.setUint32(40, count * 2, true)
  for (let i = 0; i < count; i++) {
    // each output sample is the average of the input samples it covers
    const from = Math.floor(i * step)
    const to = Math.max(from + 1, Math.min(length, Math.floor((i + 1) * step)))
    let sum = 0
    for (let j = from; j < to; j++) sum += all[j]
    const v = Math.max(-1, Math.min(1, sum / (to - from)))
    view.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true)
  }
  return new Blob([view], { type: 'audio/wav' })
}

/**
 * Open the microphone and cut what it hears into sentences by the pauses between them. Each sentence is
 * handed over as a WAV recording. Returns the function that closes the microphone (a sentence being said
 * at that moment is still handed over).
 */
async function listen(onRecording: (audio: Blob) => void, onHearing: (hearing: boolean) => void): Promise<() => void> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  })
  const ctx = new AudioContext()
  const url = URL.createObjectURL(new Blob([TAP], { type: 'application/javascript' }))
  try {
    await ctx.audioWorklet.addModule(url)
  } catch (e) {
    stream.getTracks().forEach((t) => t.stop())
    void ctx.close()
    throw e
  } finally {
    URL.revokeObjectURL(url)
  }
  if (ctx.state === 'suspended') await ctx.resume()
  const source = ctx.createMediaStreamSource(stream)
  const tap = new AudioWorkletNode(ctx, 'tap', { numberOfInputs: 1, numberOfOutputs: 1 })
  const mute = ctx.createGain() // the graph only runs when it ends at the speakers; nothing is played
  mute.gain.value = 0
  source.connect(tap).connect(mute).connect(ctx.destination)

  let noise = FLOOR / OVER_NOISE
  let lead: Float32Array[] = []
  let sentence: Float32Array[] | null = null
  let loud = 0
  let quiet = 0
  let voiced = 0

  const finish = () => {
    if (sentence && voiced >= MIN_VOICED) {
      onRecording(wav(sentence.slice(0, sentence.length - Math.max(0, quiet - TAIL_CHUNKS)), ctx.sampleRate))
    }
    sentence = null
    loud = quiet = voiced = 0
    onHearing(false)
  }

  tap.port.onmessage = (e: MessageEvent<Float32Array>) => {
    const chunk = e.data
    let sum = 0
    for (let i = 0; i < chunk.length; i++) sum += chunk[i] * chunk[i]
    const rms = Math.sqrt(sum / chunk.length)
    const threshold = Math.max(FLOOR, noise * OVER_NOISE)
    if (!sentence) {
      lead.push(chunk)
      if (rms > threshold) loud++
      else {
        loud = 0
        noise = noise * 0.95 + rms * 0.05 // the room's hum, learned while nobody speaks
      }
      if (lead.length > LEAD_CHUNKS + START_CHUNKS) lead.shift()
      if (loud >= START_CHUNKS) {
        sentence = lead
        lead = []
        voiced = loud
        quiet = 0
        onHearing(true)
      }
      return
    }
    sentence.push(chunk)
    if (rms > threshold * 0.7) {
      voiced++
      quiet = 0
    } else {
      quiet++
    }
    if (quiet >= END_CHUNKS || sentence.length >= MAX_CHUNKS) finish()
  }

  return () => {
    tap.port.onmessage = null
    finish()
    source.disconnect()
    stream.getTracks().forEach((t) => t.stop())
    void ctx.close()
  }
}

/**
 * Continuous speech to sentences. The browser only records: each sentence, cut at a pause, goes to the
 * backend, where Gemini writes down what was said (POST /transcribe), and the words go to `onSentence` in
 * the order they were spoken. `hearing` is true while someone is speaking, `writing` while a sentence is
 * with the model. A failure goes to `onError`, in words to show.
 */
export function useSpeechInput(onSentence: (text: string) => void, onError?: (text: string) => void) {
  const [state, setState] = useState<MicState>(speechInputAvailable ? 'off' : 'unsupported')
  const [hearing, setHearing] = useState(false)
  const [writing, setWriting] = useState(0)
  const wanted = useRef(false)
  const opening = useRef(false)
  const close = useRef<(() => void) | null>(null)
  const order = useRef<Promise<void>>(Promise.resolve())
  const sentence = useRef(onSentence)
  const failed = useRef(onError)
  useLayoutEffect(() => {
    sentence.current = onSentence
    failed.current = onError
  })

  const recorded = useCallback((audio: Blob) => {
    setWriting((n) => n + 1)
    const answer = transcribe(audio) // sent at once; handed on in the order spoken
    order.current = order.current.then(async () => {
      const heard = await answer
      setWriting((n) => n - 1)
      if ('error' in heard) failed.current?.(heard.error)
      else if (heard.text.length >= 4) sentence.current(heard.text)
    })
  }, [])

  const start = useCallback(() => {
    wanted.current = true
    if (!speechInputAvailable || close.current || opening.current) return
    opening.current = true
    setState('starting')
    listen(recorded, setHearing)
      .then((stop) => {
        if (!wanted.current) return stop() // switched off while the browser was asking for permission
        close.current = stop
        setState('listening')
      })
      .catch((e: unknown) => {
        wanted.current = false
        const name = e instanceof DOMException ? e.name : ''
        setState(name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'unsupported')
      })
      .finally(() => {
        opening.current = false
      })
  }, [recorded])

  const stop = useCallback(() => {
    wanted.current = false
    close.current?.()
    close.current = null
    setHearing(false)
    setState((s) => (s === 'unsupported' || s === 'denied' ? s : 'off'))
  }, [])

  useEffect(() => () => stop(), [stop])

  return { state, hearing, writing: writing > 0, start, stop }
}
