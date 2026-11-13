import json
from datetime import UTC, datetime

from terminal.contextdev import parse_scrape, parse_search


def test_parse_search_fixture():
    rows = parse_search(json.load(open("tests/fixtures/search_response.json")))
    assert len(rows) >= 5
    assert all(r["url"].startswith("http") and r["title"] and isinstance(r["description"], str) for r in rows)


def test_parse_search_drops_results_without_address_or_title():
    rows = parse_search({"results": [{"url": "https://a.example/x", "title": "T", "description": None},
                                     {"url": "", "title": "no address"}, {"url": "https://a.example/y"},
                                     {"url": "javascript:alert(1)", "title": "not a web address"}]})
    assert rows == [{"url": "https://a.example/x", "title": "T", "description": "", "text": ""}]
    assert parse_search({"error": "nope"}) == []


def test_parse_scrape_returns_text_and_publish_time():
    text, ts = parse_scrape({"markdown": {"data": "# Story\nBody"}, "metadata": {"publishedTime": "2026-11-12T23:06:04+00:00"}})
    assert text == "# Story\nBody" and ts == datetime(2026, 11, 12, 23, 6, 4, tzinfo=UTC).timestamp()
    assert parse_scrape({"markdown": {"data": None}, "metadata": {"publishedTime": "not a date"}}) == ("", None)
    assert parse_scrape({}) == ("", None)


def test_limiter_allows_ten_a_minute_per_key():
    from terminal.contextdev import Limiter

    lim = Limiter(["k1"], per_minute=10)
    assert [lim.try_take(now=0) for _ in range(10)] == ["k1"] * 10
    assert lim.try_take(now=30) is None and lim.wait_time(now=30) == 30
    assert lim.try_take(now=60) == "k1"


def test_limiter_spreads_over_several_keys():
    from terminal.contextdev import Limiter

    lim = Limiter(["k1", "k2"], per_minute=10)
    taken = [lim.try_take(now=0) for _ in range(21)]
    assert taken.count("k1") == 10 and taken.count("k2") == 10 and taken[-1] is None


def test_limiter_backs_off_a_key_the_server_refused():
    from terminal.contextdev import Limiter

    lim = Limiter(["k1"], per_minute=10)
    lim.refused("k1", retry_after=31, now=5)
    assert lim.try_take(now=35) is None and lim.try_take(now=36) == "k1"


def test_limiter_reserve_keeps_capacity_back_for_searches():
    from terminal.contextdev import Limiter

    lim = Limiter(["k1"], per_minute=10)
    assert [lim.try_take(now=0, reserve=5) for _ in range(6)] == ["k1"] * 5 + [None]
    assert [lim.try_take(now=0) for _ in range(6)] == ["k1"] * 5 + [None]


