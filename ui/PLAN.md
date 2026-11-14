# Terminal UI plan

The screen for the prediction market terminal. The backend (`terminal/`, FastAPI) already serves
everything this needs; the contract is "Interface for the frontend" in
`docs/superpowers/specs/2026-11-13-terminal-design.md`. This folder holds only the frontend.

**Stack:** React 19 + Vite + TypeScript, Tailwind for styling, `zustand` for state,
`lightweight-charts` (TradingView, Apache-2.0) for the price chart. No other runtime dependencies
unless a step below names one.

## What the screen has to do

The hackathon is won on the demo, and the demo is about two minutes:

1. **The market on us.** "Will this team win the Context.dev challenge?" starts at 20%. A judge
   talks; every sentence becomes a tick, is scored, moves the price, and the screen *says* the
   verdict out loud. The judge discovers they are moving the chart by talking.
2. **The live web.** Swap to the Nvidia CEO market: real price chart with our scored ticks pinned
   on it.
3. **Ask anything.** The judge types a question in plain words. The screen narrates the search
   ("searching venues", "found 3 contracts", "tracking"), then the tape fills within seconds.
4. **The weekend record.** How many up/down calls we made and how often the price followed.

Every design choice below serves one of those four beats. If a feature doesn't, it waits.

### Rules the UI must keep

- **Never a dead screen.** Something always moves: price pulse, stream heartbeat, status steps.
  Every loading state says what it is doing in words, never a bare spinner.
- **Never pass made-up data off as real.** Made-up markets carry a `MADE UP` badge everywhere they
  appear. Spoken and typed ticks are labelled `SPOKEN` / `TYPED`. Backfilled ticks are dimmed and
  labelled `EARLIER`.
- **Nothing specific to one market.** No hard-coded ids except the demo market's, which the API
  returns like any other.
- **Prices are percentages, changes are points.** `82%`, `+18 pts`. Never `+18%`.
- **Time shown is `published_ts ?? ts`.** Relative ("2m ago") on the tape, absolute on hover.

## Visual direction

A dark trading terminal, readable from three metres away on a projector.

- Near-black background, one monospace face for numbers (tabular figures), one sans for text.
- Colour carries the verdict and nothing else: **green = up, red = down, grey = no effect**.
  `strength` (−1…1) sets the intensity, so "up a lot" glows and "up a little" is muted.
- The price is the largest thing on screen. When it moves it flashes the verdict colour and counts
  up/down to the new value (~400 ms).
- New ticks slide in at the top of the tape with a brief highlight.
- **Presentation mode** (`P` key): hides chrome, scales type ~1.5×, keeps price, chart and tape.
  This is the mode used on stage.

## Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ TopBar: name · AskBar (link or plain words) · stream ● · keys · ⚙        │
├──────────────┬──────────────────────────────────────────┬───────────────┤
│ MarketList   │ MarketHeader: title · venue · 64% +18pts │ Tape          │
│  demo  20%   │ ┌──────────────────────────────────────┐ │  ▲ UP 82%     │
│  nvidia 7%   │ │ PriceChart + tick markers            │ │  headline…    │
│  …           │ └──────────────────────────────────────┘ │  ▼ DOWN 61%   │
│              │ Related · Sources · Rules (tabs)         │  …            │
│ RecordCard   │ MicBar (on made-up markets): ● listening │               │
└──────────────┴──────────────────────────────────────────┴───────────────┘
```

Below ~1000 px the three columns stack: header, chart, tape; the market list becomes a dropdown.

## Folder layout

```
ui/
  PLAN.md                this file
  public/                static assets (favicon, sounds)
  src/
    app/                 App.tsx, routes/views, keyboard shortcuts, presentation mode
    components/
      layout/            TopBar, MarketList, Shell, ConnectionDot
      market/            MarketHeader, PriceChart, RelatedContracts, SourcesPanel, RulesPanel
      tape/              Tape, TickRow, VerdictBadge, ConfidenceBar, KindLabel
      input/             AskBar, AskProgress, MicBar, TypeTickBox, KeyPrompt
      record/            RecordCard, RecordView
      common/            Price, Points, TimeAgo, Badge, Spinner-with-words, EmptyState
    hooks/               useStream, useMarket, useSpeechInput, useVoiceCallout, useHotkeys
    lib/                 api.ts (typed fetch), stream.ts (EventSource), format.ts, types.ts
    state/               store.ts (zustand): markets, ticks by market, prices, ask progress
    styles/              tailwind entry, theme tokens (verdict colours, type scale)
