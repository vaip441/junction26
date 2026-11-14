import pytest
from fastapi.testclient import TestClient

from terminal.api import create_app
from terminal.scoring import Score, ScoringError


async def up(*_):
    return Score(0.84, 0.12, 0.04, 0.8)


async def broken(*_):
    raise ScoringError("api down")


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "t.db")


def client(path, scorer=up):
    return TestClient(create_app(db_path=path, scorer=scorer, poll=False))


def typed(c, text="that is clever", kind="typed", market="mu-demo"):
    return c.post(f"/markets/{market}/ticks", json={"text": text, "kind": kind})


def test_demo_market_exists_at_20_percent(path):
    with client(path) as c:
        markets = c.get("/markets").json()
    assert len(markets) == 1
    assert markets[0]["id"] == "mu-demo" and markets[0]["made_up"] is True and markets[0]["price"] == 20.0


def test_typed_tick_is_scored_flagged_and_moves_the_demo_price(path):
    with client(path) as c:
        r = typed(c)
        assert r.status_code == 200
        assert r.json()["verdict"] == "up" and r.json()["test"] is True and "dedupe_key" not in r.json()
        assert abs(c.get("/markets").json()[0]["price"] - 25.61) < 0.01
        assert len(c.get("/markets/mu-demo/ticks").json()) == 1
        assert c.get("/markets").json()[0]["ticks_today"] == 1
        assert [p["price"] for p in c.get("/markets/mu-demo/prices").json()][0] == 20.0


def test_bad_tick_input_is_rejected(path):
    with client(path) as c:
        assert typed(c, text="   ").status_code == 422
        assert typed(c, text="x" * 501).status_code == 422
        assert typed(c, kind="article").status_code == 422
        assert typed(c, market="nope").status_code == 404
        assert c.get("/markets/nope").status_code == 404


def test_scorer_failure_is_a_503_and_the_service_keeps_working(path):
    with client(path, scorer=broken) as c:
        r = typed(c)
        assert r.status_code == 503 and r.json()["detail"] == "scoring unavailable, try again"
        assert c.get("/markets").status_code == 200


def test_restart_keeps_data_and_one_demo_market(path):
    with client(path) as c:
        typed(c)
    with client(path) as c:
        markets = c.get("/markets").json()
        assert [m["id"] for m in markets] == ["mu-demo"]
        assert abs(markets[0]["price"] - 25.61) < 0.01
        assert len(c.get("/markets/mu-demo/ticks").json()) == 1


def test_change_24h_is_null_without_an_old_sample(path):
    with client(path) as c:
        assert c.get("/markets").json()[0]["change_24h"] is None


def test_market_detail_has_rules_related_and_pages(path):
    with client(path) as c:
        d = c.get("/markets/mu-demo").json()
    assert d["rules"] and d["related"] == [] and d["pages"] == [] and d["queries"] == []


CONTRACTS = [{"venue": "polymarket", "venue_ref": f"tok{i}", "title": f"Contract {i}?", "rules": "rules",
              "url": f"https://polymarket.com/event/e/m{i}", "price": 40.0 + i, "slug": f"m{i}", "event": "E?"}
             for i in range(3)]
KALSHI = [{"venue": "kalshi", "venue_ref": f"KX-{i}", "title": f"Kalshi {i}?", "rules": "rules",
           "url": "https://kalshi.com/markets/kx/e/kx", "price": 45.0 + i, "event": "E?"} for i in range(2)]


def test_post_market_validates_its_input(path):
    with client(path) as c:
        assert c.post("/markets", json={"query": ""}).status_code == 422
        assert c.post("/markets", json={"query": "https://polymarket.com/event/e", "poll_seconds": 5}).status_code == 422


def test_post_market_tracks_lead_and_related(path, monkeypatch):
    from terminal import venues

    async def resolve(link):
        return CONTRACTS

    monkeypatch.setattr(venues, "resolve", resolve)
    with client(path) as c:
        r = c.post("/markets", json={"query": "https://polymarket.com/event/e", "poll_seconds": 60})
        assert r.status_code == 200
        m = r.json()
        assert m["id"] == "pm-m0" and m["price"] == 40.0 and m["poll_seconds"] == 60
        assert [x["id"] for x in m["related"]] == ["pm-m1", "pm-m2"] and m["related"][0]["price"] == 41.0
        assert [x["id"] for x in c.get("/markets").json()] == ["mu-demo", "pm-m0"]
        again = c.post("/markets", json={"query": "https://polymarket.com/event/e"}).json()
        assert again["id"] == "pm-m0" and len(c.get("/markets").json()) == 2


