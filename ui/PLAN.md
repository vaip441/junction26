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
   talks; every sentence becomes a tick, is scored, moves the price, and the verdict lands on the
   tape and the chart. The judge discovers they are moving the chart by talking.
2. **The live web.** Swap to the Nvidia CEO market: real price chart with our scored ticks pinned
   on it.
3. **Ask anything.** The judge types a question in plain words. The screen narrates the search
   ("searching venues", "found 3 contracts", "tracking"), then the tape fills within seconds.
4. **The weekend record.** How many up/down calls we made and how often the price followed.

Beat 2 has a stronger form since the backend learned to work backwards (14 Nov, `terminal/moves.py`):
**"why did it move?"** Point at a jump on the Nvidia chart and the screen names the article or post
behind it, how sure it is, and the sentence of the market's rules that makes it matter. See
"From the backend, 14 Nov" below.

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
  public/                static assets (favicon)
  src/
    app/                 App.tsx, routes/views, keyboard shortcuts, presentation mode
    components/
      layout/            TopBar, MarketList, Shell, ConnectionDot
      market/            MarketHeader, PriceChart, RelatedContracts, SourcesPanel, RulesPanel
      tape/              Tape, TickRow, VerdictBadge, ConfidenceBar, KindLabel
      input/             AskBar, AskStage, MicBar, TypeTickBox, KeyPrompt
      record/            RecordCard, RecordView
      common/            Price, Points, TimeAgo, Badge, Spinner-with-words, EmptyState
    hooks/               useStream, useMarket, useSpeechInput, useHotkeys
    lib/                 api.ts (typed fetch), stream.ts (EventSource), format.ts, types.ts
    state/               store.ts (zustand): markets, ticks by market, prices, ask progress
    styles/              tailwind entry, theme tokens (verdict colours, type scale)
```

## Data layer

### `lib/types.ts`
Mirror the spec exactly: `MarketSummary`, `MarketDetail` (+ `related`, `sources`, `rules`,
`queries`), `Tick`, `PricePoint`, `Record`, `StreamEvent` (union of `tick`, `tick_update`,
`price`, `move`, `market`, `page_check`). `Tick` has `rule: RuleRef | null`
(`{ start, end, text, confidence }`, character positions in the market's `rules`). `Move` is
`{ id, market_id, ts, since, from, to, summary, explained, asked, cause, closest, confidence, rule, related }`.
`MarketDetail` has `companies: string[]` and `pages: WatchedPage[]`.

### `lib/api.ts`
- Base URL from `VITE_API_URL` (default `http://localhost:18911`, the real backend).
- Reads need nothing. Writes (`POST /markets`, `POST /markets/{id}/ticks`, `DELETE /markets/{id}`)
  send `X-Terminal-Key`, read from `localStorage`; on 401, `KeyPrompt` asks for it once and retries.
- Errors surface the backend's `detail` text verbatim (it is already written for people): 422
  "not a question", 404 closed link, 502/503 "try again".

### `lib/stream.ts` + `hooks/useStream`
- One `EventSource` on `/stream` for the whole app; it carries every market.
- Reconnect with backoff; on reconnect, refetch `/markets` and the open market's ticks/prices so
  nothing is missed.
- `tick` → prepend to that market's tape. `tick_update` → replace the tick with the same `id`.
  `price` → append point and update header. `move` → prepend to that market's moves (its cause
  tick is already on the tape, or arrives as a `tick` just before). `market` → update ask progress / list (`deleted`
  removes it, `tracking`/`made up` selects it, `ready` ends the "finding sources" state).
- `ConnectionDot` is green while the stream (incl. keepalives every 15 s) is alive, amber while
  reconnecting.

### `state/store.ts`
Plain normalized store: `markets: Record<id, MarketSummary>`, `detail`, `ticks: Record<id, Tick[]>`
(capped at 500, newest first), `prices: Record<id, PricePoint[]>`, `moves: Record<id, Move[]>`
(newest first), `selectedId`, `ask` (query, steps[], error). First paint for a market =
`GET /markets/{id}` + `/ticks` + `/prices` + `/moves`, then the stream keeps it current.

## Components (what each one must get right)

