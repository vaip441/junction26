import json

from terminal.scoring import Score, is_hidden, parse_decision1, verdict


def test_verdict_picks_the_largest():
    assert verdict(Score(0.84, 0.12, 0.04, 0.8)) == ("up", 0.84)
    assert verdict(Score(0.09, 0.20, 0.71, -0.6)) == ("down", 0.71)


def test_ties_resolve_to_none():
    assert verdict(Score(0.4, 0.4, 0.2, 0.1))[0] == "none"
    assert verdict(Score(0.45, 0.10, 0.45, 0.0))[0] == "none"


def test_confident_no_effect_is_hidden_except_for_spoken_and_typed():
    s = Score(0.05, 0.90, 0.05, 0.0)
    assert is_hidden(s, "article") is True
    assert is_hidden(s, "typed") is False and is_hidden(s, "mic") is False
    assert is_hidden(Score(0.2, 0.7, 0.1, 0.1), "article") is False


def test_parse_decision1_fixture_is_a_strong_up():
    s = parse_decision1(json.load(open("tests/fixtures/decision1_response.json")))
    assert abs(s.up + s.none + s.down - 1) < 0.01 and -1 <= s.strength <= 1
    assert verdict(s)[0] == "up" and s.strength > 0.8