def test_a_new_market_answers_with_a_week_of_price_history(path, monkeypatch):
    from terminal import venues
    from terminal.venues import polymarket

    async def resolve(link):
        return CONTRACTS

    asked = []

    def history(token):
        asked.append(token)
        return [(1000.0, 30.0), (2000.0, 35.0)] if token == CONTRACTS[0]["venue_ref"] else []

    monkeypatch.setattr(venues, "resolve", resolve)
    monkeypatch.setattr(polymarket, "history", history)
    with client(path) as c:
        m = c.post("/markets", json={"query": "https://polymarket.com/event/e"}).json()
        assert sorted(asked) == sorted(x["venue_ref"] for x in CONTRACTS)  # the lead and its related contracts
        points = c.get("/markets/pm-m0/prices").json()
        # the venue's history first, then the price read when it was tracked, which stays the current one
        assert [(p["ts"], p["price"]) for p in points[:2]] == [(1000.0, 30.0), (2000.0, 35.0)]
        assert len(points) == 3 and points[2]["price"] == 40.0 and m["price"] == 40.0
        c.post("/markets", json={"query": "https://polymarket.com/event/e"})
        assert len(asked) == len(CONTRACTS)  # tracked already: not asked for again


def test_a_venue_that_fails_on_history_still_tracks_the_market(path, monkeypatch):
    from terminal import venues
    from terminal.venues import polymarket

    async def resolve(link):
        return CONTRACTS

    def down(token):
        raise RuntimeError("giving up")

    monkeypatch.setattr(venues, "resolve", resolve)
    monkeypatch.setattr(polymarket, "history", down)
    with client(path) as c:
        r = c.post("/markets", json={"query": "https://polymarket.com/event/e"})
        assert r.status_code == 200 and r.json()["id"] == "pm-m0"
        assert len(c.get("/markets/pm-m0/prices").json()) == 1


def test_post_market_unknown_market_is_404(path, monkeypatch):
    from terminal import venues

    async def resolve(link):
        raise venues.MarketNotFound("market not found")

    monkeypatch.setattr(venues, "resolve", resolve)
    with client(path) as c:
        assert c.post("/markets", json={"query": "https://polymarket.com/event/gone"}).status_code == 404


def test_writes_need_the_shared_key_when_one_is_set(path):
    with TestClient(create_app(db_path=path, scorer=up, poll=False, key="s3cret")) as c:
        body = {"text": "hello", "kind": "typed"}
        assert c.post("/markets/mu-demo/ticks", json=body).status_code == 401
        assert c.post("/markets/mu-demo/ticks", json=body, headers={"X-Terminal-Key": "wrong"}).status_code == 401
        assert c.post("/markets", json={"query": "https://polymarket.com/event/e"}).status_code == 401
        assert c.post("/markets/mu-demo/ticks", json=body, headers={"X-Terminal-Key": "s3cret"}).status_code == 200
        assert c.get("/markets").status_code == 200


def test_pasting_a_related_contract_makes_it_a_market(path, monkeypatch):
    from terminal import venues

    async def resolve(link):
        return CONTRACTS if link.endswith("/e") else [CONTRACTS[1], CONTRACTS[0], CONTRACTS[2]]

    monkeypatch.setattr(venues, "resolve", resolve)
    with client(path) as c:
        c.post("/markets", json={"query": "https://polymarket.com/event/e"})
        r = c.post("/markets", json={"query": "https://polymarket.com/event/e/m1"})
        assert r.status_code == 200 and r.json()["id"] == "pm-m1"
        assert [x["id"] for x in c.get("/markets").json()] == ["mu-demo", "pm-m0", "pm-m1"]
        assert [x["id"] for x in c.get("/markets/pm-m0").json()["related"]] == ["pm-m2"]


def test_venue_outage_is_a_502(path, monkeypatch):
    from terminal import venues

    async def resolve(link):
        raise venues.VenueError("kalshi answered with HTML")

    monkeypatch.setattr(venues, "resolve", resolve)
    with client(path) as c:
        r = c.post("/markets", json={"query": "https://kalshi.com/markets/a/b/c"})
        assert r.status_code == 502 and "try again" in r.json()["detail"]


