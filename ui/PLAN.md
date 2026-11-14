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
