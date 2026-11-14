---
name: screen-shots
description: Take a picture of the terminal's screen running on the mock backend and look at it. Use after any change under ui/, when asked how the screen looks, to check a state (a question being asked, a typed sentence, the record view, a narrow window), or to compare before and after.
---

# Look at the screen

A change to `ui/` is not done until it has been looked at. This script runs the mock backend and the dev
server on free ports, drives headless Chrome, saves a PNG and stops everything:

```sh
uv run --with playwright python .claude/skills/screen-shots/shot.py [options]
```

Then open the PNG with the Read tool and say what you see.

| To see | Options |
| --- | --- |
| A real market, chart and tape | (none: the market in second place) |
| The demo market before anyone speaks | `--market 1` |
| A judge's sentence scored | `--market 1 --say "This is a great demo" --wait 4` |
| A question being asked | `--ask "will the fed cut rates" --wait 2.5` (the cards), `--wait 8` (the market open, tape filling) |
| A question nobody lists | `--ask "something made up"` |
| A failed search / not a question | `--ask "fail now"` / `--ask "hello"` |
| The weekend record | `--keys r --wait 2.5` |
| The price under the pointer | `--hover 640,480` |
| A phone | `--width 420 --height 860` |
| A still tape | `--quiet` |

`--out` names the file (default `/tmp/terminal-screen.png`). The script exits 1 and prints the message if
the page threw an error.

The mock's magic words (`fail`, `hello`, `made up`, `fail503`) are listed at the top of `ui/mock/server.mjs`.

## What to look for

Check the picture against the rules in `ui/PLAN.md`, not against taste:

- Something on screen says what it is doing; no empty panel without words.
- Green, red and grey mean up, down and no effect, and no other colour carries meaning.
- Made-up things say so (`Made up`, `Typed`, `Spoken`, `Earlier`).
- Prices read as `82%`, changes as `+18 pts`.
- Nothing is cut off, overlapping or covering the price line.

## Limits

The mock is not the backend: its data is invented and its timing is scripted. A picture proves the layout,
not that the real stream fills it. Needs Chrome on the machine (or `--browser chromium` after
`uv run --with playwright playwright install chromium`) and `npm ci` done in `ui/`.