def test_polling_refuses_to_start_without_a_write_key(path, monkeypatch):
    monkeypatch.delenv("TERMINAL_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TERMINAL_KEY"):
        with TestClient(create_app(db_path=path, scorer=up, poll=True)):
            pass


def test_a_key_header_with_odd_characters_is_a_401_not_a_crash(path):
    with TestClient(create_app(db_path=path, scorer=up, poll=False, key="s3cret")) as c:
        r = c.post("/markets/mu-demo/ticks", content=b'{"text": "hi", "kind": "typed"}',
                   headers={"content-type": "application/json", "X-Terminal-Key": "k\xe9y".encode("latin-1")})
        assert r.status_code == 401


def test_adding_a_market_wakes_the_article_loop(path, monkeypatch):
    from terminal import poller, venues

    async def resolve(link):
        return CONTRACTS

    woken = []

    async def price_loop(db, bus, scorer, busy):
        return None

    async def article_loop(db, bus, scorer, wake, busy):
        await wake.wait()
        woken.append([m["id"] for m in poller.due(db, {}, now=1e12)])

    monkeypatch.setattr(venues, "resolve", resolve)
    monkeypatch.setattr(poller, "price_loop", price_loop)
    monkeypatch.setattr(poller, "article_loop", article_loop)
    with TestClient(create_app(db_path=path, scorer=up, poll=True, key="k")) as c:
        m = c.post("/markets", json={"query": "https://polymarket.com/event/e"}, headers={"X-Terminal-Key": "k"}).json()
        assert m["queries"] == []
        c.get("/markets")
    assert woken == [["pm-m0"]]


def test_status_reports_context_dev_capacity(path, monkeypatch):
    from terminal import contextdev

    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "k1, k2 ,k3")
    monkeypatch.setattr(contextdev, "_limiter", None)
    with client(path) as c:
        s = c.get("/status").json()["context_dev"]
    assert s["per_minute"] == 30 and len(s["keys"]) == 3 and s["used_last_minute"] == 0


def test_market_detail_lists_its_sources(path):
    with client(path) as c:
        assert c.get("/markets/mu-demo").json()["sources"] == []
        typed(c)
        assert c.get("/markets/mu-demo").json()["sources"] == [{"source": "typed", "ticks": 1, "moved": 1}]


def plain(monkeypatch, groups=(), pick=(None, [], []), question=None):
    """Stand-ins for the venue search, the model's pick and the question writer. Returns the writer's calls."""
    from terminal import madeup, match

    written = []

    async def candidates(words):
        if isinstance(groups, Exception):
            raise groups
        return [list(g) for g in groups]

    async def choose(words, found):
        if isinstance(pick, Exception):
            raise pick
        return pick

    async def question_for(words, today):
        written.append(words)
        if isinstance(question, Exception):
            raise question
        return question or {"title": "Will it snow?", "rules": "Resolves yes if it snows."}

    monkeypatch.setattr(match, "candidates", candidates)
    monkeypatch.setattr(match, "pick", choose)
    monkeypatch.setattr(madeup, "question_for", question_for)
    return written


def test_plain_words_matching_a_contract_tracks_it_with_the_other_venue_as_related(path, monkeypatch):
    plain(monkeypatch, [CONTRACTS, KALSHI], (0, [0.7, 0.25], [0, 1]))
    with client(path) as c:
        r = c.post("/markets", json={"query": "will contract 0 happen"})
        m = r.json()
        assert r.status_code == 200 and m["matched"] is True and m["id"] == "pm-m0"
        # its own event's contracts, then the contract asked about on the other venue
        assert [x["id"] for x in m["related"]] == ["pm-m1", "pm-m2", "k-KX-1"]
        assert [x["id"] for x in c.get("/markets").json()] == ["mu-demo", "pm-m0"]


def test_the_contract_the_question_names_leads(path, monkeypatch):
    plain(monkeypatch, [CONTRACTS], (0, [0.9], [2]))
    with client(path) as c:
        m = c.post("/markets", json={"query": "will contract 2 happen"}).json()
        assert m["id"] == "pm-m2" and [x["id"] for x in m["related"]] == ["pm-m0", "pm-m1"]


