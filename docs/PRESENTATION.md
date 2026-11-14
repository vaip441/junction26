# Two-minute presentation

One screen, one presenter, two minutes. Every live step has an offline fallback, so the talk is the same
whether the network holds or not.

No figure is written into this script. Read the numbers from the screen as you speak: the status line at
the foot shows measured latency, and the record shows its own counts. If a figure is not on the screen,
do not say one.

## Before you walk on

| Check | How |
| --- | --- |
| Live terminal running | `uv run --env-file .env uvicorn terminal.api:app --port 18911`, started at least an hour before, so the tape and the record have something on them |
| Offline fallback running | `uv run python -m terminal.offline` in a second terminal (port 18912, no keys, no network) |
| Two browser tabs open | Tab A: `http://127.0.0.1:18911/?presentation=1` (live). Tab B: `http://127.0.0.1:18912/?presentation=1&market=replay-lula` (offline) |
| Terminal key entered | In tab A, type one sentence on the made-up market once. The key prompt appears the first time only |
| Made-up market reset | On "Will this team win the Context.dev challenge?", press Reset, so it starts at its opening price with an empty tape |
| Microphone allowed | In tab A, on the made-up market, press Space once, allow the microphone, press Space again to turn it off |
| Browser zoom | 100%. Presentation mode already scales the type to the window |
| Backup video | On the desktop, ready to play full screen (see the shot list below) |

**Prepared market.** The headline market in `markets.txt`: the next CEO of Nvidia on Polymarket, checked
every minute. Presentation mode opens on the real market with the most ticks today; if that is not the
Nvidia one, press its number key (`1`-`9`, in list order) or open
`http://127.0.0.1:18911/?presentation=1&market=<id>` with its id from `GET /markets`.

**Prepared question for the closing interaction.** The made-up market "Will this team win the
Context.dev challenge?" Ask a judge to say one sentence about the demo.

**What to say about Context.dev, in one breath.** "Context.dev is how we see the web. Its search finds the
pages and posts for each market and hands us the passage that matters, its news index brings company news
minutes after it is published, and its scraper reads the page fresh for the publish time. Every item says
on the tape how it was found."

## The script

### 0:00–0:15 · The problem, and a real price move

- **Do:** Tab A is on the Nvidia market. Point at the big number, labelled "YES probability", and at the
  chart.
- **Say:** "Prediction markets move all day. When one jumps, an analyst has to dig through news, posts and
  the contract's small print to work out why. This is a real market, live. Terminal does that digging as
  it happens."
- **Offline fallback:** Tab B, the Lula replay. Say "this is a finished market, replayed from stored data"
  and point at the REPLAY tag. Use the same words for the problem.

### 0:15–0:45 · Live-web discovery and the scored tape

- **Do:** Point at the tape on the right. Read the newest call aloud: its verdict, its headline, then the
  line under it that starts "Found via Context.dev".
- **Say:** "Every article and post lands here scored: up, down, or no effect on the price of YES. This one
  was found by Context.dev's web search. Next to the publisher you see how we found it, and those are two
  different things. The percentage is the model's confidence in its call, not a promise."
- **Do:** Press the Sources tab under the chart. Point at the "items found by" row.
- **Say:** "And here is the count for this market, by how each item was found."
- **Offline fallback:** In tab B press Space to start the replay. Say "each post lands when it was posted,
  scored knowing only what was known at that minute." The ticks there are tagged "Prerecorded replay":
  do not call them Context.dev finds.

### 0:45–1:10 · The likely explanation, the passage, the rule

- **Do:** Press `W` ("Why did it move?"). If there is a move listed, click it; the tape scrolls to the
  tick. If there is none, press "Explain today's move".
- **Say:** "When the price jumps, Terminal searches at once and names the likeliest explanation among what
  it found. Here is the passage from the article, and here is the sentence of the contract's rules it
  bears on. It is a likely explanation, not proof: the model picks the best match, and sometimes the
  honest answer is that no item explains it."
- **Offline fallback:** In tab B, after the replay has played a few seconds, point at a call on the tape
  with its "Contract rule" line. Skip "Why did it move?" (a replay has no jumps of its own to explain).

### 1:10–1:30 · Real time, measured

- **Do:** Point at the status line at the foot: LIVE, "Stream connected", "last update … ago", "price
  checked every …", and the measured "found → scored" figure.