```

## Data layer

### `lib/types.ts`
Mirror the spec exactly: `MarketSummary`, `MarketDetail` (+ `related`, `sources`, `rules`,
`queries`), `Tick`, `PricePoint`, `Record`, `StreamEvent` (union of `tick`, `tick_update`,
`price`, `market`, `page_check`).

### `lib/api.ts`
- Base URL from `VITE_API_URL` (default `http://localhost:8000`).
- Reads need nothing. Writes (`POST /markets`, `POST /markets/{id}/ticks`, `DELETE /markets/{id}`)
  send `X-Terminal-Key`, read from `localStorage`; on 401, `KeyPrompt` asks for it once and retries.
- Errors surface the backend's `detail` text verbatim (it is already written for people): 422
  "not a question", 404 closed link, 502/503 "try again".

### `lib/stream.ts` + `hooks/useStream`
- One `EventSource` on `/stream` for the whole app; it carries every market.
- Reconnect with backoff; on reconnect, refetch `/markets` and the open market's ticks/prices so
  nothing is missed.
- `tick` → prepend to that market's tape. `tick_update` → replace the tick with the same `id`.
  `price` → append point and update header. `market` → update ask progress / list (`deleted`
  removes it, `tracking`/`made up` selects it, `ready` ends the "finding sources" state).
- `ConnectionDot` is green while the stream (incl. keepalives every 15 s) is alive, amber while
  reconnecting.

### `state/store.ts`
Plain normalized store: `markets: Record<id, MarketSummary>`, `detail`, `ticks: Record<id, Tick[]>`
(capped at 500, newest first), `prices: Record<id, PricePoint[]>`, `selectedId`, `ask` (query,
steps[], error). First paint for a market = `GET /markets/{id}` + `/ticks` + `/prices`, then the
stream keeps it current.

## Components (what each one must get right)

| Component | Notes |
|---|---|
| **MarketHeader** | Title, venue badge (Kalshi / Polymarket / MADE UP), big animated `Price`, `Points` change (24 h), ticks today, link out to the venue. Made-up market with `price: null` shows "setting starting odds from coverage…". |
| **PriceChart** | `lightweight-charts` line series from `/prices`. Each up/down tick is a marker at `published_ts ?? ts` (▲ green above, ▼ red below, size by `strength`). Hover a marker → its headline; click → scroll the tape to it. Backfill markers hollow. |
| **Tape / TickRow** | Verdict badge + confidence %, `KindLabel` (ARTICLE/POST/SPOKEN/TYPED/FILING/PAGE), source (`x.com/handle`, `r/sub`, domain), headline (links out), time, likes/replies for X. `none` verdicts shown grey and collapsed to one line. |
| **AskBar** | One input for a link or plain words. On submit shows `AskProgress`: the live `market` status steps as a checklist, then jumps to the new market. Errors inline with the backend's text. |
| **MicBar** | Only on made-up markets. Web Speech API `SpeechRecognition` (Chrome), continuous, final results only → `POST /ticks {kind: "mic"}`. Shows the live transcript. If recognition is unavailable or the hall is loud, `TypeTickBox` is the fallback (same endpoint, `kind: "typed"`). |
| **Voice callout** (`useVoiceCallout`) | `speechSynthesis` reads each new tick on the *selected* market: "Up, eighty-two percent. Price twenty-six." Mute toggle (`M`). Pause recognition while speaking so the terminal doesn't score itself. |
| **RelatedContracts** | Other deadlines / the other venue, with prices; "track" button promotes one to its own market via its link. |
| **SourcesPanel** | `sources` from detail: where ticks came from, ticks and moved counts. Shows the judges the terminal found these by itself. |
| **RecordCard / RecordView** | The three numbers from `/record` as large figures plus a hit-rate bar. Full-screen view for beat 4. |
| **KeyPrompt** | Modal asking for the write key on first write or 401; stored locally. |

