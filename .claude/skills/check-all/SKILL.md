---
name: check-all
description: Run everything that must pass before a change to this repo is called done or pushed (backend tests, scraper tests, the screen's typecheck, build and lint). Use after any code change, before a commit, and whenever asked whether the repo is healthy.
---

# Check everything

One script, no network, no keys:

```sh
.claude/skills/check-all/check.sh            # backend, scraper and screen
.claude/skills/check-all/check.sh backend    # one part: backend, scraper or screen
```

It prints `ok` or `FAILED` per part and exits 1 if any part failed.

| Part | What runs | Where |
| --- | --- | --- |
| backend | `uv run pytest -q` | repo root |
| scraper | `python3 -m unittest test_trump_scraper` | `trump-social-scraper/` |
| screen | `npm run build` (typecheck, then Vite) and `npm run lint` (oxlint) | `ui/` |

The screen part runs `npm ci` first when `package-lock.json` is newer than the last install.

## Reading a failure

- **A test that says "test looked up ... on X" or "test asked the writing model".** The code under test
  reached for the network. That is the test set-up working (`tests/conftest.py`): pass the function a
  stand-in through its `search=`, `decide=`, `fetch=` or similar parameter. Do not loosen the fixture.
- **A lint warning.** oxlint warnings fail nothing by themselves, but the tree is kept at zero: fix it.
- **A TypeScript error after a backend change.** The interface moved; `ui/src/lib/types.ts` and
  `ui/mock/server.mjs` have to move with it (see `CLAUDE.md`).

## What this does not show

Passing means the code is sound, not that the screen looks right or that the live sources answer. For the
screen use the `screen-shots` skill. Nothing here calls Context.dev, Gemini or a venue; say so when reporting.
