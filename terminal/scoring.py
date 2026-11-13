"""Scoring a tick with Gemini Decision 1: how much does this item move the YES price?"""
import os
from typing import NamedTuple

import httpx

URL = "https://generativelanguage.googleapis.com/v1beta/decisions"
LEVELS = ["Should lower the price a lot", "Should lower the price a little",
          "Should not change the price: it is not new, not relevant, background or reference material, "
          "opinion without new facts, or a report of this market's own odds",
          "Should raise the price a little", "Should raise the price a lot"]
# For a sentence someone says or types: taken as true and new, and an opinion counts.
SPOKEN_LEVELS = ["Moves the price down a lot", "Moves the price down a little", "No effect on the price",
                 "Moves the price up a little", "Moves the price up a lot"]
HIDE_NONE_ABOVE = 0.85
_client: httpx.AsyncClient | None = None


class ScoringError(Exception):
    pass


class Score(NamedTuple):
    up: float
    none: float
    down: float
    strength: float  # -1 (down a lot) .. 1 (up a lot)


def verdict(s: Score) -> tuple[str, float]:
    """The largest of up/none/down and its probability. Any tie resolves to none."""
    if s.up > s.none and s.up > s.down:
        return "up", s.up
    if s.down > s.none and s.down > s.up:
        return "down", s.down
    return "none", s.none


def is_hidden(s: Score, kind: str) -> bool:
    """Confident no-effect items stay off the tape. Spoken and typed ticks are always shown."""
    v, confidence = verdict(s)
    return v == "none" and confidence >= HIDE_NONE_ABOVE and kind not in ("mic", "typed")


def build_request(context: str, item: str, gate: bool) -> dict:
    """One Decision 1 call: how far the item should move the price, and (when gated) whether it is news at all.

    `context` is what the market already knows (see pipeline.context); `item` is the new thing.
    """
    item = item[:2500]
    if not gate:
        return {"model": "gemini-decision-1", "input": context, "questions": {"move": {
            "type": "score",
            "instructions": f"Just said: {item}\nTreat it as true and new. How much does it move the price of YES?",
            "criteria": SPOKEN_LEVELS,
        }}}
    questions = {"move": {
        "type": "score",
        "instructions": f"New item: {item}\nHow much should this item, on its own, change the price of YES?",
        "criteria": LEVELS,
    }}
    if gate:
        questions["new"] = {
            "type": "noul",
            "instructions": f"Item: {item}\nDoes this item report a specific new development from the last day or "
                            "two that bears directly on how this market resolves?",
        }
    return {"model": "gemini-decision-1", "input": context, "questions": questions}


def parse_decision1(response: dict) -> Score:
    """Graded answer -> Score. With a newness answer, strength and the up/down probabilities are scaled by it,
    so old news, reference pages and odds reports land on "no effect" however dramatic they read."""
    try:
        answer = response["answers"]["move"]
        p = [float(answer["probabilities"].get(str(i), 0)) for i in range(len(LEVELS))]
        total = sum(p)
        new = float(response["answers"]["new"]["noul"]) if "new" in response["answers"] else 1.0
        strength = min(max((float(answer["score"]) - 2) / 2, -1.0), 1.0) * new
        up, down = (p[3] + p[4]) / total * new, (p[0] + p[1]) / total * new
        return Score(up, 1 - up - down, down, strength)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        raise ScoringError(f"unexpected Decision 1 response: {str(response)[:200]}") from e


async def score(context: str, item: str, gate: bool = True) -> Score:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=20)
    try:
        r = await _client.post(URL, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                               json=build_request(context, item, gate))
        r.raise_for_status()
        return parse_decision1(r.json())
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise ScoringError(f"Decision 1 call failed: {type(e).__name__}: {str(e)[:200]}") from e
