import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

// The Web Speech API is Chrome-only and missing from TypeScript's DOM types: the part we use.
interface RecognitionResult {
  readonly isFinal: boolean
  readonly 0: { transcript: string }
}
interface RecognitionEvent {
  readonly resultIndex: number
  readonly results: { readonly length: number; readonly [i: number]: RecognitionResult }
}
interface Recognition {
  continuous: boolean
  interimResults: boolean
  lang: string
  start(): void
  abort(): void
  onresult: ((e: RecognitionEvent) => void) | null
  onend: (() => void) | null
  onerror: ((e: { error: string }) => void) | null
  onstart: (() => void) | null
}
type RecognitionCtor = new () => Recognition

const Ctor: RecognitionCtor | undefined =
  typeof window === 'undefined'
    ? undefined
    : ((window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor })
        .SpeechRecognition ??
      (window as unknown as { webkitSpeechRecognition?: RecognitionCtor }).webkitSpeechRecognition)

export const speechInputAvailable = Boolean(Ctor)

export type MicState = 'off' | 'starting' | 'listening' | 'unsupported' | 'denied'

/**
 * Continuous speech to sentences. Each final result goes to `onSentence`; `interim` is the words heard so
 * far, for showing live. Recognition restarts on its own when Chrome ends a session after silence.
 */
export function useSpeechInput(onSentence: (text: string) => void) {
  const [state, setState] = useState<MicState>(Ctor ? 'off' : 'unsupported')
  const [interim, setInterim] = useState('')
  const rec = useRef<Recognition | null>(null)
  const wanted = useRef(false)
  const sentence = useRef(onSentence)
  useLayoutEffect(() => {
    sentence.current = onSentence
  })
  // begin() restarts itself after Chrome ends a session; it reaches itself through this ref
  const restart = useRef<() => void>(() => {})

  const begin = useCallback(() => {
    if (!Ctor || !wanted.current) return
    if (!rec.current) {
      const r = new Ctor()
      r.continuous = true
      r.interimResults = true
      r.lang = 'en-US'
      r.onstart = () => setState('listening')
      r.onresult = (e) => {
        let heard = ''
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const res = e.results[i]
          const text = res[0].transcript.trim()
          if (res.isFinal) {
            if (text.length >= 4) sentence.current(text)
          } else {
            heard += `${text} `
          }
        }
        setInterim(heard.trim())
      }
      r.onerror = (e) => {
        if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
          wanted.current = false
          setState('denied')
        }
        // 'no-speech', 'aborted', 'network': onend restarts it
      }
      r.onend = () => {
        setInterim('')
        if (wanted.current) setTimeout(() => restart.current(), 250)
        else setState((s) => (s === 'denied' ? s : 'off'))
      }
      rec.current = r
    }
    try {
      setState('starting')
      rec.current.start()
    } catch {
      // already started
    }
  }, [])

  useEffect(() => {
    restart.current = begin
  }, [begin])

  const start = useCallback(() => {
    wanted.current = true
    begin()
  }, [begin])

  const stop = useCallback(() => {
    wanted.current = false
    rec.current?.abort()
    setInterim('')
    setState((s) => (s === 'unsupported' || s === 'denied' ? s : 'off'))
  }, [])

  useEffect(() => () => stop(), [stop])

  return { state, interim, start, stop }
}
