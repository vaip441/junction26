---
name: build-feature
description: Build one feature of the terminal that touches both the backend and the screen, by agreeing the interface first and then running the backend and screen agents side by side, a contract check, and a judge's look. Use when asked to add or change something a user sees that needs new data from the backend, or when asked to orchestrate, parallelise or split work across agents in this repo.
---

# One feature, several agents

The backend and the screen are built by different people against one written interface. This skill does the
same with agents: you are the lead, you own the interface and the final answer, and the agents in
`.claude/agents/` do the parts. `docs/agents.md` explains why it is cut this way.

Use it for a feature that crosses the line between `terminal/` and `ui/`. For a change on one side only,
skip it and do the work (or hand it to that side's agent alone).

## 1. Say what will be true

Write two or three sentences: what a person will see, on which of the demo's four beats it lands
(`ui/PLAN.md`), and what is deliberately left out. If it serves none of the four beats, stop and say so
before building anything.

## 2. Write the interface first

Before any agent starts, edit "Interface for the frontend" in
`docs/superpowers/specs/2026-11-13-terminal-design.md`: the new field, route or stream event, with its
exact name, type, units (percent, points, unix seconds) and what it is when there is nothing to send
(`null`, `[]`, absent). This paragraph is the only thing the two sides share, so make it complete enough
that neither needs to ask the other.

Show the person the sentences from step 1 and the interface paragraph, and wait for a yes if anything in
them is a real choice. Everything after this is cheap to redo; a wrong interface is not.

## 3. Run the two sides at once

Start both in one message so they run in parallel. They work in the same checkout: the backend agent writes
only under `terminal/` and `tests/`, the screen agent only under `ui/`, so they cannot collide.

- **`backend` agent**: give it the interface paragraph and step 1. It implements and tests the backend side.
- **`screen` agent**: give it the same two things. It extends `ui/src/lib/types.ts` and
  `ui/mock/server.mjs` first, so it can build against the mock without waiting for the backend, then the
  components, then looks at the result with the `screen-shots` skill.

Each brief must stand alone: an agent starts with none of this conversation. Include the interface text
itself, not a pointer to "what we discussed".

## 4. Check the contract

When both are back, run the **`contract-checker` agent**. It reads the spec, `terminal/api.py`,
`ui/src/lib/types.ts` and `ui/mock/server.mjs` and reports every place they disagree. Send each
disagreement back to the side that is wrong (continue that agent rather than starting a new one, so it
keeps what it knows). If the spec is what is wrong, fix the spec yourself and tell both sides.

## 5. Let a judge look

Run the **`judge` agent** on the beat the feature lands on. It plays a hackathon judge seeing the screen for
the first time and reports what it did not understand in ten seconds. Fix what is cheap; list what is not.

## 6. Check and report

Run the `check-all` skill yourself; do not take an agent's word that it passed. Then report:

- what is now true, in the words of step 1;
- what was verified and how (tests, the mock, pictures), and what was **not** tried against the real
  backend, Context.dev or a venue;
- anything an agent flagged that you did not fix.

Do not commit or push unless asked. If asked, one commit per side reads best in the log
(`feat: ...` for the backend, `feat(ui): ...` for the screen).

## When to break the pattern

- **The backend part is a new source of items**: the `backend` agent uses the `add-source` skill, and the
  screen side is often only a label and a logo.
- **It needs a new Context.dev call**: decide the cost in step 2, using the `context-dev` skill, and put the
  number in the brief.
- **One side is trivial**: do it yourself and spawn only the other.
- **The two sides turn out to depend on each other's details**: the interface paragraph was too thin. Stop
  both, fix the paragraph, and continue them with the new text.