| Component | Notes |
|---|---|
| **MarketHeader** | Title, venue badge (Kalshi / Polymarket / MADE UP), big animated `Price`, `Points` change (24 h), ticks today, link out to the venue. Made-up market with `price: null` shows "setting starting odds from coverage…". |
| **PriceChart** | `lightweight-charts` line series from `/prices`. Each up/down tick is a dot on the line at `published_ts ?? ts` (green up, red down, size by `strength`, a soft ring on strong calls, dimmed for backfill). Hover a dot → its headline; click → scroll the tape to it. Each `move` is a shaded band from `since` to `ts` in the move's colour (see "Why did it move?"). |
| **Tape / TickRow** | Verdict badge + confidence %, `KindLabel` (ARTICLE/POST/SPOKEN/TYPED/FILING/PAGE), source (`x.com/handle`, `r/sub`, domain), headline (links out), time, likes/replies for X. `none` verdicts shown grey and collapsed to one line. A tick with a `rule` shows that sentence as a one-line quote under the headline; a tick that is the `cause` of a move carries a `MOVED THE PRICE 24% → 20%` badge. Truth Social posts are `post` ticks with source `truthsocial.com/@realDonaldTrump`: shown as `@realDonaldTrump` with the Truth Social logo. |
| **AskBar** | One input for a link or plain words. What happens next is shown on the centre of the screen, not in the bar (see AskStage). |
| **AskStage** | The ask, as a sequence on the main stage. (1) The question takes over the centre panel: the judge's words large, a clock to a tenth of a second, and a Context.dev meter (credits spent on this question, from `GET /status`). (2) The markets found drop in as cards (`found contracts` carries one per market: venue, title, price); on `picked` the winner lifts out and the rest step back. Errors show here with the backend's text. (3) The question fades, the market opens and its week of price history is wiped in left to right. A strip over the chart shows the search phrases as chips (`finding sources` carries them), then "Found 148 items. Scoring the 50 most relevant." (`scoring`). (4) Items land on the tape as they are scored: the backend streams each one, so this is live, not staged; each row opens in place so the rows under it glide down. (5) On `ready` the strip ends on one line: "Read 148 items in 24 seconds. 10 made the tape, 4 are calls. Market says 25%." A market tracked before answers at once and goes straight to the closing line. Every animation is CSS (transform, opacity, grid rows), not timers, so it stays smooth on a slow or throttled page. |
| **MicBar** | Only on made-up markets. Web Speech API `SpeechRecognition` (Chrome), continuous, final results only → `POST /ticks {kind: "mic"}`. Shows the live transcript. If recognition is unavailable or the hall is loud, `TypeTickBox` is the fallback (same endpoint, `kind: "typed"`). |
| **RelatedContracts** | Other deadlines / the other venue, with prices; "track" button promotes one to its own market via its link. |
| **MovesPanel** (first tab, every market) | "Why did it move?": an **Explain today's move** button, then one row per move, newest first: `24% → 20%` in the move's colour and the backend's `summary` sentence. Beneath it the "likely cause" (explained) or the "closest news" (not explained), the related contracts that moved with it, and the rule sentence. Click the item → the tape scrolls to it; click the rule → the Rules tab opens on that sentence. |
| **RulesPanel** | The rules text with every sentence that some tick's `rule` points at highlighted in place (`start`/`end`), tinted by how many ticks cite it. Clicking a tick's rule quote on the tape opens this tab scrolled to that sentence. |
| **SourcesPanel** | Leads with the watched page when there is one (see below). Then `sources` from detail: where ticks came from, ticks and moved counts. Shows the judges the terminal found these by itself. |
| **RecordCard / RecordView** | The three numbers from `/record` as large figures plus a hit-rate bar. Full-screen view for beat 4. |
| **KeyPrompt** | Modal asking for the write key on first write or 401; stored locally. |

## From the backend, 14 Nov

Main gained three things the screen does not show yet. All are in the spec's "Interface for the
frontend"; the mock backend (`mock/server.mjs`) needs the same additions first so they can be built
without the real one.

### Why did it move? (`move` event, `GET /markets/{id}/moves`, `POST /markets/{id}/why`)

The terminal also goes from the price back to the web. Two ways in:

- **A jump.** A real market moves 3 points within 10 minutes; the backend searches at once and stores a move.
- **On request.** `POST /markets/{id}/why` explains the market's change over the last day, now, for any
  market (made-up ones too). It makes no search, so it answers in about a second; the answer is a move with
  `asked: true`, also sent as a `move` event.

