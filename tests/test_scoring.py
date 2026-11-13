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


def scored_with(handler, monkeypatch):
    import asyncio

    import httpx

    from terminal import scoring

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(scoring, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return asyncio.run(scoring.score("Market: title", "text", True))


def test_score_parses_a_real_response(monkeypatch):
    import httpx

    body = json.load(open("tests/fixtures/decision1_response.json"))
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=body)

    s = scored_with(handler, monkeypatch)
    assert verdict(s)[0] == "up"
    assert seen[0]["model"] == "gemini-decision-1" and seen[0]["questions"]["move"]["type"] == "score"
    assert seen[0]["input"] == "Market: title"


def test_score_turns_api_failures_into_scoring_errors(monkeypatch):
    import httpx
    import pytest

    from terminal.scoring import ScoringError

    def boom(request):
        raise httpx.ReadTimeout("slow")

    for handler in (lambda r: httpx.Response(500, text="oops"), lambda r: httpx.Response(200, text="<html>"),
                    lambda r: httpx.Response(200, json={"prompt_feedback": {"block_reason": "x"}}), boom):
        with pytest.raises(ScoringError):
            scored_with(handler, monkeypatch)


def answers(score, probs, new=None):
    a = {"move": {"type": "score", "score": score, "probabilities": {str(i): p for i, p in enumerate(probs)}}}
    if new is not None:
        a["new"] = {"type": "noul", "noul": new}
    return {"answers": a}


def test_request_puts_the_market_context_in_the_input_and_asks_two_questions():
    from terminal.scoring import build_request

    r = build_request("Today is 13 November 2026.\nMarket: M", "reuters.com: Board meets", True)
    assert r["input"] == "Today is 13 November 2026.\nMarket: M"
    assert set(r["questions"]) == {"move", "new"}
    assert r["questions"]["move"]["type"] == "score" and len(r["questions"]["move"]["criteria"]) == 5
    assert "not new" in r["questions"]["move"]["criteria"][2]
    assert "reuters.com: Board meets" in r["questions"]["move"]["instructions"]
    assert r["questions"]["new"]["type"] == "noul" and "reuters.com: Board meets" in r["questions"]["new"]["instructions"]


def test_spoken_and_typed_items_are_not_asked_whether_they_are_new():
    from terminal.scoring import build_request

    r = build_request("ctx", "typed: that is clever", False)
    assert set(r["questions"]) == {"move"}
    # a sentence someone says is taken as true and new; opinions count, unlike in a news article
    assert r["questions"]["move"]["criteria"][2] == "No effect on the price"
    assert "Treat it as true and new" in r["questions"]["move"]["instructions"]


def test_an_item_that_is_not_new_loses_its_strength_and_becomes_no_effect():
    strong_up = [0.0, 0.0, 0.05, 0.15, 0.80]
    fresh = parse_decision1(answers(3.75, strong_up, new=0.9))
    stale = parse_decision1(answers(3.75, strong_up, new=0.1))
    ungated = parse_decision1(answers(3.75, strong_up))
    assert abs(ungated.strength - 0.875) < 1e-9 and verdict(ungated)[0] == "up"
    assert abs(fresh.strength - 0.875 * 0.9) < 1e-9 and verdict(fresh)[0] == "up"
    assert abs(stale.strength - 0.0875) < 1e-9 and verdict(stale)[0] == "none"
    assert abs(stale.up - 0.095) < 1e-9 and abs(stale.up + stale.none + stale.down - 1) < 1e-9


def test_an_out_of_range_newness_answer_cannot_inflate_the_score():
    import pytest

    from terminal.scoring import ScoringError

    strong_up = [0.0, 0.0, 0.05, 0.15, 0.80]
    over = parse_decision1(answers(3.75, strong_up, new=1.7))
    assert abs(over.strength - 0.875) < 1e-9 and over.up <= 1 and over.none >= 0
    under = parse_decision1(answers(3.75, strong_up, new=-0.5))
    assert under.strength == 0 and under.up == 0 and under.none == 1
    with pytest.raises(ScoringError):
        parse_decision1(answers(3.75, strong_up, new=float("nan")))
    with pytest.raises(ScoringError):
        parse_decision1(answers(float("inf"), strong_up))


def test_decide_returns_answers_and_maps_failures(monkeypatch):
    import asyncio

    import httpx
    import pytest

    from terminal import scoring

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    seen = []

    def ask(response):
        def handler(request):
            seen.append(json.loads(request.content))
            return response
        monkeypatch.setattr(scoring, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        return asyncio.run(scoring.decide("the input", {"q": {"type": "noul", "instructions": "i"}}))

    assert ask(httpx.Response(200, json={"answers": {"q": {"noul": 0.4}}})) == {"q": {"noul": 0.4}}
    assert seen[0] == {"model": "gemini-decision-1", "input": "the input",
                       "questions": {"q": {"type": "noul", "instructions": "i"}}}
    for bad in (httpx.Response(500), httpx.Response(200, json={"error": "blocked"}), httpx.Response(200, text="x")):
        with pytest.raises(scoring.ScoringError):
            ask(bad)
