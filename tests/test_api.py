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
              "url": f"https://polymarket.com/event/e/m{i}", "price": 40.0 + i, "slug": f"m{i}"} for i in range(3)]


def test_post_market_rejects_plain_words_for_now(path):
    with client(path) as c:
        r = c.post("/markets", json={"query": "will jensen get fired"})
        assert r.status_code == 422 and r.json()["detail"] == "paste a Kalshi or Polymarket market link"
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

    async def price_loop(db, bus):
        return None

    async def article_loop(db, bus, scorer, wake):
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
