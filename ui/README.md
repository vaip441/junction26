# Terminal UI

React + Vite + TypeScript screen for the prediction market terminal. The plan, layout and build order
are in [PLAN.md](PLAN.md); the backend contract is "Interface for the frontend" in
`../docs/superpowers/specs/2026-11-13-terminal-design.md`.

```bash
npm install
cp .env.example .env.local   # point VITE_API_URL at the backend
npm run dev                  # http://localhost:5173
```

### Without the backend

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

Done so far: build steps 1-6 (scaffold and stream; the weekend record as a card and full screen on R; the price chart with every call pinned on it; the
AskBar, which turns a link or a plain question into a tracked market and narrates each step; typing or speaking moves the demo market, with a
voice call-out of each verdict; hotkeys and presentation mode) plus these differentiators from PLAN.md:
the tick lifecycle ("not priced in"), the decision bar, the pending scoring row, the judge prompt and the
big-move flash and sound, lead-time lines on the chart. Next: step 7 (stage polish: related/sources/rules tabs, responsive stacking) and step 8 (rehearsal).
