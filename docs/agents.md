# Working on this repo with agents

An exploration, on the branch `agent-orchestration`: what Claude Code needs to know to be useful on this
project, and how several agents can build one feature without stepping on each other. Nothing here changes
the product. Everything lives in `CLAUDE.md` and `.claude/`.

## What is here

| File | What it is for |
| --- | --- |
| `CLAUDE.md` | What every session should know: the map, the commands, the rules that hold everywhere, how we write. |
| `.claude/skills/check-all/` | One script for everything that must pass (backend, scraper, screen). |
| `.claude/skills/screen-shots/` | A script that runs the screen on the mock and takes a picture, so a change is looked at. |
| `.claude/skills/add-source/` | How a new kind of item gets onto the tape. |
| `.claude/skills/context-dev/` | What each Context.dev call costs, the limits, and how to try one before coding. |
| `.claude/skills/rehearse-demo/` | The checklist for the two minutes on stage, and the clean-up after. |
| `.claude/skills/build-feature/` | The orchestration: one feature built by several agents. |
| `.claude/agents/backend.md` | Writes under `terminal/` and `tests/` only. |
| `.claude/agents/screen.md` | Writes under `ui/` only, and looks at its work in a browser. |
| `.claude/agents/contract-checker.md` | Read-only. Finds where spec, backend, types and mock disagree. |
| `.claude/agents/judge.md` | Read-only. Looks at the demo as a stranger with two minutes. |
| `.claude/agents/market-scout.md` | Proposes markets that are in the news today. |

A skill is used by name (`/check-all`) or picked up when the task matches its description. An agent is
started by asking for it ("use the judge agent on beat 3") or by the `build-feature` skill.

## Why it is cut this way

**The seam already exists.** The backend and the screen are written by different people against one
section of the spec, "Interface for the frontend". So the agents are cut along the same seam: one owns
`terminal/`, one owns `ui/`, and the lead owns the interface between them. Because their directories do not
overlap, the two can work in the same checkout at the same time with no worktrees and no merges.

**The interface is written before anyone builds.** An agent starts with none of the conversation. The one
thing both sides must share is the interface paragraph, so the lead writes it first, completely, and puts
the text itself in both briefs. When the two sides turn out to need each other's details, that is a sign
the paragraph was too thin, not that the agents should talk.

**The checks are separate from the builders.** An agent that wrote the code is a poor judge of whether it
matches the other side or reads well on a projector. So the contract check and the judge are their own
agents, read-only, and they have not seen the work being made. The lead runs `check-all` itself rather than
taking a builder's word.

**The contract has four copies.** The spec, `terminal/api.py`, `ui/src/lib/types.ts` and
`ui/mock/server.mjs`. The mock is the dangerous one: the screen is built against it, so a field the mock
sends and the backend does not will pass every check and fail on stage. The contract-checker exists for
that case.

**Skills hold what is easy to get wrong here.** Not general advice: the things specific to this repo that
cost time or money when missed. Tests must not reach the network. Context.dev is ten requests a minute per
key and a monitor bills until it is deleted. Made-up data must say so. A screen change has to be looked at.

## The shape of a run

```
            lead: what will be true + the interface paragraph
                               |
              +----------------+----------------+
              |                                 |
        backend agent                     screen agent
     terminal/, tests/              types + mock first, then ui/
        uv run pytest               build, lint, pictures on the mock
              |                                 |
              +----------------+----------------+
                               |
                     contract-checker (read-only)
                               |
                        judge (read-only)
                               |
                 lead: check-all, then the report
```

## Tried so far

See "What a first run showed" at the end of this file. It is filled in from real runs, not from how the
pieces are meant to behave.

## Open questions

- **Does the judge find things a person would not?** It is cheap to run, but a critique that lists twenty
  small things is worse than none. Its brief asks for a ranking; whether that holds needs more runs.
- **Is the contract check better as a test?** A pytest that starts the app with a fake scorer and compares
  what the routes send against a schema generated from `types.ts` would catch the same drift without a model
  in the loop. The agent is the quick version; the test would be the durable one.
- **Should the scout write to `markets.txt`?** Today it only proposes, because adding a market starts
  fetching that costs credits. With a budget line in its brief it could be allowed to.
- **A hook instead of a habit.** `check-all` could run from a pre-push hook or a Claude Code hook after
  edits, so it does not depend on anyone remembering.
- **Real backend in the loop.** Everything the screen and judge agents see is the mock. An agent that could
  point the screen at the deployment (read-only: no key) would judge the product instead of the layout.