def client_with(handler, monkeypatch):
    import httpx

    from terminal import contextdev

    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "k1")
    monkeypatch.setattr(contextdev, "_limiter", None)
    monkeypatch.setattr(contextdev, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return contextdev


def test_search_sends_the_filters_and_parses_results(monkeypatch):
    import asyncio

    import httpx

    seen = []

    def handler(request):
        seen.append((request.url.path, request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json=json.load(open("tests/fixtures/search_response.json")))

    cd = client_with(handler, monkeypatch)
    rows = asyncio.run(cd.search("nvidia ceo", include_domains=["x.com"], num_results=20))
    assert len(rows) >= 5
    assert seen == [("/v1/web/search", "Bearer k1", {"query": "nvidia ceo", "freshness": "last_24_hours",
                                                     "numResults": 20, "highlightsOptions": {"enabled": True},
                                                     "includeDomains": ["x.com"]})]


def test_a_refused_request_raises_and_rests_the_key(monkeypatch):
    import asyncio

    import httpx
    import pytest

    cd = client_with(lambda r: httpx.Response(429, headers={"retry-after": "31"}, json={"error_code": "RATE_LIMITED"}),
                     monkeypatch)
    with pytest.raises(cd.ContextError):
        asyncio.run(cd.search("q"))
    assert cd.limiter().try_take() is None and 30 < cd.limiter().wait_time() <= 31


def test_scrape_without_spare_capacity_is_skipped_not_an_error(monkeypatch):
    import asyncio

    import httpx

    calls = []
    cd = client_with(lambda r: calls.append(r) or httpx.Response(200, json={}), monkeypatch)
    for _ in range(5):
        cd.limiter().try_take()
    assert asyncio.run(cd.scrape("https://a.example/x")) == ("", None) and calls == []


def test_search_results_carry_the_passages_as_text():
    rows = parse_search(json.load(open("tests/fixtures/search_highlights_response.json")))
    assert rows and sum(len(r["text"]) > 200 for r in rows) >= 3
    assert parse_search({"results": [{"url": "https://a.example/x", "title": "T", "highlights": {"highlights": None}}]})[0]["text"] == ""


def test_search_asks_for_passages_and_can_exclude_sites(monkeypatch):
    import asyncio

    import httpx

    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"results": []})

    cd = client_with(handler, monkeypatch)
    asyncio.run(cd.search("q", exclude_domains=["wikipedia.org"]))
    assert seen[0]["highlightsOptions"] == {"enabled": True} and seen[0]["excludeDomains"] == ["wikipedia.org"]


def test_absurd_publish_times_are_ignored():
    for bad in ("9999-12-31T23:59:59+00:00", "0001-01-01T00:00:00+00:00", "1970-01-01T00:00:00+00:00", "2126-11-13"):
        assert parse_scrape({"markdown": {"data": "x"}, "metadata": {"publishedTime": bad}}) == ("x", None)


def test_load_is_spread_evenly_over_the_keys_and_duplicates_count_once():
    from terminal.contextdev import Limiter

    lim = Limiter(["k1", "k2", "k1", "k3"], per_minute=10)
    assert [lim.try_take(now=0) for _ in range(6)] == ["k1", "k2", "k3", "k1", "k2", "k3"]
    assert sum(lim.try_take(now=0) is not None for _ in range(30)) == 24  # 3 keys x 10 a minute, 6 already used


def pool(handler, monkeypatch, keys="k1,k2"):
    cd = client_with(handler, monkeypatch)
    monkeypatch.setenv("CONTEXT_DEV_API_KEY", keys)
    return cd


def test_a_refused_key_rests_and_the_request_goes_out_on_the_next_key(monkeypatch):
    import asyncio

    import httpx

    used = []

    def handler(request):
        key = request.headers["authorization"].removeprefix("Bearer ")
        used.append(key)
        if key == "k1":
            return httpx.Response(403, json={"error_code": "INSUFFICIENT_CREDITS"})
        return httpx.Response(200, json={"results": [{"url": "https://a.example/x", "title": "T"}],
                                         "key_metadata": {"credits_remaining": 4321}})

    cd = pool(handler, monkeypatch)
    assert len(asyncio.run(cd.search("q"))) == 1 and used == ["k1", "k2"]
    assert len(asyncio.run(cd.search("q"))) == 1 and used == ["k1", "k2", "k2"]  # k1 is resting
    status = cd.status()
    assert status["per_minute"] == 20 and status["used_last_minute"] == 3
    assert [k["key"] for k in status["keys"]] == [1, 2]
    assert status["keys"][0]["resting_seconds"] > 590 and status["keys"][0]["credits_remaining"] is None
    assert status["keys"][1]["resting_seconds"] == 0 and status["keys"][1]["credits_remaining"] == 4321
    assert "k1" not in str(status) and "k2" not in str(status)


def test_when_every_key_is_refused_the_error_reaches_the_caller(monkeypatch):
    import asyncio

    import httpx
    import pytest

    cd = pool(lambda r: httpx.Response(429, headers={"retry-after": "30"}, json={}), monkeypatch)
    with pytest.raises(cd.ContextError):
        asyncio.run(cd.search("q"))


