import json

from terminal.venues import kalshi, polymarket

KALSHI = json.load(open("tests/fixtures/kalshi_event.json"))["event"]
POLY = json.load(open("tests/fixtures/polymarket_event.json"))[0]


def test_parse_links():
    assert kalshi.parse_link("https://kalshi.com/markets/kxfed/fed-meeting/kxfed-26dec") == "KXFED-26DEC"
    assert kalshi.parse_link("https://www.kalshi.com/markets/kxfed/fed-meeting/kxfed-26dec/?x=1") == "KXFED-26DEC"
    assert polymarket.parse_link("https://polymarket.com/event/fed-decision-in-december") == ("fed-decision-in-december", None)
    assert polymarket.parse_link("https://polymarket.com/event/a-b/c-d?tid=1") == ("a-b", "c-d")
    assert kalshi.parse_link("https://example.com/x") is None and kalshi.parse_link("will it rain") is None
    assert polymarket.parse_link("will it rain") is None and polymarket.parse_link("https://kalshi.com/markets/a/b/c") is None


def check(contracts, venue):
    assert contracts
    for c in contracts:
        assert c["venue"] == venue and c["venue_ref"] and c["title"] and c["rules"] and c["url"].startswith("https://")
        assert c["price"] is None or 0 <= c["price"] <= 100


def test_kalshi_fixture_yields_contracts_with_the_busiest_first():
    contracts = kalshi.parse_event(KALSHI, wanted=KALSHI["event_ticker"])
    check(contracts, "kalshi")
    busiest = max(KALSHI["markets"], key=lambda m: float(m["volume_fp"] or 0))
    assert contracts[0]["venue_ref"] == busiest["ticker"]
    assert len(contracts) == len(KALSHI["markets"])


def test_kalshi_wanted_ticker_leads():
    last = KALSHI["markets"][-1]["ticker"]
    assert kalshi.parse_event(KALSHI, wanted=last)[0]["venue_ref"] == last


def test_polymarket_fixture_yields_contracts_and_the_named_market_leads():
    contracts = polymarket.parse_event(POLY, None)
    check(contracts, "polymarket")
    busiest = max((m for m in POLY["markets"] if not m["closed"]), key=lambda m: m.get("volumeNum") or 0)
    assert contracts[0]["title"] == busiest["question"]
    named = [m for m in POLY["markets"] if not m["closed"]][-1]
    assert polymarket.parse_event(POLY, named["slug"])[0]["title"] == named["question"]


def test_closed_markets_are_left_out():
    closed = {**POLY, "markets": [{**m, "closed": True} for m in POLY["markets"]]}
    assert polymarket.parse_event(closed, None) == []
    finalized = {**KALSHI, "markets": [{**m, "status": "finalized"} for m in KALSHI["markets"]]}
    assert kalshi.parse_event(finalized, wanted="x") == []


def test_kalshi_price_rules():
    assert kalshi.price({"yes_bid_dollars": "0.4000", "yes_ask_dollars": "0.4400", "last_price_dollars": "0.9000"}) == 42.0
    assert kalshi.price({"yes_bid_dollars": "0.0000", "yes_ask_dollars": "0.0200", "last_price_dollars": "0.0200"}) == 2.0
    assert kalshi.price({"yes_bid_dollars": "0.0000", "yes_ask_dollars": "1.0000", "last_price_dollars": "0.0000"}) is None
    assert kalshi.price({}) is None


def test_kalshi_contracts_sharing_a_title_are_told_apart_by_their_outcome():
    ms = [{**KALSHI["markets"][0], "ticker": f"T{i}", "title": "Who will IPO first?", "yes_sub_title": sub}
          for i, sub in enumerate(["OpenAI", "Anthropic"])]
    titles = [c["title"] for c in kalshi.parse_event({**KALSHI, "markets": ms}, wanted="T0")]
    assert titles == ["Who will IPO first? (OpenAI)", "Who will IPO first? (Anthropic)"]


def test_kalshi_title_is_left_alone_when_it_already_names_the_outcome():
    m = {**KALSHI["markets"][0], "title": "Will X leave before Nov 12, 2026?", "yes_sub_title": "Before Nov 12, 2026"}
    assert kalshi.parse_event({**KALSHI, "markets": [m]}, wanted="x")[0]["title"] == "Will X leave before Nov 12, 2026?"


def test_only_web_links_are_accepted_and_the_stored_address_is_rebuilt():
    assert kalshi.parse_link("javascript://kalshi.com/markets/a/b/c") is None
    assert polymarket.parse_link("javascript://polymarket.com/event/a-b") is None
    assert kalshi.parse_link("https://kalshi.com/markets/a/<script>/c") is None
    link = "HTTP://www.Kalshi.com/markets/kxfed/fed-meeting/kxfed-26dec/?x=<b>#frag"
    assert kalshi.canonical(link) == "https://kalshi.com/markets/kxfed/fed-meeting/kxfed-26dec"
    assert kalshi.canonical("https://example.com/markets/a/b") is None
