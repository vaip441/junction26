# First run of the agents: what they found

14 Nov. The `contract-checker` and `judge` agents were each run once on `main` as of commit `4bf9755`, to see
whether they turn up anything a person would act on. They did. This file keeps their findings so they can be
fixed; `docs/agents.md` says what the runs taught about the agents themselves.

Nothing here has been fixed on this branch. The three findings marked **checked** were read again in the
code by the lead after the agent reported them; the rest are the agents' reading and should be confirmed
before anyone spends time on them.

## Backend and screen disagree (contract-checker)

It read the spec, the backend, the screen's types and the mock, and ran nothing. Most damaging first. The
first three pass on the mock and go wrong on the real backend, which is the kind nobody sees until the demo.

| # | What | Evidence | Who should change |
| --- | --- | --- | --- |
| 1 | **Checked.** The picked market can be one the screen has no card for. The backend names at most six markets found (`MAX_SHOWN`, `terminal/api.py:29,295-297`) but weighs up to eleven (`terminal/match.py:17`) and sends `winner` as a place among all of them (`api.py:298,318`). The screen lights the card whose place equals `winner` (`ui/src/components/input/AskStage.tsx:185`), so a winner in seventh place or later dims every card and lifts none. | The mock always picks the first of four (`ui/mock/server.mjs:489-518`). | Backend: send the winner among the six, or its place in that list. |
| 2 | **Checked.** A sentence said to the demo market never shows the rules sentence it touches. `rules.deciding` returns nothing when a market's rules are one sentence (`terminal/rules.py:42-43`), and the demo market's rules are one sentence (`terminal/seed.py:5`). | The mock gives the demo market four sentences and puts a rule on every spoken call (`ui/mock/server.mjs:156,218-221`), so rehearsals on the mock show a quote the real opener will not. | Backend seed: give the demo market rules of several sentences, as the mock has. |
| 3 | **Checked by reading; not run.** A sentence or question over 500 characters is refused with FastAPI's own 422, whose `detail` is a list (`terminal/api.py:53-60`). The screen keeps `detail` only when it is a string (`ui/src/lib/api.ts:53`), so it shows "422 Unprocessable Entity". | The mock accepts any length. A long sentence from the microphone is the likely way to hit this. | Backend: answer with a sentence. Spec: state the limits. |
| 4 | `consensus` (the same question on both venues) is never sent by the mock, so the two-venue header has never been drawn from mock data. | `api.py:78` always sends it; `mock:172-177` omits it. | Mock. |
| 5 | The tick kind `filing` is promised by the spec, the types and the mock, and the backend never sends it. | Kinds produced: `article`, `post`, `page`, `mic`, `typed`. | Drop it or build it. |
| 6 | A sentence sent to a made-up market that has no price yet gets a 409 from the backend; the spec does not list it and the mock scores it. | `api.py:218-219`; `mock:423-426`. | Spec and mock. |
| 7 | A link that is neither Kalshi nor Polymarket: the backend treats it as plain words, the mock refuses it with a 422, and the two 404 texts differ. | `api.py:341-342`; `mock:473-474`. | Mock. |
| 8 | The spec says "the two POST routes" need the key. Every write does, `DELETE` included. | `api.py:152,165,193,201,215,331`. | Spec. |
| 9 | `POST /markets/{id}/pair` exists on the backend and cannot be reached from the screen or tried on the mock. | `api.py:201-213`. | Screen and mock, if it is wanted. |
| 10 | A market dropped because it resolved is sent with `resolved: true`; the screen's types and the mock do not know the field, so the screen cannot say why a market vanished. | `terminal/poller.py:52`. | Types and mock. |
| 11 | `since` in `GET /record` is null when there are no ticks; the type says `number`. | `terminal/record.py:26-27`; `ui/src/lib/types.ts:133`. | Types. |
| 12 | Every tick carries an internal column, `date_checked`, that `pipeline.public` does not strip. | `terminal/pipeline.py:159`. | Backend. |
| 13 | "Ticks today" is the last 24 hours on the backend and since local midnight on the mock. | `api.py:80`; `mock:171,175`. | Mock; spec should say which. |
| 14 | "Why did it move?" asked twice within five minutes returns the stored answer on the backend and a new move every time on the mock. | `terminal/moves.py:139-141`; `mock:595-598`. | Mock. |
| 15 | A typed tick's `source` is `typed` on the backend and `keyboard` on the mock. | `api.py:221`; `mock:423`. | Mock. |

The spec is also silent on things the other three agree on between themselves: the field names of a market
summary, of `/record` and of `/status`. They match today, but nothing written says what they should be.

## What a stranger sees in two minutes (judge)

It took a dozen pictures on the mock at 1440 by 860 and did not read the code. Its ranking:

1. **The second beat's chart hides its own claim.** On "All", every call, both shaded bands and the "?"
   marks sit in the last twentieth of the chart's width, the "1 min early" label has the price line through
   it, and the "?" marks look like help icons. The row that best shows the web reacting ("Not priced in, 12
   min left", from a filing three minutes old) is not where the eye goes. The `1H` range gives the calls
   room; the judge could not try it, because the script could not click then. It can now.
2. **Every row of the tape leads with a percentage that is not a price.** "Up 77%" beside a price of 24%
   reads as a price move; nothing says it is how sure the call is. The three-colour bar under each row is
   unexplained.
3. **The first beat shows no web at all**, and its one web sentence is wrong: the Sources tab of a made-up
   market says "The terminal is still searching the web for this market". The jump from a spoken sentence is
   drawn as a slope across an hour, as if the price climbed.
4. **The record invites a question it does not answer**: 71 of 142 calls is exactly half, and the 45 calls
   the price ignored are left out without a reason given on the screen. Its start is a weekday and a clock
   time in 12-hour form where the charts use 24.
5. **A market just opened looks switched off.** All its rows are dimmed and tagged "Earlier" at the moment
   it should look alive; the banner covers the chart's range buttons; "57 credits" does not say whether they
   were spent or are left.
6. Smaller: three change figures on one screen that disagree (24 hours, the range on screen, the list); six
   different phrasings of what happened after a call; the last-price tag overlapping an axis label.

What it would remember tomorrow: its own sentence moving a price from 20% to 24%, and a green 73%. Not the
web doing anything.

One of its points is the mock, not the screen: the record view has no "MOCK" on it, the only place where
made-up numbers could be taken for real ones on a screenshot.
