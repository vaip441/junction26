import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { focusTick } from '../../lib/focus'
import { shortSource } from '../../lib/sources'
import type { ReadItem, Verdict } from '../../lib/types'
import { useStore } from '../../state/store'
import { SourceIcon } from '../common/SourceIcon'

const POLL_MS = 2000
const KEEP = 24 // items on the strip
const STEP_MS = 240 // they come in one at a time, so a batch reads as a stream
const RUSH_MS = 90 // quicker while many are waiting
const WAITING = 60 // of a longer burst only the newest wait; the count is right all the same

const MARK: Record<Verdict, { sign: string; tone: string; said: string }> = {
  up: { sign: '▲', tone: 'text-up', said: 'Up' },
  down: { sign: '▼', tone: 'text-down', said: 'Down' },
  none: { sign: '•', tone: 'text-none', said: 'No effect' },
}

/**
 * One article is read once for every market it might bear on. On the strip it is one item, carrying the
 * call if any of those readings made one. Returns the new list, or null when the item adds nothing to see.
 */
function admit(list: ReadItem[], item: ReadItem): { list: ReadItem[]; front: boolean } | null {
  const at = list.findIndex((x) => x.source === item.source && x.headline === item.headline)
  if (at < 0) return { list: [item, ...list].slice(0, KEEP), front: true }
  if (list[at].verdict !== 'none' || item.verdict === 'none') return null
  return { list: list.map((x, i) => (i === at ? item : x)), front: false } // the call takes the item's place
}

/**
 * Everything the service reads, as it reads it: most of it is judged "no effect" and never reaches a tape,
 * so this strip is the only place the reading itself can be seen. Each item leads with the decision made on
 * it. The pointer over the strip holds it still; a click opens the market the item was read for.
 */
export function ReadingStrip() {
  const [items, setItems] = useState<ReadItem[]>([])
  const list = useRef<ReadItem[]>([]) // what `items` holds, for the timer that adds to it
  const [counts, setCounts] = useState<{ read: number; shown: number } | null>(null)
  const waiting = useRef<ReadItem[]>([]) // oldest first
  const newest = useRef(0)
  const held = useRef(false)
  const moving = useRef(0) // how long the slide for the item just let in may take; 0 before the first one
  const track = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let stopped = false
    let filled = false
    const poll = async () => {
      if (document.hidden) return
      try {
        const r = await api.reading(newest.current)
        if (stopped) return
        setCounts({ read: r.read, shown: r.shown })
        if (r.recent.length) newest.current = r.recent[0].id
        // what was read before the page opened is simply there; what comes after arrives one by one
        if (!filled) {
          for (const item of r.recent.slice().reverse()) list.current = admit(list.current, item)?.list ?? list.current
          setItems(list.current)
        } else waiting.current = [...waiting.current, ...r.recent.slice().reverse()].slice(-WAITING)
        filled = true
      } catch {
        // the strip is an extra: it tries again at the next poll
      }
    }
    void poll()
    const timer = setInterval(poll, POLL_MS)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>
    const step = () => {
      const rush = waiting.current.length > 8
      // the next item that has something to show: a repeat of one already here is passed over
      let added = null
      while (!held.current && !added && waiting.current.length) added = admit(list.current, waiting.current.shift()!)
      if (added) {
        moving.current = added.front ? (rush ? 70 : 200) : 0
        list.current = added.list
        setItems(added.list)
      }
      timer = setTimeout(step, rush ? RUSH_MS : STEP_MS)
    }
    timer = setTimeout(step, STEP_MS)
    return () => clearTimeout(timer)
  }, [])

  // The new item takes its place at the front and the row slides over to make room: the row starts shifted
  // left by the newcomer's width and glides back. Only the transform moves, so nothing is laid out again.
  const head = items[0]?.id
  useLayoutEffect(() => {
    const row = track.current
    const first = row?.firstElementChild as HTMLElement | null
    if (!row || !first || !moving.current) return
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    for (const a of row.getAnimations()) a.cancel()
    row.animate([{ transform: `translateX(${-first.offsetWidth}px)` }, { transform: 'translateX(0)' }], {
      duration: moving.current,
      easing: 'cubic-bezier(0.23, 1, 0.32, 1)',
    })
  }, [head])

  const open = (item: ReadItem) => {
    const store = useStore.getState()
    if (!store.markets[item.market_id]) return
    store.select(item.market_id)
    // on the tape only if it was shown; its market's tape may still be loading
    if (!item.hidden) setTimeout(() => focusTick(item.id), 700)
  }

  return (
    <div className="flex h-8 shrink-0 items-center border-b border-line bg-panel text-xs" aria-label="What is being read from the web">
      <span className="label shrink-0 pl-4 pr-3">Reading</span>
      <div
        className="strip-fade min-w-0 flex-1 overflow-hidden"
        onPointerEnter={(e) => {
          if (e.pointerType === 'mouse') held.current = true // a finger never leaves, so it never holds
        }}
        onPointerLeave={() => {
          held.current = false
        }}
      >
        <div ref={track} className="flex w-max items-center">
          {items.map((item) => {
            const mark = MARK[item.verdict]
            const call = item.verdict !== 'none'
            return (
              <button
                key={item.id}
                tabIndex={-1} // a row that keeps moving is no place for the Tab key; every item is on its market's tape or in its count
                onClick={() => open(item)}
                title={`${mark.said} on “${item.market}”: ${item.headline}`}
                className="read-in flex shrink-0 items-center gap-1.5 pr-5 text-muted hover:text-text"
              >
                <span className={`num text-[0.8em] font-bold ${mark.tone}`}>{mark.sign}</span>
                <SourceIcon source={item.source} className="h-3 w-3" />
                <span className="max-w-[9rem] truncate">{shortSource(item.source)}</span>
                <span className={`max-w-[17rem] truncate ${call ? 'font-medium text-text' : ''}`}>{item.headline}</span>
              </button>
            )
          })}
          {counts && items.length === 0 && <span className="text-muted">Nothing read yet.</span>}
        </div>
      </div>
      {counts && (
        <span className="num hidden shrink-0 border-l border-line px-4 text-muted md:block" title="Items read from the web in the last 24 hours, and how many of them earned a place on a tape">
          <span className="text-text">{counts.read.toLocaleString('en')}</span> read in 24 h ·{' '}
          <span className="text-text">{counts.shown.toLocaleString('en')}</span> shown
        </span>
      )}
    </div>
  )
}
