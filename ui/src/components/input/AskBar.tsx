import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useMedia } from '../../hooks/useMedia'
import { speechInputAvailable, useSpeechInput } from '../../hooks/useSpeechInput'
import { askFor } from '../../lib/actions'
import { NARROW } from '../../lib/device'
import { useStore } from '../../state/store'

export const ASK_INPUT_ID = 'ask-input'

/**
 * One box for a Kalshi/Polymarket link or a question in plain words. `/` focuses it. What happens next is
 * shown on the centre of the screen (AskStage), not here.
 *
 * The question can also be said: the Speak button listens for one sentence, shows the words as they are
 * heard, and asks it when the speaker pauses. The microphone then turns itself off.
 */
export function AskBar() {
  const [text, setText] = useState('')
  const narrow = useMedia(NARROW)
  const ask = useStore((s) => s.ask)
  const working = Boolean(ask && !ask.marketId && !ask.error)
  const [wanted, setListening] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const asked = useRef(false) // one spoken sentence is one question: what is heard after it is not asked too

  const run = async (query: string) => {
    // leave the field while it works (it is disabled, and a disabled field with focus swallows every key),
    // so P, R and the number keys work again as soon as the question is sent
    const input = document.getElementById(ASK_INPUT_ID)
    input?.blur()
    if (await askFor(query)) setText('')
    else input?.focus() // it failed: back in the field, ready to fix the question
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const query = text.trim()
    if (!query || working) return
    void run(query)
  }

  const stopMic = useRef<() => void>(() => {})
  const { state, hearing, writing, interim, start, stop } = useSpeechInput(
    (said) => {
      if (asked.current) return
      asked.current = true
      stopMic.current()
      setListening(false)
      setText(said) // left in the box, so a misheard question can be fixed and sent again
      void run(said)
    },
    (error) => {
      stopMic.current()
      setListening(false)
      setNote(error)
    },
  )
  useEffect(() => {
    stopMic.current = stop
  }, [stop])
  // a blocked microphone is not listening, whatever was asked of it, and the bar says why
  const blocked = state === 'denied' || state === 'unsupported'
  const listening = wanted && !blocked
  const shown = note ?? (wanted && state === 'denied' ? 'Mic blocked: allow it in the address bar' : null)

  const speak = () => {
    setNote(null)
    if (listening) {
      // turned off by hand: a sentence being said at this moment is not asked
      asked.current = true
      stop()
      setListening(false)
      return
    }
    asked.current = false
    useStore.getState().setMic(false) // the made-up market's microphone must not score the question as a tick
    setText('')
    setListening(true)
    start()
  }

  const heard = listening || writing
  const status = !heard
    ? null
    : interim
      ? null // the words themselves are in the box
      : writing && !hearing
        ? 'Writing down what was said…'
        : hearing
          ? 'Hearing you…'
          : state === 'starting'
            ? 'Starting the mic…'
            : 'Listening: say your question'

  return (
    // a cell of the top bar, not a box inside it: the whole cell is the field, and it darkens while typed in
    <form
      onSubmit={submit}
      className="group flex min-w-0 flex-1 items-center gap-3 border-l border-line px-4 transition-colors max-sm:gap-2 max-sm:px-3 focus-within:bg-bg focus-within:shadow-[inset_0_-2px_0_var(--color-text)]"
    >
      <label htmlFor={ASK_INPUT_ID} className="shrink-0 text-xs font-semibold text-muted group-focus-within:text-text">
        Ask
      </label>
      <input
        id={ASK_INPUT_ID}
        value={heard && interim ? interim : text}
        onChange={(e) => setText(e.target.value)}
        disabled={working}
        readOnly={heard}
        // the whole example does not fit beside the Speak button on a phone
        placeholder={status ?? (narrow ? 'a question, or a market link' : 'will Jensen step down this year? Or paste a Kalshi or Polymarket link')}
        enterKeyHint="go"
        autoCapitalize="none"
        autoCorrect="off"
        // 16px on a narrow screen: a phone's browser zooms the whole page into any field with smaller text
        className="h-full min-w-0 flex-1 bg-transparent text-sm text-text placeholder:text-faint focus:outline-none disabled:opacity-60 max-lg:text-base"
      />
      {shown ? (
        <span className="hidden shrink-0 text-xs text-down md:inline">{shown}</span>
      ) : (
        !heard && (
          <span className="hidden shrink-0 text-xs text-faint group-focus-within:hidden md:inline" aria-hidden="true">
            press /
          </span>
        )
      )}
      {speechInputAvailable && (
        <button
          type="button"
          onClick={speak}
          disabled={working || state === 'unsupported'}
          aria-pressed={listening}
          title={listening ? 'Stop listening' : 'Say your question: it is asked when you pause'}
          className={`press btn flex h-7 shrink-0 items-center gap-2 px-2.5! ${listening ? 'border-text! text-text!' : ''}`}
        >
          <span className={`h-2 w-2 rounded-full ${listening && state === 'listening' ? 'animate-pulse bg-down' : listening ? 'bg-madeup' : 'bg-faint'}`} />
          {listening ? 'Listening' : 'Speak'}
        </button>
      )}
    </form>
  )
}
