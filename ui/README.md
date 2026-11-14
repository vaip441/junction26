# Terminal UI

React + Vite + TypeScript screen for the prediction market terminal. The plan, layout and build order
are in [PLAN.md](PLAN.md); the backend contract is "Interface for the frontend" in
`../docs/superpowers/specs/2026-11-13-terminal-design.md`.

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

`npm run build` typechecks and builds into `dist/`; `npm run lint` runs oxlint.

Done so far: build steps 1-7 (scaffold and stream; the weekend record as a card and full screen on R;
sources / related / rules tabs under the chart, with a Track button on related contracts; stacking on small screens; the price chart with every call pinned on it, range buttons, a readout of the price under the pointer and of the change over the stretch on screen, in local time; the
AskBar, which turns a link or a plain question into a tracked market and narrates each step; typing or speaking moves the demo market; hotkeys) plus these differentiators from PLAN.md:
the tick lifecycle ("not priced in"), the decision bar, the pending scoring row, the judge prompt and the
big-move flash, lead-time lines on the chart, site logos on the tape. Step 8 is built too: "why did it move?" (price jumps as bands on the chart, a tab listing each with its likely cause, a live banner when one arrives), the rules sentence behind a tick quoted on the tape and highlighted in the Rules tab, and Truth Social posts. Next: step 9, rehearsing against the deployed backend on the demo laptop and projector.
