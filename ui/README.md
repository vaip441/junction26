# Priced In UI

React + Vite + TypeScript screen for the prediction market terminal. The backend contract is
"Interface for the frontend" in `../docs/superpowers/specs/2026-11-13-terminal-design.md`.

The UI runs against the real backend. Start that first, from the repository root (see `../README.md`;
it needs the keys in `../.env`):

```bash
uv run --env-file .env uvicorn terminal.api:app --port 18911
```

Then, in this folder:

```bash
npm install
npm run dev                  # http://localhost:5173, talking to http://localhost:18911
```

`VITE_API_URL` points the UI at another address (copy `.env.example` to `.env.local` and change it).
Writes (asking a question, typing or speaking a sentence) need the backend's `TERMINAL_KEY`: the UI asks
for it once and keeps it in the browser.

### Offline, without the backend

Only for working on the screen when the backend or its keys are not at hand:

```bash
npm run dev:mock             # mock backend on :8765 + the UI pointed at it
```

`mock/server.mjs` serves the whole frontend interface with made-up data (every title starts with
`MOCK`) and keeps the stream busy: prices drift, new ticks arrive every 12–25 s, and strong calls are
often followed by a move their way. Spoken/typed ticks are scored from keywords ("great", "win" → up;
"bad", "broken" → down) and move the demo market like the real one. Magic inputs reach the error
states: ask `fail …` (502), `hello` (422), anything with `made up` (no contract, made-up market);
type `fail503 …` (scoring down). `MOCK_PORT` moves the mock off 8765; `MOCK_KEY=secret` makes writes need the key; `MOCK_QUIET=1` stops the
scripted ticks. Details at the top of `mock/server.mjs`.

`npm run build` typechecks and builds into `dist/`; `npm run lint` runs oxlint; `npm test` runs the
state tests with Node's own test runner.

### What opens first

The screen opens on the first real market in the list, where something is already moving. The demo market
is first in the list but is an empty chart until someone talks to it: the `1` key (or its row) opens it.

### Narrow screens

Under 1024px wide (a phone, a tablet upright) the three columns do not fit side by side, and stacked they
were three boxes that each scrolled inside a page that scrolled too. There the screen is one view at a
time, picked from a bar at the bottom (`components/layout/BottomNav.tsx`): **Markets** (the list and the
weekend record), **Live** (the chart with the tape under it) and **Details** (why it moved, sources,
related contracts, rules). The question and its price stay above the page, and the page is the only thing
that scrolls. Each view is found where it was left; picking a market, asking a question, or tapping a call,
a cause or a rules sentence opens the view that holds it (`view` in the store). `App.tsx` holds both
layouts (`Columns`, `OneView`), drawn from the same components.

What is built: the stream; the weekend record as a card and full screen on R;
sources / related / rules tabs under the chart, with a Track button on related contracts; the price chart with every call pinned on it, range buttons, a readout of the price under the pointer and of the change over the stretch on screen, in local time; the
AskBar, which turns a link or a plain question into a tracked market and narrates each step; typing or speaking moves the demo market; hotkeys;
the tick lifecycle ("not priced in"), the decision bar, the pending scoring row, the judge prompt and the
big-move flash, lead-time lines on the chart, site logos on the tape; "why did it move?" (price jumps as bands on the chart, a tab listing each with its likely cause, a live banner when one arrives), the rules sentence behind a tick quoted on the tape and highlighted in the Rules tab, and Truth Social posts.