## Keyboard (stage control)

`P` presentation mode · `/` focus AskBar · `M` mute voice · `Space` mic on/off ·
`1`–`9` jump to market in list · `R` record view · `Esc` back.

## Differentiators

What makes judges remember this screen over the other trading dashboards. Ordered by
impact for the effort. Tier 1 uses data the backend already sends, so none of it needs backend work.

### Tier 1: cheap, big payoff (fold into steps 2–7)

| Idea | What the judge sees | Built from |
|---|---|---|
| **"Not priced in yet"**: each tick has a lifecycle | Each up/down tick carries a live state: `WATCHING` → `PRICED IN ✓ +6 pts in 12m` (price moved the way we said) or `FADED ✗`. A strong tick where the price hasn't moved yet glows as **NOT PRICED IN**. This is the trader's edge Georg asked for ("see the news before the price has finished moving"), and the tape *proves the terminal works* in real time instead of only claiming it. | `price_at` vs the latest price, `strength`, `confidence`; client-side only |
| **Lead-time lines on the chart** | From each tick marker a thin dashed line runs to the point where the price reached the move, labelled "7 min early". Turns the chart from a picture into evidence. | `price_at`, `/prices` |
| **The decision, shown** | Each new tick animates a three-part bar (up / no effect / down) filling to its probabilities before the verdict badge settles. It looks like watching the model think, and it explains the confidence number without a word. | `up`, `none`, `down` on the tick |
| **Big-move moment** | When `|strength| > 0.6`, the screen briefly pulses the verdict colour at the edges, the price does a larger count-up, and a short sound plays (rising for up, falling for down, pitch set by strength). Small moves stay quiet so the big ones land. Settles the "sound effects?" open question: yes, but only for big moves. | `strength`, Web Audio (no files, no dependency) |
| **Live Context.dev meter** | A small strip in the TopBar: requests per minute, credits used this weekend, a spark of activity. The judges are Context.dev, so this shows them their product doing the work live. | `GET /status`, polled every 10 s |
| **Source logos on the tape** | Each row has the favicon of its site (Reuters, x.com, reddit), which makes it readable at a glance from the back of the room and looks finished. | `https://www.google.com/s2/favicons?domain=…&sz=32`, domain from `source`/`url` |
| **Prompt the judge** | On the demo market, before the first sentence: a large ghost line *"Say something about this team. The market is listening."* that cycles through example sentences. It fixes the cold start where the judge doesn't know they are supposed to talk. | static text, hidden after the first `mic` tick |
| **Instant pending row** | When a sentence is sent, its row appears at once as `SCORING…` with the transcript, then turns into the scored tick when it arrives. It hides scoring latency, the riskiest second of beat 1. | optimistic insert, matched by text on the `tick` event |

### Tier 2: memorable set-pieces (after step 6 if time allows)

