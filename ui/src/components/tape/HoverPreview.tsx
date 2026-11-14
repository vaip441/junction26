import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../lib/api'
import { touchOnly } from '../../lib/device'
import { shortSource } from '../../lib/sources'
import type { Preview } from '../../lib/types'
import { SourceIcon } from '../common/SourceIcon'

const HOVER_DELAY = 320
const CARD_WIDTH = 320
const cardCache = new Map<string, Preview | null>() // null: asked, and the page gave nothing

/**
 * The card that opens over a tape row after a moment of hovering: the image the page declares as its own,
 * the headline it was scored under, and where it came from. It sits to the left of the tape, so it never
 * covers the row being read.
 */
export function HoverPreview({
  url,
  headline,
  source,
  passage,
  children,
}: {
  url: string | null
  headline: string
  source: string
  passage?: string | null
  children: ReactNode
}) {
  const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(null)
  const [preview, setPreview] = useState<Preview | null | undefined>(undefined)
  const [broken, setBroken] = useState(false)
  const timer = useRef<number | null>(null)

  const stop = () => {
    if (timer.current != null) window.clearTimeout(timer.current)
    timer.current = null
  }
  useEffect(() => stop, [])

  // the image is read on the first hover and kept: the backend remembers it too
  useEffect(() => {
    if (!anchor || !url || preview !== undefined) return
    let alive = true
    api
      .preview(url)
      .then((p) => {
        cardCache.set(url, p)
        if (alive) setPreview(p)
      })
      .catch(() => {
        cardCache.set(url, null)
        if (alive) setPreview(null)
      })
    return () => {
      alive = false
    }
  }, [anchor, url, preview])

  // a card left behind while the tape scrolls would point at the wrong row
  useEffect(() => {
    if (!anchor) return
    const close = () => setAnchor(null)
    window.addEventListener('scroll', close, true)
    return () => window.removeEventListener('scroll', close, true)
  }, [anchor])

  const open = (e: MouseEvent<HTMLDivElement>) => {
    // a tap also reports the pointer "entering": the card would open over the row just tapped and stay there
    if (!url || touchOnly()) return
    const row = e.currentTarget.getBoundingClientRect()
    stop()
    timer.current = window.setTimeout(() => {
      setBroken(false)
      setPreview(cardCache.get(url))
      const left = Math.max(12, row.left - CARD_WIDTH - 12) // to the left of the tape, inside the window
      const top = Math.max(12, Math.min(row.top, window.innerHeight - 300))
      setAnchor({ top, left })
    }, HOVER_DELAY)
  }

  const close = () => {
    stop()
    setAnchor(null)
  }

  const image = preview?.image && !broken ? preview.image : null
  return (
    <div onMouseEnter={open} onMouseLeave={close}>
      {children}
      {anchor &&
        createPortal(
          <div
            style={{ top: anchor.top, left: anchor.left, width: CARD_WIDTH }}
            className="pointer-events-none fixed z-50 overflow-hidden rounded-xs border border-line bg-panel shadow-[0_18px_50px_rgba(0,0,0,0.55)]"
          >
            {image && (
              <img
                src={image}
                alt=""
                referrerPolicy="no-referrer"
                className="aspect-video w-full bg-panel-2 object-cover"
                onError={() => setBroken(true)}
              />
            )}
            <div className="flex flex-col gap-1.5 p-3">
              <p className="line-clamp-3 text-sm font-medium leading-snug text-text">{headline}</p>
              {!image && passage && <p className="line-clamp-3 text-xs leading-snug text-muted">{passage}</p>}
              <p className="flex items-center gap-1.5 text-[11px] text-faint">
                <SourceIcon source={source} className="h-3 w-3" />
                <span className="truncate">{shortSource(source)}</span>
              </p>
            </div>
          </div>,
          document.body,
        )}
    </div>
  )
}
