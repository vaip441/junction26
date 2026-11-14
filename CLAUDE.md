# Prediction market terminal

Junction 2026, Context.dev challenge: a product that reacts to the live web. A question in plain words, or
a Kalshi or Polymarket link, becomes a tracked market; every new article and post about it lands on a tape
with a verdict: does it move the price of YES up, down, or not at all. It reads public data and places no
trades. The hackathon is won on a two-minute demo: read "What the screen has to do" in `ui/PLAN.md` before
deciding what matters.

## Where things are

| Path | What |
| --- | --- |
| `terminal/` | The backend: FastAPI, one process, SQLite. `poller.py` finds items, `pipeline.py` scores and stores them, `api.py` serves them and one event stream. |
| `tests/` | pytest. No network: `conftest.py` makes any lookup fail loudly. |
| `ui/` | The screen: React 19, Vite, TypeScript, Tailwind, zustand. `ui/mock/server.mjs` is a mock backend. |
| `trump-social-scraper/` | Separate program, standard library only. Nothing in `terminal/` imports it. |
| `docs/superpowers/specs/2026-11-13-terminal-design.md` | The design. Its section "Interface for the frontend" is the contract between backend and screen. |
| `deploy/`, `scripts/`, `markets.txt` | systemd units, seeding and monitor scripts, the markets tracked on the deployment. |

## Commands

```sh
.claude/skills/check-all/check.sh        # everything that must pass: backend, scraper, screen
uv run pytest                            # backend only
(cd ui && npm run build && npm run lint) # screen only
(cd ui && npm run dev:mock)              # the screen on made-up data, no keys needed
```

Running the real backend needs the keys in `.env`; see `README.md`.

## Rules that hold everywhere

- Prices are percentages from 0 to 100, changes are points ("+18 pts", never "+18%"), times are unix seconds.
- Nothing is specific to one market: no market id, title or company name in code outside `terminal/seed.py`,
  the tests and the mock. The one id the screen may know is the demo market's, `mu-demo`.
- Made-up data is never passed off as real. Spoken and typed ticks are stored with `test = 1`; test ticks,
  backfilled ticks and made-up markets never count in the record. Every title in the mock starts with `MOCK`.
- Articles and posts are fetched in the poller's loops only, never in a request handler.
- Every route is `async def`: the store is one SQLite connection.
- Tests never reach the network. Functions that fetch take their fetchers as parameters (`search=`, `decide=`,
  `fetch=`); a test passes stand-ins.
- Context.dev costs credits and allows 10 requests a minute per key. Read the `context-dev` skill before adding
  a call. A page monitor bills every ten minutes for as long as it exists, whether or not the terminal runs.
- Secrets live in `.env` only. Never print a key, and never put one in a URL.
- A change to what the backend sends is a change in four places: the spec's interface section,
  `terminal/api.py`, `ui/src/lib/types.ts` and `ui/mock/server.mjs`. Change them together.
- On the screen, colour means the verdict and nothing else, labels are sentence case, and a new runtime
  dependency needs a reason (`ui/PLAN.md`).

## How we write

- Comments and docs say in plain words what a thing does and why it is that way, with the measurement behind
  a number when there is one. No jargon where a common word does.
- A commit says what is now true, as a sentence: `feat(ui): the price chart has range buttons`. Types are
  `feat`, `fix`, `polish`, `revert`; the scope `(ui)` marks a change to the screen alone.
- The team commits small changes straight to `main`. Fetch and rebase before a push, and push only when asked.

## Skills and agents

Skills (`.claude/skills/`): `check-all` (what must pass), `screen-shots` (look at the screen), `add-source`
(a new kind of item on the tape), `context-dev` (what a call costs and how to try one), `rehearse-demo`
(the two minutes on stage), `build-feature` (one feature built by several agents).

Agents (`.claude/agents/`): `backend`, `screen`, `contract-checker`, `judge`, `market-scout`. How they work
together is in `docs/agents.md`.