| Idea | Why it's worth it |
|---|---|
| **Audience mode (QR code)** | A QR code in the corner of the demo market opens the UI on a phone in a "talk to the market" view (one text box, one big price). The whole room moves the price, not only one judge. Put the write key in the URL *fragment* (`#k=…`), not the query, so it never reaches a server log. Needs `qrcode` (tiny) and the deployed URL. The most memorable beat there could be. |
| **Weekend replay (time-lapse)** | A scrubber on any market replays the weekend at 60–600×: ticks land, the price moves, the voice stays muted. Purely client-side from `/ticks` + `/prices`. It doubles as the **fallback for beat 2** if no news breaks, and as a strong opener for beat 4 ("here's Friday to Sunday in 20 seconds"). |
| **Live-web radar** | A slow radar sweep in the Sources panel; each watched page and source is a blip that flashes on `page_check` and on each new tick. The challenge is "reacts to the live web", and this shows the terminal watching it. |
| **Ask flow, shown working** | During `AskProgress`, show the actual search phrases (`queries`) typing out, then the found contracts dropping in as cards with venue and price before the jump. The wait looks like the terminal working, not loading. |

### Tier 3: finishing touches

- **Threshold moments** on the demo market: crossing 50% shows "The judges now favour us"; above 75%, a short confetti burst. Write the closing line of the pitch around it.
- **"Market disagrees" flag**: a confident tick against which the price moved the other way gets an amber `CONTRARIAN` tag. That's interesting to a trader and rare enough to stand out.
- **News velocity strip**: a thin heat strip under the chart showing ticks per 5 minutes, so "a story is breaking" is visible before reading anything.
- **End-of-demo card** (`E` key): one full-screen card with the demo market's start→end price, sentences scored and the weekend hit-rate. It's the screen left up during Q&A.

### Guardrails for all of the above

- None of it overrides the colour rule: green/red/grey still mean verdict only; the lifecycle states
  use the same colours plus an icon, and `CONTRARIAN` is the one amber exception.
- `PRICED IN` / `FADED` must use a fixed, stated window (the same as `/record`'s `window_seconds`)
  so the tape and the record never disagree.
- Every animation respects `prefers-reduced-motion` and is skipped when the tab is hidden, so a long
  stream backlog after a reconnect doesn't fire a burst of sounds and splashes.

## Build order

Each step ends with something demoable; stop where time runs out.

1. **Scaffold.** `npm create vite@latest ui -- --template react-ts` into this folder, Tailwind,
   theme tokens, `types.ts`, `api.ts`. Shell with the three columns and empty states.
2. **Live demo market.** `useStream`, store, MarketHeader, Tape, TypeTickBox. Typing a sentence
   moves the demo market's price on screen. *Beat 1 works by typing.*
3. **Voice.** MicBar + voice callout + mute. *Beat 1 complete.*
4. **Chart.** PriceChart with tick markers, MarketList with switching. *Beat 2 works.*
5. **Ask.** AskBar + AskProgress + error states + KeyPrompt. *Beat 3 works.*
6. **Record.** RecordCard and full-screen RecordView. *Beat 4 works.*
7. **Polish for the stage.** Presentation mode, hotkeys, price flash/count animation, tick slide-in,
   related/sources/rules tabs, responsive stacking.
8. **Rehearse against the deployed backend** on the demo laptop and projector; check Chrome mic
   permission, voice volume, and readability from the back of the room.

## Risks and fallbacks

| Risk | Fallback |
|---|---|
| Speech recognition fails or the hall is too loud | TypeTickBox is always visible next to the mic |
| The terminal hears its own voice callout | Recognition paused while `speechSynthesis` is speaking |
| No news breaks during the demo | Backend instant fill; the tape is already full when a market opens |
| Stream drops on venue wifi | Auto-reconnect + refetch; ConnectionDot shows it honestly |
| Plain-words search is slow | AskProgress narrates each step so the wait reads as work, not a hang |
| Scoring down (503) | Inline "scoring unavailable, try again", the typed sentence stays in the box |

## Open questions

- Hosting for the UI: same Railway service (serve the built files from FastAPI) or a separate
  static host? Same service is fewer moving parts and avoids CORS surprises.
- Does the teammate want sound effects on big moves (a short tick/chime), or voice only?
- Concept mockup referenced in the spec (claude.ai artifact) — align colours/layout with it if the
  team likes it.