- **Say:** "This is live: the stream is connected, the price is checked every minute, and the web is
  searched on a schedule. And we measure ourselves: from the moment an item reaches us to the moment it is
  scored and on the tape takes" *(read the median from the status line)*. "That is measured on real ticks
  from the last day, not estimated."
- **If no latency figure is shown:** fewer than five live ticks have been measured. Say "it reports its
  own latency once it has enough ticks to measure" and move on. Do not quote a number.
- **Offline fallback:** In tab B the status line says REPLAY and shows no latency, by design. Say "the
  live terminal measures its own latency; a replay has none to measure."

### 1:30–1:45 · Directional follow-through, with the method

- **Do:** Press `R`.
- **Say:** Read the sentence on the screen as written: "Of … calls followed by a qualifying price move, …
  moved in the predicted direction." Then: "The rest moved the other way or did not move, and all three
  counts are here. We compare the price fifteen minutes after each call. This is follow-through, not
  accuracy, and it does not prove any item moved the price."
- **Do:** Press `Esc`.
- **If the record is empty:** it says so. Say "no live call has completed its window yet" and show the
  method paragraph instead.
- **Offline fallback:** In tab B let the Texas replay (the shortest) run to its end, or have it finished
  beforehand: its result card gives the same counts for that replay. Say "these are the replay's own
  calls, kept apart from the live record."

### 1:45–2:00 · The judge speaks, and the close

- **Do:** In tab A press the number key of "Will this team win the Context.dev challenge?" (tagged Made
  up; the status line says SYNTHETIC). Press Space to turn the microphone on. Hand over to a judge.
- **Say:** "Last one is for fun, and it is labelled as such: a made-up market about us. Say something
  about this demo." *(The judge speaks; the sentence lands on the tape, scored, and the price moves.)*
  "That is an illustrative market, not a forecast. Everything before it was real. Terminal: the live web,
  turned into sourced explanations for why markets move."
- **Do:** Press Space to turn the microphone off.
- **Offline fallback:** The made-up market takes no input offline (there is no scorer, and none is
  imitated). End on the replay's result card and the closing line.

## If something goes wrong

| What you see | What to do |
| --- | --- |
| Status line says "Stream disconnected, reconnecting…" and NOT LIVE | Keep talking; it reconnects by itself and reloads what it missed. If it has not within about fifteen seconds, switch to tab B and say "here is a finished market, replayed" |
| A typed or spoken sentence answers "scoring unavailable, try again" | Type it again once. If it fails again, say "the scorer is not answering" and close on the record or a replay instead |
| A new question in the Ask bar is slow | Do not wait on stage. The prepared market is already tracked; skip asking a new one |
| "Explain today's move" answers "the price has not moved a point in the last day" | That is a true answer. Say so, and point at a call on the tape with its passage and rule instead |
| The microphone hears nothing, or the hall is too loud | Turn it off with Space and type the judge's sentence into the box beside it. Same scoring, tagged Typed |
| The key prompt appears | Enter the terminal key (it is in `.env` as `TERMINAL_KEY`); it is asked once per browser |
| The live terminal is down altogether | Tab B. Everything from 0:00 to 1:45 has an offline line above |
| Both are down | Play the backup video |

## Backup video: shot list

Record these from the live terminal in presentation mode, at the projector's resolution, with no
narration (speak over it live). Nothing here is recorded yet; this is the list to shoot.

1. The populated Nvidia market: YES probability, chart, tape, status line showing LIVE. Five seconds, still.
2. A new tick arriving on the tape, with its "Found via Context.dev" line readable.
3. The Sources tab, with the "items found by" row.
4. `W`: a move in "Why did it move?", a click on it, and the tape scrolling to the tick with its passage and
   contract rule.
5. The status line, held long enough to read the measured latency.
6. `R`: the record, held for the sentence and the three counts, then `Esc`.
7. A replay (Texas) from Replay to its result card. May be sped up in editing; keep the REPLAY tag in frame.
8. The made-up market: one spoken sentence landing on the tape and the price moving.

## What needs rehearsal by hand

- The whole run against the clock: the 0:45 and 1:30 marks are the tight ones.
- Which number key reaches the Nvidia market and the made-up market in the list as it is on the day.
- The microphone in the actual hall: how loud the room is decides between speaking and typing.
- The projector: check the tape is readable from the back row at its resolution.
- Switching from tab A to tab B mid-sentence, once, so the fallback is not a surprise.