def test_a_weak_second_candidate_is_not_added_as_related(path, monkeypatch):
    plain(monkeypatch, [CONTRACTS, KALSHI], (0, [0.9, 0.05], [0, 0]))
    with client(path) as c:
        m = c.post("/markets", json={"query": "will contract 0 happen"}).json()
        assert [x["id"] for x in m["related"]] == ["pm-m1", "pm-m2"]


def test_plain_words_without_a_match_make_a_made_up_market(path, monkeypatch):
    from terminal import madeup

    plain(monkeypatch)  # also what happens when search finds only closed pages: no groups
    with client(path) as c:
        r = c.post("/markets", json={"query": "Will it snow?", "poll_seconds": 60})
        m = r.json()
        assert r.status_code == 200 and m["matched"] is False and m["made_up"] is True and m["price"] is None
        assert m["id"] == madeup.market_id("Will it snow?") and m["title"] == "Will it snow?" and m["poll_seconds"] == 60


def test_markets_found_but_none_matching_is_a_made_up_market(path, monkeypatch):
    plain(monkeypatch, [CONTRACTS], (None, [0.1], [0]))
    with client(path) as c:
        assert c.post("/markets", json={"query": "Will it snow?"}).json()["made_up"] is True


def test_asking_the_same_words_twice_returns_the_same_market(path, monkeypatch):
    written = plain(monkeypatch)
    with client(path) as c:
        a = c.post("/markets", json={"query": "Will it snow?"}).json()
        b = c.post("/markets", json={"query": "will it  snow"}).json()
        assert a["id"] == b["id"] and b["matched"] is False and written == ["Will it snow?"]
        assert len(c.get("/markets").json()) == 2


def test_words_that_are_not_a_question_create_nothing(path, monkeypatch):
    from terminal import madeup

    plain(monkeypatch, question=madeup.NotAQuestion("asdf"))
    with client(path) as c:
        r = c.post("/markets", json={"query": "asdf"})
        assert r.status_code == 422
        assert r.json()["detail"] == "that does not look like a question about something that could happen"
        assert len(c.get("/markets").json()) == 1


def test_outages_are_reported_and_leave_nothing_behind(path, monkeypatch):
    from terminal import madeup, match

    with client(path) as c:
        for kw, status, text in [({"groups": match.SearchFailed("x")}, 502, "could not reach search, try again"),
                                 ({"groups": [CONTRACTS], "pick": ScoringError("x")}, 503, "scoring unavailable, try again"),
                                 ({"question": madeup.WritingFailed("x")}, 502, "could not reach the writing model, try again")]:
            plain(monkeypatch, **kw)
            r = c.post("/markets", json={"query": "Will it snow?"})
            assert (r.status_code, r.json()["detail"]) == (status, text)
            assert len(c.get("/markets").json()) == 1


def test_status_events_carry_the_query(path, monkeypatch):
    plain(monkeypatch, [CONTRACTS, KALSHI], (0, [0.7, 0.25], [0, 0]))
    with client(path) as c:
        q = c.app.state.bus.subscribe()
        c.post("/markets", json={"query": "will contract 0 happen"})
        events = [q.get_nowait()[1] for _ in range(q.qsize())]
    assert [(e["market_id"], e["status"]) for e in events] == [
        (None, "searching venues"), (None, "found contracts"), (None, "picked"), ("pm-m0", "tracking")]
    assert events[0]["query"] == "will contract 0 happen" and events[1]["count"] == 2
    # the markets found are named, one card each, and then the one picked: the frontend shows the choice being made
    assert events[1]["contracts"] == [{"venue": "polymarket", "title": "E?", "price": 40.0, "contracts": 3},
                                      {"venue": "kalshi", "title": "E?", "price": 45.0, "contracts": 2}]
    assert events[2] == {"market_id": None, "query": "will contract 0 happen", "status": "picked", "winner": 0,
                         "venue": "polymarket", "title": "Contract 0?", "price": 40.0}


def test_a_link_is_a_match(path, monkeypatch):
    from terminal import venues

    async def resolve(link):
        return CONTRACTS

    monkeypatch.setattr(venues, "resolve", resolve)
    with client(path) as c:
        assert c.post("/markets", json={"query": "https://polymarket.com/event/e"}).json()["matched"] is True


