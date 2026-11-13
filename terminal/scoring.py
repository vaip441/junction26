"""Scoring a tick with Gemini Decision 1: how much does this item move the YES price?"""
import os
from typing import NamedTuple

import httpx

URL = "https://generativelanguage.googleapis.com/v1beta/decisions"
LEVELS = ["Moves the price down a lot", "Moves the price down a little", "No effect on the price",
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


def build_request(title: str, rules: str, text: str) -> dict:
    return {
        "model": "gemini-decision-1",
        "input": f"Market: {title}\nRules: {rules[:1500]}",
        "questions": {"move": {
            "type": "score",
            "instructions": f"New item: {text[:2000]}\nHow much does this new item move the price of YES in this market?",
            "criteria": LEVELS,
        }},
    }


def parse_decision1(response: dict) -> Score:
    try:
        answer = response["answers"]["move"]
        p = [float(answer["probabilities"].get(str(i), 0)) for i in range(len(LEVELS))]
        total = sum(p)
        strength = min(max((float(answer["score"]) - 2) / 2, -1.0), 1.0)
        return Score((p[3] + p[4]) / total, p[2] / total, (p[0] + p[1]) / total, strength)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        raise ScoringError(f"unexpected Decision 1 response: {str(response)[:200]}") from e


async def score(title: str, rules: str, text: str) -> Score:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=20)
    try:
        r = await _client.post(URL, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                               json=build_request(title, rules, text))
        r.raise_for_status()
        return parse_decision1(r.json())
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise ScoringError(f"Decision 1 call failed: {type(e).__name__}: {str(e)[:200]}") from e