def test_status_without_any_key_configured_is_empty_not_an_error(monkeypatch):
    from terminal import contextdev

    monkeypatch.delenv("CONTEXT_DEV_API_KEY", raising=False)
    monkeypatch.setattr(contextdev, "_limiter", None)
    assert contextdev.status() == {"keys": [], "per_minute": 0, "used_last_minute": 0}


def test_search_can_leave_freshness_out(monkeypatch):
    import asyncio

    import httpx

    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"results": []})

    cd = client_with(handler, monkeypatch)
    asyncio.run(cd.search("q", freshness=None))
    asyncio.run(cd.search("q"))
    assert "freshness" not in seen[0] and seen[1]["freshness"] == "last_24_hours"


def test_background_searches_leave_room_for_a_person_asking(monkeypatch):
    import asyncio

    import httpx

    cd = client_with(lambda request: httpx.Response(200, json={"results": []}), monkeypatch)

    async def go():
        for _ in range(8):
            await cd.search("background", reserve=2)
        late = asyncio.create_task(cd.search("background", reserve=2))
        await cd.search("a person asking")          # goes straight out
        await asyncio.sleep(0.2)
        waiting = not late.done()                   # the ninth background search is held back
        late.cancel()
        return waiting

    assert asyncio.run(go()) is True


def test_wait_time_counts_the_reserve():
    from terminal.contextdev import Limiter

    lim = Limiter(["k"], per_minute=10)
    for t in range(8):
        lim.try_take(now=t)
    assert lim.wait_time(now=10) == 0 and lim.wait_time(now=10, reserve=2) == 50  # the first request ages out at 60


def test_published_times_come_from_one_batch_read_page_by_page(monkeypatch):
    import asyncio

    import httpx

    seen, polls = [], []

    def handler(request):
        path = request.url.path
        seen.append((request.method, path, dict(request.url.params)))
        if path == "/v1/batch/submit":
            assert [u["url"] for u in json.loads(request.content)["input"]["data"]["urls"]] == ["https://a.example/1", "https://a.example/2", "https://a.example/3"]
            return httpx.Response(202, json={"id": "batch_1", "status": "queued"})
        if path == "/v1/batch/batch_1":
            polls.append(1)
            return httpx.Response(200, json={"status": "running" if len(polls) < 2 else "completed"})
        if request.url.params.get("cursor") is None:
            return httpx.Response(200, json={"data": [{"url": "https://a.example/1", "status": "ok",
                                                       "metadata": {"publishedTime": "2026-11-13T12:00:00Z"}}],
                                             "has_more": True, "next_cursor": "1:1"})
        return httpx.Response(200, json={"data": [{"url": "https://a.example/2", "status": "ok", "metadata": {}}],
                                         "has_more": False, "next_cursor": None})

    cd = client_with(handler, monkeypatch)
    monkeypatch.setattr(cd, "BATCH_POLL_SECONDS", 0)
    times = asyncio.run(cd.published_times(["https://a.example/1", "https://a.example/2", "https://a.example/3"]))
    assert times == {"https://a.example/1": 1794571200.0, "https://a.example/2": None}  # /3 failed: not in the results
    assert [s[1] for s in seen] == ["/v1/batch/submit", "/v1/batch/batch_1", "/v1/batch/batch_1",
                                    "/v1/batch/batch_1/results", "/v1/batch/batch_1/results"]
    assert seen[-1][2] == {"limit": "100", "cursor": "1:1"}


def test_a_batch_that_is_refused_or_fails_is_an_error(monkeypatch):
    import asyncio

    import httpx
    import pytest

    cd = client_with(lambda request: httpx.Response(403, json={"error_code": "BATCH_LIMIT_EXCEEDED"}), monkeypatch)
    with pytest.raises(cd.ContextError):
        asyncio.run(cd.published_times(["https://a.example/1"]))
