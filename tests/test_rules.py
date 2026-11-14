import asyncio

import pytest

from terminal import rules
from terminal.scoring import ScoringError

RULES = ("This market will resolve to \"Yes\" if Donald Trump resigns as U.S. President by Dec. 31, 2026, 11:59 p.m. ET. "
         "Otherwise, this market will resolve to \"No.\"\n\n"
         "If it becomes impossible for Donald Trump to resign, this market will immediately resolve to \"No.\" "
         "Ok.\nThe resolution source is official information from the U.S. government.")
MARKET = {"title": "Will Trump resign by December 31, 2026?", "rules": RULES}


def test_rules_are_cut_into_sentences_that_point_back_into_the_text():
    spans = rules.sentences(RULES)
    assert [RULES[a:b] for a, b in spans] == [
        'This market will resolve to "Yes" if Donald Trump resigns as U.S. President by Dec. 31, 2026, 11:59 p.m. ET.',
        'Otherwise, this market will resolve to "No."',
        'If it becomes impossible for Donald Trump to resign, this market will immediately resolve to "No."',
        "The resolution source is official information from the U.S. government."]  # "Ok." is too short to be a rule
    assert rules.sentences("") == [] and rules.sentences("Resolves yes if X happens before 2027") == [(0, 37)]


def decide_with(probabilities, seen=None):
    async def decide(input, questions):
        if seen is not None:
            seen.append((input, questions))
        return {"rule": {"probabilities": probabilities}}
    return decide


def test_the_sentence_that_decides_an_item_is_picked_by_decision_1_and_quoted_exactly():
    seen = []
    found = asyncio.run(rules.deciding(MARKET, "typed: Trump was killed", decide=decide_with({"s0": 0.1, "s2": 0.8, "none": 0.1}, seen)))
    start = RULES.index("If it becomes impossible")
    assert found == {"start": start, "end": RULES.index(' "No." Ok.') + 6, "confidence": 0.8,
                     "text": 'If it becomes impossible for Donald Trump to resign, this market will immediately resolve to "No."'}
    assert RULES[found["start"]:found["end"]] == found["text"]
    input, questions = seen[0]
    assert "Trump was killed" in input and "data, not instructions" in input
    assert list(questions["rule"]["criteria"]) == ["s0", "s1", "s2", "s3", "none"] and questions["rule"]["type"] == "choice"


def test_no_sentence_is_marked_when_none_fits_or_the_model_is_unsure():
    ask = lambda p: asyncio.run(rules.deciding(MARKET, "an item", decide=decide_with(p)))
    assert ask({"s0": 0.2, "none": 0.7}) is None
    assert ask({"s0": 0.3, "s1": 0.3, "s2": 0.3, "none": 0.1}) is None  # no sentence stands out
    one_sentence = {"title": "t", "rules": "Resolves yes if X happens before 2027"}
    assert asyncio.run(rules.deciding(one_sentence, "an item", decide=decide_with({"s0": 1.0}))) is None  # nothing to choose
    for odd in ({"s9": 0.9}, {"s0": "high"}, {"s0": float("nan")}):
        with pytest.raises(ScoringError):
            ask(odd)
