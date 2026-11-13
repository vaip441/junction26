"""Plain words -> the Kalshi or Polymarket market that asks the same thing, if there is one.

Context.dev search restricted to the two venues, and Polymarket's own search, find market pages from
the raw words; each is resolved through the venue (web search also returns closed and last-year pages)
and Decision 1 picks.
"""
import asyncio
import logging
import math

from terminal import contextdev, scoring, venues
from terminal.venues import kalshi, polymarket

VENUE_SITES = ["polymarket.com", "kalshi.com"]
log = logging.getLogger(__name__)
MAX_EVENTS, OWN_RESULTS = 8, 3  # events weighed in all; how many of them may come from Polymarket's own search
SHOWN, MAX_CONTRACTS = 6, 30  # contracts named when describing an event; contracts offered when choosing one
SEARCH_SECONDS = 20  # a person is waiting: with every key resting, fail rather than queue for minutes


class SearchFailed(Exception):
    pass


def _links(results: list[dict]) -> dict[str, str]:
    links = {}
    for r in results:
        if (ticker := kalshi.parse_link(r["url"])) is not None:
            links.setdefault("k:" + ticker, kalshi.canonical(r["url"]))
        elif (slugs := polymarket.parse_link(r["url"])) is not None:
            links.setdefault("pm:" + slugs[0], f"https://polymarket.com/event/{slugs[0]}")
    return links


def market_links(results: list[dict]) -> list[str]:
    """Event pages among search results, in rank order, one per event. A page naming one contract is
    taken as its event: which contract leads is decided by the question, not by search rank."""
    return list(_links(results).values())[:MAX_EVENTS]


async def candidates(words: str, *, search=None, resolve=None, venue_search=None) -> list[list[dict]]:
    """One list of open contracts per event found, most undecided contract first.

    Two searches side by side: Polymarket's own (it knows markets listed today) and the web search
    restricted to both venues (it also finds Kalshi). SearchFailed only when both fail.
    """
    web, own = await asyncio.gather(
        asyncio.wait_for((search or contextdev.search)(words, freshness=None, include_domains=VENUE_SITES,
                                                       num_results=10), SEARCH_SECONDS),
        asyncio.wait_for(asyncio.to_thread(venue_search or polymarket.search, words), SEARCH_SECONDS),
        return_exceptions=True)
    for name, found in (("web", web), ("Polymarket", own)):
        if isinstance(found, BaseException):
            log.warning("%s search failed for %r: %s: %s", name, words[:60], type(found).__name__, found)
    if isinstance(web, BaseException) and isinstance(own, BaseException):
        raise SearchFailed(str(web))
    links = {} if isinstance(own, BaseException) else {
        "pm:" + slug: f"https://polymarket.com/event/{slug}" for slug in own[:OWN_RESULTS]}
    for key, link in ({} if isinstance(web, BaseException) else _links(web)).items():
        links.setdefault(key, link)
    found = await asyncio.gather(*((resolve or venues.resolve)(link) for link in list(links.values())[:MAX_EVENTS]),
                                 return_exceptions=True)
    return [g for g in found if isinstance(g, list) and g]  # closed, missing or unreachable ones drop out


async def pick(words: str, groups: list[list[dict]], *, decide=None) -> tuple[int | None, list[float], list[int]]:
    """(the matching group or None, each group's probability, the contract to lead each group).

    One Decision 1 call: which event, and for each event with several contracts, which contract. A group
    keeps its own lead (index 0) unless one contract is more likely than not the one asked about.
    """
    if not groups:
        return None, [], []
    describe = lambda g: f"{g[0]['event']} (contracts: {'; '.join(c['title'] for c in g[:SHOWN])})"[:600]
    questions = {"match": {
        "type": "choice", "instructions": "Which of these prediction markets would a person watch to follow this question?",
        "criteria": {**{f"c{i}": describe(g) for i, g in enumerate(groups)},
                     "none": "None of these markets is about this question"}}}
    for i, g in enumerate(groups):
        if len(g) > 1:
            questions[f"g{i}"] = {
                "type": "choice", "instructions": f'In the market "{g[0]["event"][:200]}", which contract is this question about?',
                "criteria": {**{f"k{j}": c["title"][:300] for j, c in enumerate(g[:MAX_CONTRACTS])},
                             "any": "The question is about the whole market, not one contract"}}
    answers = await (decide or scoring.decide)(f"A person wants to track this question: {words}", questions)
    try:
        p = {k: float(v) for k, v in answers["match"]["probabilities"].items()}
        probs = [p.get(f"c{i}", 0.0) for i in range(len(groups))]
        if not all(math.isfinite(v) for v in p.values()):
            raise ValueError("not a number")
        leads = []
        for i, g in enumerate(groups):
            kp = {k: float(v) for k, v in answers[f"g{i}"]["probabilities"].items()} if f"g{i}" in questions else {}
            best = max(kp, key=kp.get, default="any")
            j = int(best[1:]) if best != "any" and kp[best] > 0.5 else 0
            leads.append(j if 0 <= j < len(g) else 0)  # an answer naming no contract keeps the group's own lead
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise scoring.ScoringError(f"unexpected Decision 1 answer: {str(answers)[:200]}") from e
    # the same question on both venues splits the vote, so "none" must beat all the markets together
    winner = None if p.get("none", 0.0) >= sum(probs) else max(range(len(groups)), key=probs.__getitem__)
    return winner, probs, leads