What a move says matters more than how it looks. Measured on 14 Nov, 10 of 11 jumps had no news behind
them: thin markets move on trades. So a move is honest by construction, and the screen shows it the way the
backend means it:

- `explained: true` → `cause` is the item taken as the reason. It is shown our way: the label, the headline, its
  source, the `rule` it touches. The label follows the backend: "likely cause" from 0.4, with the percentage;
  "possible cause" below that, without it (a dozen items split the vote, so a low figure is not doubt).
- `summary` is the backend's one-sentence version. The screen builds its rows from the fields, which read
  better at a glance, and keeps the summary as the tooltip.
- `explained: false` → `closest` is only the nearest item: label it "closest news", never as the reason.
  `related` names the related contracts that moved over the same stretch, which is often the whole story
  ("a contract falling while its rival rises").
- A confidence figure is shown only where it means something: on a likely cause, and in a rule's tooltip
  from 0.4. Never on closest news, a possible cause, or a spoken sentence's closest rule.

On screen: a shaded band over each jump on the chart (grey when not explained; none for an asked move,
which spans the whole day), the "Why did it move?" tab listing each move by its summary with an
**Explain today's move** button, and a banner over the chart when a move arrives. The button is the demo
moment: it does not wait for one of the ten jumps a day.

### The rules sentence behind a tick (`tick.rule`, `move.rule`)

Decision 1 picks the exact sentence of the market's rules that makes an item matter. It is set only on
ticks called up or down, never on "no effect". For a spoken or typed sentence it is the closest sentence
however weak (a person who typed it is watching for it); for an item from the web only a sentence that
stands out. Shown as a one-line `§` quote on the tape and highlighted in place in the Rules tab.

### The watched page (`detail.pages`, `page_check` event, `page` ticks)

Each market has one page a Context.dev monitor checks every ten minutes: the page most likely to change
when the outcome is decided (a newsroom, a results page, a Wikipedia article). It needs the backend to
have a public address (`PUBLIC_URL`), so it shows on the deployed instance, not on a laptop. The Sources tab
leads with it: title, "checked 3m ago", "changed 2h ago", updated live by `page_check`. A change that bears
on the market lands on the tape as a `PAGE` tick. This is the judges' own product watching the web for us.

### Resetting the demo market (`POST /markets/mu-demo/reset`)

After a rehearsal the demo market goes back to 20% with an empty tape. A small two-click "Reset" beside the
mic on the demo market; the `reset` market event clears the tape, chart and moves on every open screen.

### Truth Social (`post` ticks from `truthsocial.com/@realDonaldTrump`)

Trump's posts arrive within about 20 seconds through the team's own scraper. Nothing new to build
beyond the source label and logo in `lib/sources.ts`; they are ordinary `post` ticks. Worth a line in
the pitch, and worth tracking one market where his posts move the price so the tape shows them.

## Keyboard (stage control)

`P` presentation mode · `/` focus AskBar · `Space` mic on/off ·
`1`–`9` jump to market in list · `R` record view · `W` why-did-it-move tab · `Esc` back.

## Differentiators

What makes judges remember this screen over the other trading dashboards. Ordered by
impact for the effort. Tier 1 uses data the backend already sends, so none of it needs backend work.

### Tier 1: cheap, big payoff (fold into steps 2–7)

| Idea | What the judge sees | Built from |
|---|---|---|
| **"Not priced in yet"**: each tick has a lifecycle | Each up/down tick carries a live state: `WATCHING` → `PRICED IN ✓ +6 pts in 12m` (price moved the way we said) or `FADED ✗`. A strong tick where the price hasn't moved yet glows as **NOT PRICED IN**. This is the trader's edge Georg asked for ("see the news before the price has finished moving"), and the tape *proves the terminal works* in real time instead of only claiming it. | `price_at` vs the latest price, `strength`, `confidence`; client-side only |
| **Lead-time lines on the chart** | From each tick marker a thin dashed line runs to the point where the price reached the move, labelled "7 min early". Turns the chart from a picture into evidence. | `price_at`, `/prices` |
| **The decision, shown** | Each new tick animates a three-part bar (up / no effect / down) filling to its probabilities before the verdict badge settles. It looks like watching the model think, and it explains the confidence number without a word. | `up`, `none`, `down` on the tick |
| **Big-move moment** | When `|strength| > 0.6`, the screen briefly pulses the verdict colour at the edges, and the price does a larger count-up. Small moves stay still so the big ones land. The screen makes no sound: no effects and no spoken call-outs. | `strength` |
| **Live Context.dev meter** | A small strip in the TopBar: requests per minute, credits used this weekend, a spark of activity. The judges are Context.dev, so this shows them their product doing the work live. | `GET /status`, polled every 10 s |
| **Source logos on the tape** | Each row has the favicon of its site (Reuters, x.com, reddit), which makes it readable at a glance from the back of the room and looks finished. | `https://www.google.com/s2/favicons?domain=…&sz=32`, domain from `source`/`url` |
| **Prompt the judge** | On the demo market, before the first sentence: a large ghost line *"Say something about this team. The market is listening."* that cycles through example sentences. It fixes the cold start where the judge doesn't know they are supposed to talk. | static text, hidden after the first `mic` tick |
| **Instant pending row** | When a sentence is sent, its row appears at once as `SCORING…` with the transcript, then turns into the scored tick when it arrives. It hides scoring latency, the riskiest second of beat 1. | optimistic insert, matched by text on the `tick` event |

