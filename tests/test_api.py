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
