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


def undecided(prices):
    return sorted(prices, key=lambda p: abs(p - 50))


def test_kalshi_fixture_yields_contracts_with_the_most_undecided_first():
    contracts = kalshi.parse_event(KALSHI, wanted=KALSHI["event_ticker"])
    check(contracts, "kalshi")
    assert len(contracts) == len(KALSHI["markets"])
    prices = [c["price"] for c in contracts]
    assert prices == undecided(prices)


def test_the_most_undecided_contract_leads_not_the_busiest():
    def m(ticker, bid, ask, volume):
        return {**KALSHI["markets"][0], "ticker": ticker, "yes_bid_dollars": bid, "yes_ask_dollars": ask,
                "volume_fp": volume}
    event = {**KALSHI, "markets": [m("LONGSHOT", "0.0100", "0.0200", "9000000"), m("LIVE", "0.3000", "0.3400", "5"),
                                   m("NOPRICE", "0.0000", "1.0000", "50")]}
    event["markets"][2]["last_price_dollars"] = "0.0000"
    assert [c["venue_ref"] for c in kalshi.parse_event(event, wanted="x")] == ["LIVE", "LONGSHOT", "NOPRICE"]


def test_kalshi_wanted_ticker_leads():
    last = KALSHI["markets"][-1]["ticker"]
    assert kalshi.parse_event(KALSHI, wanted=last)[0]["venue_ref"] == last


def test_polymarket_fixture_yields_contracts_and_the_named_market_leads():
    contracts = polymarket.parse_event(POLY, None)
    check(contracts, "polymarket")
    prices = [c["price"] for c in contracts]
    assert prices == undecided(prices)
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


def test_resolve_tells_bad_links_missing_markets_and_outages_apart(monkeypatch):
    import asyncio

    import pytest

    from terminal import venues

    with pytest.raises(venues.NotAVenueLink):
        asyncio.run(venues.resolve("will jensen get fired"))
    monkeypatch.setattr(polymarket, "lookup", lambda *a: [])
    with pytest.raises(venues.MarketNotFound):
        asyncio.run(venues.resolve("https://polymarket.com/event/gone"))

    def html_instead_of_json(*a):
        raise ValueError("Expecting value: line 1 column 1")

    monkeypatch.setattr(polymarket, "lookup", html_instead_of_json)
    with pytest.raises(venues.VenueError):
        asyncio.run(venues.resolve("https://polymarket.com/event/e"))
    monkeypatch.setattr(kalshi, "lookup", lambda *a: (_ for _ in ()).throw(KeyError("event")))
    with pytest.raises(venues.VenueError):
        asyncio.run(venues.resolve("https://kalshi.com/markets/a/b/c"))


def test_kalshi_lookup_accepts_a_market_ticker(monkeypatch):
    import io
    import urllib.error

    def get(path, **params):
        if path == "/events/KX-M1":
            raise urllib.error.HTTPError(path, 404, "not found", {}, io.BytesIO(b"{}"))
        if path == "/markets/KX-M1":
            return {"market": {"event_ticker": "KX"}}
        assert path == "/events/KX"
        return {"event": KALSHI}

    monkeypatch.setattr(kalshi, "get", get)
    assert len(kalshi.lookup("KX-M1")) == len(KALSHI["markets"])


