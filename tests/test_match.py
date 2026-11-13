import asyncio
import json

import pytest

from terminal import match, venues
from terminal.contextdev import ContextError, parse_search
from terminal.scoring import ScoringError


def contract(venue, name, event="Event?", price=40.0):
    return {"venue": venue, "venue_ref": name, "title": f"Will {name} win?", "rules": "r", "url": None,
            "price": price, "slug": name, "event": event}


def test_market_links_keeps_one_page_per_event_in_rank_order():
    rows = parse_search(json.load(open("tests/fixtures/venue_search_response.json")))
    links = match.market_links(rows)
    assert 2 <= len(links) <= 6 and len(set(links)) == len(links)
    # a result naming one contract (Tim Cook) is tracked as its event, so the lead is the most undecided contract
    assert "https://polymarket.com/event/next-ceo-of-nvidia" in links
    assert sum("polymarket.com/event/next-ceo-of-nvidia" in u for u in links) == 1
    assert any(u.startswith("https://kalshi.com/markets/kxnvdaceo/") for u in links)


def test_market_links_drops_news_pages_and_odd_addresses():
    rows = [{"url": u, "title": "t", "description": ""} for u in [
        "https://news.kalshi.com/p/some-story", "https://polymarket.com/sports/live",
        "javascript://polymarket.com/event/x", "https://polymarket.com/event/a-b"]]
    assert match.market_links(rows) == ["https://polymarket.com/event/a-b"]


def test_candidates_skips_links_that_do_not_resolve():
    asked = []

    async def search(query, **kw):
        asked.append((query, kw))
        return [{"url": f"https://polymarket.com/event/e{i}", "title": "t", "description": ""} for i in range(3)]

    async def resolve(link):
        if link.endswith("e0"):
            raise venues.MarketNotFound("closed")
        if link.endswith("e1"):
            raise venues.VenueError("down")
        return [contract("polymarket", "a"), contract("polymarket", "b")]

    groups = asyncio.run(match.candidates("will a win", search=search, resolve=resolve))
    assert [[c["slug"] for c in g] for g in groups] == [["a", "b"]]
    assert asked == [("will a win", {"freshness": None, "include_domains": ["polymarket.com", "kalshi.com"],
                                     "num_results": 10})]


def test_candidates_raises_when_the_search_fails():
    async def search(query, **kw):
        raise ContextError("down")

    with pytest.raises(match.SearchFailed):
        asyncio.run(match.candidates("x", search=search))


def decider(answers, seen=None):
    async def decide(input, questions):
        if seen is not None:
            seen.append((input, questions))
        return answers
    return decide


def choice(**p):
    return {"type": "choice", "probabilities": p}


def test_pick_returns_the_most_probable_market_and_asks_about_its_event_and_contracts():
    groups = [[contract("kalshi", "a", "Who wins?"), contract("kalshi", "b", "Who wins?")], [contract("polymarket", "c")]]
    seen = []
    pick = asyncio.run(match.pick("will b win", groups, decide=decider(
        {"match": choice(c0=0.7, c1=0.1, none=0.2), "g0": choice(k0=0.1, k1=0.8, any=0.1)}, seen)))
    assert pick == (0, [0.7, 0.1], [1, 0])
    input, questions = seen[0]
    assert input == "A person wants to track this question: will b win"
    assert questions["match"]["criteria"] == {
        "c0": "Who wins? (contracts: Will a win?; Will b win?)", "c1": "Event? (contracts: Will c win?)",
        "none": "None of these markets is about this question"}
    assert questions["g0"]["criteria"] == {"k0": "Will a win?", "k1": "Will b win?",
                                           "any": "The question is about the whole market, not one contract"}
    assert "g1" not in questions  # one contract: nothing to choose


def test_pick_keeps_the_most_undecided_contract_when_the_question_is_about_the_whole_market():
    groups = [[contract("kalshi", "a"), contract("kalshi", "b")]]
    answers = {"match": choice(c0=0.9, none=0.1), "g0": choice(k0=0.05, k1=0.45, any=0.5)}
    assert asyncio.run(match.pick("who wins", groups, decide=decider(answers))) == (0, [0.9], [0])


def test_pick_is_no_match_only_when_none_is_likelier_than_all_markets_together():
    groups = [[contract("kalshi", "a")], [contract("polymarket", "b")]]

    def pick(**p):
        return asyncio.run(match.pick("x", groups, decide=decider({"match": choice(**p)})))[0]

    assert pick(c0=0.3, c1=0.3, none=0.4) == 0   # the same question on two venues splits the vote
    assert pick(c0=0.2, c1=0.3, none=0.5) is None
    assert pick(c0=0.05, c1=0.05, none=0.9) is None


def test_pick_with_no_groups_does_not_call_the_model():
    async def decide(input, questions):
        raise AssertionError("called")

    assert asyncio.run(match.pick("x", [], decide=decide)) == (None, [], [])


def test_pick_turns_an_odd_answer_into_a_scoring_error():
    with pytest.raises(ScoringError):
        asyncio.run(match.pick("x", [[contract("kalshi", "a")]], decide=decider({"match": {"type": "choice"}})))
