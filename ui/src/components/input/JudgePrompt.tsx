import { useEffect, useState } from 'react'

const EXAMPLES = [
  '“Honestly, this is the best demo I have seen today.”',
  '“The idea is great, but will anyone pay for it?”',
  '“It crashed on me earlier.”',
  '“Reacting to the live web in seconds is impressive.”',
]

/** Shown on a made-up market until the first sentence lands, so the judge knows to talk. */
export function JudgePrompt() {
  const [i, setI] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setI((n) => (n + 1) % EXAMPLES.length), 3500)
    return () => clearInterval(t)
  }, [])
  return (
    <div className="pointer-events-none flex flex-col items-center gap-2 text-center">
      <p className="text-2xl font-semibold text-text/80">Say something about it. The market is listening.</p>
      <p key={i} className="fade-in text-sm text-muted">
        {EXAMPLES[i]}
      </p>
    </div>
  )
}