def test_kalshi_lookup_of_nothing_is_market_not_found(monkeypatch):
    import io
    import urllib.error

    import pytest

    from terminal import venues

    def get(path, **params):
        raise urllib.error.HTTPError(path, 404, "not found", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(kalshi, "get", get)
    with pytest.raises(venues.MarketNotFound):
        kalshi.lookup("NOPE")


def test_placeholder_contracts_are_left_out_unless_named_but_new_untraded_ones_are_kept():
    def pm(slug, price, volume, open_):
        return {**POLY["markets"][0], "slug": slug, "question": slug, "closed": False, "volumeNum": volume,
                "acceptingOrders": open_, "outcomePrices": json.dumps([str(price), str(1 - price)])}
    # "Candidate S" style placeholders take no orders; a game listed today takes orders but has no trades yet
    event = {**POLY, "markets": [pm("candidate-s", 0.5, 0, False), pm("real", 0.2, 900.0, True),
                                 pm("candidate-t", 0.5, None, False), pm("listed-today", 0.34, None, True)]}
    assert [c["slug"] for c in polymarket.parse_event(event, None)] == ["listed-today", "real"]
    assert [c["slug"] for c in polymarket.parse_event(event, "candidate-s")] == ["candidate-s", "listed-today", "real"]

    def k(ticker, volume, bid="0.0000", ask="1.0000"):
        return {**KALSHI["markets"][0], "ticker": ticker, "status": "active", "volume_fp": volume,
                "yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": "0.0000"}
    event = {**KALSHI, "markets": [k("PLACEHOLDER", "0.00"), k("REAL", "12.00", "0.10", "0.12"),
                                   k("QUOTED", "0.00", "0.30", "0.40")]}
    assert [c["venue_ref"] for c in kalshi.parse_event(event, wanted="x")] == ["QUOTED", "REAL"]
    assert [c["venue_ref"] for c in kalshi.parse_event(event, wanted="PLACEHOLDER")] == ["PLACEHOLDER", "QUOTED", "REAL"]


def test_every_contract_carries_its_events_title():
    assert {c["event"] for c in kalshi.parse_event(KALSHI, wanted="x")} == {KALSHI["title"]}
    assert {c["event"] for c in polymarket.parse_event(POLY, None)} == {POLY["title"]}


def test_polymarket_search_returns_open_event_slugs_in_rank_order(monkeypatch):
    asked = []

    def get(url, **params):
        asked.append((url, params))
        return {"events": [{"slug": "unl-est-bul-2026-11-16", "closed": False}, {"slug": "old-game", "closed": True},
                           {"slug": "bad slug!"}, {"slug": "estonia-kml-2027-champion"}]}

    monkeypatch.setattr(polymarket, "get", get)
    assert polymarket.search("will estonia win at home") == ["unl-est-bul-2026-11-16", "estonia-kml-2027-champion"]
    assert asked[0][0].endswith("/public-search") and asked[0][1]["q"] == "will estonia win at home"
    assert asked[0][1]["events_status"] == "active"


def test_polymarket_history_is_percent_oldest_first_without_odd_points():
    data = {"history": [{"t": 200, "p": 0.61}, {"t": 100, "p": 0.28}, {"t": 300}, {"t": "x", "p": 0.5}, {"t": 400, "p": 7}]}
    assert polymarket.parse_history(data) == [(100.0, 28.0), (200.0, 61.0)]
    assert polymarket.parse_history(None) == [] and polymarket.parse_history({}) == []


def test_kalshi_history_reads_each_hour_like_a_live_price():
    quote = {"end_period_ts": 100, "yes_bid": {"close_dollars": "0.4000"}, "yes_ask": {"close_dollars": "0.4400"},
             "price": {"close_dollars": "0.3000"}}
    one_sided = {"end_period_ts": 200, "yes_bid": {"close_dollars": "0.9900"}, "yes_ask": {"close_dollars": "1.0000"},
                 "price": {"close_dollars": "0.9900"}}
    nothing = {"end_period_ts": 300, "yes_bid": {}, "yes_ask": {}, "price": {}}
    # a real two-sided quote gives its midpoint; without one, the last trade; with neither, the hour is left out
    assert kalshi.parse_history({"candlesticks": [one_sided, nothing, quote, {"price": {}}]}) == [(100.0, 42.0), (200.0, 99.0)]
    assert kalshi.parse_history(None) == []


from terminal.venues.kalshi import search as kalshi_search  # the real one: conftest swaps kalshi.search out


def test_kalshi_search_returns_open_event_pages_in_rank_order(monkeypatch):
    def get(path, **params):
        assert (path, params) == (kalshi.SEARCH, {"query": "super ballon d'or winner", "page_size": 10})
        return {"current_page": [
            {"series_ticker": "KXBALLONDOR", "event_ticker": "KXBALLONDOR-27", "active_market_count": 80},
            {"series_ticker": "KXBALLONDOR", "event_ticker": "KXBALLONDOR-26", "active_market_count": 0},  # closed
            {"series_ticker": "KXSUPERBALLONDOR", "event_ticker": "KXSUPERBALLONDOR-30", "active_market_count": 1},
            {"series_ticker": "KX/odd", "event_ticker": "x y", "active_market_count": 3},
            {"event_ticker": "KXNOSERIES-1", "active_market_count": 1}]}

    monkeypatch.setattr(kalshi, "get", get)
    assert kalshi_search("super ballon d'or winner") == [
        "https://kalshi.com/markets/kxballondor/e/kxballondor-27",
        "https://kalshi.com/markets/kxsuperballondor/e/kxsuperballondor-30"]
    monkeypatch.setattr(kalshi, "get", lambda path, **params: {})
    assert kalshi_search("nothing like it") == []

