import asyncio
import re
from datetime import date

import pytest

from terminal import madeup, watch
from terminal.madeup import market_id


def test_same_words_give_the_same_id_whatever_the_spacing_or_case():
    assert market_id("Will it snow  in Helsinki?") == market_id("will it snow in helsinki")
    assert market_id("a") != market_id("b") and re.fullmatch(r"mu-[0-9a-f]{10}", market_id("a"))


def asked(monkeypatch, reply):
    prompts = []

    async def ask_json(prompt):
        prompts.append(prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(watch, "ask_json", ask_json)
    return prompts


def test_question_for_builds_title_and_rules_with_a_30_day_deadline(monkeypatch):
    prompts = asked(monkeypatch, {"question": "Will X happen before 13 December 2026?",
                                  "resolves_yes_if": "X is officially announced."})
    q = asyncio.run(madeup.question_for("will x happen", date(2026, 11, 13)))
    assert q == {"title": "Will X happen before 13 December 2026?", "rules": "Resolves yes if X is officially announced."}
    assert "They typed: will x happen" in prompts[0] and "Today is 2026-11-13" in prompts[0] and "2026-12-13" in prompts[0]


def test_words_that_are_not_a_question_are_refused(monkeypatch):
    for reply in ({"question": None, "resolves_yes_if": ""}, {"question": "  ", "resolves_yes_if": "x"}):
        asked(monkeypatch, reply)
        with pytest.raises(madeup.NotAQuestion):
            asyncio.run(madeup.question_for("asdf", date(2026, 11, 13)))


def test_a_failed_or_malformed_reply_is_a_writing_failure(monkeypatch):
    for reply in (RuntimeError("down"), ["not", "an", "object"], {"question": 7}):
        asked(monkeypatch, reply)
        with pytest.raises(madeup.WritingFailed):
            asyncio.run(madeup.question_for("will x happen", date(2026, 11, 13)))


def test_long_replies_are_cut(monkeypatch):
    asked(monkeypatch, {"question": "Q" * 500, "resolves_yes_if": "r" * 2000})
    q = asyncio.run(madeup.question_for("will x happen", date(2026, 11, 13)))
    assert len(q["title"]) == 200 and len(q["rules"]) == 600


def test_starting_price_is_the_models_yes_probability_in_percent():
    seen = []

    def price(p, headlines):
        async def decide(input, questions):
            seen.append((input, questions))
            return {"start": {"type": "noul", "noul": p}}
        return asyncio.run(madeup.starting_price("Will X?", "Resolves yes if X.", headlines, decide=decide))

    assert price(0.37, ["Headline one", "Headline two"]) == pytest.approx(37.0)
    assert price(0.9999, []) == 99.0 and price(0.0, []) == 1.0
    assert "Question: Will X?" in seen[0][0] and "- Headline one\n- Headline two" in seen[0][0]
    assert seen[0][1] == {"start": {"type": "noul", "instructions": "Will this resolve yes?"}}
    assert "none found" in seen[1][0]
