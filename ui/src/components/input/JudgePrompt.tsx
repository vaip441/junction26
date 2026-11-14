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
      {/* sized to the window on a wide screen, to be read from across a room; never so large that a narrow
          middle column needs more lines than the chart has room for */}
      <p className="text-balance text-2xl font-semibold text-text/80 lg:text-[clamp(1.5rem,2.2vw,2.25rem)] lg:leading-tight lg:tracking-[-0.015em]">
        Say something about it. The market is listening.
      </p>
      <p key={i} className="fade-in text-sm text-muted lg:text-[clamp(0.875rem,1.1vw,1.125rem)]">
        {EXAMPLES[i]}
      </p>
    </div>
  )
}