def test_restart_turns_an_old_demo_market_into_a_never_polled_one(path):
    from terminal import db as store

    with client(path) as c:
        store.set_poll_seconds(c.app.state.db, "mu-demo", 900)
    with client(path) as c:
        assert c.get("/markets").json()[0]["poll_seconds"] == 0


def test_matching_words_asked_again_return_the_same_market_without_searching_again(path, monkeypatch):
    from terminal import match

    plain(monkeypatch, [CONTRACTS], (0, [0.9], [0]))
    searches = []
    found = match.candidates

    async def counted(words):
        searches.append(words)
        return await found(words)

    monkeypatch.setattr(match, "candidates", counted)
    with client(path) as c:
        a = c.post("/markets", json={"query": "Will contract 0 happen?"}).json()
        b = c.post("/markets", json={"query": "will contract 0  happen"}).json()
        assert a["id"] == b["id"] == "pm-m0" and b["matched"] is True and len(searches) == 1


def test_a_sentence_sent_to_a_market_that_has_no_price_yet_is_turned_away(path, monkeypatch):
    plain(monkeypatch)
    with client(path) as c:
        id = c.post("/markets", json={"query": "Will it snow?"}).json()["id"]
        r = typed(c, market=id)
        assert r.status_code == 409 and "still opening" in r.json()["detail"]
        assert c.get(f"/markets/{id}/ticks").json() == []


def test_words_that_once_made_a_made_up_market_find_the_real_one_when_it_appears(path, monkeypatch):
    with client(path) as c:
        plain(monkeypatch)
        made = c.post("/markets", json={"query": "Will it snow?"}).json()
        plain(monkeypatch, [CONTRACTS], (0, [0.9], [0]))
        real = c.post("/markets", json={"query": "Will it snow?"}).json()
        assert made["made_up"] is True and real["id"] == "pm-m0" and real["matched"] is True


def test_deleting_a_market_removes_it_and_tells_the_stream(path, monkeypatch):
    from terminal import venues

    async def resolve(link):
        return CONTRACTS

    monkeypatch.setattr(venues, "resolve", resolve)
    with client(path) as c:
        c.post("/markets", json={"query": "https://polymarket.com/event/e"})
        q = c.app.state.bus.subscribe()
        r = c.delete("/markets/pm-m0")
        assert r.status_code == 200 and r.json() == {"deleted": "pm-m0"}
        assert q.get_nowait() == ("market", {"market_id": "pm-m0", "status": "deleted"})
        assert [m["id"] for m in c.get("/markets").json()] == ["mu-demo"]
        assert c.get("/markets/pm-m1").status_code == 404 and c.delete("/markets/pm-m0").status_code == 404
        assert c.delete("/markets/mu-demo").status_code == 409  # the demo market is part of the app
    with TestClient(create_app(db_path=path, scorer=up, poll=False, key="k")) as c:
        assert c.delete("/markets/mu-demo").status_code == 401


def test_every_route_runs_on_the_event_loop_because_the_store_is_one_connection(path):
    # A plain `def` route runs on a worker thread; sharing the one sqlite connection with the background
    # loops from there raised "InterfaceError: bad parameter or other API misuse" under load (14 Nov).
    import inspect

    from fastapi.routing import APIRoute

    app = create_app(db_path=path, scorer=up, poll=False)
    plain_routes = [r.path for r in app.routes if isinstance(r, APIRoute) and not inspect.iscoroutinefunction(r.endpoint)]
    assert plain_routes == []


def test_moves_are_listed_newest_first_with_their_cause_as_a_tick(path):
    from terminal import db as store

    with client(path) as c:
        tick = typed(c).json()
        db = c.app.state.db
        store.add_move(db, "mu-demo", 100.0, 40.0, 20.0, 24.0, None, None, None)
        store.add_move(db, "mu-demo", 200.0, 140.0, 24.0, 30.0, tick["id"], 0.8, '{"start": 0, "end": 4, "text": "Rule", "confidence": 0.9}')
        first, second = c.get("/markets/mu-demo/moves").json()
        assert c.get("/markets/nope/moves").status_code == 404
    assert first == {"id": 2, "market_id": "mu-demo", "ts": 200.0, "since": 140.0, "from": 24.0, "to": 30.0,
                     "confidence": 0.8, "rule": {"start": 0, "end": 4, "text": "Rule", "confidence": 0.9}, "cause": tick}
    assert second["cause"] is None and second["rule"] is None and second["to"] == 24.0
