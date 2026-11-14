"""Measured latency: real figures from stored ticks, nothing when there is too little to measure."""
import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from terminal import db as store
from terminal import metrics
from terminal.api import create_app


def tick(market_id, n, **kw):
    return {"market_id": market_id, "ts": 1000.0 + n, "published_ts": None, "kind": "article", "source": "s", "url": None,
            "headline": "h", "up": 0.8, "none": 0.1, "down": 0.1, "strength": 0.5, "verdict": "up", "confidence": 0.8,
            "price_at": 40.0, "test": False, "backfill": False, "hidden": False, "dedupe_key": f"{market_id}-{n}",
            "provenance": "context_web_search", **kw}


def real(db, id="m"):
    return store.add_market(db, id=id, venue="kalshi", venue_ref="T", title="t", rules="r", url=None)


def test_median_and_p95_of_a_list():
    assert metrics.summary([5, 1, 3, 2, 4]) == {"n": 5, "median": 3, "p95": 5}
    assert metrics.summary([1, 2, 3, 4, 5, 6]) == {"n": 6, "median": 3.5, "p95": 6}
    hundred = metrics.summary(list(range(1, 101)))
    assert hundred == {"n": 100, "median": 50.5, "p95": 95}


def test_too_few_samples_give_no_figure_not_a_zero():
    assert metrics.summary([]) == {"n": 0, "median": None, "p95": None}
    assert metrics.summary([2.0] * (metrics.MIN_SAMPLES - 1)) == {"n": metrics.MIN_SAMPLES - 1, "median": None, "p95": None}
    db = store.connect(":memory:")
    real(db)
    store.add_tick(db, tick("m", 1, discovered_ts=1000.0, scored_ts=1002.0, published_ts=900.0))
    out = metrics.latency(db, now=2000.0)
    assert out["ticks"] == 1
    assert out["discovery_to_scored"] == {"n": 1, "median": None, "p95": None}
    assert out["publication_to_discovery"] == {"n": 1, "median": None, "p95": None}


def test_latency_is_measured_from_the_stored_times():
    db = store.connect(":memory:")
    real(db)
    for n, (waited, took) in enumerate([(60, 1.0), (120, 2.0), (180, 3.0), (240, 4.0), (300, 10.0)]):
        store.add_tick(db, tick("m", n, published_ts=5000.0 - waited, discovered_ts=5000.0, scored_ts=5000.0 + took))
    store.add_tick(db, tick("m", 9, published_ts=None, discovered_ts=5000.0, scored_ts=5005.0))  # no publish time
    out = metrics.latency(db, now=6000.0)
    assert out["publication_to_discovery"] == {"n": 5, "median": 180.0, "p95": 300.0}
    assert out["discovery_to_scored"] == {"n": 6, "median": 3.5, "p95": 10.0}
    assert out["window_seconds"] == 86400 and out["price_check_seconds"] == 60 and out["ticks"] == 6


def test_only_live_ticks_on_real_markets_are_measured():
    db = store.connect(":memory:")
    real(db)
    store.add_market(db, id="mu", venue="made_up", venue_ref=None, title="t", rules="r", url=None)
    store.add_market(db, id="rp", venue="polymarket", venue_ref=None, title="t", rules="r", url=None,
                     replay={"start": 0, "end": 1, "outcome": "yes"})
    times = {"published_ts": 4900.0, "discovered_ts": 5000.0, "scored_ts": 5001.0}
    for n in range(5):
        store.add_tick(db, tick("m", n, **times))
    left_out = [tick("mu", 1, **times),                                  # a made-up market
                tick("rp", 1, **times),                                  # a replay
                tick("m", 20, test=True, **times),                       # spoken or typed
                tick("m", 21, backfill=True, **times),                   # history
                tick("m", 22),                                           # from before the times were stored
                tick("m", 23, **{**times, "discovered_ts": 100.0})]      # older than the window
    for t in left_out:
        assert store.add_tick(db, t) is not None
    out = metrics.latency(db, now=6000.0, window=2000)
    assert out["ticks"] == 5
    assert out["publication_to_discovery"] == {"n": 5, "median": 100.0, "p95": 100.0}
    assert out["discovery_to_scored"] == {"n": 5, "median": 1.0, "p95": 1.0}


def test_hidden_ticks_and_clocks_running_ahead_do_not_bend_the_figures():
    db = store.connect(":memory:")
    real(db)
    for n in range(5):
        store.add_tick(db, tick("m", n, published_ts=4990.0, discovered_ts=5000.0, scored_ts=5002.0))
    store.add_tick(db, tick("m", 7, hidden=True, published_ts=4980.0, discovered_ts=5000.0, scored_ts=5000.001))  # trash: never scored
    store.add_tick(db, tick("m", 8, published_ts=5600.0, discovered_ts=5000.0, scored_ts=5002.0))  # "published" in the future
    out = metrics.latency(db, now=6000.0)
    assert out["discovery_to_scored"] == {"n": 6, "median": 2.0, "p95": 2.0}        # the hidden one is not a scored call
    assert out["publication_to_discovery"] == {"n": 6, "median": 10.0, "p95": 20.0}  # found is found; the future one is out


def test_request_durations_are_kept_per_kind(monkeypatch):
    monkeypatch.setattr(metrics, "_recent", {})
    for s in (0.2, 0.4, 0.6, 0.8, 1.0):
        metrics.timed("gemini_decision", s)
    metrics.timed("context_dev_web_search", 2.0)
    out = metrics.latency(store.connect(":memory:"), now=10.0)["requests"]
    assert out["gemini_decision"] == {"n": 5, "median": 0.6, "p95": 1.0}
    assert out["context_dev_web_search"] == {"n": 1, "median": None, "p95": None}


def test_requests_to_context_dev_and_the_scorer_are_timed(monkeypatch):
    from terminal import contextdev, scoring

    monkeypatch.setattr(metrics, "_recent", {})
    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "k1")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setattr(contextdev, "_limiter", None)
    monkeypatch.setattr(contextdev, "_client", httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"results": []}))))
    monkeypatch.setattr(scoring, "_client", httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"answers": {"move": {}}}))))
    asyncio.run(contextdev.search("q"))
    asyncio.run(scoring.decide("i", {}))
    assert {k: len(v) for k, v in metrics._recent.items()} == {"context_dev_web_search": 1, "gemini_decision": 1}
    assert all(0 <= s < 5 for v in metrics._recent.values() for s in v)


def test_a_page_found_just_now_is_read_fresh_not_from_a_cache(monkeypatch):
    from terminal import contextdev

    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"markdown": {"data": "text"}, "metadata": {}})

    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "k1")
    monkeypatch.setattr(contextdev, "_limiter", None)
    monkeypatch.setattr(contextdev, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(contextdev.scrape("https://a.example/x")) == ("text", None)
    assert seen == [("/v1/web/scrape", {"url": "https://a.example/x", "formats": {"markdown": True},
                                        "sharedParams": {"mainContentOnly": True}, "maxAgeMs": 0})]


def test_metrics_route_is_open_and_says_live(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "_recent", {})
    with TestClient(create_app(db_path=str(tmp_path / "t.db"), poll=False, key="secret")) as c:
        r = c.get("/metrics")  # a read: no key needed
        assert r.status_code == 200 and r.json()["mode"] == "live" and r.json()["ticks"] == 0
        assert r.json()["discovery_to_scored"] == {"n": 0, "median": None, "p95": None}
        assert r.json()["requests"] == {}