### Tier 2: memorable set-pieces (after step 6 if time allows)

| Idea | Why it's worth it |
|---|---|
| **Audience mode (QR code)** | A QR code in the corner of the demo market opens the UI on a phone in a "talk to the market" view (one text box, one big price). The whole room moves the price, not only one judge. Put the write key in the URL *fragment* (`#k=…`), not the query, so it never reaches a server log. Needs `qrcode` (tiny) and the deployed URL. The most memorable beat there could be. |
| **Weekend replay (time-lapse)** | A scrubber on any market replays the weekend at 60–600×: ticks land, the price moves. Purely client-side from `/ticks` + `/prices`. It doubles as the **fallback for beat 2** if no news breaks, and as a strong opener for beat 4 ("here's Friday to Sunday in 20 seconds"). |
| **Live-web radar** | A slow radar sweep in the Sources panel; each watched page and source is a blip that flashes on `page_check` and on each new tick. The challenge is "reacts to the live web", and this shows the terminal watching it. |

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
  stream backlog after a reconnect doesn't fire a burst of splashes.

## Build order

Each step ends with something demoable; stop where time runs out.

1. **Scaffold.** `npm create vite@latest ui -- --template react-ts` into this folder, Tailwind,
   theme tokens, `types.ts`, `api.ts`. Shell with the three columns and empty states.
2. **Live demo market.** `useStream`, store, MarketHeader, Tape, TypeTickBox. Typing a sentence
   moves the demo market's price on screen. *Beat 1 works by typing.*
3. **Voice.** MicBar. *Beat 1 complete.*
4. **Chart.** PriceChart with tick markers, MarketList with switching. *Beat 2 works.*
5. **Ask.** AskBar + AskStage + error states + KeyPrompt. *Beat 3 works.*
6. **Record.** RecordCard and full-screen RecordView. *Beat 4 works.*
7. **Polish for the stage.** Presentation mode, hotkeys, price flash/count animation, tick slide-in,
   related/sources/rules tabs, responsive stacking.
8. **Why did it move?** `Move` and `rule` types, mock support, `/moves` + `move` event in the store,
   MovesPanel, rule quote on the tape, rules highlighting. Then the chart bands and the live banner.
   *Beat 2 answers its own question.*
9. **Rehearse against the deployed backend** on the demo laptop and projector; check Chrome mic
   permission and readability from the back of the room.

## Risks and fallbacks

| Risk | Fallback |
|---|---|
| Speech recognition fails or the hall is too loud | TypeTickBox is always visible next to the mic |
| No news breaks during the demo | Backend instant fill; the tape is already full when a market opens |
| No price jumps during the demo | Past moves are stored: the Moves tab and the chart bands are already there when the market opens |
| Stream drops on venue wifi | Auto-reconnect + refetch; ConnectionDot shows it honestly |
| Plain-words search is slow | AskStage narrates each step on the centre of the screen so the wait reads as work, not a hang |
| Scoring down (503) | Inline "scoring unavailable, try again", the typed sentence stays in the box |

## Open questions

- Hosting for the UI: same Railway service (serve the built files from FastAPI) or a separate
  static host? Same service is fewer moving parts and avoids CORS surprises.
- Concept mockup referenced in the spec (claude.ai artifact) — align colours/layout with it if the
  team likes it.
