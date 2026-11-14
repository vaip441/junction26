# Terminal UI

React + Vite + TypeScript screen for the prediction market terminal. The plan, layout and build order
are in [PLAN.md](PLAN.md); the backend contract is "Interface for the frontend" in
`../docs/superpowers/specs/2026-11-13-terminal-design.md`.

```bash
npm install
cp .env.example .env.local   # point VITE_API_URL at the backend
npm run dev                  # http://localhost:5173
```

`npm run build` typechecks and builds into `dist/`; `npm run lint` runs oxlint.

Done so far: build step 1 (scaffold, typed API client, one app-wide event stream, three-column shell
with live market list, header and tape). Next: step 2 onward in PLAN.md.
