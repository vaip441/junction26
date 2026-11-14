---
name: rehearse-demo
description: Prepare, rehearse or check the two-minute hackathon demo of the terminal (the market on us, the live web, ask anything, the weekend record). Use before a rehearsal or the real pitch, when asked whether the demo is ready, or to put the deployment back in a clean state afterwards.
---

# The two minutes on stage

The hackathon is won on the demo. It has four beats (`ui/PLAN.md`, "What the screen has to do"):

1. **The market on us.** "Will this team win the Context.dev challenge?" starts at 20%. A judge talks, every
   sentence is scored, and the price moves.
2. **The live web.** A real market with its price chart, the calls pinned on it, and "why did it move?".
3. **Ask anything.** A judge's question in plain words becomes a tracked market and the tape fills.
4. **The weekend record.** How many calls were made and how often the price followed.

Nothing on screen may depend on news happening to break during those two minutes.

## Before: is everything in place?

Work down the list and report each line as ready, not ready, or not checked. Do not report a line as ready
on the strength of the mock.

| Check | How |
| --- | --- |
| The code is sound | `check-all` skill |
| The deployed screen is the current one | it is built once and served by the terminal: `(cd ui && npm ci && VITE_API_URL= npm run build)`, then restart the terminal |
| The backend answers | `curl -s $BASE/markets` lists the demo market (`mu-demo`) and the tracked ones |
| The stream is alive | `curl -sN $BASE/stream` prints events or a keepalive within 15 seconds |
| Credits will last | `curl -s $BASE/status`: credits left on each key, and no key resting |
| The demo market is clean | 20%, empty tape. If not: reset it (below) |
| Beat 2 has something to show | the headline market has calls on its chart and at least one explained move: `curl -s $BASE/markets/<id>/moves` |
| Beat 3 will find a market | ask the planned question once beforehand. The match is remembered for as long as the terminal keeps running (not across a restart), so on stage it is instant |
| Beat 4 has numbers | `curl -s $BASE/record` |
| The write key is in the browser | the screen asks once; type a sentence to the demo market on the demo laptop, then reset |
| The mic works in that room | Chrome only, on the demo laptop, with the hall's noise. Typing is the fallback and is always there |

`$BASE` is the deployment's address. Writes need `-H "X-Terminal-Key: $TERMINAL_KEY"`. Never echo the key.

## Reset between rehearsals

```sh
curl -s -X POST -H "X-Terminal-Key: $TERMINAL_KEY" $BASE/markets/mu-demo/reset
```

or the Reset button under the demo market (two clicks). Only the demo market can be reset. A market asked
for in rehearsal stays tracked: remove it with "Stop tracking" if the question should look new on stage.

## Rehearsing without the backend

`npm run dev:mock` in `ui/` runs the whole screen on made-up data, and the `screen-shots` skill takes
pictures of each beat. This rehearses the hands and the words, not the product: the mock scores by keyword
and its timing is scripted.

## Keys on stage

`/` question box · `1`-`9` market by place in the list · `Space` mic on a made-up market · `W` the "why did
it move?" tab · `R` the record · `Esc` back.

## What to say when asked

Have a true answer ready, from the code, for the questions a judge will ask:

- *Is this real data?* Prices are the venues' own; items are found through Context.dev search, its news
  index, Google News, X, Reddit, Polymarket comments and Truth Social. Made-up markets and typed or spoken
  ticks are labelled and never counted in the record.
- *How fast is it?* Say what was measured and where (`README.md`, "How it works"), not a round number.
- *How do you know the calls are any good?* The record: of the ticks called up or down, how often the price
  then moved that way, judged 15 minutes later, moves under 1 point left out.
- *Does it trade?* No. It reads public data only.

## After

Page monitors cost a credit per page every ten minutes for as long as they exist, whether or not the
terminal runs. When the weekend is over, stop the terminal and then:

```sh
PYTHONPATH=. uv run --env-file .env python scripts/stop_monitors.py data/terminal.db
```
